"""Linux tray icons via GTK 3 `Gtk.StatusIcon` (XEmbed), one per provider.

Why not pystray here (docs/decisions/0005-linux-tray-gtk-statusicon.md):
- pystray's AppIndicator backend can't do left-click (it always opens the menu) and
  has no hover tooltip; its GTK backend needs a shim for tooltips; and a missing
  AppIndicator typelib makes `import pystray` raise ValueError instead of falling back.
- Gtk.StatusIcon gives left-click, right-click menu, and a real tooltip on X11 panels
  (XFCE's systray hosts XEmbed icons). It is X11-only; Wayland support would need a
  StatusNotifier backend (docs/plans/roadmap.md).

Threading: GTK runs its own main loop on one daemon thread, and ONLY that thread ever
touches GTK objects. Other threads hand work over with GLib.idle_add. All callbacks
into the app just enqueue commands (the Tk thread does the real work).

Same public API as tray.py (Windows) and tray_macos.py.
"""
from __future__ import annotations

import threading
import warnings
from typing import Callable, Optional

from . import config
from .icons import ring_image
from .model import Snapshot, tooltip


class Tray:
    def __init__(self, providers: list[tuple[str, str]], *, on_open: Callable[[str], None],
                 on_refresh: Callable[[], None], on_toggle_login: Callable[[], None],
                 on_quit: Callable[[], None], on_open_window: Callable[[], None],
                 is_login_enabled: Callable[[], bool]):
        self._providers = list(providers)          # [(provider_id, title)] in display order
        self._cb_open = on_open
        self._cb_refresh = on_refresh
        self._cb_toggle_login = on_toggle_login
        self._cb_quit = on_quit
        self._cb_open_window = on_open_window
        self._is_login_enabled = is_login_enabled
        self._icons: dict = {}                      # provider_id -> Gtk.StatusIcon
        self._sizes: dict[str, int] = {}
        self._last: dict[str, tuple] = {}           # provider_id -> (snapshot, note, stale)
        self._ready = threading.Event()
        self._GLib = None
        self._Gtk = None
        self._login_item = None
        self._menu = None
        self._syncing = False

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        threading.Thread(target=self._run, name="tray-gtk", daemon=True).start()
        if not self._ready.wait(10):
            config.log("tray: GTK did not start within 10s")

    def _run(self) -> None:
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf, GLib, Gtk
        except (ImportError, ValueError) as e:
            config.log(f"tray: GTK unavailable ({e}); install python3-gi and gir1.2-gtk-3.0")
            self._ready.set()
            return
        self._Gtk, self._GLib, self._Pixbuf = Gtk, GLib, GdkPixbuf
        warnings.filterwarnings("ignore", category=DeprecationWarning)   # StatusIcon is deprecated in GTK 3
        self._menu = self._build_menu()
        for pid, title in self._providers:
            self._make_icon(pid, title)
        self._ready.set()
        Gtk.main()

    def stop(self) -> None:
        if self._GLib and self._Gtk:
            Gtk = self._Gtk

            def _quit():
                for icon in self._icons.values():
                    icon.set_visible(False)
                Gtk.main_quit()
                return False
            self._GLib.idle_add(_quit)

    # ------------------------------------------------------------ icons (GTK thread)
    def _make_icon(self, pid: str, title: str) -> None:
        Gtk = self._Gtk
        icon = Gtk.StatusIcon()
        icon.set_name(f"{config.LINUX_ID}-{pid}")
        icon.set_title(f"{config.APP_NAME} — {title}")
        icon.connect("activate", lambda _i, p=pid: self._cb_open(p))
        icon.connect("popup-menu", self._on_popup)
        icon.connect("size-changed", lambda _i, size, p=pid: self._on_size(p, size))
        self._icons[pid] = icon
        self._sizes[pid] = 32
        self._paint(pid, None, "", False)
        icon.set_visible(True)

    def _on_size(self, pid: str, size: int) -> bool:
        if size > 0:
            self._sizes[pid] = size
            snap, note, stale = self._last.get(pid, (None, "", False))
            self._paint(pid, snap, note, stale)
        return True

    def _pixbuf(self, img):
        GLib, Pix = self._GLib, self._Pixbuf
        img = img.convert("RGBA")
        w, h = img.size
        return Pix.Pixbuf.new_from_bytes(GLib.Bytes.new(img.tobytes()), Pix.Colorspace.RGB, True, 8, w, h, w * 4)

    def _paint(self, pid: str, snap: Optional[Snapshot], note: str, stale: bool) -> None:
        icon = self._icons.get(pid)
        if icon is None:
            return
        title = dict(self._providers).get(pid, pid)
        worst = snap.worst() if snap else None
        img = ring_image(worst.percent if worst else None, pid, self._sizes.get(pid, 32), stale)
        icon.set_from_pixbuf(self._pixbuf(img))
        icon.set_tooltip_text(tooltip(snap, title, note))

    # ------------------------------------------------------------ menu (GTK thread)
    def _build_menu(self):
        Gtk = self._Gtk
        menu = Gtk.Menu()

        def item(label, cb):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda _w: cb())
            menu.append(mi)

        item("Quick view", lambda: self._cb_open(""))
        item("Open window", self._cb_open_window)
        item("Refresh now", self._cb_refresh)
        menu.append(Gtk.SeparatorMenuItem())
        self._login_item = Gtk.CheckMenuItem(label="Start on login")
        self._login_item.connect("toggled", self._on_login_toggled)
        menu.append(self._login_item)
        menu.append(Gtk.SeparatorMenuItem())
        item("Quit", self._cb_quit)
        menu.show_all()
        return menu

    def _on_login_toggled(self, _w) -> None:
        if not self._syncing:
            self._cb_toggle_login()

    def _sync_login_check(self) -> None:
        self._syncing = True
        try:
            self._login_item.set_active(bool(self._is_login_enabled()))
        finally:
            self._syncing = False

    def _on_popup(self, icon, button, activate_time) -> None:
        self._sync_login_check()
        self._menu.popup(None, None, self._Gtk.StatusIcon.position_menu, icon, button, activate_time)

    # ------------------------------------------------------------ public API (any thread)
    def update(self, snapshots: dict[str, Optional[Snapshot]], notes: dict[str, str],
               stale: dict[str, bool]) -> None:
        for pid, _title in self._providers:
            self._last[pid] = (snapshots.get(pid), notes.get(pid, ""), stale.get(pid, False))
        if not self._GLib:
            return

        def _apply():
            for pid, (snap, note, st) in list(self._last.items()):
                self._paint(pid, snap, note, st)
            return False
        self._GLib.idle_add(_apply)

    def refresh_menu(self) -> None:
        if self._GLib and self._login_item is not None:
            self._GLib.idle_add(lambda: (self._sync_login_check(), False)[1])

    def notify(self, message: str, title: Optional[str] = None) -> None:
        from . import notify
        notify.send(title or config.APP_NAME, message)
