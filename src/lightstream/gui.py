"""Sidebar window for streaming. Thin: logic is in gui_controller and gui_pages.

Native ttk widgets plus one small tk.Canvas per sparkline graph; no embedded browser. Each page
is built the first time it is opened, so unused pages cost no memory.
tkinter is imported guarded so this module imports (and the tests run) on
machines without a display or without tkinter. Window rendering is UNVERIFIED:
it has not been run on a screen in this repository's test environment.
"""

import io
import os
import sys
import time
import webbrowser

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter import font as tkfont
except ImportError:  # some Linux Pythons ship without tkinter
    tk = None
    ttk = None
    tkfont = None
    filedialog = None

from . import gui_controller as gc
from . import gui_pages as gp
from . import gui_theme as gt
from . import remote as rm
from .telemetry import TelemetrySampler, UNKNOWN_SAMPLE
from .cli import cmd_doctor
from .config import scenes_path
from .portable import (ffmpeg_download_url, ffmpeg_guidance, find_ffmpeg,
                       is_portable, save_configured_ffmpeg, validate_ffmpeg)

POLL_MS = 500
# Health card readings that ease toward a new value: (summary key, text template).
# They are the first cards of gp.health_cards, in the same order.
EASED_READINGS = (("recent_speed", "%.2fx"), ("recent_fps", "%.0f"),
                  ("recent_bitrate_kbps", "%.0f kbps"))
