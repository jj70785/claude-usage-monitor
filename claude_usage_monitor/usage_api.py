"""The only module that knows the (unofficial) usage endpoint + response shape.

Isolated on purpose: if Anthropic changes the API, this is the one file to touch.
Everything above it consumes the clean `Usage` dataclass.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from . import config
from .auth import Auth

OAUTH_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_AI_BASE = "https://claude.ai/api"


class UsageError(Exception):
    pass


class AuthExpired(UsageError):
    """401/403 — credential no longer valid."""


class RateLimited(UsageError):
    """429 — backoff and try later."""
    def __init__(self, retry_after: Optional[int] = None):
        super().__init__("rate limited")
        self.retry_after = retry_after


@dataclass
class Window:
    """One usage limit (a 5-hour session, a weekly bucket, etc.)."""
    percent: float
    resets_at: Optional[datetime] = None
    severity: str = "normal"          # normal | warning | critical
    is_active: bool = False

    def reset_in_text(self) -> str:
        if not self.resets_at:
            return ""
        delta = self.resets_at - datetime.now(timezone.utc)
        secs = int(delta.total_seconds())
        if secs <= 0:
            return "resets now"
        days, rem = divmod(secs, 86400)
        hrs, rem = divmod(rem, 3600)
        mins = rem // 60
        if days:
            return f"resets in {days}d {hrs}h"
        if hrs:
            return f"resets in {hrs} hr {mins} min"
        return f"resets in {mins} min"

    def reset_at_text(self) -> str:
        """Local clock form, e.g. 'Wed 10:59 PM' (used for the weekly line)."""
        if not self.resets_at:
            return ""
        local = self.resets_at.astimezone()
        return local.strftime("%a %I:%M %p").replace(" 0", " ")


@dataclass
class Usage:
    five_hour: Optional[Window] = None
    weekly: Optional[Window] = None
    sonnet: Optional[Window] = None          # parsed but not shown in v1
    plan: str = ""                            # e.g. "Max", "Pro"
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: dict = field(default_factory=dict)


# --- parsing helpers ----------------------------------------------------------
def _parse_dt(s) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _severity_for(percent: float, sev: Optional[str]) -> str:
    if sev in ("normal", "warning", "critical"):
        return sev
    if percent >= config.CRIT_THRESHOLD:
        return "critical"
    if percent >= config.WARN_THRESHOLD:
        return "warning"
    return "normal"


def _window_from_limit(item: dict) -> Window:
    pct = float(item.get("percent") or 0)
    return Window(
        percent=pct,
        resets_at=_parse_dt(item.get("resets_at")),
        severity=_severity_for(pct, item.get("severity")),
        is_active=bool(item.get("is_active")),
    )


def _window_from_legacy(obj) -> Optional[Window]:
    if not isinstance(obj, dict):
        return None
    pct = obj.get("utilization")
    if pct is None:
        return None
    pct = float(pct)
    return Window(
        percent=pct,
        resets_at=_parse_dt(obj.get("resets_at")),
        severity=_severity_for(pct, None),
    )


def parse(data: dict, plan: str = "") -> Usage:
    """Map the raw JSON to a clean Usage. Prefer the normalized `limits` array,
    fall back to the legacy top-level keys (five_hour / seven_day / ...)."""
    u = Usage(plan=_plan_label(plan or _plan_from_raw(data)), raw=data)

    # Preferred: the `limits` array.
    for item in data.get("limits") or []:
        kind = item.get("kind")
        if kind == "session" and u.five_hour is None:
            u.five_hour = _window_from_limit(item)
        elif kind == "weekly_all" and u.weekly is None:
            u.weekly = _window_from_limit(item)
        elif kind == "weekly_scoped":
            scope = (item.get("scope") or {}).get("model") or {}
            if str(scope.get("display_name", "")).lower() == "sonnet" and u.sonnet is None:
                u.sonnet = _window_from_limit(item)

    # Fallback / fill gaps from legacy keys.
    if u.five_hour is None:
        u.five_hour = _window_from_legacy(data.get("five_hour"))
    if u.weekly is None:
        u.weekly = _window_from_legacy(data.get("seven_day"))
    if u.sonnet is None:
        u.sonnet = _window_from_legacy(data.get("seven_day_sonnet"))
    return u


def _plan_from_raw(data: dict) -> str:
    return data.get("subscriptionType") or ""


def _plan_label(sub: str) -> str:
    return {"max": "Max", "pro": "Pro", "team": "Team", "enterprise": "Enterprise"}.get(
        (sub or "").lower(), sub.title() if sub else ""
    )


# --- network ------------------------------------------------------------------
# Stdlib urllib uses the OS (Windows) certificate store via the default SSL
# context, so the packaged exe needs no bundled certifi CA file (which is what
# broke HTTPS in the frozen build before).
_SSL_CTX = ssl.create_default_context()


def _get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT_SEC, context=_SSL_CTX) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code in (401, 403):
            raise AuthExpired(f"HTTP {e.code}")
        if e.code == 429:
            ra = e.headers.get("retry-after")
            raise RateLimited(int(ra) if ra and str(ra).isdigit() else None)
        raise UsageError(f"HTTP {e.code}: {body[:200]}")
    except (urllib.error.URLError, OSError) as e:
        raise UsageError(f"network error: {e}") from e


def fetch(auth: Auth) -> Usage:
    """Fetch + parse current usage. Raises AuthExpired / RateLimited / UsageError."""
    if auth.kind == "oauth":
        return _fetch_oauth(auth)
    if auth.kind == "cookie":
        return _fetch_cookie(auth)
    raise UsageError(f"unknown auth kind {auth.kind!r}")


def _fetch_oauth(auth: Auth) -> Usage:
    data = _get_json(OAUTH_USAGE_URL, {
        "Authorization": f"Bearer {auth.token}",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": auth.user_agent,
        "Accept": "application/json",
    })
    return parse(data, plan=auth.subscription or "")


def _fetch_cookie(auth: Auth) -> Usage:
    headers = {
        "Cookie": f"sessionKey={auth.token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    org = auth.org_uuid
    plan = auth.subscription or ""
    if not org:
        acc = _get_json(f"{CLAUDE_AI_BASE}/account", headers)
        memberships = acc.get("memberships") or []
        if memberships:
            orgobj = memberships[0].get("organization") or {}
            org = orgobj.get("uuid")
            plan = plan or orgobj.get("rate_limit_tier") or ""
    if not org:
        raise UsageError("no organization uuid")
    data = _get_json(f"{CLAUDE_AI_BASE}/organizations/{org}/usage", headers)
    return parse(data, plan=plan)


# --- tiny disk cache so the popup has something to show on first paint --------
def save_cache(usage: Usage) -> None:
    try:
        def win(w: Optional[Window]):
            if not w:
                return None
            return {
                "percent": w.percent,
                "resets_at": w.resets_at.isoformat() if w.resets_at else None,
                "severity": w.severity,
                "is_active": w.is_active,
            }
        with open(config.cache_path(), "w", encoding="utf-8") as f:
            json.dump({
                "five_hour": win(usage.five_hour),
                "weekly": win(usage.weekly),
                "plan": usage.plan,
                "fetched_at": usage.fetched_at.isoformat(),
            }, f)
    except Exception:
        pass


def load_cache() -> Optional[Usage]:
    try:
        with open(config.cache_path(), "r", encoding="utf-8") as f:
            d = json.load(f)

        def win(o):
            if not o:
                return None
            return Window(
                percent=o["percent"],
                resets_at=_parse_dt(o.get("resets_at")),
                severity=o.get("severity", "normal"),
                is_active=o.get("is_active", False),
            )
        u = Usage(
            five_hour=win(d.get("five_hour")),
            weekly=win(d.get("weekly")),
            plan=d.get("plan", ""),
        )
        ft = _parse_dt(d.get("fetched_at"))
        if ft:
            u.fetched_at = ft
        return u
    except Exception:
        return None
