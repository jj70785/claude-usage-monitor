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


def exec_line(argv: list[str]) -> str:
    """Build a Desktop Entry `Exec=` value. Each argument is quoted per the spec (escape
    " ` $ \\ inside double quotes; double any % so it isn't read as a field code), then
    the whole value gets key-file escaping (backslashes doubled; newline/tab/CR escaped).
    A path like ~/apps/100%done/ or one with quotes would otherwise launch nothing."""
    def arg(a: str) -> str:
        a = "".join("\\" + c if c in '"`$\\' else c for c in a).replace("%", "%%")
        return '"' + a + '"'
    value = " ".join(arg(a) for a in argv)
    return (value.replace("\\", "\\\\").replace("\n", "\\n")
            .replace("\t", "\\t").replace("\r", "\\r"))


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
        f.write(desktop_entry(exec_line(config.launch_argv()), autostart=False))
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
