"""App orchestration.

Surfaces:
  - one tray icon per AI (always) : left-click toggles the flyout, right-click = menu
  - corner flyout (frameless)     : quick glance
  - main window (the Tk root)     : movable, pinnable; opened from the app menu or tray

Threads: main (Tk + 200 ms poller + 1 s button ticker) · tray (GTK on Linux, pystray on
Windows, main thread on macOS) · worker (fetch + peek loop) · ipc (single-instance SHOW).
Only the main thread touches Tk; everything else talks to it through queues.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from typing import Optional

from . import config, singleinstance
from .config import Prefs
from .model import Snapshot, utcnow
from .notify import ThresholdNotifier
from .panel import BG, ProviderView, UsagePanel
from .popup import Popup
from .providers import NotLoggedIn, Provider, ProviderError, RateLimited, build_providers
from .providers.claude import SOURCE_LABELS

if sys.platform == "darwin":
    from .tray_macos import Tray      # native NSStatusItem on the main thread
elif config.IS_LINUX:
    from .tray_linux import Tray      # native Gtk.StatusIcon on its own thread
else:
    from .tray import Tray            # pystray (Windows)


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


class ProviderState:
    """Scheduling state for one provider (touched by the worker; read by the UI)."""

    def __init__(self, provider: Provider):
        self.provider = provider
        self.bucket = TokenBucket(config.RL_CAPACITY, config.RL_REFILL_SEC)
        self.block_until = 0.0            # monotonic; set after a 429
        self.next_due = 0.0               # monotonic; 0 = fetch right away
        self.fetching = False

    def ready(self) -> bool:
        return time.monotonic() >= self.block_until and self.bucket.seconds_until_token() == 0


# --- snapshot cache (first paint before the first fetch) ---------------------------
def load_snapshots() -> dict[str, Snapshot]:
    try:
        with open(config.snapshots_path(), "r", encoding="utf-8") as f:
            return {d["provider_id"]: Snapshot.from_dict(d) for d in json.load(f)}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def save_snapshots(snaps: dict[str, Snapshot]) -> None:
    path = config.snapshots_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([s.to_dict() for s in snaps.values()], f)
        os.replace(tmp, path)
    except OSError:
        pass


class App:
    def __init__(self, lock_sock, show_window_on_start: bool):
        self._lock_sock = lock_sock
        self._show_on_start = show_window_on_start
        self.prefs = Prefs.load()
        self.providers = build_providers(self.prefs)
        self.states = {p.id: ProviderState(p) for p in self.providers}
        self.snapshots: dict[str, Snapshot] = {
            pid: s for pid, s in load_snapshots().items() if pid in self.states}
        for p in self.providers:
            if hasattr(p, "seed"):
                p.seed(self.snapshots.get(p.id))
        self.notes: dict[str, str] = {}
        self.status = ""
        self.live = False
        self.pinned = self.prefs.window_pinned
        self._window_shown_once = False
        self._notifier = ThresholdNotifier()

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._manual = threading.Event()
        self._results: "queue.Queue" = queue.Queue()
        self._commands: "queue.Queue" = queue.Queue()
        self._last_ui_tick = 0.0
        self._refreshing = False

        # The Tk root IS the main pop-out window. Starts hidden.
        self.root = tk.Tk(className=config.LINUX_ID)
        self.root.title(config.APP_NAME)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self._set_window_icon()
        if sys.platform == "darwin":
            try:
                self.root.wm_attributes("-titlepath", "")
            except tk.TclError:
                pass
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.withdraw()

        self.window_panel = UsagePanel(self.root, on_refresh=self.request_refresh,
                                       on_live=self.set_live, on_pin=self.toggle_pin)
        self.window_panel.frame.pack(fill="both", expand=True)
        self.window_panel.set_pinned(self.pinned)
        self.flyout = Popup(self.root, on_refresh=self.request_refresh, on_live=self.set_live)

        cmd = self._commands.put
        self.tray = Tray(
            [(p.id, p.title) for p in self.providers],
            on_open=lambda pid: cmd(("open", pid)),
            on_refresh=lambda: cmd(("refresh", None)),
            on_toggle_login=lambda: cmd(("toggle_login", None)),
            on_quit=lambda: cmd(("quit", None)),
            on_open_window=lambda: cmd(("show_window", None)),
            is_login_enabled=config.is_run_on_login,
        )
        self._update_views()

    def _set_window_icon(self):
        try:
            if sys.platform == "win32":
                self.root.iconbitmap(config.asset_path("icon.ico"))
                return
            import base64
            import io

            from PIL import Image
            buf = io.BytesIO()
            Image.open(config.asset_path("icon.ico")).convert("RGBA").resize((64, 64)).save(buf, "PNG")
            self._icon_img = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
            self.root.iconphoto(True, self._icon_img)
        except Exception as e:
            config.log(f"window icon skipped: {e}")

    # ------------------------------------------------------------------ worker
    def _interval(self, st: ProviderState) -> float:
        base = config.LIVE_REFRESH_SEC if self.live else self.prefs.auto_refresh_sec
        return max(base, st.provider.min_interval_sec)

    def _worker(self):
        while not self._stop.is_set():
            manual = self._manual.is_set()
            self._manual.clear()
            now = time.monotonic()
            for st in self.states.values():
                if self._stop.is_set():
                    break
                due = manual or now >= st.next_due
                if not due or now < st.block_until or not st.bucket.take():
                    continue
                st.next_due = now + self._interval(st)
                self._fetch(st)
            if manual:
                self._results.put(("manual_done", None, None))
            for st in self.states.values():
                try:
                    snap = st.provider.peek()
                except Exception as e:
                    config.log(f"peek {st.provider.id} failed: {type(e).__name__}: {e}")
                    snap = None
                if snap is not None:
                    self._results.put(("peek", st.provider.id, snap))
            nxt = min((st.next_due for st in self.states.values()), default=now + config.PEEK_SEC)
            self._wake.wait(timeout=max(1.0, min(config.PEEK_SEC, nxt - time.monotonic())))
            self._wake.clear()

    def _fetch(self, st: ProviderState):
        pid = st.provider.id
        st.fetching = True
        try:
            self._results.put(("ok", pid, st.provider.fetch()))
        except RateLimited as e:
            self._results.put(("rate", pid, e.retry_after))
        except NotLoggedIn as e:
            self._results.put(("login", pid, str(e)))
        except ProviderError as e:
            self._results.put(("err", pid, str(e)))
        except Exception as e:
            config.log(f"fetch {pid} crashed:\n{traceback.format_exc()}")
            self._results.put(("err", pid, f"{type(e).__name__}: {e}"))
        finally:
            st.fetching = False

    # --------------------------------------------------------------- refresh
    def request_refresh(self):
        if self._refreshing:
            return
        if not any(st.ready() for st in self.states.values()):
            self._update_button()
            return
        self._refreshing = True
        self._set_refresh_button(False, "Refreshing…")
        self._manual.set()
        self._wake.set()

    def set_live(self, on: bool):
        self.live = on
        self.flyout.set_live_display(on)
        self.window_panel.set_live_display(on)
        now = time.monotonic()
        for st in self.states.values():            # re-plan with the new interval
            st.next_due = min(st.next_due, now + self._interval(st))
        self._wake.set()

    def _set_refresh_button(self, enabled: bool, label: str):
        self.flyout.set_refresh_enabled(enabled, label)
        self.window_panel.set_refresh_enabled(enabled, label)

    def _update_button(self):
        if self._refreshing:
            return
        now = time.monotonic()
        waits = []
        for st in self.states.values():
            if now < st.block_until:
                waits.append(int(st.block_until - now))
            else:
                waits.append(st.bucket.seconds_until_token())
        wait = min(waits) if waits else 0
        if wait <= 0:
            self._set_refresh_button(True, "Refresh")
        else:
            self._set_refresh_button(False, f"Wait {wait}s")

    def _button_tick(self):
        self._update_button()
        if not self._stop.is_set():
            self.root.after(1000, self._button_tick)

    # --------------------------------------------------------------- views
    def _views(self) -> list[ProviderView]:
        out = []
        for p in self.providers:
            snap = self.snapshots.get(p.id)
            stale = bool(snap) and snap.is_stale(config.STALE_AFTER_SEC)
            out.append(ProviderView(p.id, p.title, snap, note=self.notes.get(p.id, ""), stale=stale,
                                    source_label=SOURCE_LABELS.get(snap.source, "") if snap else ""))
        return out

    def _update_views(self):
        views = self._views()
        sources = [f"{v.title}: {v.source_label}" for v in views if v.source_label]
        status = self.status or " · ".join(sources)
        self.flyout.update(views, status)
        self.window_panel.update(views, status)
        self.tray.update({v.provider_id: v.snapshot for v in views},
                         {v.provider_id: v.note for v in views},
                         {v.provider_id: v.stale for v in views})

    # --------------------------------------------------------------- main loop
    def _poll(self):
        try:
            while True:
                cmd, arg = self._commands.get_nowait()
                self._handle_command(cmd, arg)
        except queue.Empty:
            pass
        changed = False
        try:
            while True:
                kind, pid, payload = self._results.get_nowait()
                changed |= self._handle_result(kind, pid, payload)
        except queue.Empty:
            pass
        now = time.monotonic()
        if changed or now - self._last_ui_tick > 30:
            self._last_ui_tick = now
            self._update_views()
        if not self._stop.is_set():
            self.root.after(200, self._poll)

    def _handle_command(self, cmd: str, arg):
        if cmd == "open":                       # tray left-click: toggle the flyout
            if self.flyout.is_visible():
                self.flyout.hide()
            else:
                self._update_views()
                self.flyout.show()
                self._refresh_if_old()
        elif cmd == "show_window":
            self.show_window()
        elif cmd == "refresh":
            self.request_refresh()
        elif cmd == "toggle_login":
            config.set_run_on_login(not config.is_run_on_login())
            self.prefs.start_on_login = config.is_run_on_login()
            self.prefs.save()
            self.tray.refresh_menu()
        elif cmd == "quit":
            self.shutdown()

    def _refresh_if_old(self):
        """Opening the flyout only spends a request when the data is actually old."""
        newest = [s.fetched_at for s in self.snapshots.values() if s.fetched_at]
        if not newest or (utcnow() - max(newest)).total_seconds() > config.LIVE_REFRESH_SEC:
            self.request_refresh()

    def _handle_result(self, kind: str, pid: Optional[str], payload) -> bool:
        if kind == "manual_done":
            self._refreshing = False
            self._update_button()
            return False
        st = self.states.get(pid)
        if kind in ("ok", "peek"):
            snap: Snapshot = payload
            self.snapshots[pid] = snap
            if kind == "ok":
                self.notes[pid] = ""
                pcts = ", ".join(f"{m.key}={m.percent:.0f}" for m in snap.meters)
                config.log(f"{pid} ok via {snap.source}: {pcts}")
            save_snapshots(self.snapshots)
            if not snap.is_stale(config.STALE_AFTER_SEC):
                self._notifier.check(snap, self.prefs)
        elif kind == "rate":
            retry = payload if isinstance(payload, int) and payload > 0 else 300
            config.log(f"{pid} rate limited, retry_after={retry}")
            if st:
                st.block_until = time.monotonic() + retry
                st.next_due = st.block_until
                st.bucket.drain()
            self.notes[pid] = f"Rate limited — trying again in {max(1, retry // 60)} min"
        elif kind in ("login", "err"):
            config.log(f"{pid} {kind}: {payload}")
            self.notes[pid] = str(payload)
        self._update_button()
        return True

    # --------------------------------------------------------------- window
    def show_window(self):
        self.root.deiconify()
        self.root.attributes("-topmost", self.pinned)
        self.window_panel.set_pinned(self.pinned)
        self._apply_dark_titlebar()
        self.root.update_idletasks()
        # Position only (never a fixed size), so the window grows with more providers.
        if self.prefs.window_geometry:
            try:
                self.root.geometry(self.prefs.window_geometry)
            except tk.TclError:
                pass
        elif not self._window_shown_once:
            w = self.root.winfo_reqwidth() or 352
            h = self.root.winfo_reqheight() or 480
            x = max(0, (self.root.winfo_screenwidth() - w) // 2)
            y = max(0, (self.root.winfo_screenheight() - h) // 3)
            self.root.geometry(f"+{x}+{y}")
        self._window_shown_once = True
        self.root.lift()
        self.root.focus_force()
        self._refresh_if_old()

    def hide_window(self):
        try:
            self.prefs.window_geometry = "+" + "+".join(self.root.geometry().split("+")[1:])
            self.prefs.save()
        except (tk.TclError, IndexError):
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
        while not self._stop.is_set():
            try:
                conn, _ = self._lock_sock.accept()
            except OSError:
                break
            try:
                if b"SHOW" in conn.recv(64):
                    self._commands.put(("show_window", None))
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _set_dock_icon_macos(self):
        try:
            import io

            from AppKit import NSApplication, NSImage
            from Foundation import NSData
            from PIL import Image
            im = Image.open(config.asset_path("icon.ico")).convert("RGBA").resize((512, 512))
            buf = io.BytesIO()
            im.save(buf, "PNG")
            data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
            NSApplication.sharedApplication().setApplicationIconImage_(NSImage.alloc().initWithData_(data))
        except Exception as e:
            config.log(f"dock icon skipped: {e}")

    # --------------------------------------------------------------- lifecycle
    def run(self):
        config.log(f"app start (frozen={getattr(sys, 'frozen', False)}, show_window={self._show_on_start}, "
                   f"providers={[p.id for p in self.providers]})")
        if sys.platform == "darwin":
            self._set_dock_icon_macos()
        self.tray.start()
        self._update_views()
        threading.Thread(target=self._worker, name="fetch", daemon=True).start()
        threading.Thread(target=self._listener, name="ipc", daemon=True).start()
        self.root.after(200, self._poll)
        self.root.after(1000, self._button_tick)
        if self._show_on_start:
            self.root.after(80, self.show_window)
        self.root.mainloop()

    def shutdown(self):
        self._stop.set()
        self._wake.set()
        singleinstance.release(self._lock_sock)
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass


# --- command line -------------------------------------------------------------------
def _probe() -> int:
    """Print what each provider reports right now (no GUI). Never prints secrets."""
    prefs = Prefs.load()
    code = 0
    for p in build_providers(prefs):
        try:
            s = p.fetch()
        except ProviderError as e:
            print(f"{p.title}: {type(e).__name__}: {e}")
            code = 1
            continue
        print(f"{p.title} · {s.plan or '?'} · {SOURCE_LABELS.get(s.source, s.source)}"
              + (f" · {s.note}" if s.note else ""))
        for m in s.meters:
            print(f"  {m.label:24} {m.percent:5.0f}%   {m.reset_text()}")
    return code


def main(argv: Optional[list[str]] = None):
    ap = argparse.ArgumentParser(prog="ai-usage-monitor", description=config.APP_NAME)
    ap.add_argument("--tray", action="store_true", help="start in the tray without opening the window")
    ap.add_argument("--probe", action="store_true", help="print current usage and exit (no GUI)")
    if config.IS_LINUX:
        ap.add_argument("--install", action="store_true", help="add the app to your desktop's app menu")
        ap.add_argument("--uninstall", action="store_true", help="remove the menu entry and login autostart")
    args = ap.parse_args(argv)

    if args.probe:
        sys.exit(_probe())
    if config.IS_LINUX and (args.install or args.uninstall):
        from . import linux_desktop
        if args.install:
            print(f"Installed launcher: {linux_desktop.install()}")
        else:
            removed = linux_desktop.uninstall()
            print("Removed: " + (", ".join(removed) if removed else "nothing to remove"))
        return

    sock = singleinstance.acquire()
    if sock is None:
        singleinstance.signal_show()          # already running: surface its window
        return
    App(sock, show_window_on_start=not args.tray).run()


if __name__ == "__main__":
    main()
