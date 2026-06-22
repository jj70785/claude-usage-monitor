"""Paths, defaults, persisted preferences, and the Windows 'run on login' helper.

Kept OS-aware so the macOS/Linux port only has to touch a couple of functions here
and in auth.py.
"""
from __future__ import annotations

import colorsys
import json
import os
import sys
from dataclasses import asdict, dataclass

APP_NAME = "Claude Usage Monitor"
APP_ID = "ClaudeUsageMonitor"  # used for config dir, keyring service, registry run key
KEYRING_SERVICE = APP_ID

# --- network / refresh tuning -------------------------------------------------
# The endpoint rate-limits hard if polled faster than ~120-180s, so keep auto
# generous and put a hard floor under the manual Refresh button.
DEFAULT_AUTO_REFRESH_SEC = 300      # 5 min
MIN_AUTO_REFRESH_SEC = 65
LIVE_REFRESH_SEC = 70               # "Live" mode interval (max safe sustained rate)
HTTP_TIMEOUT_SEC = 20

# --- manual-refresh budget ----------------------------------------------------
# The endpoint hard-limits to a short burst (~5) then 429s with retry-after 300,
# and retry-looping can flag the token into a persistent 429. So we mirror the
# server with a client token bucket: a burst, then ~1 per refill period.
RL_CAPACITY = 5                     # quick refreshes allowed in a burst
RL_REFILL_SEC = 65                  # one token back roughly every this many seconds

# --- thresholds (used for desktop notifications) ------------------------------
WARN_THRESHOLD = 80
CRIT_THRESHOLD = 95


def color_for_percent(pct) -> str:
    """Smooth green -> yellow -> red as usage climbs. Returns a #rrggbb hex."""
    try:
        p = max(0.0, min(100.0, float(pct)))
    except (TypeError, ValueError):
        p = 0.0
    hue = (120.0 - (p / 100.0) * 120.0) / 360.0   # 120deg green -> 0deg red
    r, g, b = colorsys.hsv_to_rgb(hue, 0.80, 0.92)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def config_dir() -> str:
    """Per-user writable config dir."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = os.path.join(base, APP_ID)
    os.makedirs(d, exist_ok=True)
    return d


def credentials_path() -> str:
    """Where Claude Code stores its OAuth token (Windows/Linux file path).

    macOS keeps it in the Keychain ('Claude Code-credentials'); auth.py handles
    that branch separately.
    """
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    base = override if override else os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, ".credentials.json")


def prefs_path() -> str:
    return os.path.join(config_dir(), "prefs.json")


def asset_path(name: str) -> str:
    """Resolve a bundled asset (e.g. icon.ico) in both frozen and source runs."""
    if getattr(sys, "frozen", False):
        base = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "assets")
    else:
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    return os.path.join(base, name)


def log_path() -> str:
    return os.path.join(config_dir(), "monitor.log")


def log(msg: str) -> None:
    """Append a timestamped line to the log file (best-effort). Useful for
    diagnosing the packaged exe, which has no console."""
    try:
        from datetime import datetime
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}  {msg}\n")
    except Exception:
        pass


def cache_path() -> str:
    return os.path.join(config_dir(), "last_usage.json")


@dataclass
class Prefs:
    auto_refresh_sec: int = DEFAULT_AUTO_REFRESH_SEC
    warn_threshold: int = WARN_THRESHOLD
    notify_on_warn: bool = False
    start_on_login: bool = False
    window_pinned: bool = True       # pop-out window always-on-top by default
    window_geometry: str = ""        # remembered "+X+Y" position of the pop-out window

    @classmethod
    def load(cls) -> "Prefs":
        try:
            with open(prefs_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            p = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except Exception:
            p = cls()
        p.auto_refresh_sec = max(MIN_AUTO_REFRESH_SEC, int(p.auto_refresh_sec))
        return p

    def save(self) -> None:
        try:
            with open(prefs_path(), "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2)
        except Exception:
            pass


# --- run on Windows login -----------------------------------------------------
def _run_command() -> str:
    """The command Windows should run at login. Uses the frozen exe when packaged,
    else pythonw -m claude_usage_monitor for dev."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    pyw = sys.executable
    if pyw.lower().endswith("python.exe"):
        cand = pyw[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(cand):
            pyw = cand
    return f'"{pyw}" -m claude_usage_monitor --tray'


def set_run_on_login(enabled: bool) -> bool:
    """Add/remove an HKCU Run entry. Returns True on success. No-op off Windows."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            if enabled:
                winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, _run_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_ID)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def is_run_on_login() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
        try:
            winreg.QueryValueEx(key, APP_ID)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False
