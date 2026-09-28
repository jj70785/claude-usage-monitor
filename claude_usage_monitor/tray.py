"""Windows tray icons via pystray, one per provider.

Left-click an icon to toggle the corner flyout; right-click for the menu.
(Linux uses tray_linux.py, macOS uses tray_macos.py; all three share this API.)

NOTE: not yet re-tested on Windows after the multi-provider rewrite. See
docs/plans/roadmap.md (Phase 2: Windows).
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

import pystray

from . import config, notify
from .icons import ring_image
from .model import Snapshot, tooltip

_TIP_MAX = 127     # Windows tray tooltips are limited to 128 characters


class Tray:
    def __init__(self, providers: list[tuple[str, str]], *, on_open: Callable[[str], None],
                 on_refresh: Callable[[], None], on_toggle_login: Callable[[], None],
                 on_quit: Callable[[], None], on_open_window: Callable[[], None],
                 is_login_enabled: Callable[[], bool]):
        self._providers = list(providers)
        self._on_open = on_open
        self._on_refresh = on_refresh
        self._on_toggle_login = on_toggle_login
        self._on_quit = on_quit
        self._on_open_window = on_open_window
        self._is_login_enabled = is_login_enabled
        self._icons: dict[str, pystray.Icon] = {
            pid: pystray.Icon(f"ai_usage_{pid.replace(':', '_')}", ring_image(None, pid),
                              title, menu=self._build_menu(pid))
            for pid, title in self._providers
        }

    def _build_menu(self, pid: str) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("Quick view", lambda i, it: self._on_open(pid), default=True),
            pystray.MenuItem("Open window", lambda i, it: self._on_open_window()),
            pystray.MenuItem("Refresh now", lambda i, it: self._on_refresh()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start on login", lambda i, it: self._on_toggle_login(),
                             checked=lambda it: self._is_login_enabled()),
            pystray.MenuItem("Quit", lambda i, it: self._on_quit()),
        )

    def update(self, snapshots: dict[str, Optional[Snapshot]], notes: dict[str, str],
               stale: dict[str, bool]) -> None:
        titles = dict(self._providers)
        for pid, icon in self._icons.items():
            snap = snapshots.get(pid)
            worst = snap.worst() if snap else None
            try:
                icon.icon = ring_image(worst.percent if worst else None, pid, 64, stale.get(pid, False))
                icon.title = tooltip(snap, titles[pid], notes.get(pid, ""))[:_TIP_MAX]
            except Exception as e:
                config.log(f"tray update failed: {e}")

    def notify(self, message: str, title: Optional[str] = None) -> None:
        first = next(iter(self._icons.values()), None)
        try:
            if first is not None:
                first.notify(message, title or config.APP_NAME)
                return
        except Exception:
            pass
        notify.send(title or config.APP_NAME, message)

    def refresh_menu(self) -> None:
        for ic in self._icons.values():
            try:
                ic.update_menu()
            except Exception:
                pass

    def start(self) -> None:
        for ic in self._icons.values():
            threading.Thread(target=ic.run, name=f"tray-{ic.name}", daemon=True).start()

    def stop(self) -> None:
        for ic in self._icons.values():
            try:
                ic.stop()
            except Exception:
                pass
