"""Hybrid record + stream (tee) argv and a real loopback kill test.

The kill tests need a real ffmpeg (LIGHTSTREAM_TEST_FFMPEG) and a loopback RTMP
listener; they skip cleanly without it. Real platform ingest is UNVERIFIED.
"""

import io
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lightstream.command import (FRAGMENTED_MP4, build_command, publisher_command,
                                 recording_format, tee_output, numbered_recording_path)
from lightstream.config import resolve_settings
from lightstream.runner import format_command, run_with_reconnect

KEY = "live_SECRET123"
FFMPEG = os.environ.get("LIGHTSTREAM_TEST_FFMPEG")


def settings(**changes):
    return resolve_settings({}, {})._replace(**changes)


class RecordingFormatTests(unittest.TestCase):
    def test_mkv_is_default_and_unknown_extension_is_matroska(self):
        self.assertEqual("matroska", recording_format("a.mkv"))
        self.assertEqual("matroska", recording_format("a.bin"))

    def test_mp4_is_fragmented(self):
        self.assertEqual("mp4", recording_format("A.MP4"))
        spec = tee_output("rtmp://h/a/k", "out.mp4")
        self.assertIn("[f=mp4:%s:onfail=ignore]out.mp4" % FRAGMENTED_MP4, spec)

    def test_webm_is_refused_with_the_reason(self):
        with self.assertRaises(ValueError) as caught:
            recording_format("a.webm")
        self.assertIn("VP8/VP9", str(caught.exception))
        with self.assertRaises(ValueError):
            build_command(settings(record_to="a.webm"), KEY, "linux", "libx264")

    def test_live_slot_aborts_and_file_slot_is_ignored(self):
        spec = tee_output("rtmp://h/a/k", "a.mkv")
        self.assertTrue(spec.startswith("[f=flv:onfail=abort:"))
        self.assertIn("|[f=matroska:onfail=ignore]a.mkv", spec)


class HybridArgvTests(unittest.TestCase):
    def test_tee_maps_both_streams_and_sets_global_header(self):
        argv = build_command(settings(record_to="a.mkv"), KEY, "linux", "libx264")
        self.assertEqual(["-map", "0:v", "-map", "1:a"],
                         argv[argv.index("-map"):argv.index("-map") + 4])
        self.assertIn("+global_header", argv)
        self.assertEqual("tee", argv[argv.index("-f", argv.index("-flush_packets")) + 1])

    def test_macos_audio_is_in_the_first_input(self):
        argv = build_command(settings(record_to="a.mkv"), KEY, "macos", "libx264")
        self.assertIn("0:a", argv)

    def test_without_record_there_is_no_map_or_global_header(self):
        argv = build_command(settings(), KEY, "linux", "libx264")
        self.assertNotIn("-map", argv)
        self.assertNotIn("+global_header", argv)

    def test_key_is_hidden_in_tee_argv(self):
        argv = build_command(settings(record_to="a.mkv"), KEY, "linux", "libx264")
        self.assertNotIn(KEY, format_command(argv, KEY))


class RateModeTests(unittest.TestCase):
    def test_vbr_is_default_and_adds_nothing(self):
        argv = build_command(settings(), KEY, "linux", "libx264")
        self.assertNotIn("-x264-params", argv)
        self.assertNotIn("-minrate", argv)

    def test_cbr_adds_nal_hrd_for_x264_only(self):
        argv = build_command(settings(rate_mode="cbr"), KEY, "linux", "libx264")
        self.assertIn("nal-hrd=cbr", argv)
        self.assertIn("-minrate", argv)
        argv = build_command(settings(rate_mode="cbr"), KEY, "linux", "h264_nvenc")
        self.assertNotIn("nal-hrd=cbr", argv)

    def test_unknown_rate_mode_is_refused(self):
        with self.assertRaises(ValueError):
            build_command(settings(rate_mode="abr"), KEY, "linux", "libx264")


