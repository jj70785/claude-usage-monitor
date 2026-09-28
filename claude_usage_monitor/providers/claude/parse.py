"""Claude usage JSON -> Meters.

The same `rate_limits` shape comes back from three places: Claude Code's get_usage
reply, the /api/oauth/usage endpoint, and Claude Code's cachedUsageUtilization
snapshot. The server's `limits[]` rows are the current format; the older top-level
keys (five_hour, seven_day, seven_day_<model>) are the fallback.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ...model import Meter, parse_dt

SESSION_LABEL = "5-hour session"
WEEKLY_LABEL = "Weekly · all models"


def _scope_name(scope) -> str:
    if not isinstance(scope, dict):
        return ""
    for k in ("model", "surface"):
        v = scope.get(k)
        if isinstance(v, dict) and v.get("display_name"):
            return str(v["display_name"])
    return ""


def _from_limits(rows: list, as_of: Optional[datetime]) -> list[Meter]:
    meters: list[Meter] = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("percent") is None:
            continue
        kind = str(row.get("kind") or "")
        if kind == "session":
            key, label, primary = "session", SESSION_LABEL, True
        elif kind == "weekly_all":
            key, label, primary = "weekly", WEEKLY_LABEL, True
        elif kind == "weekly_scoped":
            name = _scope_name(row.get("scope")) or "scoped"
            key, label, primary = f"weekly:{name}", f"Weekly · {name}", False
        else:
            name = _scope_name(row.get("scope"))
            key = f"{kind}:{name}" if name else kind
            label = kind.replace("_", " ").capitalize() + (f" · {name}" if name else "")
            primary = False
        if key in seen:
            continue
        seen.add(key)
        try:
            pct = float(row["percent"])
        except (TypeError, ValueError):
            continue
        meters.append(Meter(key=key, label=label, percent=pct, resets_at=parse_dt(row.get("resets_at")),
                            severity=str(row.get("severity") or ""), as_of=as_of, primary=primary))
    return meters


_LEGACY = [
    ("five_hour", "session", SESSION_LABEL, True),
    ("seven_day", "weekly", WEEKLY_LABEL, True),
    ("seven_day_opus", "weekly:Opus", "Weekly · Opus", False),
    ("seven_day_sonnet", "weekly:Sonnet", "Weekly · Sonnet", False),
]


def _from_legacy(data: dict, as_of: Optional[datetime]) -> list[Meter]:
    meters = []
    for field, key, label, primary in _LEGACY:
        obj = data.get(field)
        if not isinstance(obj, dict) or obj.get("utilization") is None:
            continue
        try:
            pct = float(obj["utilization"])
        except (TypeError, ValueError):
            continue
        meters.append(Meter(key=key, label=label, percent=pct, resets_at=parse_dt(obj.get("resets_at")),
                            as_of=as_of, primary=primary))
    return meters


def _extra_usage(data: dict, as_of: Optional[datetime]) -> Optional[Meter]:
    """Paid 'usage credits' beyond the plan, only when the user has them switched on."""
    ex = data.get("extra_usage")
    if not isinstance(ex, dict) or not ex.get("is_enabled") or ex.get("utilization") is None:
        return None
    try:
        pct = float(ex["utilization"])
    except (TypeError, ValueError):
        return None
    return Meter(key="extra", label="Extra usage (monthly)", percent=pct, as_of=as_of)


def meters_from_rate_limits(data: dict, as_of: Optional[datetime]) -> list[Meter]:
    """Primary meters first (session, weekly), then per-model/other limits."""
    if not isinstance(data, dict):
        return []
    meters = _from_limits(data.get("limits") or [], as_of)
    have = {m.key for m in meters}
    for m in _from_legacy(data, as_of):
        if m.key not in have:
            meters.append(m)
            have.add(m.key)
    extra = _extra_usage(data, as_of)
    if extra:
        meters.append(extra)
    order = {"session": 0, "weekly": 1}
    meters.sort(key=lambda m: order.get(m.key, 2))
    return meters
