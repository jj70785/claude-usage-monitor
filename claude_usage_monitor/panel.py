"""Reusable usage panel — the centered content shared by the corner flyout and the
main pop-out window. Build it into any parent, then drive it with update() etc.

Header is parameterized:
  - on_close  -> shows a ✕ top-right (the corner flyout)
  - on_pin    -> shows a 📌 top-left  (the main window)
Both keep the title centered via uniform side columns.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from typing import Callable, Optional

from . import config
from .usage_api import Usage, Window

BG = "#202124"
FG = "#e8eaed"
SUB = "#9aa0a6"
TRACK = "#3c3d40"
ACCENT = "#3a6df0"
PIN_ON_BG = "#34406b"   # subtle highlight behind the pin when pinned

_seq = [0]


class UsagePanel:
    def __init__(self, parent, *, on_refresh: Callable[[], None], on_live: Callable[[bool], None],
                 on_pin: Optional[Callable[[], None]] = None,
                 on_close: Optional[Callable[[], None]] = None):
        self._on_refresh = on_refresh
        self._on_live = on_live
        self._on_pin = on_pin
        self._on_close = on_close
        _seq[0] += 1
        self._sp = f"p{_seq[0]}"            # unique ttk style prefix (styles are global)
        self.frame = tk.Frame(parent, bg=BG)
        self._init_styles(parent)
        self._build()

    @property
    def _fh_style(self) -> str:
        return f"{self._sp}fh.Horizontal.TProgressbar"

    @property
    def _wk_style(self) -> str:
        return f"{self._sp}wk.Horizontal.TProgressbar"

    def _init_styles(self, parent):
        self.style = ttk.Style(parent)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        for name in (self._fh_style, self._wk_style):
            self.style.configure(name, troughcolor=TRACK, bordercolor=BG, background=ACCENT,
                                 lightcolor=ACCENT, darkcolor=ACCENT, thickness=12)

    def _label(self, parent, text, font, fg=FG):
        return tk.Label(parent, text=text, font=font, fg=fg, bg=BG, justify="left")

    def _build(self):
        outer = tk.Frame(self.frame, bg=BG, padx=18, pady=14)
        outer.pack(fill="both", expand=True)

        # header: [pin|spacer]  centered title  [close|spacer]
        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x", pady=(0, 2))
        header.columnconfigure(0, weight=1, uniform="h")
        header.columnconfigure(2, weight=1, uniform="h")
        if self._on_pin:
            self.pin = tk.Label(header, text="📌", font=("Segoe UI Emoji", 11), fg=FG, bg=BG,
                                cursor="hand2", padx=4)
            self.pin.grid(row=0, column=0, sticky="w")
            self.pin.bind("<Button-1>", lambda e: self._on_pin())
        else:
            tk.Frame(header, bg=BG).grid(row=0, column=0, sticky="w")
        self._label(header, "Claude usage", ("Segoe UI Semibold", 14), fg=FG).grid(row=0, column=1)
        if self._on_close:
            close = tk.Label(header, text="✕", font=("Segoe UI", 13), fg=SUB, bg=BG, cursor="hand2")
            close.grid(row=0, column=2, sticky="e")
            close.bind("<Button-1>", lambda e: self._on_close())
        else:
            tk.Frame(header, bg=BG).grid(row=0, column=2, sticky="e")

        # 5-hour
        fh = tk.Frame(outer, bg=BG)
        fh.pack(fill="x", pady=(14, 0))
        self._label(fh, "5-hour session", ("Segoe UI", 12), fg=SUB).pack()
        fhn = tk.Frame(fh, bg=BG)
        fhn.pack(pady=(2, 0))
        self.fh_pct = self._label(fhn, "--", ("Segoe UI", 28, "bold"), fg=FG)
        self.fh_pct.pack(side="left")
        self._label(fhn, "used", ("Segoe UI", 12), fg=SUB).pack(side="left", anchor="s", padx=(7, 0), pady=(0, 5))
        self.fh_bar = ttk.Progressbar(fh, style=self._fh_style, maximum=100, length=300)
        self.fh_bar.pack(pady=(8, 3))
        self.fh_reset = self._label(fh, "", ("Segoe UI", 11), fg=SUB)
        self.fh_reset.pack()

        # weekly
        wk = tk.Frame(outer, bg=BG)
        wk.pack(fill="x", pady=(16, 0))
        self._label(wk, "Weekly · all models", ("Segoe UI", 12), fg=SUB).pack()
        wkn = tk.Frame(wk, bg=BG)
        wkn.pack(pady=(2, 0))
        self.wk_pct = self._label(wkn, "--", ("Segoe UI", 24, "bold"), fg=FG)
        self.wk_pct.pack(side="left")
        self._label(wkn, "used", ("Segoe UI", 12), fg=SUB).pack(side="left", anchor="s", padx=(7, 0), pady=(0, 4))
        self.wk_bar = ttk.Progressbar(wk, style=self._wk_style, maximum=100, length=300)
        self.wk_bar.pack(pady=(8, 3))
        self.wk_reset = self._label(wk, "", ("Segoe UI", 11), fg=SUB)
        self.wk_reset.pack()

        # footer
        foot = tk.Frame(outer, bg=BG)
        foot.pack(fill="x", pady=(16, 0))
        self.status = self._label(foot, "", ("Segoe UI", 10), fg=SUB)
        self.status.pack()
        controls = tk.Frame(foot, bg=BG)
        controls.pack(pady=(8, 0))
        self.live_var = tk.BooleanVar(value=False)
        self.live_check = tk.Checkbutton(
            controls, text="Fast Update", variable=self.live_var,
            command=lambda: self._on_live(bool(self.live_var.get())),
            font=("Segoe UI", 10), fg=SUB, bg=BG, selectcolor=BG, activebackground=BG,
            activeforeground=FG, bd=0, highlightthickness=0, cursor="hand2",
        )
        self.live_check.pack(side="left", padx=(0, 12))
        self._refresh_enabled = True
        if sys.platform == "darwin":
            # macOS Aqua tk.Button ignores bg/fg (renders a white box). A tk.Label honours
            # colours, so style one as a button and drive clicks ourselves.
            self.refresh_btn = tk.Label(
                controls, text="Refresh", font=("Segoe UI", 10),
                bg=ACCENT, fg="white", padx=16, pady=6, cursor="hand2",
            )
            self.refresh_btn.bind("<Button-1>", lambda e: self._refresh_clicked())
        else:
            self.refresh_btn = tk.Button(
                controls, text="Refresh", font=("Segoe UI", 10), relief="flat",
                bg=ACCENT, fg="white", activebackground="#2f5bd0", activeforeground="white",
                bd=0, padx=16, pady=5, cursor="hand2", command=lambda: self._on_refresh(),
            )
        self.refresh_btn.pack(side="left")

    def _refresh_clicked(self):
        if self._refresh_enabled:
            self._on_refresh()

    # --- updates --------------------------------------------------------------
    def _apply(self, w: Optional[Window], bar, style_name, pct_label, reset_label, reset_mode):
        if not w:
            pct_label.config(text="--")
            reset_label.config(text="no data")
            self.style.configure(style_name, background=TRACK, lightcolor=TRACK, darkcolor=TRACK)
            bar.config(value=0)
            return
        color = config.color_for_percent(w.percent)
        self.style.configure(style_name, background=color, lightcolor=color, darkcolor=color)
        bar.config(value=min(w.percent, 100))
        pct_label.config(text=f"{w.percent:.0f}%")
        if reset_mode == "at":
            reset_label.config(text=("Resets " + w.reset_at_text()) if w.reset_at_text() else w.reset_in_text())
        else:
            reset_label.config(text=w.reset_in_text())

    def update(self, usage: Optional[Usage], note: str = ""):
        if usage:
            self._apply(usage.five_hour, self.fh_bar, self._fh_style, self.fh_pct, self.fh_reset, "in")
            self._apply(usage.weekly, self.wk_bar, self._wk_style, self.wk_pct, self.wk_reset, "at")
            mins = int((datetime.now(usage.fetched_at.tzinfo) - usage.fetched_at).total_seconds() // 60)
            when = "just now" if mins <= 0 else f"{mins} min ago"
            plan = f"{usage.plan} · " if usage.plan else ""
            self.status.config(text=f"{plan}updated {when}" + (f" · {note}" if note else ""))
        elif note:
            self.status.config(text=note)

    def set_refresh_enabled(self, enabled: bool, label: str = "Refresh"):
        self._refresh_enabled = enabled
        if sys.platform == "darwin":
            # Label-as-button: no "state" option; grey it out via colour instead.
            self.refresh_btn.config(text=label, bg=ACCENT if enabled else TRACK,
                                    fg="white" if enabled else SUB)
        else:
            self.refresh_btn.config(text=label, state="normal" if enabled else "disabled",
                                    bg=ACCENT if enabled else TRACK)

    def set_live_display(self, on: bool):
        self.live_var.set(bool(on))

    def set_pinned(self, pinned: bool):
        if self._on_pin and hasattr(self, "pin"):
            self.pin.config(bg=PIN_ON_BG if pinned else BG)
