"""Sidebar window for streaming. Thin: logic is in gui_controller and gui_pages.

Native ttk widgets only, no canvas drawing and no embedded browser. Each page
is built the first time it is opened, so unused pages cost no memory.
tkinter is imported guarded so this module imports (and the tests run) on
machines without a display or without tkinter. Window rendering is UNVERIFIED:
it has not been run on a screen in this repository's test environment.
"""

import io
import os
import sys
import webbrowser

try:
    import tkinter as tk
    from tkinter import filedialog, ttk
except ImportError:  # some Linux Pythons ship without tkinter
    tk = None
    ttk = None
    filedialog = None

from . import gui_controller as gc
from . import gui_pages as gp
from .telemetry import TelemetrySampler, UNKNOWN_SAMPLE
from .cli import cmd_doctor
from .config import scenes_path
from .portable import (ffmpeg_download_url, ffmpeg_guidance, find_ffmpeg,
                       is_portable, save_configured_ffmpeg, validate_ffmpeg)

POLL_MS = 500
CLOSE_WAIT_MS = 5000
TITLE_FONT = ("Segoe UI", 18, "bold")
STEP_FONT = ("Segoe UI", 12, "bold")
TEXT_FONT = ("Segoe UI", 11)
BUTTON_FONT = ("Segoe UI", 20, "bold")
LOG_FONT = ("Consolas", 10)
WRAP = 480
BANNER_COLORS = {"grey": "#555555", "orange": "#B35900",
                 "green": "#1B7F3B", "red": "#B00020"}
NO_GUI_MESSAGE = ("The window could not open. This computer has no screen "
                  "for it (or Python has no 'tkinter').\n"
                  "You can still use the command line: lightstream start")


