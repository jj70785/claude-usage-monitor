"""Provider-neutral usage model.

Every provider (Claude, and later Codex / Gemini) turns whatever it reads into a
`Snapshot`: a titled list of `Meter`s (one per plan limit). The UI, tray icons,
cache, and notifications only ever see this model, never a provider's raw JSON.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from . import config


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value) -> Optional[datetime]:
    """ISO-8601 string, epoch seconds, or epoch milliseconds -> aware UTC datetime."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            secs = value / 1000.0 if value > 1e12 else float(value)
            return datetime.fromtimestamp(secs, tz=timezone.utc)
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def age_text(when: Optional[datetime]) -> str:
    """'just now', '4 min ago', '3 hr ago', '2 days ago'."""
    if not when:
        return "never"
    secs = int((utcnow() - when).total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60} min ago"
    if secs < 86400:
        return f"{secs // 3600} hr ago"
    days = secs // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


@dataclass
class Meter:
    """One plan limit, e.g. the 5-hour session or the weekly all-models bucket."""
    key: str                          # stable id: "session", "weekly", "weekly:Fable", ...
    label: str                        # "5-hour session"
    percent: float                    # 0-100 (can exceed 100 if the server says so)
    resets_at: Optional[datetime] = None
    severity: str = ""                # server-provided "normal" | "warning" | "critical", or ""
    as_of: Optional[datetime] = None  # when this number was measured
    primary: bool = False             # shown first / drives notifications

    @property
    def expired(self) -> bool:
        """The window has reset since we measured it, so the number is known-wrong."""
        return bool(self.resets_at and self.resets_at <= utcnow())

    def is_stale(self, max_age_sec: int) -> bool:
        """Measured too long ago to present as current (or age unknown)."""
        if self.as_of is None:
            return True
        return (utcnow() - self.as_of).total_seconds() > max_age_sec

    def level(self) -> str:
        if self.severity in ("normal", "warning", "critical"):
            return self.severity
        if self.percent >= config.CRIT_THRESHOLD:
            return "critical"
        if self.percent >= config.WARN_THRESHOLD:
            return "warning"
        return "normal"

    def reset_in_text(self) -> str:
        if not self.resets_at:
            return ""
        secs = int((self.resets_at - utcnow()).total_seconds())
        if secs <= 0:
            return "reset — waiting for fresh data"
        days, rem = divmod(secs, 86400)
        hrs, rem = divmod(rem, 3600)
        mins = rem // 60
        if days:
            return f"resets in {days}d {hrs}h"
        if hrs:
            return f"resets in {hrs} hr {mins} min"
        return f"resets in {mins} min"

    def reset_at_text(self) -> str:
        """Local clock form, e.g. 'Wed 10:59 PM'."""
        if not self.resets_at:
            return ""
        return self.resets_at.astimezone().strftime("%a %I:%M %p").replace(" 0", " ")

    def reset_text(self) -> str:
        """Short windows read best as a countdown, long ones as a clock time."""
        if not self.resets_at or self.expired:
            return self.reset_in_text()
        if (self.resets_at - utcnow()).total_seconds() > 86400:
            return "resets " + self.reset_at_text()
        return self.reset_in_text()

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "percent": self.percent,
            "resets_at": self.resets_at.isoformat() if self.resets_at else None,
            "severity": self.severity,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "primary": self.primary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Meter":
        return cls(
            key=d["key"], label=d.get("label", d["key"]), percent=float(d.get("percent") or 0),
            resets_at=parse_dt(d.get("resets_at")), severity=d.get("severity") or "",
            as_of=parse_dt(d.get("as_of")), primary=bool(d.get("primary")),
        )


