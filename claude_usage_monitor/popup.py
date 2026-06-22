"""The corner flyout: a frameless, auto-hiding popup shown when you left-click the
tray icon. Hosts a shared UsagePanel; hides on Escape or focus loss."""
from __future__ import annotations

import sys
import tkinter as tk
from typing import Callable, Optional

from . import config
from .panel import BG, UsagePanel
from .usage_api import Usage


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
        except Exception:
            pass
        self.win.bind("<Escape>", lambda e: self.hide())
        # No auto-hide on focus loss: the flyout stays open until you click a tray
        # icon again (toggle), press Escape, or hit the ✕.

        self.panel = UsagePanel(self.win, on_refresh=on_refresh, on_live=on_live, on_close=self.hide)
        self.panel.frame.pack(fill="both", expand=True)

    # delegate the view API to the panel
    def update(self, usage: Optional[Usage], note: str = ""):
        self.panel.update(usage, note)

    def set_refresh_enabled(self, enabled: bool, label: str = "Refresh"):
        self.panel.set_refresh_enabled(enabled, label)

    def set_live_display(self, on: bool):
        self.panel.set_live_display(on)

    # --- visibility -----------------------------------------------------------
    def is_visible(self) -> bool:
        return self.win.state() != "withdrawn"

    def _position(self):
        self.win.update_idletasks()
        w = self.win.winfo_width() or 336
        h = self.win.winfo_height() or 360
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        if sys.platform == "darwin":
            # Center under the clicked menu-bar icon (cursor is on it at click time),
            # clamped so the flyout never runs off either screen edge.
            ww = w if w > 1 else (self.win.winfo_reqwidth() or 336)
            x = max(12, min(self.win.winfo_pointerx() - ww // 2, sw - ww - 12))
            self.win.geometry(f"+{x}+34")                       # just under the menu bar
        else:
            self.win.geometry(f"+{sw - w - 12}+{sh - h - 56}")  # above the Windows taskbar

    def show(self):
        self._position()
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        self.win.focus_force()

    def hide(self):
        self.win.withdraw()

    def toggle(self):
        if self.is_visible():
            self.hide()
        else:
            self.show()