CLOSE_WAIT_MS = 5000
APP_NAME = "LightStream"
TAGLINE = "Streaming made simple"
WRAP = 560
GRAPH_NAMES = tuple(name for name, _ in gt.SERIES)
GRAPH_COLUMNS = 4
GRAPH_SAMPLES = 60  # one reading per redraw (about 1 Hz): the last minute
GRAPH_SIZE = (150, 40)
GRAPH_TITLES = dict(gt.SERIES)
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
        self.ui_file = gt.ui_prefs_path(self.prefs_file)
        look = gt.load_ui_prefs(self.ui_file)
        self.theme, self.compact = look["theme"], look["compact"]
        self.reduce_motion = look["reduce_motion"]
        self.eased_targets = [None] * len(EASED_READINGS)
        self.eased_shown = [None] * len(EASED_READINGS)
        self._animating = False
        self.graph_data = gt.PerformanceBuffers(GRAPH_SAMPLES)
        self.graph_canvases = {}
        self.redraw_gate = gt.RedrawGate(1.0)
        root.title(APP_NAME + (" (portable)" if is_portable() else ""))
        self._init_fonts()
        (width, height), self.min_size = gt.fit_window(
            root.winfo_screenwidth(), root.winfo_screenheight())
        root.geometry(self._centered_geometry(width, height))
        root.minsize(*self.min_size)
        self._init_variables(saved)
        self._pages = {}
        self._build_shell()
        self.show_page(gp.DEFAULT_PAGE)
        self.apply_look()
        self._bind_shortcuts()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.poll()

    def _init_fonts(self):
        """Pick installed font families (Segoe UI only exists on Windows)."""
        try:
            families = tkfont.families(self.root)
        except tk.TclError:
            families = ()
        self.family = gt.pick_font_family(families)
        self.mono_family = gt.pick_font_family(
            families, gt.MONO_PREFERENCE, gt.FALLBACK_MONO_FONT)

    def _centered_geometry(self, width, height):
        x, y = gt.center_position(self.root.winfo_screenwidth(),
                                  self.root.winfo_screenheight(), width, height)
        return "%dx%d+%d+%d" % (width, height, x, y)

    def font(self, role, weight="normal"):
        """Tk font tuple for a size role in gt.FONT_SIZES at the current density."""
        return (self.family, gt.font_sizes(self.compact)[role], weight)

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
        self.record_format = tk.StringVar(value=gc.label_for(
            gc.RECORD_FORMAT_CHOICES, saved.get("record_format")))
        self.rate_mode = tk.StringVar(value=gc.label_for(
            gc.RATE_MODE_CHOICES, saved.get("rate_mode")))
        self.potato = tk.StringVar(value=gc.label_for(
            gc.POTATO_CHOICES, saved.get("potato")))
        self.potato_grayscale = tk.BooleanVar(value=bool(saved.get("potato_grayscale")))
        self.potato_skip_static = tk.BooleanVar(value=bool(saved.get("potato_skip_static")))
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
        self.guardian = tk.BooleanVar(value=saved.get("guardian") is True)
        self.auto_survival = tk.BooleanVar(value=saved.get("auto_survival") is True)
        self.persistent_ingest = tk.BooleanVar(
            value=saved.get("persistent_ingest") is True)
        self.remote = tk.BooleanVar(value=saved.get("remote") is True)
        # Never restored: the home-network choice is made fresh each session.
        self.remote_lan = tk.BooleanVar(value=False)
        self.remote_url = tk.StringVar(value="")
        self.remote_session = rm.RemoteSession(self.controller)
        self.backup_url = tk.StringVar(value=saved.get("backup_url") or "")
        self.noise = saved.get("noise")
        self.status = tk.StringVar(value="")

    # -- shell: sidebar, page area, always-visible banner ---------------------
    def _build_shell(self):
        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True)
        self.outer = outer
        sidebar = ttk.Frame(outer, style="Sidebar.TFrame", padding=(10, 14))
        sidebar.pack(side="left", fill="y")
        self.title_label = ttk.Label(sidebar, text=APP_NAME, style="Brand.TLabel")
        self.title_label.pack(anchor="w")
        self.tagline_label = ttk.Label(sidebar, text=TAGLINE, style="SidebarHint.TLabel",
                                       wraplength=170, justify="left")
        self.tagline_label.pack(anchor="w", pady=(0, 14))
        self.page_var = tk.StringVar()
        for page_id, label in gp.PAGES:
            ttk.Radiobutton(sidebar, text=gt.with_accelerator(label, "page:" + page_id),
                            value=page_id, variable=self.page_var,
                            style="Nav.Toolbutton", takefocus=True,
                            command=lambda p=page_id: self.show_page(p)
                            ).pack(fill="x", pady=1)
        self.sidebar = sidebar
        self.reduce_motion_var = tk.BooleanVar(value=self.reduce_motion)
        ttk.Checkbutton(sidebar, text="Reduce motion", variable=self.reduce_motion_var,
                        command=self.on_reduce_motion).pack(
                            side="bottom", fill="x", pady=(3, 0))
        self.theme_var = tk.StringVar(value=gt.THEME_LABELS[self.theme])
        self.theme_picker = ttk.Combobox(
            sidebar, textvariable=self.theme_var, state="readonly", takefocus=True,
            values=[gt.THEME_LABELS[name] for name in gt.THEMES])
        self.theme_picker.pack(side="bottom", fill="x", pady=(3, 0))
        self.theme_picker.bind("<<ComboboxSelected>>", self.on_pick_theme)
        ttk.Label(sidebar, text=gt.with_accelerator("Theme", "theme"),
                  style="SidebarHint.TLabel").pack(side="bottom", anchor="w")
        ttk.Button(sidebar, text=gt.with_accelerator("Compact", "compact"),
                   command=self.on_toggle_compact).pack(side="bottom", fill="x", pady=(3, 0))
        right = ttk.Frame(outer, padding=(14, 12))
        right.pack(side="left", fill="both", expand=True)
        self.right = right
        self.banner_row = tk.Frame(right, highlightthickness=0, borderwidth=0)
        self.banner_row.pack(fill="x")
        self.banner_bar = tk.Frame(self.banner_row, width=6, highlightthickness=0,
                                   borderwidth=0)
        self.banner_bar.pack(side="left", fill="y")
        self.banner = tk.Label(self.banner_row, text="", wraplength=WRAP, pady=10,
                               padx=12, anchor="w", justify="left")
        self.banner.pack(side="left", fill="x", expand=True)
        self.status_label = ttk.Label(right, textvariable=self.status, wraplength=WRAP,
                                      justify="left", style="Hint.TLabel")
        self.status.trace_add("write", self._on_status_changed)
        self._build_page_area(right)

    def _on_status_changed(self, *_args):
        """Show the status line only while it has text (no blank strip)."""
        if self.status.get():
            if not self.status_label.winfo_manager():
                self.status_label.pack(side="bottom", fill="x", pady=(6, 0),
                                       before=self.page_holder)
        else:
            self.status_label.pack_forget()

    def _build_page_area(self, parent):
        """Scrollable area: every page stays reachable on a small screen."""
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True, pady=(10, 0))
        self.page_holder = holder
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.page_canvas = tk.Canvas(holder, highlightthickness=0, borderwidth=0,
                                     takefocus=False)
        self.page_scroll = ttk.Scrollbar(holder, orient="vertical",
                                         command=self.page_canvas.yview)
        self.page_canvas.configure(yscrollcommand=self._on_page_scrolled)
        self.page_canvas.grid(row=0, column=0, sticky="nsew")
        self.page_area = ttk.Frame(self.page_canvas)
        self._page_window = self.page_canvas.create_window(
            (0, 0), window=self.page_area, anchor="nw")
        self.page_canvas.bind("<Configure>", self._on_page_resized)
        self.page_area.bind("<Configure>", self._on_page_content_resized)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.bind_all(sequence, self._on_wheel, add="+")

    def _on_page_scrolled(self, first, last):
        self.page_scroll.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.page_scroll.grid_remove()
        else:
            self.page_scroll.grid(row=0, column=1, sticky="ns", padx=(10, 0))

    def _on_page_resized(self, event):
        self.page_canvas.itemconfigure(self._page_window, width=event.width)

    def _on_page_content_resized(self, _event):
        self.page_canvas.configure(scrollregion=self.page_canvas.bbox("all"))

    def _on_wheel(self, event):
        widget = event.widget
        if not hasattr(widget, "winfo_toplevel") or widget.winfo_toplevel() is not self.root:
            return  # a dialog or other window: not ours to scroll
        if widget.winfo_class() in ("Text", "Listbox", "TCombobox", "TSpinbox", "Spinbox"):
            return  # these scroll or change themselves
        content = self.page_area.winfo_reqheight()
        if not gt.needs_scrollbar(content, self.page_canvas.winfo_height()):
            return
        steps = gt.scroll_steps(getattr(event, "num", None), getattr(event, "delta", 0))
        if steps:
            self.page_canvas.yview_scroll(steps * 3, "units")

    def show_page(self, page_id):
        page_id = gp.resolve_page(page_id)
        self.page_var.set(page_id)
        for frame in self._pages.values():
            frame.pack_forget()
        if page_id not in self._pages:
            frame = ttk.Frame(self.page_area, padding=(2, 4))
            getattr(self, "_build_" + page_id)(frame)
            self._pages[page_id] = frame
            self._style_plain_widgets()
        self._pages[page_id].pack(fill="both", expand=True)
        self.page_canvas.yview_moveto(0)

    def _label(self, parent, text, style="TLabel", top=8):
        label = ttk.Label(parent, text=text, style=style, wraplength=WRAP, justify="left")
        label.pack(anchor="w", pady=(top, 0))
        return label

    def _heading(self, parent, text):
        return self._label(parent, text, "Heading.TLabel", top=0)

    def _hint(self, parent, text):
        return self._label(parent, text, "Hint.TLabel", top=2)

    def _entry(self, parent, label, variable, show=None, hint=None):
        self._label(parent, label)
        if hint:
            self._hint(parent, hint)
        entry = ttk.Entry(parent, textvariable=variable, show=show or "")
        entry.pack(fill="x", pady=(2, 0))
        return entry

    def _combo(self, parent, label, variable, values, hint=None):
        self._label(parent, label)
        if hint:
            self._hint(parent, hint)
        ttk.Combobox(parent, textvariable=variable, state="readonly",
                     values=values).pack(fill="x", pady=(2, 0))

    def _card(self, parent, title, style="Card"):
        """Bordered card with a heading. Returns the body frame to fill."""
        outer = ttk.Frame(parent, style="Card.TFrame", padding=(12, 8))
        outer.pack(fill="x", pady=(8, 0))
        ttk.Label(outer, text=title, style="CardHeading.TLabel").pack(anchor="w")
        body = ttk.Frame(outer, style="CardBody.TFrame")
        body.pack(fill="x", pady=(4, 0))
        return body

    def _big_button(self, parent, text, command, kind, enabled, **pack):
        button = tk.Button(parent, text=text, command=command, relief="flat",
                           borderwidth=0, cursor="hand2", pady=8,
                           takefocus=True, highlightthickness=2)
        button.kind = kind
        button.pack(**pack)
        self._paint_big_button(button, enabled)
        return button

    def _paint_big_button(self, button, enabled):
        background, foreground = gt.big_button_colors(self.theme, button.kind, enabled)
        colors = gt.palette(self.theme)
        button.config(bg=background, fg=foreground, disabledforeground=foreground,
                      activebackground=background, activeforeground=foreground,
                      highlightbackground=background, highlightcolor=colors["focus"],
                      font=self.font("step" if button.kind == "emergency" else "button",
                                     "bold"),
                      state="normal" if enabled else "disabled")

    def _set_big_button(self, button, enabled, text=None):
        """Repaint only when the state changes (the poll runs twice a second)."""
        wanted = "normal" if enabled else "disabled"
        if text is not None:
            button.config(text=text)
        if str(button.cget("state")) != wanted:
            self._paint_big_button(button, enabled)

    # -- pages ----------------------------------------------------------------
    def _build_dashboard(self, frame):
        go = self._card(frame, "Go live")
        go.columnconfigure(0, weight=1, uniform="go")
        go.columnconfigure(1, weight=1, uniform="go")
        self._grid_field(go, 0, 0, "Where do you want to stream?",
                         ttk.Combobox(go, textvariable=self.platform, state="readonly",
                                      values=[l for l, _ in gc.PLATFORM_CHOICES]))
        self._grid_field(go, 0, 1, "How good is your PC?",
                         ttk.Combobox(go, textvariable=self.strength, state="readonly",
                                      values=[l for l, _ in gc.STRENGTH_CHOICES]))
        self._grid_field(go, 2, 0, "Other site only: address starting with rtmp://",
                         ttk.Entry(go, textvariable=self.url))
        self.key_entry = ttk.Entry(go, textvariable=self.key, show="*")
        self._grid_field(go, 2, 1, "Secret stream key (never saved)", self.key_entry)
        ttk.Checkbutton(go, text="Show the key", variable=self.show_key,
                        style="Card.TCheckbutton", command=self.toggle_key
                        ).grid(row=4, column=1, sticky="w", padx=(0, 0), pady=(4, 0))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        self.start_btn = self._big_button(
            buttons, gt.with_accelerator("START", "start"), self.on_start,
            "start", True, side="left", expand=True, fill="x", padx=(0, 6))
        self.stop_btn = self._big_button(
            buttons, gt.with_accelerator("STOP", "stop"), self.on_stop,
            "stop", False, side="left", expand=True, fill="x", padx=(6, 0))
        self.emergency_btn = self._big_button(
            frame, gp.emergency_button_label(False), self.on_emergency,
            "emergency", False, fill="x", pady=(8, 0))
        self.test_btn = ttk.Button(frame, text="Test first: record 10 seconds to a "
                                   "file (not live)", command=self.on_test)
        self.test_btn.pack(anchor="w", pady=(8, 0))
        body = self._card(frame, "Stream health")
        self.card_values = []
        for index, card in enumerate(gp.health_cards({})):
            body.columnconfigure(index, weight=1, uniform="health")
            ttk.Label(body, text=card.title, style="CardCaption.TLabel", wraplength=110,
                      justify="left").grid(row=0, column=index, padx=6, sticky="w")
            value = ttk.Label(body, text=card.value, style="CardValue.TLabel")
            value.grid(row=1, column=index, padx=6, sticky="w")
            self.card_values.append(value)
        self._build_graphs(frame)
        body = self._card(frame, "This PC")
        self.telemetry_values = []
        for index, card in enumerate(gp.telemetry_cards(UNKNOWN_SAMPLE)):
            body.columnconfigure(index, weight=1, uniform="pc")
            ttk.Label(body, text=card.title, style="CardCaption.TLabel", wraplength=90,
                      justify="left").grid(row=0, column=index, padx=6, sticky="w")
            value = ttk.Label(body, text=card.value, style="CardSmallValue.TLabel")
            value.grid(row=1, column=index, padx=6, sticky="w")
            self.telemetry_values.append(value)
        self.telemetry = TelemetrySampler()
        self.health_label = ttk.Label(frame, text="", wraplength=WRAP, justify="left")
        self.health_label.pack(fill="x", pady=(8, 0))
        ttk.Button(frame, text="Compare last two saved sessions",
                   command=self.on_compare).pack(anchor="w", pady=(8, 0))
        self.compare_label = ttk.Label(frame, text="", wraplength=WRAP, justify="left")
        self.compare_label.pack(fill="x")
        self.advice = ttk.Label(frame, text="", wraplength=WRAP, justify="left")
        self.advice.pack(fill="x")
        self.timeline_view = tk.Text(frame, height=4, state="disabled", relief="flat",
                                     borderwidth=1, highlightthickness=1, padx=6, pady=4)
        self.timeline_view.pack(fill="x", pady=(8, 0))
        self._shown_timeline = None
        self.rec_frame = self._card(
            frame, "Suggestions (nothing changes unless you press Apply)")
        self._shown_recs = None
        self.log = tk.Text(frame, height=5, state="disabled", relief="flat",
                           borderwidth=1, highlightthickness=1, padx=6, pady=4)
        self.log.pack(fill="both", expand=True, pady=(8, 0))

    def _grid_field(self, parent, row, column, label, widget):
        """Caption above a control, two fields per row, on a card."""
        pad = (0, 8) if column == 0 else (8, 0)
        ttk.Label(parent, text=label, style="Card.TLabel", wraplength=WRAP // 2 - 12,
                  justify="left").grid(row=row, column=column, sticky="w", padx=pad,
                                       pady=(6 if row else 0, 0))
        widget.grid(row=row + 1, column=column, sticky="ew", padx=pad, pady=(2, 0))

    def _build_graphs(self, frame):
        """Small line graphs of the last minute. Failure here must not break the page."""
        graphs = self._card(frame, "Last minute")
        try:
            for index, name in enumerate(GRAPH_NAMES):
                row, column = divmod(index, GRAPH_COLUMNS)
                graphs.columnconfigure(column, weight=1, uniform="graph")
                ttk.Label(graphs, text=GRAPH_TITLES[name], style="CardCaption.TLabel"
                          ).grid(row=row * 2, column=column, padx=6, sticky="w",
                                 pady=(4 if row else 0, 0))
                canvas = tk.Canvas(graphs, width=GRAPH_SIZE[0], height=GRAPH_SIZE[1],
                                   highlightthickness=1, takefocus=False)
                canvas.grid(row=row * 2 + 1, column=column, padx=6, sticky="ew")
                self.graph_canvases[name] = canvas
        except tk.TclError:
            self.graph_canvases = {}  # numbers on the cards still work
        self._style_graphs()

    def _style_graphs(self):
        colors = gt.palette(self.theme)
        for canvas in self.graph_canvases.values():
            canvas.config(bg=colors["graph_back"], highlightbackground=colors["card_border"])
        self._draw_graphs()

    def _record_graphs(self, summary, sample):
        """Add one reading per graph. Called at most once per second."""
        self.graph_data.record(summary, sample)

    def _draw_graphs(self):
        colors = gt.palette(self.theme)
        _width, height = GRAPH_SIZE
        for name, canvas in self.graph_canvases.items():
            canvas.delete("all")
            width = max(canvas.winfo_width(), GRAPH_SIZE[0])
            for y in gt.graph_grid_ys(height):
                canvas.create_line(0, y, width, y, fill=colors["graph_grid"])
            raw = self.graph_data.values(name)
            if gt.graph_is_empty(raw):
                canvas.create_text(width // 2, height // 2, text=gt.EMPTY_GRAPH_TEXT,
                                   fill=colors["muted"], font=self.font("caption"))
                continue
            values = gt.downsample(raw, width // 2)
            coords = gt.sparkline_points(values, width, height)
            if coords:
                canvas.create_line(*coords, fill=colors["graph_line"], width=2)

    # -- look: theme, compact mode, shortcuts -----------------------------------
    def apply_look(self):
        """Apply theme colors, fonts and compact mode. A Tk failure keeps the old look."""
        colors = gt.palette(self.theme)
        sizes = gt.font_sizes(self.compact)
        try:
            self._configure_named_fonts(sizes)
            style = ttk.Style(self.root)
            if "clam" in style.theme_names():
                style.theme_use("clam")  # the only built-in theme that honors colors everywhere
            self._configure_styles(style, colors)
            self.root.configure(background=colors["background"])
            self.page_canvas.configure(background=colors["background"])
            self.banner.config(font=self.font("step", "bold"))
            self._style_plain_widgets()
            self._style_graphs()
            self._repaint_dynamic()
            if self.compact:
                self.right.pack_forget()
                self.root.minsize(160, 200)
                self.root.geometry("")  # shrink to the sidebar
            elif not self.right.winfo_manager():
                self.right.pack(side="left", fill="both", expand=True)
                (width, height), self.min_size = gt.fit_window(
                    self.root.winfo_screenwidth(), self.root.winfo_screenheight())
                self.root.minsize(*self.min_size)
                self.root.geometry(self._centered_geometry(width, height))
        except tk.TclError as err:
            self.status.set("Could not change the look: %s" % err)

    def _configure_named_fonts(self, sizes):
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(name).configure(family=self.family, size=sizes["text"])
        tkfont.nametofont("TkFixedFont").configure(family=self.mono_family,
                                                   size=sizes["log"])

    def _configure_styles(self, style, c):
        text, bold = self.font("text"), self.font("text", "bold")
        style.configure(".", background=c["background"], foreground=c["foreground"],
                        bordercolor=c["card_border"], focuscolor=c["focus"],
                        lightcolor=c["card_border"], darkcolor=c["card_border"],
                        troughcolor=c["surface"], font=text)
        style.configure("TLabel", background=c["background"], foreground=c["foreground"])
        style.configure("Hint.TLabel", foreground=c["muted"], font=self.font("caption"))
        style.configure("Heading.TLabel", font=self.font("step", "bold"))
        style.configure("TCheckbutton", background=c["background"])
        style.configure("TRadiobutton", background=c["background"])
        style.map("TCheckbutton", background=[("active", c["background"])])
        for name in ("TCheckbutton", "Card.TCheckbutton", "TRadiobutton"):
            style.map(name,
                      indicatorbackground=[("selected", c["accent"]),
                                           ("!selected", c["surface"])],
                      indicatorforeground=[("selected", c["accent_fg"]),
                                           ("!selected", c["surface"])])
            style.configure(name, indicatorbackground=c["surface"],
                            indicatorforeground=c["accent_fg"],
                            upperbordercolor=c["card_border"],
                            lowerbordercolor=c["card_border"])
        # Cards: filled with the card color, so labels inside use Card.* styles.
        style.configure("Card.TFrame", background=c["card"], bordercolor=c["card_border"],
                        borderwidth=1, relief="solid")
        style.configure("CardBody.TFrame", background=c["card"], borderwidth=0,
                        relief="flat")
        style.configure("Card.TLabel", background=c["card"], foreground=c["foreground"])
        style.configure("Card.TCheckbutton", background=c["card"],
                        foreground=c["foreground"])
        style.map("Card.TCheckbutton", background=[("active", c["card"])])
        style.configure("CardHeading.TLabel", background=c["card"],
                        foreground=c["foreground"], font=self.font("step", "bold"))
        style.configure("CardCaption.TLabel", background=c["card"], foreground=c["muted"],
                        font=self.font("caption"))
        style.configure("CardValue.TLabel", background=c["card"],
                        foreground=c["foreground"], font=self.font("value", "bold"))
        style.configure("CardSmallValue.TLabel", background=c["card"],
                        foreground=c["foreground"], font=bold)
        # Buttons: calm secondary, blue accent for the main action.
        style.configure("TButton", background=c["button_bg"], foreground=c["foreground"],
                        bordercolor=c["card_border"], padding=(12, 6), relief="flat")
        style.map("TButton", background=[("active", c["button_hover"])],
                  foreground=[("disabled", c["muted"])])
        style.configure("Accent.TButton", background=c["accent"],
                        foreground=c["accent_fg"], bordercolor=c["accent"],
                        padding=(14, 8), font=bold)
        style.map("Accent.TButton", background=[("active", c["accent_hover"])],
                  foreground=[("disabled", c["muted"])])
        style.configure("TEntry", fieldbackground=c["surface"], foreground=c["foreground"],
                        insertcolor=c["foreground"], padding=4)
        style.configure("TCombobox", fieldbackground=c["surface"], background=c["button_bg"],
                        foreground=c["foreground"], arrowcolor=c["foreground"], padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", c["surface"])],
                  foreground=[("readonly", c["foreground"])])
        style.configure("TScale", background=c["background"], troughcolor=c["surface"])
        style.configure("TScrollbar", background=c["button_bg"], troughcolor=c["trough"],
                        bordercolor=c["trough"], lightcolor=c["button_bg"],
                        darkcolor=c["button_bg"], arrowcolor=c["foreground"],
                        gripcount=0, arrowsize=14)
        style.map("TScrollbar", background=[("active", c["button_hover"])])
        self.root.option_add("*TCombobox*Listbox.background", c["surface"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["foreground"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", c["accent_fg"])
        # Sidebar
        style.configure("Sidebar.TFrame", background=c["sidebar"], borderwidth=0)
        style.configure("Brand.TLabel", background=c["sidebar"], foreground=c["foreground"],
                        font=self.font("title", "bold"))
        style.configure("SidebarHint.TLabel", background=c["sidebar"],
                        foreground=c["muted"], font=self.font("caption"))
        style.configure("Nav.Toolbutton", background=c["sidebar"],
                        foreground=c["foreground"], padding=(12, 8), anchor="w",
                        relief="flat", borderwidth=0, font=self.font("nav"))
        style.map("Nav.Toolbutton",
                  background=[("selected", c["accent"]), ("active", c["nav_hover"])],
                  foreground=[("selected", c["accent_fg"])])
        self.sidebar.configure(style="Sidebar.TFrame")
        self.title_label.config(font=self.font("title", "bold"))

    def _style_plain_widgets(self):
        """Classic tk widgets ignore ttk styles, so color them directly."""
        c = gt.palette(self.theme)
        for name in ("log", "timeline_view"):
            if hasattr(self, name):
                getattr(self, name).config(
                    bg=c["surface"], fg=c["foreground"], font="TkFixedFont",
                    insertbackground=c["foreground"],
                    highlightbackground=c["card_border"], highlightcolor=c["focus"])
        if hasattr(self, "scene_list"):
            self.scene_list.config(bg=c["surface"], fg=c["foreground"],
                                   selectbackground=c["accent"],
                                   selectforeground=c["accent_fg"],
                                   highlightbackground=c["card_border"],
                                   highlightcolor=c["focus"], relief="flat",
                                   font=self.font("text"))

    def _repaint_dynamic(self):
        """Repaint widgets whose colors depend on the current state."""
        text, color, _help, _log, running = self.controller.snapshot()
        self._paint_banner(text, color)
        if "dashboard" in self._pages:
            self._paint_big_button(self.start_btn, not running)
            self._paint_big_button(self.stop_btn, running)
            self._paint_big_button(self.emergency_btn, running)
            self._shown_recs = None

    def _paint_banner(self, text, color):
        background, foreground = gt.banner_colors(self.theme, color)
        self.banner_row.config(bg=background)
        self.banner_bar.config(bg=gt.banner_accent(self.theme, color))
        self.banner.config(text=text, bg=background, fg=foreground)

    def _save_look(self):
        try:
            gt.save_ui_prefs(self.ui_file, self.theme, self.compact,
                             self.reduce_motion)
        except OSError:
            pass  # remembering the look is optional

    def on_cycle_theme(self):
        self.set_theme(gt.cycle_theme(self.theme))

    def on_pick_theme(self, _event=None):
        labels = {label: name for name, label in gt.THEME_LABELS.items()}
        self.set_theme(labels.get(self.theme_var.get(), self.theme))
        self.theme_picker.selection_clear()

    def set_theme(self, theme):
        self.theme = theme
        self.theme_var.set(gt.THEME_LABELS[theme])
        self.apply_look()
        self._save_look()

    def on_reduce_motion(self):
        self.reduce_motion = self.reduce_motion_var.get()
        self._save_look()

    def motion_on(self):
        """Easing runs unless Reduce motion is set or Potato/Emergency is active."""
        potato = bool(gc.value_for(gc.POTATO_CHOICES, self.potato.get())) \
            or self.controller.emergency_active()
        return gt.animation_enabled({"reduce_motion": self.reduce_motion}, potato)

    def on_toggle_compact(self):
        self.compact = not self.compact
        self.apply_look()
        self._save_look()

    def _bind_shortcuts(self):
        for sequence, action, _text in gt.SHORTCUTS:
            try:
                self.root.bind(sequence, lambda _e, a=action: self.on_shortcut(a))
            except tk.TclError:
                pass  # a shortcut that cannot bind is skipped, buttons still work

    def on_shortcut(self, action):
        if action.startswith("page:"):
            if not self.compact:
                self.show_page(action.split(":", 1)[1])
        elif action == "theme":
            self.on_cycle_theme()
        elif action == "compact":
            self.on_toggle_compact()
        elif "dashboard" in self._pages:
            button = {"start": self.start_btn, "stop": self.stop_btn,
                      "emergency": self.emergency_btn}[action]
            if str(button.cget("state")) != "disabled":
                button.invoke()
        return "break"

    def _build_setup(self, frame):
        self._heading(frame, "Setup wizard")
        self._hint(frame, "Looks at this PC and picks safe settings. You can still "
                   "change everything afterwards.")
        ttk.Button(frame, text="One-click setup: pick safe settings for this PC",
                   style="Accent.TButton", command=self.on_setup
                   ).pack(anchor="w", pady=(12, 0))
        ttk.Button(frame, text="Optimize: propose settings (asks first)",
                   command=self.on_optimize).pack(anchor="w", pady=(8, 0))
        ttk.Button(frame, text="Check my PC", command=self.on_doctor
                   ).pack(anchor="w", pady=(8, 0))
        self._combo(frame, "PC type (hardware profile)", self.hardware,
                    gp.hardware_choices(),
                    hint="Leave on automatic unless the wizard guessed wrong.")

    def _build_scenes(self, frame):
        self._heading(frame, "Scenes")
        self._hint(frame, "A scene is a saved look for your stream, such as overlays.")
        self.scene_list = tk.Listbox(frame, height=8, exportselection=False,
                                     borderwidth=0, highlightthickness=1)
        self.scene_list.pack(fill="x", pady=(8, 0))
        self.scene_name = tk.StringVar()
        self._entry(frame, "Scene name (for Save Scene)", self.scene_name)
        row = ttk.Frame(frame)
        row.pack(anchor="w", pady=(10, 0))
        for text, command, style in (("Save Scene", self.on_scene_save, "Accent.TButton"),
                                     ("Duplicate Scene", self.on_scene_duplicate, "TButton"),
                                     ("Import Scene", self.on_scene_import, "TButton"),
                                     ("Export Scene", self.on_scene_export, "TButton")):
            ttk.Button(row, text=text, style=style, command=command
                       ).pack(side="left", padx=(0, 6))
        self._combo(frame, "Scene used when you press START", self.scene,
                    gc.scene_choices(self.scenes_file))
        self._refresh_scene_list()

    def _build_overlays(self, frame):
        self._heading(frame, "Overlays")
        self._hint(frame, "Drawn by FFmpeg and saved with Save Scene.")
        self.ov_kind = tk.StringVar(value="text")
        self.ov_text = tk.StringVar()
        self.ov_corner = tk.StringVar(value="top-left")
        self.ov_size = tk.IntVar(value=gp.size_range("text")[0] * 3)
        self.ov_path = tk.StringVar()
        self._combo(frame, "Kind", self.ov_kind, gp.OVERLAY_KIND_CHOICES)
        self._entry(frame, "Text (text overlays) or PNG path (image overlays)", self.ov_text)
        self._combo(frame, "Position", self.ov_corner, gp.CORNER_CHOICES)
        self._label(frame, "Scale")
        self._hint(frame, "Font size, or percent of width for images.")
        ttk.Scale(frame, from_=8, to=200, variable=self.ov_size, orient="horizontal",
                  command=lambda _v: self.update_overlay_preview()).pack(fill="x")
        for variable in (self.ov_kind, self.ov_text, self.ov_corner):
            variable.trace_add("write", lambda *_a: self.update_overlay_preview())
        self._label(frame, "Preview")
        self._hint(frame, "Filter text, not a picture.")
        self.ov_preview = ttk.Label(frame, text=gp.PREVIEW_PLACEHOLDER,
                                    wraplength=WRAP, justify="left", style="Hint.TLabel")
        self.ov_preview.pack(anchor="w", pady=(2, 0))
        ttk.Button(frame, text="Add to scene being built", style="Accent.TButton",
                   command=self.on_overlay_add).pack(anchor="w", pady=(12, 0))
        self.update_overlay_preview()

    def _build_recording(self, frame):
        self._heading(frame, "Recording")
        ttk.Checkbutton(frame, text="Record a copy to a file while streaming",
                        variable=self.record).pack(anchor="w", pady=(8, 0))
        self._hint(frame, "Files go to the recordings folder in the app data folder.")
        self._combo(frame, "File type", self.record_format,
                    [l for l, _ in gc.RECORD_FORMAT_CHOICES])
        self._combo(frame, "Bitrate mode", self.rate_mode,
                    [l for l, _ in gc.RATE_MODE_CHOICES])
        self._combo(frame, "Potato Stream", self.potato,
                    [l for l, _ in gc.POTATO_CHOICES],
                    hint="Very low CPU use for old PCs. Replaces size, frame rate and "
                    "quality. Grayscale and skipping still frames are options; neither "
                    "is guaranteed to save CPU.")
        ttk.Checkbutton(frame, text="Grayscale picture", variable=self.potato_grayscale
                        ).pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(frame, text="Skip near-identical frames",
                        variable=self.potato_skip_static).pack(anchor="w")
        ttk.Checkbutton(frame, text="Keep connection alive when quality changes "
                        "(persistent ingest)", variable=self.persistent_ingest
                        ).pack(anchor="w", pady=(8, 0))
        self._hint(frame, "Off by default. A separate copy-only process holds the "
                   "connection while the encoder restarts. The picture size stays "
                   "fixed, and it cannot be combined with a backup server address. "
                   "Emergency mode then keeps the size and lowers frame rate and bitrate.")

    def _build_advanced(self, frame):
        self._heading(frame, "Advanced")
        self._hint(frame, "Safe to leave empty. Empty means automatic.")
        for label, var in (("Frames per second (empty = automatic)", self.fps),
                           ("Video kbps (empty = automatic)", self.bitrate),
                           ("Window title (Windows only)", self.window_title),
                           ("Audio device (empty = automatic)", self.audio)):
            self._entry(frame, label, var)
        self._entry(frame, "Backup server address (optional)", self.backup_url,
                    hint="rtmp://host/app, no key. Used if the main one keeps failing.")
        self._combo(frame, "Hardware profile", self.hardware, gp.hardware_choices())
        self._combo(frame, "Performance profile", self.profile, gp.profile_choices(),
                    hint="Replaces Strength when chosen.")
        self._combo(frame, "Microphone profile", self.audio_profile,
                    gp.audio_profile_choices())
        for text, variable in (
                ("Auto-scale quality (off by default). When the stream struggles it "
                 "steps quality down, and back up when healthy. Each step restarts "
                 "the stream for a moment.", self.auto_scale),
                ("Performance Guardian (off by default). Turns on auto-scale and also "
                 "watches CPU, RAM, temperature and a bandwidth trend. Every step "
                 "restarts the encoder for a moment; persistent ingest keeps the "
                 "connection alive meanwhile.", self.guardian),
                ("Auto-survival (off by default). If CPU stays at 95% or RAM at 90% "
                 "for 10 seconds, keeps the picture size and audio but cuts frame rate, "
                 "bitrate and overlays, with a brief restart.", self.auto_survival),
                ("Mute (send silence)", self.mute),
                ("Keep trying if the internet drops", self.keep_trying),
                ("Save a session report after streaming (off by default, stays on "
                 "this PC, never contains your key)", self.analytics)):
            ttk.Checkbutton(frame, text=text, variable=variable).pack(
                anchor="w", pady=(8, 0))
        ttk.Checkbutton(frame, text=rm.REMOTE_LABEL, variable=self.remote).pack(
            anchor="w", pady=(8, 0))
        ttk.Checkbutton(frame, text=rm.REMOTE_LAN_LABEL,
                        variable=self.remote_lan).pack(anchor="w", padx=(20, 0))
        self._hint(frame, rm.REMOTE_LAN_WARNING + " " + rm.REMOTE_HINT)
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(2, 0))
        self.remote_entry = ttk.Entry(row, textvariable=self.remote_url,
                                      state="readonly")
        self.remote_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Copy link", command=self.on_copy_remote).pack(
            side="left", padx=(6, 0))

    # -- actions ---------------------------------------------------------------
    def on_copy_remote(self):
        if self.remote_url.get():
            self.root.clipboard_clear()
            self.root.clipboard_append(self.remote_url.get())
            self.status.set("Remote link copied.")
        else:
            self.status.set("The remote link appears once a stream is running.")
    def on_compare(self):
        self.compare_label.config(text="\n".join(self.controller.comparison_lines()))

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
            "record_format": gc.value_for(gc.RECORD_FORMAT_CHOICES, self.record_format.get()),
            "rate_mode": gc.value_for(gc.RATE_MODE_CHOICES, self.rate_mode.get()),
            "potato": gc.value_for(gc.POTATO_CHOICES, self.potato.get()),
            "potato_grayscale": self.potato_grayscale.get(),
            "potato_skip_static": self.potato_skip_static.get(),
            "hardware": gp.hardware_pref(self.hardware.get()),
            "noise": self.noise,
            "analytics": self.analytics.get(),
            "profile": gp.profile_pref(self.profile.get()),
            "audio_profile": gp.audio_profile_pref(self.audio_profile.get()),
            "auto_scale": self.auto_scale.get(),
            "backup_url": self.backup_url.get(),
            "persistent_ingest": self.persistent_ingest.get(),
            "guardian": self.guardian.get(),
            "auto_survival": self.auto_survival.get(),
            "remote": self.remote.get(),
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

    def on_optimize(self):
        """Show the proposed config changes; write them only after Yes."""
        platform = gc.value_for(gc.PLATFORM_CHOICES, self.platform.get())
        proposal, message = gc.optimize_proposal(platform=platform)
        if not proposal.diff:
            self.status.set("Optimize: your config already matches this PC.")
            return
        if messagebox.askyesno("Apply these changes?", message):
            gc.apply_optimization(proposal)
            self.status.set("Optimize applied. Restart the window to see the new settings.")
        else:
            self.status.set("Optimize: nothing changed.")

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

    def on_emergency(self):
        """One click, no confirmation. A second click restores the settings."""
        if self.controller.emergency_active():
            self.status.set(self.controller.restore_after_emergency())
        else:
            self.status.set(self.controller.emergency())

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
        self._paint_banner(text, color)
        self.remote_url.set(self.remote_session.sync(
            running, self.remote.get(), self.remote_lan.get()) or "")
        if help_text:
            self.status.set(help_text)
        if "dashboard" in self._pages:
            self._poll_dashboard(running, log_text)
        self.root.after(POLL_MS, self.poll)

    def _show_health_cards(self, summary):
        """Show the cards. Speed, fps and bitrate ease toward the new reading."""
        easing = self.motion_on()
        for index, (label, card) in enumerate(
                zip(self.card_values, gp.health_cards(summary))):
            if index >= len(EASED_READINGS):
                label.config(text=card.value)
                continue
            target = summary.get(EASED_READINGS[index][0])
            self.eased_targets[index] = target
            if not easing:
                self.eased_shown[index] = target
                label.config(text=card.value)
        if easing and not self._animating:
            self._animating = True
            self.root.after(gt.ANIMATION_TICK_MS, self._animate_cards)

    def _animate_cards(self):
        """One easing tick; stops rescheduling once every card reached its target."""
        moving = False
        for index, label in enumerate(self.card_values[:len(EASED_READINGS)]):
            shown = gt.ease_step(self.eased_shown[index], self.eased_targets[index])
            if shown != self.eased_shown[index]:
                self.eased_shown[index] = shown
                template = EASED_READINGS[index][1]
                label.config(text=gp.MISSING_VALUE if shown is None else template % shown)
            moving = moving or shown != self.eased_targets[index]
        if moving:
            self.root.after(gt.ANIMATION_TICK_MS, self._animate_cards)
        else:
            self._animating = False

    def _poll_dashboard(self, running, log_text):
        if self.root.winfo_viewable():  # sampler skips ticks until 2 s have passed
            sample = self.telemetry.tick_if_due()
            if sample is not None:
                for label, card in zip(self.telemetry_values, gp.telemetry_cards(sample)):
                    label.config(text=card.value)
        self._show_health_cards(self.controller.health_summary())
        self.advice.config(text="\n".join(
            filter(None, [self.controller.health_advice()]
                   + self.controller.insight_lines())) if running else "")
        self._set_big_button(self.start_btn, not running)
        self.test_btn.config(state="disabled" if running else "normal")
        self._set_big_button(self.stop_btn, running)
        self._set_big_button(
            self.emergency_btn, running,
            text=gt.with_accelerator(gp.emergency_button_label(
                self.controller.emergency_active()), "emergency"))
        self._show_recommendations(self.inbox.visible(self.controller.recommendations()))
        self.health_label.config(text=self.controller.health_line() if running else "")
        if self.graph_canvases and self.redraw_gate.ready(time.monotonic()):
            self._record_graphs(self.controller.health_summary(),
                                self.telemetry.latest)
            self._draw_graphs()
        timeline = rm.timeline_text(self.controller.timeline_lines())
        if timeline != self._shown_timeline:
            self._shown_timeline = timeline
            self.timeline_view.config(state="normal")
            self.timeline_view.delete("1.0", "end")
            self.timeline_view.insert("end", timeline)
            self.timeline_view.config(state="disabled")
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
            ttk.Label(self.rec_frame, text="None right now.", style="Card.TLabel"
                      ).pack(anchor="w")
        for rec in recs:
            row = ttk.Frame(self.rec_frame, style="CardBody.TFrame")
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=rec.message, wraplength=WRAP - 160, style="Card.TLabel",
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
        dialog.configure(background=gt.palette(self.theme)["background"])
        ttk.Label(dialog, text=ffmpeg_guidance(), justify="left",
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

    def on_callback_error(self, exc_type, exc, tb):
        """Tk calls this for an uncaught error in any callback: keep a local,
        redacted crash report and tell the user, instead of printing a
        traceback (which could quote the key) to a console nobody sees."""
        if exc is not None and exc.__traceback__ is None:
            exc = exc.with_traceback(tb)
        try:
            self.status.set(gc.report_gui_crash(exc, self.key.get().strip()))
        except Exception:  # never let the handler itself raise into Tk
            pass

    def on_close(self, waited=0):
        """Ask ffmpeg to stop, then close once it has (or after a few seconds)."""
        self.controller.stop(wait=False)
        self.remote.set(False)  # stops the poll from reopening it
        self.remote_session.close()
        if self.controller.is_running() and waited < CLOSE_WAIT_MS:
            self.root.after(100, lambda: self.on_close(waited + 100))
        else:
            self.root.destroy()


def main(argv=None, out=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    out = out or sys.stdout
    if "--self-test" in argv:
        from .selftest import main as selftest_main
        return selftest_main(json_output="--self-test-json" in argv, out=out)
    if tk is None:
        print(NO_GUI_MESSAGE, file=out)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError:
        print(NO_GUI_MESSAGE, file=out)
        return 1
    window = StreamWindow(root)
    root.report_callback_exception = window.on_callback_error
    if find_ffmpeg() is None:
        root.after(200, window.offer_ffmpeg_help)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
