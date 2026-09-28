"""The corner flyout: a frameless popup shown when you left-click a tray icon. Hosts a
shared UsagePanel; hides on Escape, the ✕, or another tray click."""
from __future__ import annotations

import sys
import tkinter as tk
from typing import Callable

from . import config
from .panel import BG, ProviderView, UsagePanel


class Popup:
    def __init__(self, root: tk.Tk, on_refresh: Callable[[], None], on_live: Callable[[bool], None]):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.title(config.APP_NAME)
        self.win.configure(bg=BG)
        self.win.overrideredirect(True)   # frameless flyout
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.98)
        except tk.TclError:
            pass
        self.win.bind("<Escape>", lambda e: self.hide())
        self.panel = UsagePanel(self.win, on_refresh=on_refresh, on_live=on_live, on_close=self.hide)
        self.panel.frame.pack(fill="both", expand=True)

    def update(self, views: list[ProviderView], status: str = ""):
        self.panel.update(views, status)

    def set_refresh_enabled(self, enabled: bool, label: str = "Refresh"):
        self.panel.set_refresh_enabled(enabled, label)

    def set_live_display(self, on: bool):
        self.panel.set_live_display(on)

    # --- visibility -----------------------------------------------------------
    def is_visible(self) -> bool:
        return self.win.state() != "withdrawn"

    def _position(self):
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth() or 336
        h = self.win.winfo_reqheight() or 360
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        if sys.platform == "darwin":
            # Center under the clicked menu-bar icon, clamped to the screen.
            x = max(12, min(self.win.winfo_pointerx() - w // 2, sw - w - 12))
            self.win.geometry(f"+{x}+34")
        elif sys.platform == "win32":
            self.win.geometry(f"+{sw - w - 12}+{sh - h - 56}")   # above the taskbar
        else:
            # Linux panels can sit on any edge (e.g. an XFCE vertical deskbar on the
            # left), so open next to the pointer, on the side with more room.
            px, py = self.win.winfo_pointerx(), self.win.winfo_pointery()
            x = px + 24 if px < sw // 2 else px - w - 24
            y = py - h // 2
            x = max(8, min(x, sw - w - 8))
            y = max(8, min(y, sh - h - 8))
            self.win.geometry(f"+{x}+{y}")

    def show(self):
        self._position()
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        self.win.focus_force()

    def hide(self):
        self.win.withdraw()
