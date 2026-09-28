"""Free, local sources that other tools already write. Never any network.

1. Claude Code's own usage snapshot: `cachedUsageUtilization` in .claude.json. Claude
   Code writes it (with a timestamp) whenever anything asks it for usage: /usage,
   the settings Usage tab, or our get_usage call.
2. The status-line drop file: the optional hook in the user's status line script saves
   the `rate_limits` Claude Code passes to it. See docs/statusline-hook.md.

Both are only as fresh as their timestamps. Callers compare `as_of` before using them.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

from ... import config
from ...model import Meter, parse_dt
from .account import ClaudeAccount
from .parse import SESSION_LABEL, WEEKLY_LABEL, meters_from_rate_limits

STATUSLINE_FILE = "claude-statusline.json"


class _MtimeCache:
    """Re-read a file only when its mtime changes (.claude.json can be ~100 KB)."""

    def __init__(self):
        self._mtime: dict[str, float] = {}
        self._value: dict[str, object] = {}

    def read_json(self, path: str):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        if self._mtime.get(path) == mtime:
            return self._value.get(path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return self._value.get(path)   # mid-write; keep the last good read
        self._mtime[path] = mtime
        self._value[path] = data
        return data


_cache = _MtimeCache()


def claude_snapshot(account: ClaudeAccount) -> tuple[Optional[datetime], list[Meter]]:
    """Claude Code's cached usage: (fetched_at, meters), or (None, [])."""
    data = _cache.read_json(account.state_path())
    if not isinstance(data, dict):
        return None, []
    snap = data.get("cachedUsageUtilization")
    if not isinstance(snap, dict):
        return None, []
    as_of = parse_dt(snap.get("fetchedAtMs"))
    return as_of, meters_from_rate_limits(snap.get("utilization") or {}, as_of)


def statusline_path() -> str:
    """Same path on every OS, so one status-line script works everywhere:
    $XDG_CACHE_HOME/ai-usage-monitor/claude-statusline.json (default ~/.cache/...)."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, config.LINUX_ID, STATUSLINE_FILE)


def statusline_meters(account: ClaudeAccount) -> tuple[Optional[datetime], list[Meter]]:
    """Session/weekly numbers saved by the status-line hook: (observed_at, meters).

    `observed_at` is when Claude Code last got a response in that session (the
    transcript's mtime), not when the status line was redrawn, because an idle
    session keeps redrawing old numbers.
    """
    data = _cache.read_json(statusline_path())
    if not isinstance(data, dict):
        return None, []
    if (data.get("config_dir") or None) != (account.config_dir or None):
        return None, []
    observed = parse_dt(data.get("observed_at"))
    rl = data.get("rate_limits") or {}
    meters = []
    for field, key, label in (("five_hour", "session", SESSION_LABEL), ("seven_day", "weekly", WEEKLY_LABEL)):
        w = rl.get(field)
        if not isinstance(w, dict) or w.get("used_percentage") is None:
            continue
        try:
            pct = float(w["used_percentage"])
        except (TypeError, ValueError):
            continue
        meters.append(Meter(key=key, label=label, percent=pct, resets_at=parse_dt(w.get("resets_at")),
                            as_of=observed, primary=True))
    return observed, meters
