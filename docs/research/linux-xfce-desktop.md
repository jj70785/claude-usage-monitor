# Linux desktop integration: XFCE 4.20 on X11

**TLDR:** On XFCE 4.20 under X11, the app shows its tray icons through a small native module that uses `Gtk.StatusIcon` via PyGObject. That gives a left-click flyout, a right-click menu, and a hover tooltip, and needs no pip packages. We dropped pystray on Linux because the backend it picks depends on how it was installed, it can crash at import time, and its AppIndicator backend cannot run anything on left-click. The flyout and window stay in Tk (`python3-tk`), start-on-login uses an XDG autostart `.desktop` file, single-instance uses a per-user Unix socket, and `xfce4-genmon-plugin` is a possible future panel readout.

This document explains *why* the Linux build works the way it does. It is written for future contributors, human or AI. If you are about to change tray, flyout, autostart, notification or packaging code on Linux, read this first.

---

## How to read the evidence labels

Every factual claim carries one of these labels:

| Label | Meaning |
|---|---|
| `[S#]` | Public source listed in [Sources](#sources) at the end, with URL and access date. |
| `[obs]` | Observed locally on the reference machine (below) on 2026-09-28. |
| `[unverified]` | Inferred from source reading or reasoning, and not yet tested at runtime. Treat it as a hypothesis. |

---

## 1. Target environment

The reference machine is the first Linux target. All values below are `[obs]`.

| Item | Value |
|---|---|
| Distribution | MX Linux 25.3 "Infinity", Xfce edition, on a Debian 13.7 ("trixie") base |
| Desktop | Xfce 4.20 (`xfce4-panel 4.20.4`) |
| Display server | X11 (`XDG_SESSION_TYPE=x11`, no `WAYLAND_DISPLAY`) |
| Init | systemd on this boot; MX also offers a sysVinit boot entry in GRUB |
| Python | 3.13.5, PEP 668 "externally managed" |
| PyGObject / GTK / GLib | 3.50.0 / 3.24.49 / 2.84.4 |
| Notification daemon | `xfce4-notifyd` 0.9.7 |

Xfce 4.20 was released on 2024-12-15 and includes "experimental Wayland support for most components" [S23]. X11 is still the default session on MX 25.3 `[obs]`. **Plan for X11 now, and keep a Wayland path in mind** (section 3.6).

---

## 2. The XFCE panel: what the tray actually looks like

### 2.1 A vertical "deskbar" is a real possibility

The reference machine has a single panel in **deskbar mode** (vertical, `mode=2`), docked on the **left** screen edge. It is about 36 px wide `[obs]`. Do not assume a horizontal bottom panel the way Windows does:

- **Flyout placement.** The current non-macOS code places the flyout at the bottom-right corner ("above the Windows taskbar", `popup.py`). On a left deskbar, that puts it on the opposite side of the screen from the icon. Anchor to the icon instead (section 4.1).
- **Width budget.** Anything drawn *in* the panel (for example a genmon widget, section 7) gets about 36 px of width `[obs]`.

### 2.2 One systray plugin hosts both tray protocols

There are two tray protocols on Linux:

| Protocol | How it works | Who uses it |
|---|---|---|
| **XEmbed system tray** ("legacy") | The app creates an X window, and the panel embeds it through the `_NET_SYSTEM_TRAY_S<n>` selection [S29]. X11 only. | `Gtk.StatusIcon`, older apps |
| **StatusNotifierItem (SNI)** | The app exports an object over D-Bus, and the panel draws the icon and menu itself [S28]. Works on Wayland too. | AppIndicator / Ayatana, Qt, Electron |

Since xfce4-panel 4.15.4, the "Status Tray" plugin (`systray`) supports both protocols in one plugin: "New plugin: statustray (supports statusnotifier and systray)" [S17]. On the reference machine, the 4.20 plugin owns both `org.kde.StatusNotifierWatcher` on the session bus and the `_NET_SYSTEM_TRAY_S0` X selection. It shows SNI items and XEmbed items side by side `[obs]`. **No extra indicator plugin or `snixembed` bridge is needed.**

### 2.3 Icon size: plan for about 32 px

- xfce4-panel added a per-panel `icon-size` setting in 4.13.4 [S17]. On the reference machine it is `0`, which means automatic `[obs]`.
- Embedded XEmbed tray icons measured 32x32 px `[obs]`.
- **Correction to earlier notes:** a `size-max=24` key exists in the reference machine's xfconf, but the 4.20 systray plugin does not read it. It is a stale legacy key, so do not size art for 24 px `[obs]`.
- `Gtk.StatusIcon` emits a `size-changed` signal [S18]. Re-render the PIL image at the size it reports instead of hard-coding one.

### 2.4 Stable names matter

XFCE remembers every tray item it has seen, so users can hide or reorder items:

- For XEmbed icons, `systray-socket.c` reads `_NET_WM_NAME`, falling back to `WM_NAME`. It lowercases the value and **caches it the first time it is read** [S16].
- With `Gtk.StatusIcon`, `set_title()` on X11 sets that window title [S19][S3].
- Rules that follow:
  - Give each icon a **fixed** title such as "Claude usage (5-hour)" *before* it is embedded.
  - **Never** put changing percentages in the title. Put them in the tooltip.
  - For SNI items, use a fixed item id. An app that registers a PID-based id gets a new "known item" in the panel's saved settings on every launch. The list grows without bound, and hide preferences never stick `[obs]`.

---

## 3. Tray backend analysis

### 3.1 Summary table

| Option | Left-click | Right-click menu | Hover tooltip | X11 | Wayland | Extra packages on Debian 13 |
|---|---|---|---|---|---|---|
| pystray, `appindicator` backend | Opens the menu. No custom action. | Yes | XFCE shows the SNI Title instead; other hosts may show nothing | Yes | Yes | `python3-pystray` (pulls in the Ayatana typelib, `python3-xlib`, `python3-six`) |
| pystray, `gtk` backend | Runs the default menu item | Yes | **No.** `title` is not a tooltip (see 3.4) | Yes | No | any pystray install, plus `PYSTRAY_BACKEND=gtk` set before import |
| pystray, `xorg` backend | Runs the default menu item | **No menu at all** | No | Yes | No | `python-xlib` |
| **Native `Gtk.StatusIcon` via PyGObject (chosen)** | **Any callback** (`activate`) | **Yes** (`popup-menu`) | **Yes** (`set_tooltip_text` / `set_tooltip_markup`) | **Yes** | **No** | **None beyond `python3-gi` and `gir1.2-gtk-3.0`** |
| Hand-written SNI over Gio D-Bus (future) | Could call `Activate` on XFCE (see 3.6) `[unverified]` | Needs a DBusMenu implementation | Yes (`ToolTip` property) | Yes | Yes | None beyond `python3-gi` |

Sources: pystray rows [S1][S2][S3][S5]; AppIndicator and XFCE behavior [S13][S14][S15]; GTK [S18][S19]. Details follow.

### 3.2 pystray's backend selection, and the ValueError pitfall

pystray 0.19.5 is still the latest release (uploaded 2023-09-17) [S11]. On Linux, when `PYSTRAY_BACKEND` is unset, it tries backends in the order `[appindicator, gtk, xorg]`, and the fallback loop **catches only `ImportError`** [S1]:

```python
# pystray/__init__.py (v0.19.5), abridged
for candidate in candidates:
    try:
        return candidate()
    except ImportError as e:
        errors.append(e)
```

The appindicator backend tries `AppIndicator3` first. If that raises `ValueError`, it tries `AyatanaAppIndicator3` **with no guard around the second attempt** [S2]:

```python
# pystray/_appindicator.py (v0.19.5)
try:
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import AppIndicator3 as AppIndicator
except ValueError:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
```

`gi.require_version()` raises `ValueError("Namespace ... not available")` when a typelib is missing [S33], and `ValueError` is not an `ImportError`. The result: **if PyGObject is importable but neither AppIndicator typelib is installed, `import pystray` raises `ValueError`. It does not fall back to gtk or xorg.**

That is exactly the default state of MX 25.3: the `libayatana-appindicator3-1` library is installed, but its typelib package `gir1.2-ayatanaappindicator3-0.1` is not `[obs]`.

What you get depends on how pystray was installed:

| Install method | Backend you actually get |
|---|---|
| `apt install python3-pystray` | **appindicator.** The Debian package depends on `gir1.2-ayatanaappindicator3-0.1` [S12]. |
| pip into a venv **without** system site-packages | **xorg** (silently). `import gi` fails with a real `ImportError`, so the loop falls through to xorg, which has no menu and no notifications [S5]. |
| pip where the system `gi` is visible, and no Ayatana typelib | **Crash** with `ValueError` at import |
| Any method with `PYSTRAY_BACKEND` set | Only that backend. There is no fallback, and a failure raises `ImportError` [S1]. |

**Gotcha:** `try: import pystray / except ImportError:` does **not** catch this failure. Any code that still imports pystray on Linux must catch `Exception`, or set `PYSTRAY_BACKEND` before the import.

### 3.3 AppIndicator limitations (what apt's pystray gives you)

- **No left-click action.** libayatana-appindicator 0.5.94's SNI interface has no `Activate` method and no `ToolTip` property. It exposes `Title`, `SecondaryActivate` and `Scroll` [S13]. pystray reflects this with `HAS_DEFAULT_ACTION = False` [S2].
- **Left-click opens the menu on XFCE.** XFCE 4.20 treats an SNI item as "menu only" unless the item says otherwise. On a button-1 press it pops up the menu instead of calling `Activate` [S14][S15]. Our "Quick view" item (`default=True`) is drawn in bold in that menu, but left-clicking the icon does not run it [S4]. Opening the flyout would take two clicks.
- **Tooltip: XFCE-specific fallback.** When an item has no `ToolTip`, XFCE 4.20 uses its `Title` as the tooltip [S14]. So pystray's `title` probably *does* appear on hover in XFCE. Other SNI hosts may show nothing `[unverified]`.
- **Middle-click.** XFCE sends `SecondaryActivate` [S15]. libayatana can route that to a menu item, but pystray never sets that target [S2].

### 3.4 Gtk.StatusIcon (XEmbed): why it fits, and its costs

What `Gtk.StatusIcon` gives us on X11 [S18]:

- an `activate` signal on left-click, which toggles the flyout
- a `popup-menu` signal on right-click, which shows a `Gtk.Menu`
- `set_tooltip_text()` / `set_tooltip_markup()`, for a real multi-line hover tooltip
- `get_geometry()`, which "can be used to e.g. position popups" [S20]. The flyout can therefore open next to the icon, wherever the panel is.
- `set_from_pixbuf()`, so a PIL image can be handed over in memory. pystray writes a temp PNG for every icon update, and those files can leak in `/tmp` (open issue [S10]).

What it costs:

- **Deprecated since GTK 3.14** [S18]. It still exists in GTK 3.24, and Debian 13 ships 3.24.49 `[obs]`. PyGObject emits deprecation warnings when you use it; filter them if a console is visible `[unverified]`.
- **X11 only.** It implements the freedesktop System Tray spec (XEmbed) [S18]. A native Wayland session has no XEmbed host, so it will not show there (section 3.6).
- **pystray's gtk backend does not give a tooltip.** pystray maps `Icon.title` to `Gtk.StatusIcon.set_title()`. GTK documents that as a string that "may be used by tools like screen readers", not a hover tooltip [S19][S3]. Hovering shows no title on that backend (reported in [S8]).

### 3.5 Decision: a native Linux tray module (like the macOS one)

The macOS build already skips pystray. `claude_usage_monitor/tray_macos.py` creates native `NSStatusItem`s, because pystray's macOS backend runs the AppKit loop on a background thread, which AppKit does not allow. It exposes the **same `Tray` API** as `tray.py` (`start/stop/update/notify/refresh_menu`) (repo source).

The Linux build follows the same pattern: a Linux-only tray module built directly on `Gtk.StatusIcon` through PyGObject, with the same `Tray` API.

Why:

1. **Behavior matches Windows and macOS.** Left-click opens the flyout, right-click opens the menu, and hovering shows a percentage tooltip. That is only possible with `Gtk.StatusIcon` on XFCE/X11 (table 3.1).
2. **No install-method roulette.** Section 3.2 shows that pystray's behavior on Linux changes with apt vs pip vs venv, including a crash at import.
3. **Fewer packages.** `python3-gi` and `gir1.2-gtk-3.0` were already installed on the reference MX 25.3 machine `[obs]`, and many GTK desktop apps depend on them, so they are common on Debian desktops `[unverified]`. **pystray and keyring are not needed on Linux.**
4. **Better integration:** in-memory icons (no temp files), a real tooltip, and icon-anchored flyout placement.

Implementation notes:

- **Threads.** Tk keeps the main thread. A single daemon thread runs one `GLib.MainLoop` that serves *all* status icons.
  - The Tk side must never call GTK directly. It posts work with `GLib.idle_add(...)`. `g_source_attach` (which `idle_add` uses) is documented as safe to call from any thread [S21].
  - GTK callbacks (menu items, `activate`) run on the GLib thread. They must not touch Tk widgets. They put a command on the app's existing queue, which Tk drains with `root.after` (the current `app.py` design already works this way).
- **Initialize GTK on the GLib thread.** Import `Gtk` and create every widget inside that thread, so that all GTK calls happen on one thread `[unverified]`.
  - For comparison, pystray initializes GTK on the importing thread and then drives it from its loop thread. That works in practice, but it technically breaks GTK's single-thread rule [S4].
  - Tk and GTK each open their own X connection. libX11 1.8 and later calls `XInitThreads()` by default [S32], and Debian 13 ships 1.8.12 `[obs]`.
- **Two separate loops are wasteful.** If you ever keep pystray, know that two `Icon.run()` calls in two threads do work, but the second thread just blocks while the first loop serves both icons [S4]. The native module avoids this by design.
- **pystray's own threading advice.** It has not crashed off the main thread on GTK backends since v0.18.0 [S7]. For a toolkit that does not run a GLib loop, such as Tk, upstream says to run the icon in a dedicated thread rather than use `run_detached()` [S6][S9].
- **Do not import `tray.py` on Linux.** The icon renderers (`make_bars_image`, `make_ring_image`, `_tip`) currently live in `tray.py`, which does `import pystray` at module level. The macOS module imports them from there. The Linux module should get them from a pystray-free module, or `tray.py` should import pystray lazily. Otherwise the Linux build either needs pystray installed or hits the section 3.2 crash.
- **Keyring is not needed.** `auth.py` imports `keyring` lazily inside `try/except` (repo source). Its only two uses were the pasted claude.ai session key and a cached copy of a self-refreshed Claude token, and both features are being removed: see [claude-usage-sources.md](claude-usage-sources.md#6-claudeai-web-route-with-sessionkey-removed) and [claude-oauth-tokens.md](claude-oauth-tokens.md#5-the-rule-for-this-app).
  - For reference only: `apt install python3-keyring` pulls `python3-secretstorage`, and on MX 25.3 gnome-keyring provides `org.freedesktop.secrets` (started by `systemd --user` on the systemd boot) `[obs]`.
  - The Antigravity CLI keeps its own login in that same Secret Service, which matters for how the app spawns `agy` (see [gemini-antigravity-usage.md](gemini-antigravity-usage.md#6-invocation-guardrails)). The app itself never reads it.

Minimal sketch (**untested**, for orientation only):

```python
import threading, queue
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GLib

def _pixbuf(pil_img):
    from gi.repository import GdkPixbuf
    img = pil_img.convert("RGBA")
    w, h = img.size
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(img.tobytes()), GdkPixbuf.Colorspace.RGB, True, 8, w, h, w * 4)

class LinuxTray:
    def __init__(self, commands: "queue.Queue"):
        self._cmds = commands          # drained by Tk via root.after
        self._ready = threading.Event()

    def start(self):
        threading.Thread(target=self._gtk_thread, daemon=True).start()
        self._ready.wait(5)

    def _gtk_thread(self):
        from gi.repository import Gtk  # GTK is initialized and used only on this thread
        self._icon = Gtk.StatusIcon(title="Claude usage (5-hour)")  # fixed title, see 2.4
        self._icon.connect("activate", lambda *_: self._cmds.put("toggle_flyout"))
        menu = Gtk.Menu()
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda *_: self._cmds.put("quit"))
        menu.append(quit_item)
        menu.show_all()
        self._icon.connect("popup-menu", lambda icon, button, t: menu.popup(
            None, None, Gtk.StatusIcon.position_menu, icon, button, t))
        self._loop = GLib.MainLoop()
        self._ready.set()
        self._loop.run()

    def update(self, pil_img, tooltip: str):   # called from the Tk thread
        GLib.idle_add(self._apply, pil_img, tooltip)

    def _apply(self, pil_img, tooltip):
        self._icon.set_from_pixbuf(_pixbuf(pil_img))
        self._icon.set_tooltip_text(tooltip)
        return False                   # run once

    def anchor(self):
        """(ok, screen, rect, orientation): use rect to place the flyout."""
        return self._icon.get_geometry()
```

### 3.6 Wayland and other desktops (future work)

`Gtk.StatusIcon` is not expected to work in a native Wayland session, because it relies on XEmbed (section 3.4; not tested). When Wayland support matters, there are two options:

1. **AppIndicator via `AyatanaAppIndicator3`.** This needs `gir1.2-ayatanaappindicator3-0.1`. You get a menu and, on XFCE, a Title tooltip, but no left-click action (section 3.3). The flyout would have to be reached from a menu item, a global hotkey, or a panel widget.
2. **A hand-written SNI item over Gio D-Bus** that exports `Activate`, a `ToolTip` property, and `ItemIsMenu=false`.
   - XFCE 4.20 reads `ItemIsMenu`. When an item is not menu-only and the user has not set "menu is primary", XFCE calls `Activate` on left-button release [S14][S15]. This would restore left-click-to-flyout under SNI `[unverified]`, untested.
   - The cost: the menu must be exported through the `com.canonical.dbusmenu` interface, which is a meaningful amount of code.

Other desktops were not tested for this document. GNOME needs an extension to show any tray icons at all, and KDE Plasma speaks SNI natively. Treat any claim about them as `[unverified]`.

---

## 4. The flyout and window (Tk on X11)

Tk stays the UI toolkit for the flyout and the full window, so **`python3-tk` is required**. It was *not* installed on the reference MX 25.3 machine `[obs]`, and the app cannot start without it. Known Linux issues in the current Tk code (repo source, `[obs]`):

| Issue | Where | Fix direction |
|---|---|---|
| Flyout hard-placed bottom-right "above the Windows taskbar" | `popup.py` | Anchor to `Gtk.StatusIcon.get_geometry()` [S20], clamp to the monitor, and open away from the panel edge. |
| On first show, `winfo_width()` returns 1 for a never-mapped window, so the size fallback never fires and the flyout can land mostly off-screen `[unverified]`: standard Tk behavior, not run here | `popup.py` (the macOS branch already guards with `w > 1`) | Call `update_idletasks()` and use `winfo_reqwidth()`, or apply the same guard. |
| `iconbitmap("icon.ico")` fails silently on X11 | `app.py` | Use `iconphoto()` with a PNG. |
| Fonts hard-coded to "Segoe UI". On Linux, fontconfig substitutes another font (Cantarell on the reference machine `[obs]`), so text sizes shift. | `panel.py` | Pick a font family per platform, or use Tk named fonts. |
| `overrideredirect(True)` plus `-topmost`: the window manager does not manage the flyout, and it can draw over fullscreen apps and games | `popup.py` | Keep the flyout short-lived, close it on focus-out or Escape, and never pop it up without a user action. |
| `-alpha` needs a compositor | `popup.py` | xfwm4 compositing is enabled on the reference machine `[obs]`. Without a compositor the window is simply opaque `[unverified]`. |

---

## 5. Notifications

The freedesktop Desktop Notifications spec defines the D-Bus service `org.freedesktop.Notifications` [S27]. On the reference machine, `xfce4-notifyd` 0.9.7 provides it and reports the capabilities `actions`, `action-icons`, `body`, `body-hyperlinks`, `body-markup` and `icon-static` `[obs]`.

Options, in order of preference:

| Option | Extra dependency | Notes |
|---|---|---|
| Call `Notify` directly through `Gio.DBusProxy` | none (`python3-gi`) | This is what pystray's own notifier does [S4]. Full control over `replaces_id`, `expire_timeout` and actions. |
| `gi.repository.Notify` (libnotify) | `gir1.2-notify-0.7` | Installed on MX 25.3 `[obs]`, but not guaranteed on other distributions. |
| `notify-send` subprocess | `libnotify-bin` | Simplest option, and handy for shell scripts or a genmon script. |

Spec details worth using [S27]:

- **`replaces_id`.** Pass the id returned by the previous `Notify` call, and the server "must atomically ... replace the given notification". Use it so repeated threshold alerts update one bubble instead of stacking.
- **`expire_timeout`.** `-1` means the server decides, and `0` means never expire.

GTK's documentation recommends `GNotification` with `GtkApplication` over status icons [S18]. That API needs a registered application id and an installed `.desktop` file, and we have not evaluated it here.

---

## 6. Start on login: XDG autostart

The current start-on-login code is Windows-only (it writes an `HKCU\...\Run` value), and the tray menu says "Start on Windows login" (repo source). On Linux:

- **Use `~/.config/autostart/<app>.desktop`.** The XDG Autostart spec [S25] defines `$XDG_CONFIG_HOME/autostart` (default `~/.config/autostart`) as the per-user autostart directory, and XFCE's session manager honors it.
- **Do not use a `systemd --user` unit.** MX offers a sysVinit boot entry, where user units do not run. Autostart `.desktop` files work under both init systems `[obs]`.
- **Disabling.** Delete the file. Alternatively, write `Hidden=true`, which per the spec means the file "MUST be ignored" [S25]. A same-named file with `Hidden=true` is also how a user disables a *system* autostart entry [S25], so a user override may already exist.
- **Write absolute paths.** The Desktop Entry spec defines no `~` or `$HOME` expansion in `Exec`, and it lists `~` as a reserved character [S26]. Generate the file at runtime with the real path.
- **Set `Path=` when running from a source checkout.** `Path` is "the working directory to run the program in" [S26]. The repo has no installable entry point yet, so `python3 -m claude_usage_monitor` only works from the checkout directory.

Example the app would write, with paths filled in at runtime:

```ini
[Desktop Entry]
Type=Application
Name=Claude Usage Monitor
Comment=Plan usage in the system tray
Exec=/usr/bin/python3 -m claude_usage_monitor --tray
Path=/absolute/path/to/claude-usage-monitor
Terminal=false
```

The menu label should become platform-neutral ("Start on login"), and `is_run_on_login()` should check that the file exists and is not `Hidden=true`.

---

## 7. Optional future panel widget: xfce4-genmon-plugin

A tray icon can only show a tiny picture plus a tooltip. `xfce4-genmon-plugin` ("Generic Monitor") runs a command on an interval and shows its output *in the panel*. That is a good fit for "always visible" numbers across several providers. It was installed on the reference MX 25.3 machine (version 4.1.1) but not added to the panel `[obs]`. **This is optional future work; the tray module above is the main UI.**

**Output tags.** The upstream docs list `<txt>`, `<txtclick>`, `<img>`, `<click>` (for the image), `<icon>`, `<iconclick>`, `<tool>` (tooltip), `<bar>` and `<css>`. `<txt>` and `<tool>` accept Pango markup [S22].

**Version gap.**
- `<css>` arrived in genmon **4.2.0**, and the latest upstream release is 4.3.0 (2025-05-20) [S22].
- Debian 13 / MX 25.3 ship **4.1.1**, which has no `<css>` support `[obs]`.
- Color text with Pango `<span foreground="#rrggbb">` instead. The existing `config.color_for_percent()` already returns hex colors.

**Hard rule: the genmon command must only read a cache file.** On 4.1.1, the plugin runs the command synchronously in the panel plugin and waits for it to exit; no worker thread was found `[obs]`. A slow command, such as a network call or an expensive CLI, therefore freezes that panel widget. The genmon script should:

1. read a JSON snapshot written by the running app (for example `~/.cache/<app>/state.json`, written atomically with a temp file and rename)
2. print tags and exit. Python starts in about 17 ms on the reference machine `[obs]`, so this costs next to nothing even at a 10-30 s period.

**Push refreshes instead of waiting for the timer.** After each fetch, the app can run:

```sh
xfce4-panel --plugin-event=genmon-N:refresh:bool:true
```

where `genmon-N` is that instance's widget name [S22]. The `--plugin-event` option works but is not listed in `xfce4-panel --help-all` on 4.20.4 `[obs]`. A new instance can be added with `xfce4-panel --add=genmon`; its `N` then has to be looked up with `xfconf-query -c xfce4-panel` `[obs]`.

**Deskbar layout.** In a 36 px vertical panel, one-line text such as `Claude 42% | 71%` does not fit. Genmon 4.1.1 does not rotate text `[obs]`. Use two or three stacked short lines (for example `C` / `42` / `71`), or a narrow `<img>` rendered with PIL.

**Click to open.** `<txtclick>` can launch the app. The single-instance handshake (section 8) then just shows the window of the already-running instance.

Example output:

```xml
<txt><span foreground="#3fb950">42</span>
<span foreground="#d29922">71</span></txt>
<tool>Claude, 5-hour: 42% (resets 16:20)
Claude, weekly: 71% (resets Thu)
Updated 3 min ago</tool>
<txtclick>/usr/bin/python3 -m claude_usage_monitor</txtclick>
```

### Always show data age

Some usage sources only update while the matching CLI is actively in use. Examples are data that arrives with each Claude Code response, and Codex's local session logs. The app can be running while the newest data point is days old. On the reference machine, the newest local Codex rate-limit record was three days old at check time `[obs]`.

- Every Linux surface (tooltip, flyout, genmon) should show when the data was fetched.
- Stale values should be dimmed or hidden rather than shown as current.
- A missing value means "unknown", not 0%.
- Per-provider freshness details are in the provider research docs.

---

## 8. Single instance: move off TCP port 49219

**Current behavior (repo source).** `app.py` binds TCP `127.0.0.1:49219` as a lock. If the bind fails, the new launch sends `SHOW` to the running instance and exits silently.

**Why this is fragile on Linux:**

- **The port is in the ephemeral range.** Linux picks local ports for *outgoing* TCP and UDP connections from `ip_local_port_range`, which defaults to **32768-60999** [S30]. The reference machine uses that default `[obs]`. Any unrelated outgoing connection can briefly hold 49219. A launch at that moment fails to bind, tries to send `SHOW`, finds nothing of ours listening, and exits with no message, so the app looks like it "just doesn't start."
- **It is not per-user.** On a machine with several users, one user's instance blocks everyone else's.

**Replacement: a pathname Unix socket in `$XDG_RUNTIME_DIR`.**

- **Where.** Use a socket such as `$XDG_RUNTIME_DIR/claude-usage-monitor.sock`. The spec requires that directory to be owned by the user with mode 0700, and to exist only for the login session [S24]. That makes the socket per-user and private, and it disappears at logout.
- **Stale socket files.** A pathname socket leaves a file behind that the owner must `unlink` [S34]. On startup, try to `connect()`:
  - If it succeeds, send `SHOW` and exit.
  - If it fails with `ECONNREFUSED` or `ENOENT`, unlink the stale file and `bind()`.
- **Races.** Two launches at the same instant could both see "stale". Serialize them with `fcntl.flock()` on a lock file next to the socket.
- **Fallback.** If `$XDG_RUNTIME_DIR` is unset, the spec says to "fall back to a replacement directory with similar capabilities and print a warning" [S24]. For example, use a 0700 directory under `~/.cache/<app>/`.
- **Why not an abstract socket.** Linux abstract sockets (leading NUL byte) need no cleanup, but "socket permissions have no meaning for abstract sockets" [S34], so any local user can connect to them. If you use one anyway, put the UID in the name and treat incoming messages as untrusted.
- **Keep the `SHOW` protocol unchanged.** Only the transport differs per platform.

---

## 9. Packages and the Python environment

### 9.1 Required and optional Debian packages

| Package | Why | Installed on the reference MX 25.3 machine `[obs]` |
|---|---|---|
| `python3-tk` | Tk flyout and window | **No.** It must be installed. |
| `python3-gi` | PyGObject, for the native tray, D-Bus notifications and GLib | Yes (3.50.0) |
| `gir1.2-gtk-3.0` | GTK 3 typelib (`Gtk.StatusIcon`, and GdkPixbuf through its dependencies) | Yes (3.24.49) |
| `python3-pil` | Renders the icon images | Yes (11.1.0) |
| `python3-keyring` *(not needed)* | Only served the removed session-key paste and token cache (section 3.5) | No |
| `libnotify-bin` *(optional)* | `notify-send`, for scripts | Yes |
| `xfce4-genmon-plugin` *(optional)* | Future panel readout (section 7) | Yes (4.1.1) |
| `gir1.2-ayatanaappindicator3-0.1` *(future, Wayland only)* | AppIndicator path (section 3.6) | No |

**Not needed on Linux:** `pystray`, `python3-xlib`, `python3-six`, `xfce4-indicator-plugin`, `snixembed`.

One-line install for the required set:

```sh
sudo apt install python3-tk python3-gi gir1.2-gtk-3.0 python3-pil
```

The app's Tk code uses only `tkinter`, not `PIL.ImageTk` (repo source), so `python3-pil.imagetk` is not needed.

### 9.2 PEP 668: do not pip install into the system Python

- **What PEP 668 does.** It lets a distribution mark its Python "externally managed" with an `EXTERNALLY-MANAGED` file. pip then refuses to install into that environment [S31]. Debian 13 ships this marker for Python 3.13 `[obs]`, so `pip install pystray keyring` into the system Python is refused unless you pass `--break-system-packages`. **Don't.**
- **Preferred: apt packages plus the system `python3`.** Every Linux dependency above is in Debian.
- **If you need a venv:**
  - Install `python3-venv` first. It was not installed on the reference machine `[obs]`.
  - Create the venv with `python3 -m venv --system-site-packages .venv`, so it can see the system `gi`.
  - PyGObject publishes no wheels on PyPI. pip builds it from source, which needs `libcairo-dev`, `libgirepository1.0-dev`, a compiler and `pkg-config` [S6].
  - A venv *without* system site-packages also changes pystray's backend silently (section 3.2).

### 9.3 Quick diagnostics

```sh
# Session type and desktop
echo "$XDG_SESSION_TYPE $XDG_CURRENT_DESKTOP"

# Does the panel host SNI items? (true/false)
gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
  --method org.freedesktop.DBus.NameHasOwner org.kde.StatusNotifierWatcher

# Can Python see GTK 3 and Tk?
python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk; print('gtk ok')"
python3 -c "import tkinter; print('tk', tkinter.TkVersion)"

# Would pystray's appindicator backend crash at import? (ValueError = yes)
python3 -c "import gi; gi.require_version('AyatanaAppIndicator3','0.1')"
```

---

## 10. Open questions and untested claims

- **Needs a runtime test (smoke test on XFCE 4.20/X11):**
  - the native `Gtk.StatusIcon` module running on a GLib thread next to Tk's main loop
  - multi-line `set_tooltip_text` rendering in the XFCE systray
  - `get_geometry()` returning a usable rectangle in deskbar mode
- **Whether XFCE shows an Ayatana indicator's `Title` as its tooltip** (section 3.3). This is inferred from xfce4-panel source and has not been observed.
- **A hand-written SNI item with `ItemIsMenu=false` getting left-click `Activate` on XFCE** (section 3.6). Inferred from source only.
- **Whether PyGObject's `Gtk.StatusIcon` deprecation warnings are noisy enough to matter** in a packaged build.
- **Other desktops** (GNOME with an AppIndicator extension, KDE Plasma, Cinnamon, MATE): not researched.
- **Wayland session on Xfce 4.20:** not tested. `Gtk.StatusIcon` is expected not to work there.

---

## Sources

Unless noted otherwise, all URLs were accessed on 2026-09-28.

| ID | Source |
|---|---|
| S1 | pystray v0.19.5, `lib/pystray/__init__.py` (backend map, `PYSTRAY_BACKEND`, fallback loop): https://github.com/moses-palmer/pystray/blob/v0.19.5/lib/pystray/__init__.py |
| S2 | pystray v0.19.5, `lib/pystray/_appindicator.py`: https://github.com/moses-palmer/pystray/blob/v0.19.5/lib/pystray/_appindicator.py |
| S3 | pystray v0.19.5, `lib/pystray/_gtk.py` (`activate`/`popup-menu` wiring; `title` goes to `set_title`): https://github.com/moses-palmer/pystray/blob/v0.19.5/lib/pystray/_gtk.py |
| S4 | pystray v0.19.5, `lib/pystray/_util/gtk.py` and `_util/notify_dbus.py` (GLib loop on the default context, `idle_add` dispatch, guarded `signal.signal`, default item drawn bold, D-Bus notifications): https://github.com/moses-palmer/pystray/tree/v0.19.5/lib/pystray/_util |
| S5 | pystray v0.19.5, `lib/pystray/_xorg.py` (`HAS_MENU = False`, `HAS_NOTIFICATION = False`): https://github.com/moses-palmer/pystray/blob/v0.19.5/lib/pystray/_xorg.py |
| S6 | pystray FAQ (no PyGObject wheel; build deps; running the icon loop in a thread): https://github.com/moses-palmer/pystray/blob/v0.19.5/docs/faq.rst |
| S7 | pystray changelog, v0.18.0 "Do not crash when running the icon in a non-main thread when using a GTK+ backend": https://github.com/moses-palmer/pystray/blob/v0.19.5/CHANGES.rst |
| S8 | pystray issue #45, "Title/name not working" (2020-03-27): https://github.com/moses-palmer/pystray/issues/45 |
| S9 | pystray issue #117, maintainer on Tkinter and `run_detached` (comment 2022-03-22): https://github.com/moses-palmer/pystray/issues/117 |
| S10 | pystray issue #194, temp icon PNGs left behind (opened 2026-09-09): https://github.com/moses-palmer/pystray/issues/194 |
| S11 | pystray on PyPI (latest 0.19.5, uploaded 2023-09-17): https://pypi.org/project/pystray/ |
| S12 | Debian trixie `python3-pystray` 0.19.5-1 dependencies: https://packages.debian.org/trixie/python3-pystray |
| S13 | libayatana-appindicator 0.5.94, `src/notification-item.xml` (SNI interface: no `Activate`, no `ToolTip`): https://github.com/AyatanaIndicators/libayatana-appindicator/blob/0.5.94/src/notification-item.xml |
| S14 | xfce4-panel 4.20.4, `plugins/systray/sn-item.c` (`item_is_menu` defaults to TRUE; `ItemIsMenu` handling; tooltip falls back to Title): https://gitlab.xfce.org/xfce/xfce4-panel/-/blob/xfce4-panel-4.20.4/plugins/systray/sn-item.c |
| S15 | xfce4-panel 4.20.4, `plugins/systray/sn-button.c` (button 1 opens the menu when menu-only; `Activate` on release otherwise; middle-click behavior): https://gitlab.xfce.org/xfce/xfce4-panel/-/blob/xfce4-panel-4.20.4/plugins/systray/sn-button.c |
| S16 | xfce4-panel 4.20.4, `plugins/systray/systray-socket.c` (legacy item name from `_NET_WM_NAME`/`WM_NAME`, lowercased and cached): https://gitlab.xfce.org/xfce/xfce4-panel/-/blob/xfce4-panel-4.20.4/plugins/systray/systray-socket.c |
| S17 | xfce4-panel NEWS (4.13.4 per-panel `icon-size`; 4.15.4 "statustray (supports statusnotifier and systray)"): https://gitlab.xfce.org/xfce/xfce4-panel/-/blob/xfce4-panel-4.20.4/NEWS |
| S18 | GTK 3 `GtkStatusIcon` reference (deprecated since 3.14; X11 follows the System Tray spec; recommends `GNotification`): https://docs.gtk.org/gtk3/class.StatusIcon.html |
| S19 | GTK 3 `gtk_status_icon_set_title` ("may be used by tools like screen readers"): https://docs.gtk.org/gtk3/method.StatusIcon.set_title.html |
| S20 | GTK 3 `gtk_status_icon_get_geometry` ("can be used to e.g. position popups"): https://docs.gtk.org/gtk3/method.StatusIcon.get_geometry.html |
| S21 | GLib 2.84.4 `glib/gmain.c`, `g_source_attach` documented as safe to call from any thread: https://gitlab.gnome.org/GNOME/glib/-/blob/2.84.4/glib/gmain.c |
| S22 | xfce4-genmon-plugin documentation (tags, Pango markup, `<css>` since 4.2.0, `--plugin-event` refresh, latest 4.3.0 released 2025-05-20): https://docs.xfce.org/panel-plugins/xfce4-genmon-plugin/start |
| S23 | Xfce 4.20 release announcement (2024-12-15; experimental Wayland support): https://www.xfce.org/about/news/?post=1734220800 |
| S24 | XDG Base Directory Specification 0.8 (`$XDG_RUNTIME_DIR` ownership, mode 0700, lifetime, fallback): https://specifications.freedesktop.org/basedir/latest/ |
| S25 | Desktop Application Autostart Specification 0.5 (autostart dirs, `Hidden`, `OnlyShowIn`, `TryExec`, user overrides): https://specifications.freedesktop.org/autostart/latest/ |
| S26 | Desktop Entry Specification 1.5 (`Path` key; `Exec` quoting and reserved characters): https://specifications.freedesktop.org/desktop-entry/latest/recognized-keys.html and https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html |
| S27 | Desktop Notifications Specification 1.3, protocol (`replaces_id`, `expire_timeout`, capabilities): https://specifications.freedesktop.org/notification/latest/protocol.html |
| S28 | StatusNotifierItem specification (freedesktop wiki; not re-fetched for this document): https://www.freedesktop.org/wiki/Specifications/StatusNotifierItem/ |
| S29 | System Tray Protocol Specification (XEmbed tray; linked from S18): https://specifications.freedesktop.org/systemtray-spec/latest/ |
| S30 | Linux kernel `ip-sysctl` documentation, `ip_local_port_range` default 32768 60999: https://docs.kernel.org/networking/ip-sysctl.html |
| S31 | PEP 668, "Marking Python base environments as externally managed" (Final; created 2021-05-18): https://peps.python.org/pep-0668/ |
| S32 | libX11 1.8 release announcement (`XInitThreads` called by default), April 2022: https://lists.x.org/archives/xorg-announce/2022-April/003161.html |
| S33 | PyGObject 3.50.0, `gi/__init__.py` (`require_version` raises `ValueError` for a missing namespace): https://gitlab.gnome.org/GNOME/pygobject/-/blob/3.50.0/gi/__init__.py |
| S34 | `unix(7)` Linux man page (abstract socket permissions; unlinking pathname sockets): https://man7.org/linux/man-pages/man7/unix.7.html |

"Repo source" means this repository's own code on the `linux-multi-ai` branch, before the Linux tray module landed (`app.py`, `auth.py`, `config.py`, `panel.py`, `popup.py`, `tray.py`, `tray_macos.py`).
