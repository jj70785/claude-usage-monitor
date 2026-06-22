"""App orchestration.

Surfaces:
  - tray icon (always)            : left-click toggles the corner flyout (+refresh)
  - corner flyout (frameless)     : quick glance, auto-hides
  - main window (the Tk root)      : a real taskbar app you can move + pin; opened from
                                     Windows Search / Start / tray "Open window"

Both the flyout and the main window render the same shared UsagePanel and are updated
together. A second launch of the exe doesn't start a duplicate — it connects to the
single-instance socket and sends SHOW, and the running instance raises its window.

Threads: main (Tk + 200ms poller + 1s button ticker) · tray (pystray) ·
worker (serialized fetch loop) · listener (single-instance SHOW channel).
"""
from __future__ import annotations

import queue
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import simpledialog, messagebox

from . import auth, config, usage_api
from .config import Prefs
from .panel import BG, UsagePanel
from .popup import Popup
if sys.platform == "darwin":
    from .tray_macos import Tray   # native NSStatusItem on the main thread (no pystray)
else:
    from .tray import Tray
from .usage_api import AuthExpired, RateLimited, UsageError, Usage

_LOCK_PORT = 49219


class TokenBucket:
    """Thread-safe token bucket. capacity = burst size, one token per refill_sec."""
    def __init__(self, capacity: int, refill_sec: float):
        self.capacity = float(capacity)
        self.refill_sec = float(refill_sec)
        self.tokens = float(capacity)
        self.last = time.monotonic()
        self._lock = threading.Lock()

    def _refill_locked(self):
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) / self.refill_sec)
        self.last = now

    def take(self) -> bool:
        with self._lock:
            self._refill_locked()
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False

    def seconds_until_token(self) -> int:
        with self._lock:
            self._refill_locked()
            if self.tokens >= 1.0:
                return 0
            return int(self.refill_sec * (1.0 - self.tokens)) + 1

    def drain(self):
        with self._lock:
            self.tokens = 0.0
            self.last = time.monotonic()


