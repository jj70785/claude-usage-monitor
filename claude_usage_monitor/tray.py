"""System-tray icons.

Two icons sit in the tray, each coloured green -> yellow -> red by its own level:
  - signal bars  -> 5-hour session
  - ring gauge   -> weekly (all models)
Left-click either to toggle the corner flyout; right-click for the menu.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw

from . import config
from .usage_api import Usage, Window

TRACK = (74, 74, 80)


def make_bars_image(percent: Optional[float]) -> Image.Image:
    """4 bars of increasing height; the first ceil(%/25) light up in the level colour."""
    s = 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    n, m = 4, int(s * 0.12)
    gap = int(s * 0.08)
    bw = (s - 2 * m - (n - 1) * gap) / n
    p = percent or 0
    lit = round(p / 100.0 * n)
    color = config.color_for_percent(p)
    for i in range(n):
        bx = m + i * (bw + gap)
        bh = (s - 2 * m) * ((i + 1) / n)
        by = s - m - bh
        d.rounded_rectangle((bx, by, bx + bw, s - m), radius=max(1, int(bw * 0.3)),
                            fill=color if i < lit else TRACK)
    return img


def make_ring_image(percent: Optional[float]) -> Image.Image:
    """A thick donut whose arc fills with usage, in the level colour."""
    s = 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = int(s * 0.22)
    pad = w // 2 + 2
    box = (pad, pad, s - pad, s - pad)
    d.arc(box, 0, 360, fill=TRACK, width=w)
    p = percent or 0
    if p > 0:
        d.arc(box, -90, -90 + p / 100.0 * 360, fill=config.color_for_percent(p), width=w)
    return img


def _tip(label: str, w: Optional[Window], note: str = "") -> str:
    lines = [config.APP_NAME]
    if w:
        line = f"{label}: {w.percent:.0f}%"
        rt = w.reset_in_text()
        if rt:
            line += f"  ·  {rt}"
        lines.append(line)
    else:
        lines.append(f"{label}: --")
    if note:
        lines.append(note)
    return "\n".join(lines)


class Tray:
    def __init__(
        self,
        on_open: Callable[[], None],
        on_refresh: Callable[[], None],
        on_toggle_login: Callable[[], None],
        on_quit: Callable[[], None],
        on_paste_key: Callable[[], None],
        on_open_window: Callable[[], None],
    ):
        self._on_open = on_open
        self._on_refresh = on_refresh
        self._on_toggle_login = on_toggle_login
        self._on_quit = on_quit
        self._on_paste_key = on_paste_key
        self._on_open_window = on_open_window
        # icon 1: 5-hour session (bars) · icon 2: weekly (ring)
        self.icon5h = pystray.Icon("claude_usage_5h", make_bars_image(None),
                                   config.APP_NAME, menu=self._build_menu())
        self.iconwk = pystray.Icon("claude_usage_week", make_ring_image(None),
                                   config.APP_NAME, menu=self._build_menu())
        self._icons = (self.icon5h, self.iconwk)

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("Quick view", lambda i, it: self._on_open(), default=True),
            pystray.MenuItem("Open window", lambda i, it: self._on_open_window()),
            pystray.MenuItem("Refresh now", lambda i, it: self._on_refresh()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Paste session key…", lambda i, it: self._on_paste_key()),
            pystray.MenuItem(
                "Start on Windows login",
                lambda i, it: self._on_toggle_login(),
                checked=lambda it: config.is_run_on_login(),
            ),
            pystray.MenuItem("Quit", lambda i, it: self._on_quit()),
        )

    def update(self, usage: Optional[Usage], note: str = "") -> None:
        five = usage.five_hour if usage else None
        week = usage.weekly if usage else None
        try:
            self.icon5h.icon = make_bars_image(five.percent if five else None)
            self.icon5h.title = _tip("5-hour", five, note)
            self.iconwk.icon = make_ring_image(week.percent if week else None)
            self.iconwk.title = _tip("Weekly", week, note)
        except Exception:
            pass

    def notify(self, message: str, title: Optional[str] = None) -> None:
        try:
            self.icon5h.notify(message, title or config.APP_NAME)
        except Exception:
            pass

    def refresh_menu(self) -> None:
        for ic in self._icons:
            try:
                ic.update_menu()
            except Exception:
                pass

    def start(self) -> None:
        for ic in self._icons:
            threading.Thread(target=ic.run, name=f"tray-{ic.name}", daemon=True).start()

    def stop(self) -> None:
        for ic in self._icons:
            try:
                ic.stop()
            except Exception:
                pass
