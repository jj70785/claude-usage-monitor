# 0005 — Linux tray uses native `Gtk.StatusIcon`, not pystray

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

The tray must support **left-click → flyout**, **right-click → menu**, and a **hover
tooltip** with the numbers. It targets XFCE 4.20 on X11 first (MX Linux 25.3); the panel
there is often a vertical "deskbar". Options, analyzed in
[research/linux-xfce-desktop.md](../research/linux-xfce-desktop.md):

- **pystray, AppIndicator backend** (what `apt install python3-pystray` selects): no
  left-click activate (it always opens the menu) and no tooltip.
- **pystray, GTK backend:** works, but `Icon.title` is not a tooltip, so it needs a shim.
  Also, if the AppIndicator typelib is missing, `import pystray` raises `ValueError`
  instead of falling back to another backend.
- **pystray, xorg backend:** no menu and no notifications.
- **Native `Gtk.StatusIcon` via PyGObject:** left-click (`activate`), right-click
  (`popup-menu`), a real tooltip, and exact-size icons (`size-changed`). Deprecated in
  GTK 3 but fully functional on X11; XFCE's systray hosts these XEmbed icons.

The macOS build already made the same call (native `NSStatusItem` instead of pystray).

## Decision

`claude_usage_monitor/tray_linux.py` implements the shared `Tray` API with
`Gtk.StatusIcon`. GTK runs its own main loop on a daemon thread; only that thread touches
GTK objects. Other threads hand work over with `GLib.idle_add`, and GTK callbacks only
enqueue commands for the Tk thread. `pystray` is now used on Windows only.

## Consequences

- Linux needs `python3-gi` and `gir1.2-gtk-3.0` (preinstalled on most Debian desktops)
  plus `python3-tk`. No pip packages.
- **X11 only.** On Wayland, `Gtk.StatusIcon` doesn't show. A StatusNotifierItem (SNI)
  backend is on the roadmap.
- XFCE draws XEmbed icons on an opaque square (same as nm-applet, Notes, and Clipman).
  Cosmetic; SNI would fix it too.
- GTK logs one harmless `Gdk-CRITICAL … thaw_toplevel_updates` line at startup (see
  [bugs/known-issues.md](../bugs/known-issues.md)).
