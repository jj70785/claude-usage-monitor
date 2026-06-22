"""macOS menu-bar icons via native NSStatusItem.

pystray's macOS backend calls ``[NSApplication run]`` on a background thread, which
AppKit only permits on the main thread -> SIGTRAP crash. Instead we create native
``NSStatusItem``s on the main thread; tkinter's mainloop already pumps the Cocoa event
loop, so the status items and their menus work without ``NSApplication.run()`` or any
extra threads.

This module is macOS-only and exposes the SAME ``Tray`` API as ``tray.py`` (the pystray
implementation used on Windows/Linux): same ``__init__`` callbacks and
start/stop/update/notify/refresh_menu methods.
"""
from __future__ import annotations

import io
from typing import Optional

from AppKit import (
    NSApplication,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSMenu,
    NSMenuItem,
    NSImage,
    NSEventMaskLeftMouseDown,
    NSEventMaskRightMouseDown,
    NSEventTypeRightMouseDown,
    NSEventModifierFlagControl,
)
from Foundation import NSObject, NSData

# Reuse the icon renderers + tooltip from the pystray module. Importing tray.py on macOS
# is safe: pystray only crashes if an icon's .run() is called, which we never do here.
from .tray import make_bars_image, make_ring_image, _tip
from .usage_api import Usage


def _nsimage(pil_img, px: int = 18) -> NSImage:
    """Convert a PIL image to a retina NSImage sized for the menu bar."""
    img = pil_img.resize((px * 2, px * 2))            # retina
    buf = io.BytesIO()
    img.save(buf, "PNG")
    raw = buf.getvalue()
    data = NSData.dataWithBytes_length_(raw, len(raw))
    ns = NSImage.alloc().initWithData_(data)
    ns.setSize_((px, px))
    ns.setTemplate_(False)                            # keep our colours (green/yellow/red)
    return ns


class _Handler(NSObject):
    """Objective-C target for the status-bar buttons and the menu items.
    Holds a strong ref to the owning Tray (which has the callbacks + menu)."""

    # --- status-bar button click: left = flyout toggle, right/ctrl = menu ---------
    def statusItemClicked_(self, sender):
        event = NSApplication.sharedApplication().currentEvent()
        is_right = False
        if event is not None:
            is_right = (event.type() == NSEventTypeRightMouseDown
                        or bool(event.modifierFlags() & NSEventModifierFlagControl))
        self._tray._handle_button_click(sender, is_right)

    # --- menu items ---------------------------------------------------------------
    def quickView_(self, _):
        self._tray._cbs["open"]()

    def openWindow_(self, _):
        self._tray._cbs["open_window"]()

    def refresh_(self, _):
        self._tray._cbs["refresh"]()

    def pasteKey_(self, _):
        self._tray._cbs["paste_key"]()

    def quitApp_(self, _):
        self._tray._cbs["quit"]()


class Tray:
    def __init__(self, on_open, on_refresh, on_toggle_login, on_quit, on_paste_key, on_open_window):
        # on_toggle_login is part of the shared API (Windows "Start on login"); unused on macOS.
        self._cbs = {
            "open": on_open,
            "refresh": on_refresh,
            "quit": on_quit,
            "paste_key": on_paste_key,
            "open_window": on_open_window,
        }
        self._handler = _Handler.alloc().init()
        self._handler._tray = self                   # strong ref so the target survives
        self._items: list = []
        self._menu_obj = None

    def _handle_button_click(self, button, is_right: bool) -> None:
        """Left-click toggles the flyout (like Windows); right/Control-click shows the menu.
        The menu is attached to the clicked item only for the duration of the pop-up so
        plain left-clicks keep firing our action instead of auto-opening the menu."""
        if is_right:
            item = next((it for it in self._items if it.button() == button), None)
            if item is not None:
                item.setMenu_(self._menu_obj)
                button.performClick_(None)           # opens the menu, blocks until dismissed
                item.setMenu_(None)
        else:
            self._cbs["open"]()

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
        add("Paste session key…", "pasteKey:")
        add("Quit", "quitApp:")
        return m

    def start(self) -> None:
        """MUST run on the main thread — it is, since App.run() calls this on main."""
        bar = NSStatusBar.systemStatusBar()
        self._menu_obj = self._menu()                # one shared menu, attached on demand

        def wire(button):
            # Fire our action on BOTH mouse-downs (no permanent menu) so we can route
            # left -> flyout, right/ctrl -> menu ourselves.
            button.setTarget_(self._handler)
            button.setAction_("statusItemClicked:")
            button.sendActionOn_(NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown)

        # macOS adds each new status item to the LEFT of existing ones. Create the weekly
        # (ring) item first so it ends up on the right, and the 5-hour (bars) item second
        # so it ends up on the left -> left = bars = 5-hour, right = ring = weekly.
        week_item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        week_item.button().setImage_(_nsimage(make_ring_image(None)))
        wire(week_item.button())

        five_item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        five_item.button().setImage_(_nsimage(make_bars_image(None)))
        wire(five_item.button())

        # Logical order for update(): [0] = bars (5-hour), [1] = ring (weekly).
        self._items = [five_item, week_item]

    def update(self, usage: Optional[Usage], note: str = "") -> None:
        if not self._items:
            return
        five = usage.five_hour if usage else None
        week = usage.weekly if usage else None
        self._items[0].button().setImage_(_nsimage(make_bars_image(five.percent if five else None)))
        self._items[0].button().setToolTip_(_tip("5-hour", five, note))
        self._items[1].button().setImage_(_nsimage(make_ring_image(week.percent if week else None)))
        self._items[1].button().setToolTip_(_tip("Weekly", week, note))

    def notify(self, message: str, title: Optional[str] = None) -> None:
        pass        # skip native notifications on macOS for now

    def refresh_menu(self) -> None:
        pass        # the macOS menu has no dynamic check state to refresh

    def stop(self) -> None:
        bar = NSStatusBar.systemStatusBar()
        for it in self._items:
            bar.removeStatusItem_(it)
        self._items = []