class App:
    def __init__(self, lock_sock: socket.socket, show_window_on_start: bool):
        self._lock_sock = lock_sock
        self._show_on_start = show_window_on_start
        self.prefs = Prefs.load()
        self.last_usage: Usage | None = usage_api.load_cache()
        self.note: str = ""
        self.live = False
        self.pinned = self.prefs.window_pinned
        self._window_shown_once = False

        self.bucket = TokenBucket(config.RL_CAPACITY, config.RL_REFILL_SEC)
        self._rl_block_until = 0.0
        self._fetching = False
        self._manual_pending = False

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._results: "queue.Queue" = queue.Queue()
        self._commands: "queue.Queue" = queue.Queue()
        self._last_ui_tick = 0.0

        # The Tk root IS the main pop-out window (taskbar app). Starts hidden.
        self.root = tk.Tk()
        self.root.title(config.APP_NAME)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        try:
            self.root.iconbitmap(config.asset_path("icon.ico"))
        except Exception:
            pass
        if sys.platform == "darwin":
            # macOS shows a generic document proxy icon in the title bar by default;
            # clearing the represented file path removes it.
            try:
                self.root.wm_attributes("-titlepath", "")
            except Exception:
                pass
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.withdraw()

        self.window_panel = UsagePanel(
            self.root, on_refresh=lambda: self.request_refresh(),
            on_live=self.set_live, on_pin=self.toggle_pin,
        )
        self.window_panel.frame.pack(fill="both", expand=True)
        self.window_panel.set_pinned(self.pinned)

        self.flyout = Popup(self.root, on_refresh=lambda: self.request_refresh(), on_live=self.set_live)

        self.tray = Tray(
            on_open=lambda: self._commands.put(("open", None)),
            on_refresh=lambda: self._commands.put(("refresh", None)),
            on_toggle_login=lambda: self._commands.put(("toggle_login", None)),
            on_quit=lambda: self._commands.put(("quit", None)),
            on_paste_key=lambda: self._commands.put(("paste_key", None)),
            on_open_window=lambda: self._commands.put(("show_window", None)),
        )
        if self.last_usage:
            self._update_views(self.last_usage)

    # ------------------------------------------------------------------ worker
    def _auto_interval(self) -> float:
        return config.LIVE_REFRESH_SEC if self.live else self.prefs.auto_refresh_sec

    def _worker(self):
        if self.bucket.take():
            self._fetching = True
            self._do_fetch()
        while not self._stop.is_set():
            triggered = self._wake.wait(timeout=self._auto_interval())
            self._wake.clear()
            if self._stop.is_set():
                break
            if self._manual_pending:
                self._manual_pending = False
                self._do_fetch()
            else:
                if time.monotonic() >= self._rl_block_until and self.bucket.take():
                    self._fetching = True
                    self._do_fetch()

    def _do_fetch(self):
        try:
            a = auth.get_auth()
            u = usage_api.fetch(a)
            self._results.put(("ok", u))
        except RateLimited as e:
            self._results.put(("rate", e.retry_after))
        except AuthExpired:
            self._results.put(("auth", None))
        except auth.AuthError as e:
            self._results.put(("noauth", str(e)))
        except UsageError as e:
            self._results.put(("err", str(e)))
        except Exception as e:
            self._results.put(("err", f"{type(e).__name__}: {e}"))

    # --------------------------------------------------------------- refresh
    def request_refresh(self, manual: bool = True):
        if self._fetching:
            return
        if time.monotonic() < self._rl_block_until:
            self._update_button()
            return
        if not self.bucket.take():
            self._update_button()
            return
        self._fetching = True
        self._manual_pending = True
        self._set_refresh_button(False, "Refreshing…")
        self._wake.set()

    def set_live(self, on: bool):
        self.live = on
        self.flyout.set_live_display(on)
        self.window_panel.set_live_display(on)
        if on:
            self._wake.set()

    def _set_refresh_button(self, enabled: bool, label: str):
        self.flyout.set_refresh_enabled(enabled, label)
        self.window_panel.set_refresh_enabled(enabled, label)

    def _update_button(self):
        if self._fetching:
            return
        now = time.monotonic()
        if now < self._rl_block_until:
            self._set_refresh_button(False, f"Limited {int(self._rl_block_until - now)}s")
        else:
            s = self.bucket.seconds_until_token()
            self._set_refresh_button(s == 0, "Refresh" if s == 0 else f"Wait {s}s")

    def _button_tick(self):
        self._update_button()
        if not self._stop.is_set():
            self.root.after(1000, self._button_tick)

    def _update_views(self, usage, note: str = ""):
        self.flyout.update(usage, note)
        self.window_panel.update(usage, note)
        self.tray.update(usage, note)

    # --------------------------------------------------------------- main loop
    def _poll(self):
        try:
            while True:
                cmd, _ = self._commands.get_nowait()
                self._handle_command(cmd)
        except queue.Empty:
            pass
        try:
            while True:
                kind, payload = self._results.get_nowait()
                self._handle_result(kind, payload)
        except queue.Empty:
            pass

        now = time.monotonic()
        if self.last_usage and now - self._last_ui_tick > 30:
            self._last_ui_tick = now
            self._update_views(self.last_usage, self.note)

        if not self._stop.is_set():
            self.root.after(200, self._poll)

    def _handle_command(self, cmd: str):
        if cmd == "open":                       # tray left-click: toggle the flyout
            if self.flyout.is_visible():
                self.flyout.hide()
            else:
                self.flyout.show()
                self.request_refresh()
        elif cmd == "show_window":              # tray "Open window" / Windows Search
            self.show_window()
        elif cmd == "refresh":
            self.request_refresh()
        elif cmd == "toggle_login":
            config.set_run_on_login(not config.is_run_on_login())
            self.prefs.start_on_login = config.is_run_on_login()
            self.prefs.save()
            self.tray.refresh_menu()
        elif cmd == "paste_key":
            self._prompt_session_key()
        elif cmd == "quit":
            self.shutdown()

    def _handle_result(self, kind: str, payload):
        self._fetching = False
        if kind == "ok":
            fh = payload.five_hour.percent if payload.five_hour else None
            wk = payload.weekly.percent if payload.weekly else None
            config.log(f"ok  five_hour={fh}  weekly={wk}  plan={payload.plan}")
            self.last_usage = payload
            self.note = ""
            usage_api.save_cache(payload)
            self._maybe_notify(payload)
            self._update_views(payload)
        elif kind == "rate":
            retry = payload if isinstance(payload, int) and payload > 0 else 300
            config.log(f"429 rate limited, retry_after={retry}")
            self._rl_block_until = time.monotonic() + retry
            self.bucket.drain()
            self.note = "Rate limited — backing off"
            self._update_views(self.last_usage, self.note)
        elif kind == "auth":
            config.log("auth expired")
            self.note = "Session expired — open Claude Code or paste a session key"
            self._update_views(self.last_usage, self.note)
        elif kind == "noauth":
            config.log(f"noauth: {payload}")
            self.note = "No login found — paste a session key"
            self._update_views(self.last_usage, self.note)
        else:
            config.log(f"error: {payload}")
            self.note = f"Error: {payload}"
            self._update_views(self.last_usage, self.note)
        self._update_button()

    def _maybe_notify(self, u: Usage):
        if not self.prefs.notify_on_warn:
            return
        for w, name in ((u.five_hour, "5-hour session"), (u.weekly, "weekly")):
            if w and w.percent >= self.prefs.warn_threshold:
                key = f"{name}:{int(w.percent // 5)}"
                if getattr(self, "_last_notify_key", None) != key:
                    self._last_notify_key = key
                    self.tray.notify(f"{name} at {w.percent:.0f}% of your limit", config.APP_NAME)
                break

    def _prompt_session_key(self):
        val = simpledialog.askstring(
            config.APP_NAME,
            "Paste your claude.ai sessionKey cookie\n(claude.ai → F12 → Application → Cookies → sessionKey):",
            parent=self.root, show="*",
        )
        if val is None:
            return
        if auth.save_session_key(val):
            messagebox.showinfo(config.APP_NAME, "Saved. Refreshing…", parent=self.root)
            self.request_refresh()
        else:
            messagebox.showerror(config.APP_NAME,
                                 "That doesn't look like a sessionKey (expected sk-ant-sid…).",
                                 parent=self.root)

    # --------------------------------------------------------------- window
    def show_window(self):
        self.root.deiconify()
        self.root.attributes("-topmost", self.pinned)
        self.window_panel.set_pinned(self.pinned)
        self._apply_dark_titlebar()
        self.root.update_idletasks()
        # Position LAST — the topmost/DWM/focus calls above reset a position set earlier.
        if self.prefs.window_geometry:
            try:
                self.root.geometry(self.prefs.window_geometry)
            except Exception:
                pass
        elif not self._window_shown_once:
            w = self.root.winfo_reqwidth() or 352
            h = self.root.winfo_reqheight() or 480
            x = max(0, (self.root.winfo_screenwidth() - w) // 2)
            y = max(0, (self.root.winfo_screenheight() - h) // 3)
            self.root.geometry(f"{w}x{h}+{x}+{y}")
        self._window_shown_once = True
        self.root.lift()
        self.root.focus_force()
        self.request_refresh()

    def hide_window(self):
        try:
            self.prefs.window_geometry = "+" + "+".join(self.root.geometry().split("+")[1:])
            self.prefs.save()
        except Exception:
            pass
        self.root.withdraw()

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.root.attributes("-topmost", self.pinned)
        self.window_panel.set_pinned(self.pinned)
        self.prefs.window_pinned = self.pinned
        self.prefs.save()

    def _apply_dark_titlebar(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            val = ctypes.c_int(1)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Win11 / older builds)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
        except Exception:
            pass

    # --------------------------------------------------------------- IPC
    def _listener(self):
        """Accept connections on the single-instance socket; a 'SHOW' means another
        launch wants us to surface the window."""
        while not self._stop.is_set():
            try:
                conn, _ = self._lock_sock.accept()
            except OSError:
                break
            try:
                data = conn.recv(64)
                if b"SHOW" in data:
                    self._commands.put(("show_window", None))
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def _set_dock_icon_macos(self):
        """Give the Dock (and app switcher) our icon instead of the generic Python one.
        Converts the bundled .ico to an NSImage at runtime — runs on the main thread."""
        try:
            import io
            from AppKit import NSApplication, NSImage
            from Foundation import NSData
            from PIL import Image
            im = Image.open(config.asset_path("icon.ico"))
            im = im.convert("RGBA").resize((512, 512))
            buf = io.BytesIO()
            im.save(buf, "PNG")
            data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
            ns = NSImage.alloc().initWithData_(data)
            NSApplication.sharedApplication().setApplicationIconImage_(ns)
        except Exception as e:
            config.log(f"dock icon skipped: {e}")

    # --------------------------------------------------------------- lifecycle
    def run(self):
        config.log(f"app start (frozen={getattr(sys, 'frozen', False)}, show_window={self._show_on_start})")
        if sys.platform == "darwin":
            self._set_dock_icon_macos()
        threading.Thread(target=self._worker, name="fetch", daemon=True).start()
        self.tray.start()   # spawns both tray icons (bars = 5-hour, ring = weekly)
        threading.Thread(target=self._listener, name="ipc", daemon=True).start()
        self.root.after(200, self._poll)
        self.root.after(1000, self._button_tick)
        if self._show_on_start:
            self.root.after(80, self.show_window)
        self.root.mainloop()

    def shutdown(self):
        self._stop.set()
        self._wake.set()
        try:
            self._lock_sock.close()   # breaks the listener's accept()
        except Exception:
            pass
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass


# --- single-instance + launch -------------------------------------------------
def _try_bind() -> "socket.socket | None":
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", _LOCK_PORT))   # no SO_REUSEADDR: bind must fail if already running
        s.listen(5)
        return s
    except OSError:
        s.close()
        return None


def _signal_show():
    try:
        c = socket.create_connection(("127.0.0.1", _LOCK_PORT), timeout=2)
        c.sendall(b"SHOW")
        c.close()
    except OSError:
        pass


def main():
    tray_only = "--tray" in sys.argv[1:]
    sock = _try_bind()
    if sock is None:
        # already running: ask the live instance to show its window, then exit
        _signal_show()
        return
    App(sock, show_window_on_start=not tray_only).run()


if __name__ == "__main__":
    main()
