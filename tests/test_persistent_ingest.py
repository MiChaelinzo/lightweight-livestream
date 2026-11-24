"""Opt-in persistent ingest: runner seam, ladder and a real loopback test.

The loopback test needs LIGHTSTREAM_TEST_FFMPEG and skips cleanly without it.
Real platform behavior (gap, timestamps) is UNVERIFIED.
"""

import io
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lightstream import autoscale as au
from lightstream import cli
from lightstream.command import build_command, publisher_command
from lightstream.config import resolve_settings
from lightstream.runner import run_with_publisher, run_with_reconnect

FFMPEG = os.environ.get("LIGHTSTREAM_TEST_FFMPEG")
KEY = "live_SECRET123"


class FakeProc:
    def __init__(self, release):
        self.stderr = iter(())
        self.release = release
        self.terminated = False

    def wait(self):
        self.release.wait(5)
        return 0

    def terminate(self):
        self.terminated = True
        self.release.set()


class RunWithPublisherTests(unittest.TestCase):
    def test_publisher_runs_during_encoder_and_stops_after(self):
        launched = []
        release = threading.Event()

        def popen(argv, **kwargs):
            proc = FakeProc(release)
            launched.append((argv, proc))
            return proc

        seen = {}

        def encoder():
            deadline = time.time() + 2
            while not launched and time.time() < deadline:
                time.sleep(0.01)
            seen["publisher_started"] = bool(launched)
            return 7

        code = run_with_publisher(["pub"], KEY, "linux", encoder, popen=popen,
                                  out=io.StringIO())
        self.assertEqual(7, code)
        self.assertTrue(seen["publisher_started"])
        self.assertTrue(launched[0][1].terminated)

    def test_encoder_exception_still_stops_publisher(self):
        release = threading.Event()
        procs = []

        def popen(argv, **kwargs):
            procs.append(FakeProc(release))
            return procs[-1]

        def encoder():
            time.sleep(0.1)
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            run_with_publisher(["pub"], KEY, "linux", encoder, popen=popen,
                               out=io.StringIO())
        self.assertTrue(procs[0].terminated)


class ConstantSizeLadderTests(unittest.TestCase):
    def test_every_step_keeps_the_top_size(self):
        ladder = au.build_ladder(au.LadderStep(1280, 720, 60, 4000), constant_size=True)
        self.assertGreater(len(ladder), 1)
        self.assertEqual({(1280, 720)}, {(s.width, s.height) for s in ladder})
        self.assertEqual(len(ladder), len(set(ladder)))

    def test_default_ladder_still_changes_size(self):
        ladder = au.build_ladder(au.LadderStep(1280, 720, 60, 4000))
        self.assertGreater(len({(s.width, s.height) for s in ladder}), 1)


class PersistentCliTests(unittest.TestCase):
    def run_cli(self, argv):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            env = {"HOME": d, "XDG_CONFIG_HOME": d, "STREAM_KEY": KEY}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(cli, "detect_gpu_names", lambda _o: []), \
                    mock.patch.object(cli, "detect_os", lambda: "linux"), \
                    mock.patch.object(cli, "find_ffmpeg", lambda: None):
                code = cli.main(argv, out)
        return code, out.getvalue()

    def test_dry_run_shows_both_commands_without_the_key(self):
        code, text = self.run_cli(["start", "--dry-run", "--persistent-ingest"])
        self.assertEqual(0, code)
        self.assertIn("-f mpegts udp://127.0.0.1:", text)
        self.assertIn("-c copy", text)
        self.assertIn("rtmp://live.twitch.tv/app/****", text)
        self.assertNotIn(KEY, text)

    def test_off_by_default(self):
        code, text = self.run_cli(["start", "--dry-run"])
        self.assertNotIn("udp://", text)
        self.assertNotIn("Persistent ingest", text)

    def test_cannot_combine_with_backup_url(self):
        code, text = self.run_cli(["start", "--dry-run", "--persistent-ingest",
                                   "--backup-url", "rtmp://b/live"])
        self.assertEqual(2, code)
        self.assertIn("--backup-url", text)


@unittest.skipUnless(FFMPEG and os.path.exists(FFMPEG or ""),
                     "set LIGHTSTREAM_TEST_FFMPEG to a real ffmpeg binary")
class LoopbackPersistentTests(unittest.TestCase):
    def test_ingest_survives_an_encoder_restart_and_recording_is_readable(self):
        from tools import spikes
        with tempfile.TemporaryDirectory() as workdir:
            rtmp_port = spikes.free_port()
            udp_port = spikes.free_port(spikes.socket.SOCK_DGRAM)
            record = os.path.join(workdir, "persist.mkv")
            receiver = spikes._rtmp_receiver(
                FFMPEG, workdir, "recv", rtmp_port, os.path.join(workdir, "r.crc"))
            try:
                s = resolve_settings({}, {})._replace(
                    platform="custom", custom_url="rtmp://127.0.0.1:%d/live" % rtmp_port,
                    local_ingest_port=udp_port, record_to=record)
                encoder_argv = spikes.swap_capture_inputs(
                    build_command(s, "k", "linux", "libx264", ffmpeg=FFMPEG), [
                        "-re", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                        "-re", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])
                publisher_argv = publisher_command(
                    udp_port, "rtmp://127.0.0.1:%d/live/k" % rtmp_port, FFMPEG)
                restart, stop = threading.Event(), threading.Event()
                states = []

                def run_encoder():
                    return run_with_reconnect(
                        encoder_argv, "k", "linux", out=io.StringIO(), stop=stop,
                        restart=restart,
                        on_status=lambda st, d: states.append(st),
                        argv_for_attempt=lambda n, enc: [
                            a.replace(record, record.replace(".mkv", "-%d.mkv" % (n + 1)))
                            for a in encoder_argv])

                result = []
                thread = threading.Thread(target=lambda: result.append(
                    run_with_publisher(publisher_argv, "k", "linux", run_encoder,
                                       out=io.StringIO())))
                thread.start()
                time.sleep(4)
                restart.set()
                deadline = time.time() + 15
                while time.time() < deadline and states.count("restarting") < 1:
                    time.sleep(0.2)
                time.sleep(4)
                receiver_alive = receiver.alive()
                stop.set()
                thread.join(20)
                self.assertIn("restarting", states)
                self.assertTrue(receiver_alive,
                                "RTMP session ended during the encoder restart")
                ok, _, _, err = spikes.framecrc_of(FFMPEG, record)
                self.assertTrue(ok, err)
            finally:
                receiver.kill()


if __name__ == "__main__":
    unittest.main()
