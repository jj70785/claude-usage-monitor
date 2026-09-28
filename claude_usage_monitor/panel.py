"""Reusable usage panel: the content shared by the corner flyout and the main window.

One section per provider (Claude now; Codex/Gemini later), one row per limit. The
section layout is rebuilt only when the set of providers/limits changes; normal updates
just change text, bar values, and colors.

Header is parameterized:
  - on_close -> shows a ✕ top-right (the corner flyout)
  - on_pin   -> shows a pin toggle top-left (the main window)
"""
from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable, Optional

from . import config
from .model import Snapshot, age_text

BG = "#202124"
FG = "#e8eaed"
SUB = "#9aa0a6"
WARN_FG = "#f2b64c"
TRACK = "#3c3d40"
ACCENT = "#3a6df0"
PIN_ON_BG = "#34406b"
BAR_LEN = 300

_seq = [0]


@dataclass
class ProviderView:
    """What the panel needs to draw one provider section."""
    provider_id: str
    title: str
    snapshot: Optional[Snapshot]
    note: str = ""
    stale: bool = False
    source_label: str = ""


def _family(root) -> str:
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "Helvetica Neue"
    have = set(tkfont.families(root))
    for f in ("Noto Sans", "Cantarell", "DejaVu Sans", "Liberation Sans"):
        if f in have:
            return f
    return "TkDefaultFont"


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
        self._fam = _family(parent)
        self.frame = tk.Frame(parent, bg=BG)
        self.style = ttk.Style(parent)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self._signature: tuple = ()
        self._rows: dict[tuple[str, str], dict] = {}     # (pid, meter key) -> widgets
        self._heads: dict[str, dict] = {}                # pid -> header widgets
        self._build()

    def _f(self, size: int, weight: str = "normal"):
        return (self._fam, size, weight) if weight != "normal" else (self._fam, size)

    def _label(self, parent, text, font, fg=FG, **kw):
        return tk.Label(parent, text=text, font=font, fg=fg, bg=BG, justify="left", **kw)

    # ------------------------------------------------------------------ skeleton
    def _build(self):
        outer = tk.Frame(self.frame, bg=BG, padx=18, pady=14)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x", pady=(0, 4))
        header.columnconfigure(0, weight=1, uniform="h")
        header.columnconfigure(2, weight=1, uniform="h")
        if self._on_pin:
            # Emoji can misrender in Tk on X11, so Linux gets a text pin.
            pin_text = "Pin" if config.IS_LINUX else "📌"
            self.pin = tk.Label(header, text=pin_text, font=self._f(10), fg=FG, bg=BG,
                                cursor="hand2", padx=6, pady=1)
            self.pin.grid(row=0, column=0, sticky="w")
            self.pin.bind("<Button-1>", lambda e: self._on_pin())
        else:
            tk.Frame(header, bg=BG).grid(row=0, column=0, sticky="w")
        self._label(header, "AI usage", self._f(14, "bold")).grid(row=0, column=1)
        if self._on_close:
            close = tk.Label(header, text="✕", font=self._f(13), fg=SUB, bg=BG, cursor="hand2")
            close.grid(row=0, column=2, sticky="e")
            close.bind("<Button-1>", lambda e: self._on_close())
        else:
            tk.Frame(header, bg=BG).grid(row=0, column=2, sticky="e")

        self.body = tk.Frame(outer, bg=BG)
        self.body.pack(fill="x")

        foot = tk.Frame(outer, bg=BG)
        foot.pack(fill="x", pady=(14, 0))
        self.status = self._label(foot, "", self._f(9), fg=SUB, wraplength=BAR_LEN)
        self.status.pack()
        controls = tk.Frame(foot, bg=BG)
        controls.pack(pady=(8, 0))
        self.live_var = tk.BooleanVar(value=False)
        self.live_check = tk.Checkbutton(
            controls, text="Fast Update", variable=self.live_var,
            command=lambda: self._on_live(bool(self.live_var.get())),
            font=self._f(10), fg=SUB, bg=BG, selectcolor=BG, activebackground=BG,
            activeforeground=FG, bd=0, highlightthickness=0, cursor="hand2",
        )
        self.live_check.pack(side="left", padx=(0, 12))
        self._refresh_enabled = True
        if sys.platform == "darwin":
            # macOS Aqua tk.Button ignores bg/fg; a styled Label honors colors.
            self.refresh_btn = tk.Label(controls, text="Refresh", font=self._f(10),
                                        bg=ACCENT, fg="white", padx=16, pady=6, cursor="hand2")
            self.refresh_btn.bind("<Button-1>", lambda e: self._refresh_clicked())
        else:
            self.refresh_btn = tk.Button(
                controls, text="Refresh", font=self._f(10), relief="flat",
                bg=ACCENT, fg="white", activebackground="#2f5bd0", activeforeground="white",
                disabledforeground="#c8cad0", bd=0, padx=16, pady=5, cursor="hand2",
                command=self._refresh_clicked,
            )
        self.refresh_btn.pack(side="left")

    def _refresh_clicked(self):
        if self._refresh_enabled:
            self._on_refresh()

    # ------------------------------------------------------------------ sections
    def _rebuild(self, views: list[ProviderView]):
        for w in self.body.winfo_children():
            w.destroy()
        self._rows.clear()
        self._heads.clear()
        for n, v in enumerate(views):
            sec = tk.Frame(self.body, bg=BG)
            sec.pack(fill="x", pady=(10 if n else 4, 0))
            head = tk.Frame(sec, bg=BG)
            head.pack(fill="x")
            title = self._label(head, v.title, self._f(12, "bold"))
            title.pack(side="left")
            plan = self._label(head, "", self._f(10), fg=SUB)
            plan.pack(side="left", padx=(6, 0), pady=(2, 0))
            age = self._label(head, "", self._f(9), fg=SUB)
            age.pack(side="right", pady=(3, 0))
            note = self._label(sec, "", self._f(9), fg=WARN_FG, wraplength=BAR_LEN)
            self._heads[v.provider_id] = {"plan": plan, "age": age, "note": note, "sec": sec}

            meters = v.snapshot.meters if v.snapshot else []
            if not meters:
                empty = self._label(sec, "No data yet", self._f(10), fg=SUB)
                empty.pack(anchor="w", pady=(6, 0))
                self._rows[(v.provider_id, "")] = {"empty": empty}
            for i, m in enumerate(meters):
                row = tk.Frame(sec, bg=BG)
                row.pack(fill="x", pady=(8, 0))
                top = tk.Frame(row, bg=BG)
                top.pack(fill="x")
                lbl = self._label(top, m.label, self._f(10), fg=SUB)
                lbl.pack(side="left")
                pct = self._label(top, "--", self._f(15 if m.primary else 11, "bold"))
                pct.pack(side="right")
                style = f"{self._sp}{v.provider_id.replace(':', '_')}{i}.Horizontal.TProgressbar"
                self.style.configure(style, troughcolor=TRACK, bordercolor=BG, background=ACCENT,
                                     lightcolor=ACCENT, darkcolor=ACCENT, thickness=10 if m.primary else 6)
                bar = ttk.Progressbar(row, style=style, maximum=100, length=BAR_LEN)
                bar.pack(fill="x", pady=(3, 2))
                reset = self._label(row, "", self._f(9), fg=SUB)
                reset.pack(anchor="w")
                self._rows[(v.provider_id, m.key)] = {"pct": pct, "bar": bar, "style": style, "reset": reset}
            note.pack(anchor="w", pady=(6, 0))

    def update(self, views: list[ProviderView], status: str = ""):
        sig = tuple((v.provider_id, tuple(m.key for m in (v.snapshot.meters if v.snapshot else []))) for v in views)
        if sig != self._signature:
            self._signature = sig
            self._rebuild(views)
        for v in views:
            head = self._heads.get(v.provider_id)
            if not head:
                continue
            snap = v.snapshot
            head["plan"].config(text=snap.plan if snap and snap.plan else "")
            if snap and snap.fetched_at:
                when = age_text(snap.fetched_at)
                txt = (f"as of {when}" if v.stale else f"updated {when}")
                head["age"].config(text=txt, fg=WARN_FG if v.stale else SUB)
            else:
                head["age"].config(text="", fg=SUB)
            note = v.note or (snap.note if snap else "")
            head["note"].config(text=note)
            if not note:
                head["note"].pack_forget()
            elif not head["note"].winfo_ismapped():
                head["note"].pack(anchor="w", pady=(6, 0))
            for m in (snap.meters if snap else []):
                r = self._rows.get((v.provider_id, m.key))
                if not r:
                    continue
                if m.expired:
                    r["pct"].config(text="--", fg=SUB)
                    self._color(r["style"], TRACK)
                    r["bar"].config(value=0)
                else:
                    r["pct"].config(text=f"{m.percent:.0f}%", fg=SUB if v.stale else FG)
                    self._color(r["style"], config.color_for_percent(m.percent))
                    r["bar"].config(value=min(max(m.percent, 0), 100))
                r["reset"].config(text=m.reset_text())
        self.status.config(text=status)

    def _color(self, style: str, color: str):
        self.style.configure(style, background=color, lightcolor=color, darkcolor=color)

    # ------------------------------------------------------------------ controls
    def set_refresh_enabled(self, enabled: bool, label: str = "Refresh"):
        self._refresh_enabled = enabled
        if sys.platform == "darwin":
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
