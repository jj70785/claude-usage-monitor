"""The corner flyout: a frameless popup shown when you left-click a tray icon. Hosts a
shared UsagePanel; hides on Escape, the ✕, or another tray click."""
from __future__ import annotations

import sys
import tkinter as tk
from typing import Callable, Optional

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
        if self.is_visible():
            self._reclamp()

    def set_refresh_enabled(self, enabled: bool, label: str = "Refresh"):
        self.panel.set_refresh_enabled(enabled, label)

    def set_live_display(self, on: bool):
        self.panel.set_live_display(on)

    # --- visibility -----------------------------------------------------------
    def is_visible(self) -> bool:
        return self.win.state() != "withdrawn"

    def _size(self) -> tuple[int, int]:
        self.win.update_idletasks()
        return max(self.win.winfo_reqwidth(), 200), max(self.win.winfo_reqheight(), 120)

    def _position(self, anchor: Optional[dict] = None):
        w, h = self._size()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        area = (0, 0, sw, sh)
        margin = 8
        if anchor:
            # From the Linux tray (GTK thread): the clicked icon's rectangle, the work area
            # of the monitor it's on, and whether the panel is vertical.
            ax, ay, aw, ah = anchor["icon"]
            area = anchor["workarea"]
            mx, my, mw, mh = area
            if anchor.get("vertical"):
                x = ax + aw + margin if ax + aw / 2 < mx + mw / 2 else ax - w - margin
                y = ay + ah // 2 - h // 2
            else:
                x = ax + aw // 2 - w // 2
                y = ay + ah + margin if ay + ah / 2 < my + mh / 2 else ay - h - margin
        elif sys.platform == "darwin":
            # Center under the clicked menu-bar icon, clamped to the screen.
            x, y = self.win.winfo_pointerx() - w // 2, 34
        elif sys.platform == "win32":
            x, y = sw - w - 12, sh - h - 56                 # above the taskbar
        else:
            # No anchor (e.g. "Quick view" from the menu): open beside the pointer.
            px, py = self.win.winfo_pointerx(), self.win.winfo_pointery()
            x = px + 24 if px < sw // 2 else px - w - 24
            y = py - h // 2
        self._area = area
        self._place(x, y, w, h)

    def _place(self, x: int, y: int, w: int, h: int):
        ax, ay, aw, ah = self._area
        m = 8
        x = max(ax + m, min(int(x), ax + aw - w - m))
        y = max(ay + m, min(int(y), ay + ah - h - m))
        self._xy, self._h = (x, y), h
        self.win.geometry(f"+{x}+{y}")

    def _reclamp(self):
        """Keep the flyout on-screen when its content grows (e.g. a note appears) without
        moving it to wherever the mouse happens to be now."""
        _, h = self._size()
        if getattr(self, "_xy", None) is None or h == self._h:
            return
        x, y = self._xy
        if sys.platform == "win32" or y + self._h >= self._area[1] + self._area[3] - 60:
            y -= h - self._h                                # bottom-anchored: grow upward
        self._place(x, y, self._size()[0], h)

    def show(self, anchor: Optional[dict] = None):
        self._position(anchor)
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        self.win.focus_force()

    def hide(self):
        self.win.withdraw()
