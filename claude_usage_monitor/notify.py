"""Desktop notifications, plus the "tell me once per threshold" bookkeeping."""
from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Callable, Optional

from . import config
from .model import Snapshot


def send(title: str, message: str, urgency: str = "normal") -> None:
    """Best-effort native notification. Never raises."""
    try:
        if config.IS_LINUX and shutil.which("notify-send"):
            from . import linux_desktop
            subprocess.Popen(["notify-send", "-a", config.APP_NAME, "-u", urgency,
                              "-i", linux_desktop.ensure_icon_png(), title, message],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "darwin":
            esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.Popen(["osascript", "-e", f'display notification "{esc(message)}" with title "{esc(title)}"'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        config.log(f"notify failed: {e}")


class ThresholdNotifier:
    """Fires once when a meter crosses the warn or critical threshold, and again only
    after that meter's window resets."""

    def __init__(self, sender: Optional[Callable[[str, str, str], None]] = None):
        self._fired: set[tuple] = set()
        self._send = sender or send

    def check(self, snap: Snapshot, prefs: config.Prefs) -> None:
        if not prefs.notify_on_warn:
            return
        for m in snap.live_meters():
            if not m.primary:
                continue
            window = m.resets_at.isoformat() if m.resets_at else ""
            for level, threshold in (("critical", prefs.crit_threshold), ("warning", prefs.warn_threshold)):
                if m.percent < threshold:
                    continue
                key = (snap.provider_id, m.key, threshold, window)
                if key not in self._fired:
                    self._fired.add(key)
                    reset = m.reset_text()
                    self._send(f"{snap.title}: {m.label} at {m.percent:.0f}%",
                               f"{reset[0].upper() + reset[1:]}" if reset else "",
                               "critical" if level == "critical" else "normal")
                break   # only the highest threshold crossed
