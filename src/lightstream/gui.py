"""Friendly window for starting a stream in 3 steps. Thin: logic is in gui_controller."""

import io
import os
import sys

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # some Linux Pythons ship without tkinter
    tk = None
    ttk = None

from . import gui_controller as gc
from .cli import cmd_doctor

POLL_MS = 500
TITLE_FONT = ("Segoe UI", 20, "bold")
STEP_FONT = ("Segoe UI", 14, "bold")
TEXT_FONT = ("Segoe UI", 13)
BUTTON_FONT = ("Segoe UI", 22, "bold")
LOG_FONT = ("Consolas", 10)
BANNER_COLORS = {"grey": "#555555", "orange": "#B35900",
                 "green": "#1B7F3B", "red": "#B00020"}
NO_GUI_MESSAGE = ("The window could not open. This computer has no screen "
                  "for it (or Python has no 'tkinter').\n"
                  "You can still use the command line: lightstream start")


class StreamWindow:
    def __init__(self, root):
        self.root = root
        self.controller = gc.StreamController(display=os.environ.get("DISPLAY"))
        self.prefs_file = gc.prefs_path()
        saved = gc.load_prefs(self.prefs_file)
        root.title("Lightstream - easy streaming")
        root.minsize(560, 640)
        self._build(saved)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Return>", lambda _e: self.on_start())
        self.poll()

    def _build(self, saved):
        pad = {"padx": 16, "pady": 6}
        frame = ttk.Frame(self.root, padding=8)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="Let's go live!", font=TITLE_FONT).pack(**pad)

        tk.Label(frame, text="1. Where do you want to stream?",
                 font=STEP_FONT, anchor="w").pack(fill="x", **pad)
        self.platform = tk.StringVar(value=gc.label_for(
            gc.PLATFORM_CHOICES, saved.get("platform", "twitch")))
        ttk.Combobox(frame, textvariable=self.platform, state="readonly",
                     font=TEXT_FONT, values=[l for l, _ in gc.PLATFORM_CHOICES]
                     ).pack(fill="x", **pad)
        self.url = tk.StringVar(value=saved.get("url") or "")
        tk.Label(frame, text="(Other site only) address starting with rtmp://",
                 font=TEXT_FONT, anchor="w").pack(fill="x", padx=16)
        tk.Entry(frame, textvariable=self.url, font=TEXT_FONT).pack(fill="x", **pad)

        tk.Label(frame, text="2. Paste your secret stream key",
                 font=STEP_FONT, anchor="w").pack(fill="x", **pad)
        self.key = tk.StringVar()
        self.key_entry = tk.Entry(frame, textvariable=self.key, show="*",
                                  font=TEXT_FONT)
        self.key_entry.pack(fill="x", **pad)
        self.show_key = tk.BooleanVar(value=False)
        tk.Checkbutton(frame, text="Show the key", font=TEXT_FONT,
                       variable=self.show_key, command=self.toggle_key
                       ).pack(anchor="w", padx=16)
        tk.Label(frame, text="Never show your key to anyone. It is not saved.",
                 font=TEXT_FONT, anchor="w").pack(fill="x", padx=16)

        tk.Label(frame, text="3. How good is your PC?", font=STEP_FONT,
                 anchor="w").pack(fill="x", **pad)
        self.strength = tk.StringVar(value=gc.label_for(
            gc.STRENGTH_CHOICES, saved.get("preset") or gc.suggest_strength(os.cpu_count())))
        ttk.Combobox(frame, textvariable=self.strength, state="readonly",
                     font=TEXT_FONT, values=[l for l, _ in gc.STRENGTH_CHOICES]
                     ).pack(fill="x", **pad)
        tk.Label(frame, text="Not sure? Pick 'Old PC (light)'.",
                 font=TEXT_FONT, anchor="w").pack(fill="x", padx=16)

        buttons = tk.Frame(frame)
        buttons.pack(fill="x", **pad)
        self.start_btn = tk.Button(buttons, text="START", font=BUTTON_FONT,
                                   bg="#1B7F3B", fg="white", command=self.on_start)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=4)
        self.stop_btn = tk.Button(buttons, text="STOP", font=BUTTON_FONT,
                                  bg="#B00020", fg="white", command=self.on_stop,
                                  state="disabled")
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=4)

        self.banner = tk.Label(frame, text="", font=STEP_FONT, fg="white",
                               wraplength=520, pady=10)
        self.banner.pack(fill="x", **pad)
        self.help = tk.Label(frame, text="", font=TEXT_FONT, wraplength=520,
                             justify="left", anchor="w", fg="#B00020")
        self.help.pack(fill="x", padx=16)

        ttk.Button(frame, text="Check my PC", command=self.on_doctor
                   ).pack(anchor="w", **pad)

        self.advanced_open = False
        self.advanced_btn = ttk.Button(frame, text="Show advanced options",
                                       command=self.toggle_advanced)
        self.advanced_btn.pack(anchor="w", **pad)
        self.advanced = tk.Frame(frame)
        self.fps = tk.StringVar(value=str(saved.get("fps") or ""))
        self.bitrate = tk.StringVar(value=str(saved.get("bitrate") or ""))
        self.window_title = tk.StringVar(value=saved.get("window") or "")
        self.audio = tk.StringVar(value=saved.get("audio_device") or "")
        self.keep_trying = tk.BooleanVar(value=bool(saved.get("keep_trying")))
        for label, var in (("Frames per second (empty = automatic)", self.fps),
                           ("Video kbps (empty = automatic)", self.bitrate),
                           ("Window title (Windows only)", self.window_title),
                           ("Audio device (empty = automatic)", self.audio)):
            tk.Label(self.advanced, text=label, font=TEXT_FONT, anchor="w"
                     ).pack(fill="x")
            tk.Entry(self.advanced, textvariable=var, font=TEXT_FONT
                     ).pack(fill="x", pady=2)
        tk.Checkbutton(self.advanced, text="Keep trying if the internet drops",
                       font=TEXT_FONT, variable=self.keep_trying).pack(anchor="w")

        self.log = tk.Text(frame, height=6, font=LOG_FONT, state="disabled")
        self.log.pack(fill="both", expand=True, **pad)

    def toggle_key(self):
        self.key_entry.config(show="" if self.show_key.get() else "*")

    def toggle_advanced(self):
        self.advanced_open = not self.advanced_open
        if self.advanced_open:
            self.advanced.pack(fill="x", padx=16, after=self.advanced_btn)
            self.advanced_btn.config(text="Hide advanced options")
        else:
            self.advanced.pack_forget()
            self.advanced_btn.config(text="Show advanced options")

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
        }

    def on_start(self):
        prefs = self.collect_prefs()
        error = self.controller.start(prefs, self.key.get())
        if error is None:
            try:
                gc.save_prefs(self.prefs_file, prefs)
            except OSError:
                pass  # remembering choices is optional

    def on_stop(self):
        self.controller.stop()

    def on_doctor(self):
        buffer = io.StringIO()
        cmd_doctor(buffer)
        self.help.config(text=buffer.getvalue().strip(), fg="#222222")

    def poll(self):
        text, color, help_text, log_text, running = self.controller.snapshot()
        self.banner.config(text=text, bg=BANNER_COLORS[color])
        if help_text:
            self.help.config(text=help_text, fg="#B00020")
        self.start_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", log_text)
        self.log.see("end")
        self.log.config(state="disabled")
        self.root.after(POLL_MS, self.poll)

    def on_close(self):
        self.controller.stop()
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
    StreamWindow(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
