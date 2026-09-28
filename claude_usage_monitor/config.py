"""Paths, defaults, persisted preferences, logging, and 'start on login' per OS.

Linux follows the XDG spec (~/.config/ai-usage-monitor, ~/.cache/ai-usage-monitor).
Windows and macOS keep the original ClaudeUsageMonitor folders so existing installs
keep their settings.
"""
from __future__ import annotations

import colorsys
import json
import logging
import logging.handlers
import os
import sys
from dataclasses import asdict, dataclass

APP_NAME = "AI Usage Monitor"
APP_ID = "ClaudeUsageMonitor"         # Windows/macOS config dir + Windows registry Run value
LINUX_ID = "ai-usage-monitor"         # Linux XDG dirs, .desktop files, socket name

# --- refresh tuning -------------------------------------------------------------
# Anthropic's usage endpoint allows a short burst (~5) and then 429s for minutes, and
# retry-looping can make that lockout sticky. Claude Code's get_usage hits the same
# endpoint, so the same budget applies: a client token bucket mirrors the server.
DEFAULT_AUTO_REFRESH_SEC = 300        # 5 min
MIN_AUTO_REFRESH_SEC = 120
LIVE_REFRESH_SEC = 90                 # "Fast Update" interval
RL_CAPACITY = 5                       # quick refreshes allowed in a burst
RL_REFILL_SEC = 65                    # one token back roughly every this many seconds
PEEK_SEC = 10                         # how often to re-check local files (free)
STALE_AFTER_SEC = 20 * 60             # data older than this is flagged in the UI
HTTP_TIMEOUT_SEC = 20

# --- thresholds -----------------------------------------------------------------
WARN_THRESHOLD = 80
CRIT_THRESHOLD = 95

IS_LINUX = sys.platform.startswith("linux")


def color_for_percent(pct) -> str:
    """Smooth green -> yellow -> red as usage climbs. Returns a #rrggbb hex."""
    try:
        p = max(0.0, min(100.0, float(pct)))
    except (TypeError, ValueError):
        p = 0.0
    hue = (120.0 - (p / 100.0) * 120.0) / 360.0   # 120deg green -> 0deg red
    r, g, b = colorsys.hsv_to_rgb(hue, 0.80, 0.92)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def _ensure(d: str) -> str:
    os.makedirs(d, exist_ok=True)
    return d


def config_dir() -> str:
    """Per-user writable settings dir."""
    if sys.platform == "win32":
        return _ensure(os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_ID))
    if sys.platform == "darwin":
        return _ensure(os.path.join(os.path.expanduser("~/Library/Application Support"), APP_ID))
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return _ensure(os.path.join(base, LINUX_ID))


def cache_dir() -> str:
    """Per-user cache dir (last snapshots, status-line drop file, CLI scratch dir).

    The Claude status-line hook writes here too, so keep this path stable.
    """
    if IS_LINUX:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
        return _ensure(os.path.join(base, LINUX_ID))
    return config_dir()


def prefs_path() -> str:
    return os.path.join(config_dir(), "prefs.json")


def snapshots_path() -> str:
    return os.path.join(cache_dir(), "last_snapshots.json")


def asset_path(name: str) -> str:
    """Resolve a bundled asset (e.g. icon.ico) in both frozen and source runs."""
    if getattr(sys, "frozen", False):
        base = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "assets")
    else:
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    return os.path.join(base, name)


# --- logging --------------------------------------------------------------------
_logger: "logging.Logger | None" = None


def log_path() -> str:
    return os.path.join(config_dir(), "monitor.log")


def log(msg: str) -> None:
    """Timestamped line in a size-capped log (the packaged app has no console).

    Never log tokens, emails, or raw provider output.
    """
    global _logger
    try:
        if _logger is None:
            lg = logging.getLogger(LINUX_ID)
            lg.setLevel(logging.INFO)
            lg.propagate = False
            h = logging.handlers.RotatingFileHandler(log_path(), maxBytes=512 * 1024,
                                                     backupCount=2, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%dT%H:%M:%S"))
            lg.addHandler(h)
            _logger = lg
        _logger.info(msg)
    except Exception:
        pass


# --- preferences ----------------------------------------------------------------
@dataclass
class Prefs:
    auto_refresh_sec: int = DEFAULT_AUTO_REFRESH_SEC
    warn_threshold: int = WARN_THRESHOLD
    crit_threshold: int = CRIT_THRESHOLD
    notify_on_warn: bool = True
    start_on_login: bool = False
    window_pinned: bool = True        # pop-out window always-on-top by default
    window_geometry: str = ""         # remembered "+X+Y" position of the pop-out window
    claude_api_fallback: bool = True  # if Claude Code's get_usage fails, read its token (never refresh)
    claude_cli_path: str = ""         # override where the `claude` binary lives

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


# --- start on login ---------------------------------------------------------------
def _source_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def launch_command(tray_only: bool) -> str:
    """Command line that starts this app (packaged exe, or python + run.py from source)."""
    flag = " --tray" if tray_only else ""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"{flag}'
    py = sys.executable
    if sys.platform == "win32" and py.lower().endswith("python.exe"):
        cand = py[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(cand):
            py = cand
    return f'"{py}" "{os.path.join(_source_root(), "run.py")}"{flag}'


def _autostart_file() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", f"{LINUX_ID}.desktop")


def desktop_entry(tray_only: bool) -> str:
    from . import linux_desktop
    return linux_desktop.desktop_entry(launch_command(tray_only), autostart=tray_only)


def set_run_on_login(enabled: bool) -> bool:
    """Add/remove the login entry. Returns True on success."""
    if sys.platform == "win32":
        return _win_set_run(enabled)
    if IS_LINUX:
        path = _autostart_file()
        try:
            if enabled:
                _ensure(os.path.dirname(path))
                with open(path, "w", encoding="utf-8") as f:
                    f.write(desktop_entry(tray_only=True))
            elif os.path.exists(path):
                os.remove(path)
            return True
        except OSError:
            return False
    return False


def is_run_on_login() -> bool:
    if sys.platform == "win32":
        return _win_is_run()
    if IS_LINUX:
        path = _autostart_file()
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                return "Hidden=true" not in f.read()
        except OSError:
            return False
    return False


def _win_set_run(enabled: bool) -> bool:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        try:
            if enabled:
                winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, launch_command(tray_only=True))
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


def _win_is_run() -> bool:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, APP_ID)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False
