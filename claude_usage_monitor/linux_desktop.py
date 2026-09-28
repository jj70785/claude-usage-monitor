"""Linux desktop integration: app-menu launcher, login autostart entry, icon file.

`python3 -m claude_usage_monitor --install` adds "AI Usage Monitor" to the XFCE (or any
freedesktop) app menu, the Linux equivalent of the Windows Start-menu shortcut.
"""
from __future__ import annotations

import os

from . import config


def icon_png_path() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "icons", "hicolor", "256x256", "apps", f"{config.LINUX_ID}.png")


def ensure_icon_png() -> str:
    """Export the bundled .ico as a PNG the desktop can use. Returns its path."""
    path = icon_png_path()
    if not os.path.exists(path):
        try:
            from PIL import Image
            os.makedirs(os.path.dirname(path), exist_ok=True)
            Image.open(config.asset_path("icon.ico")).convert("RGBA").resize((256, 256)).save(path)
        except Exception as e:
            config.log(f"icon export skipped: {e}")
    return path


def desktop_entry(exec_cmd: str, autostart: bool) -> str:
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={config.APP_NAME}",
        "Comment=Claude, Codex and Gemini plan usage in your tray",
        f"Exec={exec_cmd}",
        f"Icon={ensure_icon_png()}",
        "Terminal=false",
        "Categories=Utility;Monitor;",
        f"StartupWMClass={config.APP_NAME}",
    ]
    if autostart:
        lines += ["X-GNOME-Autostart-enabled=true", "X-XFCE-Autostart-Override=true"]
    return "\n".join(lines) + "\n"


def _launcher_path() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "applications", f"{config.LINUX_ID}.desktop")


def install() -> str:
    path = _launcher_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(desktop_entry(config.launch_command(tray_only=False), autostart=False))
    return path


def uninstall() -> list[str]:
    removed = []
    for p in (_launcher_path(), icon_png_path()):
        if os.path.exists(p):
            os.remove(p)
            removed.append(p)
    if config.is_run_on_login():
        config.set_run_on_login(False)
        removed.append("login autostart entry")
    return removed
