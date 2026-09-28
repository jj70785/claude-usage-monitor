"""macOS menu-bar icons via native NSStatusItem, one per provider.

pystray's macOS backend calls ``[NSApplication run]`` on a background thread, which
AppKit only permits on the main thread -> SIGTRAP crash. Instead we create native
``NSStatusItem``s on the main thread; tkinter's mainloop already pumps the Cocoa event
loop, so the status items and their menus work without extra threads.

Same public API as tray.py / tray_linux.py.

NOTE: not yet re-tested on macOS after the multi-provider rewrite. See
docs/plans/roadmap.md (Phase 3: macOS).
"""
from __future__ import annotations

import io
from typing import Callable, Optional

from AppKit import (
    NSApplication,
    NSEventMaskLeftMouseDown,
    NSEventMaskRightMouseDown,
    NSEventModifierFlagControl,
    NSEventTypeRightMouseDown,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSData, NSObject

from . import notify
from .icons import ring_image
from .model import Snapshot, tooltip


def _nsimage(pil_img, px: int = 18) -> NSImage:
    """Convert a PIL image to a retina NSImage sized for the menu bar."""
    img = pil_img.resize((px * 2, px * 2))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    raw = buf.getvalue()
    ns = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(raw, len(raw)))
    ns.setSize_((px, px))
    ns.setTemplate_(False)                            # keep our colors (green/yellow/red)
    return ns


class _Handler(NSObject):
    """Objective-C target for the status-bar buttons and the menu items."""

    def statusItemClicked_(self, sender):
        event = NSApplication.sharedApplication().currentEvent()
        is_right = False
        if event is not None:
            is_right = (event.type() == NSEventTypeRightMouseDown
                        or bool(event.modifierFlags() & NSEventModifierFlagControl))
        self._tray._handle_button_click(sender, is_right)

    def quickView_(self, _):
        self._tray._cbs["open"]("")

    def openWindow_(self, _):
        self._tray._cbs["open_window"]()

    def refresh_(self, _):
        self._tray._cbs["refresh"]()

    def quitApp_(self, _):
        self._tray._cbs["quit"]()


class Tray:
    def __init__(self, providers: list[tuple[str, str]], *, on_open: Callable[[str], None],
                 on_refresh: Callable[[], None], on_toggle_login: Callable[[], None],
                 on_quit: Callable[[], None], on_open_window: Callable[[], None],
                 is_login_enabled: Callable[[], bool]):
        # on_toggle_login / is_login_enabled: macOS login items are not implemented yet.
        self._providers = list(providers)
        self._cbs = {"open": on_open, "refresh": on_refresh, "quit": on_quit, "open_window": on_open_window}
        self._handler = _Handler.alloc().init()
        self._handler._tray = self                   # strong ref so the target survives
        self._items: dict[str, object] = {}          # provider_id -> NSStatusItem
        self._menu_obj = None

    def _handle_button_click(self, button, is_right: bool) -> None:
        """Left-click toggles the flyout; right/Control-click shows the menu, attached only
        for the pop-up so plain left-clicks keep firing our action."""
        pid, item = next(((p, it) for p, it in self._items.items() if it.button() == button), ("", None))
        if is_right:
            if item is not None:
                item.setMenu_(self._menu_obj)
                button.performClick_(None)           # opens the menu, blocks until dismissed
                item.setMenu_(None)
        else:
            self._cbs["open"](pid)

    def _menu(self) -> NSMenu:
        m = NSMenu.alloc().init()

        def add(title, sel):
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, "")
            it.setTarget_(self._handler)
            m.addItem_(it)

        add("Quick view", "quickView:")
        add("Open window", "openWindow:")
        add("Refresh now", "refresh:")
        m.addItem_(NSMenuItem.separatorItem())
        add("Quit", "quitApp:")
        return m

    def start(self) -> None:
        """MUST run on the main thread (App.run() calls it there)."""
        bar = NSStatusBar.systemStatusBar()
        self._menu_obj = self._menu()
        # macOS adds each new status item to the LEFT of existing ones, so create them in
        # reverse to keep the first provider leftmost.
        for pid, _title in reversed(self._providers):
            item = bar.statusItemWithLength_(NSVariableStatusItemLength)
            button = item.button()
            button.setImage_(_nsimage(ring_image(None, pid)))
            button.setTarget_(self._handler)
            button.setAction_("statusItemClicked:")
            button.sendActionOn_(NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown)
            self._items[pid] = item

    def update(self, snapshots: dict[str, Optional[Snapshot]], notes: dict[str, str],
               stale: dict[str, bool]) -> None:
        titles = dict(self._providers)
        for pid, item in self._items.items():
            snap = snapshots.get(pid)
            worst = snap.worst() if snap else None
            item.button().setImage_(_nsimage(ring_image(worst.percent if worst else None, pid, 64,
                                                        stale.get(pid, False))))
            item.button().setToolTip_(tooltip(snap, titles.get(pid, pid), notes.get(pid, "")))

    def notify(self, message: str, title: Optional[str] = None) -> None:
        notify.send(title or "AI Usage Monitor", message)

    def refresh_menu(self) -> None:
        pass        # the macOS menu has no dynamic check state yet

    def stop(self) -> None:
        bar = NSStatusBar.systemStatusBar()
        for it in self._items.values():
            bar.removeStatusItem_(it)
        self._items = {}