@dataclass
class Snapshot:
    """Everything one provider/account currently knows."""
    provider_id: str                  # "claude" (later "codex", "gemini", "claude:work", ...)
    title: str                        # "Claude"
    plan: str = ""                    # "Max 5x"
    meters: list[Meter] = field(default_factory=list)
    fetched_at: Optional[datetime] = None
    source: str = ""                  # "claude-cli" | "api" | "claude-snapshot" | "statusline" | "cache"
    note: str = ""                    # short human-readable status, e.g. "token expired"

    def live_meters(self) -> list[Meter]:
        return [m for m in self.meters if not m.expired]

    def worst(self) -> Optional[Meter]:
        """The meter closest to its limit (drives the tray icon color)."""
        live = self.live_meters()
        return max(live, key=lambda m: m.percent) if live else None

    def is_stale(self, max_age_sec: int) -> bool:
        """True when the number the tray icon shows is old.

        `fetched_at` is the newest data in the snapshot; one fresh row (say, the status
        line's session number) must not make an hours-old per-model row look current.
        """
        worst = self.worst()
        if worst is not None:
            return worst.is_stale(max_age_sec)
        if not self.fetched_at:
            return True
        return (utcnow() - self.fetched_at).total_seconds() > max_age_sec

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id, "title": self.title, "plan": self.plan,
            "meters": [m.to_dict() for m in self.meters],
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "source": self.source, "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Snapshot":
        return cls(
            provider_id=d["provider_id"], title=d.get("title", d["provider_id"]),
            plan=d.get("plan", ""), meters=[Meter.from_dict(m) for m in d.get("meters") or []],
            fetched_at=parse_dt(d.get("fetched_at")), source=d.get("source", ""),
            note=d.get("note", ""),
        )


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: max(0, n - 1)] + "…"


def tooltip(snap: Optional[Snapshot], title: str, note: str = "", max_len: Optional[int] = None,
            stale_after_sec: Optional[int] = None) -> str:
    """Multi-line hover text for a provider's tray icon.

    With `max_len` (Windows tray tooltips hold 128 characters), whole lines are kept in
    priority order instead of cutting mid-line: title, note, age, primary limits,
    then the rest.
    """
    stale_after = config.STALE_AFTER_SEC if stale_after_sec is None else stale_after_sec
    head = title if not (snap and snap.plan) else f"{title} · {snap.plan}"
    extra = note or (snap.note if snap else "")
    rows: list[tuple[bool, str, str]] = []          # (primary, full line, short line)
    age = ""
    if snap and snap.meters:
        for m in snap.meters:
            if m.expired:
                line = f"{m.label}: reset — refreshing"
                rows.append((m.primary, line, line))
                continue
            pct = f"{m.label}: {m.percent:.0f}%"
            rt = m.reset_text()
            old = f" (as of {age_text(m.as_of)})" if m.is_stale(stale_after) and m.as_of else ""
            rows.append((m.primary, pct + (f" · {rt}" if rt else "") + old, pct + old))
        age = f"updated {age_text(snap.fetched_at)}"
    else:
        age = "no data yet"

    if max_len is None:
        return "\n".join([head] + [r[1] for r in rows] + [age] + ([extra] if extra else []))

    fixed = [head] + ([_clip(extra, max_len // 2)] if extra else []) + [age]
    budget = max_len - len("\n".join(fixed))
    # Pass 1: short form of every primary limit. Pass 2: upgrade primaries to the full
    # form (with reset time). Pass 3: short form of the other limits while they fit.
    chosen: dict[int, str] = {}
    for i, (primary, _full, short) in enumerate(rows):
        if primary and len(short) + 1 <= budget:
            chosen[i] = short
            budget -= len(short) + 1
    for i, (primary, full, short) in enumerate(rows):
        if i in chosen and len(full) - len(short) <= budget:
            chosen[i] = full
            budget -= len(full) - len(short)
    for i, (primary, _full, short) in enumerate(rows):
        if not primary and len(short) + 1 <= budget:
            chosen[i] = short
            budget -= len(short) + 1
    lines = [head] + [chosen[i] for i in sorted(chosen)] + fixed[1:]
    return _clip("\n".join(lines), max_len)