class PublisherArgvTests(unittest.TestCase):
    def test_persistent_ingest_streams_mpegts_to_local_udp_without_key(self):
        argv = build_command(settings(local_ingest_port=5555), KEY, "linux", "libx264")
        self.assertEqual("mpegts", argv[-2])
        self.assertTrue(argv[-1].startswith("udp://127.0.0.1:5555"))
        self.assertNotIn(KEY, " ".join(argv))

    def test_persistent_ingest_with_recording_tees_to_local_and_file(self):
        argv = build_command(settings(local_ingest_port=5555, record_to="a.mkv"),
                             KEY, "linux", "libx264")
        self.assertEqual("[f=mpegts:onfail=abort]udp://127.0.0.1:5555?pkt_size=1316"
                         "|[f=matroska:onfail=ignore]a.mkv", argv[-1])

    def test_publisher_copies_and_carries_the_key_only_to_the_url(self):
        argv = publisher_command(5555, "rtmp://h/a/" + KEY, "ffmpeg")
        self.assertEqual(["-c", "copy"], argv[argv.index("-c"):argv.index("-c") + 2])
        self.assertNotIn(KEY, format_command(argv, KEY))


@unittest.skipUnless(FFMPEG and os.path.exists(FFMPEG or ""),
                     "set LIGHTSTREAM_TEST_FFMPEG to a real ffmpeg binary")
class LoopbackKillTests(unittest.TestCase):
    """Real ffmpeg, real loopback RTMP listener killed mid-stream."""

    def setUp(self):
        from tools import spikes
        self.spikes = spikes
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.procs = []

    def tearDown(self):
        for proc in self.procs:
            proc.kill()

    def listener(self, name):
        port = self.spikes.free_port()
        proc = self.spikes._rtmp_receiver(FFMPEG, self.dir.name, name, port,
                                          os.path.join(self.dir.name, name + ".crc"))
        self.procs.append(proc)
        return port, proc

    def argv(self, port, record):
        s = settings(record_to=record, platform="custom",
                     custom_url="rtmp://127.0.0.1:%d/live" % port)
        argv = build_command(s, "k", "linux", "libx264", ffmpeg=FFMPEG)
        return self.spikes.swap_capture_inputs(argv, [
            "-re", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
            "-re", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])

    def test_recording_is_playable_after_ingest_is_killed(self):
        record = os.path.join(self.dir.name, "hybrid.mkv")
        port, receiver = self.listener("recv1")
        encoder = self.spikes.Proc(self.argv(port, record), self.dir.name, "enc1")
        self.procs.append(encoder)
        time.sleep(4)
        receiver.kill()
        exited = encoder.wait(10)
        self.assertTrue(exited, "ffmpeg must exit when the ingest dies:\n"
                        + encoder.log_text()[-400:])
        self.assertNotEqual(0, encoder.status)
        ok, _, packets, err = self.spikes.framecrc_of(FFMPEG, record)
        self.assertTrue(ok, err)
        self.assertGreater(len(packets), 30)
        self.assertTrue(self.spikes.decode_check(FFMPEG, record)["ok"])

    def test_runner_reconnects_and_continues_in_the_next_file(self):
        record = os.path.join(self.dir.name, "hybrid.mkv")
        port1, receiver1 = self.listener("recvA")
        port2, _ = self.listener("recvB")
        ports = {0: port1}
        stop = threading.Event()
        statuses = []

        def argv_for_attempt(attempt, encoder):
            return self.argv(port2, numbered_recording_path(record, attempt))

        result = []
        thread = threading.Thread(target=lambda: result.append(run_with_reconnect(
            self.argv(ports[0], record), "k", "linux", out=io.StringIO(), stop=stop,
            on_status=lambda state, detail: statuses.append(state),
            argv_for_attempt=argv_for_attempt)))
        thread.start()
        time.sleep(4)
        receiver1.kill()
        deadline = time.time() + 20
        while time.time() < deadline and statuses.count("starting") < 2:
            time.sleep(0.2)
        time.sleep(3)
        stop.set()
        thread.join(20)
        self.assertGreaterEqual(statuses.count("starting"), 2)
        self.assertIn("reconnecting", statuses)
        second = os.path.join(self.dir.name, "hybrid-2.mkv")
        for path in (record, second):
            ok, _, _, err = self.spikes.framecrc_of(FFMPEG, path)
            self.assertTrue(ok, "%s unreadable: %s" % (path, err))


if __name__ == "__main__":
    unittest.main()