class StreamWindow:
    def __init__(self, root):
        self.root = root
        self._shown_log = None
        self.controller = gc.StreamController(display=os.environ.get("DISPLAY"))
        self.prefs_file = gc.prefs_path()
        self.scenes_file = scenes_path()
        self.inbox = gp.RecommendationInbox()
        self.overlays = gp.OverlayList()
        saved = gc.load_prefs(self.prefs_file)
        root.title("Lightstream" + (" (portable)" if is_portable() else ""))
        root.minsize(720, 560)
        self._init_variables(saved)
        self._pages = {}
        self._build_shell()
        self.show_page(gp.DEFAULT_PAGE)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.poll()

    def _init_variables(self, saved):
        self.platform = tk.StringVar(value=gc.label_for(
            gc.PLATFORM_CHOICES, saved.get("platform", "twitch")))
        self.url = tk.StringVar(value=saved.get("url") or "")
        self.key = tk.StringVar()  # never saved
        self.show_key = tk.BooleanVar(value=False)
        self.strength = tk.StringVar(value=gc.label_for(
            gc.STRENGTH_CHOICES,
            saved.get("preset") or gc.suggest_strength(os.cpu_count())))
        self.record = tk.BooleanVar(value=bool(saved.get("record")))
        self.fps = tk.StringVar(value=str(saved.get("fps") or ""))
        self.bitrate = tk.StringVar(value=str(saved.get("bitrate") or ""))
        self.window_title = tk.StringVar(value=saved.get("window") or "")
        self.audio = tk.StringVar(value=saved.get("audio_device") or "")
        self.keep_trying = tk.BooleanVar(value=bool(saved.get("keep_trying")))
        self.mute = tk.BooleanVar(value=bool(saved.get("mute")))
        self.scene = tk.StringVar(value=saved.get("scene") or gc.NO_SCENE_LABEL)
        self.hardware = tk.StringVar(value=gp.hardware_label(saved.get("hardware")))
        self.analytics = tk.BooleanVar(value=saved.get("analytics") is True)
        self.profile = tk.StringVar(value=gp.profile_label(saved.get("profile")))
        self.audio_profile = tk.StringVar(
            value=gp.audio_profile_label(saved.get("audio_profile")))
        self.auto_scale = tk.BooleanVar(value=saved.get("auto_scale") is True)
        self.noise = saved.get("noise")
        self.status = tk.StringVar(value="")

    # -- shell: sidebar, page area, always-visible banner ---------------------
    def _build_shell(self):
        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True)
        sidebar = ttk.Frame(outer, padding=6)
        sidebar.pack(side="left", fill="y")
        ttk.Label(sidebar, text="Lightstream", font=TITLE_FONT).pack(pady=(0, 8))
        self.page_var = tk.StringVar()
        for page_id, label in gp.PAGES:
            ttk.Radiobutton(sidebar, text=label, value=page_id, variable=self.page_var,
                            style="Toolbutton",
                            command=lambda p=page_id: self.show_page(p)
                            ).pack(fill="x", pady=1)
        right = ttk.Frame(outer, padding=8)
        right.pack(side="left", fill="both", expand=True)
        self.banner = tk.Label(right, text="", font=STEP_FONT, fg="white",
                               wraplength=WRAP, pady=8)
        self.banner.pack(fill="x")
        self.page_area = ttk.Frame(right)
        self.page_area.pack(fill="both", expand=True, pady=6)
        ttk.Label(right, textvariable=self.status, wraplength=WRAP,
                  justify="left").pack(fill="x")

    def show_page(self, page_id):
        page_id = gp.resolve_page(page_id)
        self.page_var.set(page_id)
        for frame in self._pages.values():
            frame.pack_forget()
        if page_id not in self._pages:
            frame = ttk.Frame(self.page_area, padding=4)
            getattr(self, "_build_" + page_id)(frame)
            self._pages[page_id] = frame
        self._pages[page_id].pack(fill="both", expand=True)

    def _label(self, parent, text, font=TEXT_FONT):
        label = ttk.Label(parent, text=text, font=font, wraplength=WRAP, justify="left")
        label.pack(anchor="w", pady=(6, 0))
        return label

    def _entry(self, parent, label, variable, show=None):
        self._label(parent, label)
        entry = ttk.Entry(parent, textvariable=variable, show=show or "")
        entry.pack(fill="x")
        return entry

    def _combo(self, parent, label, variable, values):
        self._label(parent, label)
        ttk.Combobox(parent, textvariable=variable, state="readonly",
                     values=values).pack(fill="x")

    # -- pages ----------------------------------------------------------------
    def _build_dashboard(self, frame):
        self._combo(frame, "Where do you want to stream?", self.platform,
                    [l for l, _ in gc.PLATFORM_CHOICES])
        self._entry(frame, "(Other site only) address starting with rtmp://", self.url)
        self.key_entry = self._entry(
            frame, "Paste your secret stream key (it is not saved)", self.key, show="*")
        ttk.Checkbutton(frame, text="Show the key", variable=self.show_key,
                        command=self.toggle_key).pack(anchor="w")
        self._combo(frame, "How good is your PC?", self.strength,
                    [l for l, _ in gc.STRENGTH_CHOICES])
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=8)
        self.start_btn = tk.Button(buttons, text="START", font=BUTTON_FONT, bg="#1B7F3B",
                                   fg="white", command=self.on_start)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=4)
        self.stop_btn = tk.Button(buttons, text="STOP", font=BUTTON_FONT, bg="#B00020",
                                  fg="white", command=self.on_stop, state="disabled")
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=4)
        self.test_btn = ttk.Button(frame, text="Test first: record 10 seconds to a "
                                   "file (not live)", command=self.on_test)
        self.test_btn.pack(anchor="w")
        self.cards_frame = ttk.LabelFrame(frame, text="Stream health", padding=6)
        self.cards_frame.pack(fill="x", pady=6)
        self.card_values = []
        for index, card in enumerate(gp.health_cards({})):
            ttk.Label(self.cards_frame, text=card.title).grid(row=0, column=index, padx=6)
            value = ttk.Label(self.cards_frame, text=card.value, font=STEP_FONT)
            value.grid(row=1, column=index, padx=6)
            self.card_values.append(value)
        self.telemetry_frame = ttk.LabelFrame(frame, text="This PC", padding=6)
        self.telemetry_frame.pack(fill="x", pady=6)
        self.telemetry_values = []
        for index, card in enumerate(gp.telemetry_cards(UNKNOWN_SAMPLE)):
            ttk.Label(self.telemetry_frame, text=card.title).grid(row=0, column=index, padx=6)
            value = ttk.Label(self.telemetry_frame, text=card.value)
            value.grid(row=1, column=index, padx=6)
            self.telemetry_values.append(value)
        self.telemetry = TelemetrySampler()
        self.advice = ttk.Label(frame, text="", wraplength=WRAP, justify="left")
        self.advice.pack(fill="x")
        self.rec_frame = ttk.LabelFrame(
            frame, text="Suggestions (nothing changes unless you press Apply)", padding=6)
        self.rec_frame.pack(fill="x", pady=6)
        self._shown_recs = None
        self.log = tk.Text(frame, height=5, font=LOG_FONT, state="disabled")
        self.log.pack(fill="both", expand=True)

    def _build_setup(self, frame):
        self._label(frame, "Setup wizard", STEP_FONT)
        self._label(frame, "Looks at this PC and picks safe settings. You can still "
                    "change everything afterwards.")
        ttk.Button(frame, text="One-click setup: pick safe settings for this PC",
                   command=self.on_setup).pack(anchor="w", pady=6)
        ttk.Button(frame, text="Check my PC", command=self.on_doctor).pack(anchor="w")
        self._combo(frame, "PC type (hardware profile)", self.hardware,
                    gp.hardware_choices())

    def _build_scenes(self, frame):
        self._label(frame, "Scenes", STEP_FONT)
        self.scene_list = tk.Listbox(frame, height=8, exportselection=False)
        self.scene_list.pack(fill="x", pady=4)
        self.scene_name = tk.StringVar()
        self._entry(frame, "Scene name (for Save Scene)", self.scene_name)
        row = ttk.Frame(frame)
        row.pack(anchor="w", pady=6)
        for text, command in (("Save Scene", self.on_scene_save),
                              ("Duplicate Scene", self.on_scene_duplicate),
                              ("Import Scene", self.on_scene_import),
                              ("Export Scene", self.on_scene_export)):
            ttk.Button(row, text=text, command=command).pack(side="left", padx=2)
        self._combo(frame, "Scene used when you press START", self.scene,
                    gc.scene_choices(self.scenes_file))
        self._refresh_scene_list()

    def _build_overlays(self, frame):
        self._label(frame, "Overlays (drawn by FFmpeg, saved with Save Scene)", STEP_FONT)
        self.ov_kind = tk.StringVar(value="text")
        self.ov_text = tk.StringVar()
        self.ov_corner = tk.StringVar(value="top-left")
        self.ov_size = tk.IntVar(value=gp.size_range("text")[0] * 3)
        self.ov_path = tk.StringVar()
        self._combo(frame, "Kind", self.ov_kind, gp.OVERLAY_KIND_CHOICES)
        self._entry(frame, "Text (text overlays) or PNG path (image overlays)", self.ov_text)
        self._combo(frame, "Position", self.ov_corner, gp.CORNER_CHOICES)
        self._label(frame, "Scale (font size, or percent of width for images)")
        ttk.Scale(frame, from_=8, to=200, variable=self.ov_size, orient="horizontal",
                  command=lambda _v: self.update_overlay_preview()).pack(fill="x")
        for variable in (self.ov_kind, self.ov_text, self.ov_corner):
            variable.trace_add("write", lambda *_a: self.update_overlay_preview())
        self.ov_preview = ttk.Label(frame, text=gp.PREVIEW_PLACEHOLDER,
                                    wraplength=WRAP, justify="left")
        self._label(frame, "Preview (filter text, not a picture)")
        self.ov_preview.pack(anchor="w")
        ttk.Button(frame, text="Add to scene being built",
                   command=self.on_overlay_add).pack(anchor="w", pady=6)
        self.update_overlay_preview()

    def _build_recording(self, frame):
        self._label(frame, "Recording", STEP_FONT)
        ttk.Checkbutton(frame, text="Record a copy to a file while streaming",
                        variable=self.record).pack(anchor="w")
        self._label(frame, "Files go to the recordings folder in the app data folder.")

    def _build_advanced(self, frame):
        for label, var in (("Frames per second (empty = automatic)", self.fps),
                           ("Video kbps (empty = automatic)", self.bitrate),
                           ("Window title (Windows only)", self.window_title),
                           ("Audio device (empty = automatic)", self.audio)):
            self._entry(frame, label, var)
        self._combo(frame, "Hardware profile", self.hardware, gp.hardware_choices())
        self._combo(frame, "Performance profile (replaces Strength when chosen)",
                    self.profile, gp.profile_choices())
        self._combo(frame, "Microphone profile", self.audio_profile,
                    gp.audio_profile_choices())
        ttk.Checkbutton(frame, text="Auto-scale quality (off by default). When the "
                        "stream struggles it steps quality down, and back up when "
                        "healthy. Each step restarts the stream for a moment.",
                        variable=self.auto_scale).pack(anchor="w")
        ttk.Checkbutton(frame, text="Mute (send silence)", variable=self.mute
                        ).pack(anchor="w")
        ttk.Checkbutton(frame, text="Keep trying if the internet drops",
                        variable=self.keep_trying).pack(anchor="w")
        ttk.Checkbutton(frame, text="Save a session report after streaming (off by "
                        "default, stays on this PC, never contains your key)",
                        variable=self.analytics).pack(anchor="w")

    # -- actions --------------------------------------------------------------
    def toggle_key(self):
        self.key_entry.config(show="" if self.show_key.get() else "*")

    def collect_prefs(self):
        return {
            "platform": gc.value_for(gc.PLATFORM_CHOICES, self.platform.get()),
            "url": self.url.get(),
            "preset": gc.value_for(gc.STRENGTH_CHOICES, self.strength.get()),
            "fps": self.fps.get(),
            "bitrate": self.bitrate.get(),
            "window": self.window_title.get(),
            "audio_device": self.audio.get(),
            "keep_trying": self.keep_trying.get(),
            "mute": self.mute.get(),
            "scene": "" if self.scene.get() == gc.NO_SCENE_LABEL else self.scene.get(),
            "record": self.record.get(),
            "hardware": gp.hardware_pref(self.hardware.get()),
            "noise": self.noise,
            "analytics": self.analytics.get(),
            "profile": gp.profile_pref(self.profile.get()),
            "audio_profile": gp.audio_profile_pref(self.audio_profile.get()),
            "auto_scale": self.auto_scale.get(),
        }

    def apply_prefs(self, prefs):
        """Show changed prefs in the controls (used by the Apply button)."""
        self.strength.set(gc.label_for(gc.STRENGTH_CHOICES, prefs.get("preset")))
        self.bitrate.set(str(prefs.get("bitrate") or ""))
        self.profile.set(gp.profile_label(prefs.get("profile")))

    def on_start(self):
        prefs = self.collect_prefs()
        error = self.controller.start(prefs, self.key.get())
        if error is None:
            try:
                gc.save_prefs(self.prefs_file, prefs, self.key.get().strip())
            except OSError:
                pass  # remembering choices is optional
        else:
            self.status.set(error)

    def on_test(self):
        self.controller.start(self.collect_prefs(), "", test_local=True)

    def on_setup(self):
        platform = gc.value_for(gc.PLATFORM_CHOICES, self.platform.get())
        fields, message = gc.one_click_setup(platform=platform)
        self.strength.set(gc.label_for(gc.STRENGTH_CHOICES, fields["preset"]))
        self.bitrate.set(str(fields["bitrate"]))
        self.hardware.set(gp.hardware_label(fields["hardware"]))
        self.noise = fields["noise"]
        self.status.set(message)

    def on_stop(self):
        self.controller.stop(wait=False)

    def on_doctor(self):
        buffer = io.StringIO()
        cmd_doctor(buffer)
        self.status.set(buffer.getvalue().strip())

    def on_recommendation(self, rec, apply):
        if apply:
            prefs, message = gp.apply_recommendation(rec, self.collect_prefs())
            self.apply_prefs(prefs)
            self.status.set(message)
        self.inbox.dismiss(rec)
        self._shown_recs = None

    def _refresh_scene_list(self):
        self.scene_list.delete(0, "end")
        for name in gp.scene_names(self.scenes_file):
            self.scene_list.insert("end", name)

    def _selected_scene(self):
        chosen = self.scene_list.curselection()
        return self.scene_list.get(chosen[0]) if chosen else self.scene_name.get().strip()

    def _scene_result(self, result):
        self.status.set(result[1])
        self._refresh_scene_list()

    def on_scene_save(self):
        self._scene_result(gp.save_scene_action(
            self.scenes_file, self.scene_name.get(), self.overlays.drafts))

    def on_scene_duplicate(self):
        self._scene_result(gp.duplicate_scene_action(self.scenes_file, self._selected_scene()))

    def on_scene_import(self):
        source = filedialog.askopenfilename(title="Import a scene file",
                                            filetypes=[("Scene JSON", "*.json")])
        if source:
            self._scene_result(gp.import_scene_action(self.scenes_file, source))

    def on_scene_export(self):
        name = self._selected_scene()
        dest = filedialog.asksaveasfilename(title="Export scene", defaultextension=".json",
                                            initialfile=name + ".json")
        if dest:  # the file dialog already asked about replacing an existing file
            self._scene_result(gp.export_scene_action(
                self.scenes_file, name, dest, force=True))

    def current_overlay_draft(self):
        kind = self.ov_kind.get()
        draft = gp.OverlayDraft(kind=kind, corner=self.ov_corner.get(),
                                size=int(self.ov_size.get()))
        if kind == "image":
            draft.path = self.ov_text.get()
            draft.size = max(gp.MIN_PERCENT, min(gp.MAX_PERCENT, draft.size // 4))
        else:
            draft.text = self.ov_text.get()
        return draft

    def update_overlay_preview(self):
        self.ov_preview.config(text=gp.overlay_preview(self.current_overlay_draft()))

    def on_overlay_add(self):
        try:
            self.overlays.add(self.current_overlay_draft())
            self.status.set("%d overlay(s) ready. Press Save Scene on the Scenes page."
                            % len(self.overlays.drafts))
        except ValueError as exc:
            self.status.set(str(exc))

    # -- timer ----------------------------------------------------------------
    def poll(self):
        text, color, help_text, log_text, running = self.controller.snapshot()
        self.banner.config(text=text, bg=BANNER_COLORS[color])
        if help_text:
            self.status.set(help_text)
        if "dashboard" in self._pages:
            self._poll_dashboard(running, log_text)
        self.root.after(POLL_MS, self.poll)

    def _poll_dashboard(self, running, log_text):
        if self.root.winfo_viewable():  # sampler skips ticks until 2 s have passed
            sample = self.telemetry.tick_if_due()
            if sample is not None:
                for label, card in zip(self.telemetry_values, gp.telemetry_cards(sample)):
                    label.config(text=card.value)
        for label, card in zip(self.card_values,
                               gp.health_cards(self.controller.health_summary())):
            label.config(text=card.value)
        self.advice.config(text="\n".join(
            filter(None, [self.controller.health_advice()]
                   + self.controller.insight_lines())) if running else "")
        self.start_btn.config(state="disabled" if running else "normal")
        self.test_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")
        self._show_recommendations(self.inbox.visible(self.controller.recommendations()))
        if log_text != self._shown_log:
            self._shown_log = log_text
            self.log.config(state="normal")
            self.log.delete("1.0", "end")
            self.log.insert("end", log_text)
            self.log.see("end")
            self.log.config(state="disabled")

    def _show_recommendations(self, recs):
        """Rebuild the suggestion rows only when the list changed."""
        if recs == self._shown_recs:
            return
        self._shown_recs = recs
        for child in self.rec_frame.winfo_children():
            child.destroy()
        if not recs:
            ttk.Label(self.rec_frame, text="None right now.").pack(anchor="w")
        for rec in recs:
            row = ttk.Frame(self.rec_frame)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=rec.message, wraplength=WRAP - 120,
                      justify="left").pack(side="left", fill="x", expand=True)
            if gp.can_apply(rec):
                ttk.Button(row, text="Apply", command=lambda r=rec: self.on_recommendation(
                    r, True)).pack(side="left", padx=2)
            ttk.Button(row, text="Dismiss", command=lambda r=rec: self.on_recommendation(
                r, False)).pack(side="left")

    def offer_ffmpeg_help(self):
        """Friendly first-run dialog when FFmpeg is missing. Thin: logic is in portable.py."""
        dialog = tk.Toplevel(self.root)
        dialog.title("FFmpeg needed")
        ttk.Label(dialog, text=ffmpeg_guidance(), font=TEXT_FONT, justify="left",
                  wraplength=WRAP).pack(padx=16, pady=12)
        status = ttk.Label(dialog, text="", wraplength=WRAP)
        status.pack(padx=16)

        def choose():
            path = filedialog.askopenfilename(title="Choose ffmpeg file")
            if not path:
                return
            ok, message = validate_ffmpeg(path)
            if not ok:
                status.config(text=message)
                return
            try:
                save_configured_ffmpeg(path)
            except (OSError, ValueError) as err:
                status.config(text="Could not save the setting: %s" % err)
                return
            dialog.destroy()

        row = ttk.Frame(dialog)
        row.pack(pady=12)
        ttk.Button(row, text="Open download page",
                   command=lambda: webbrowser.open(ffmpeg_download_url())).pack(side="left", padx=4)
        ttk.Button(row, text="Choose ffmpeg file...", command=choose).pack(side="left", padx=4)
        ttk.Button(row, text="Close", command=dialog.destroy).pack(side="left", padx=4)

    def on_close(self, waited=0):
        """Ask ffmpeg to stop, then close once it has (or after a few seconds)."""
        self.controller.stop(wait=False)
        if self.controller.is_running() and waited < CLOSE_WAIT_MS:
            self.root.after(100, lambda: self.on_close(waited + 100))
        else:
            self.root.destroy()


def main(argv=None):
    if tk is None:
        print(NO_GUI_MESSAGE)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError:
        print(NO_GUI_MESSAGE)
        return 1
    window = StreamWindow(root)
    if find_ffmpeg() is None:
        root.after(200, window.offer_ffmpeg_help)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
