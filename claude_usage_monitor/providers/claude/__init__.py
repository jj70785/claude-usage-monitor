"""Claude (Pro/Max) plan usage.

Source order (docs/decisions/0002-claude-get-usage-primary.md):
  1. Claude Code's `get_usage` control request (live, $0, Claude Code owns the login)
  2. Direct usage API with Claude Code's token, read-only (opt-out via prefs)
  3. Local snapshots, newest wins: Claude Code's cachedUsageUtilization, then the
     status-line drop file (session + weekly only)

`peek()` re-checks the local snapshots every few seconds so the numbers also move
while you chat in Claude Code, at zero cost.
"""
from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import Optional

from ... import config
from ...config import LIVE_REFRESH_SEC, Prefs
from ...model import Meter, Snapshot, utcnow
from ..base import NotLoggedIn, Provider, ProviderError, RateLimited
from . import api, cli_usage, local
from .account import ClaudeAccount, plan_label, read_login
from .parse import meters_from_rate_limits

# A get_usage reply is "live" if Claude Code's own snapshot was written this recently.
_FRESH_WRITE_SLACK = timedelta(seconds=90)
# How long to wait after a reply for Claude Code to write its refreshed snapshot.
SNAPSHOT_WAIT_SEC = 4.0

SOURCE_LABELS = {
    "claude-cli": "via Claude Code",
    "api": "via usage API",
    "claude-snapshot": "Claude Code's last check",
    "statusline": "from status line",
    "cache": "cached",
}


def _copy(snap: Snapshot) -> Snapshot:
    return dataclasses.replace(snap, meters=[dataclasses.replace(m) for m in snap.meters])


class ClaudeProvider(Provider):
    min_interval_sec = LIVE_REFRESH_SEC   # floor; the user's auto interval is >= 120 s anyway

    def __init__(self, prefs: Prefs, account: Optional[ClaudeAccount] = None,
                 provider_id: str = "claude", title: str = "Claude"):
        self.prefs = prefs
        self.account = account or ClaudeAccount()
        self.id = provider_id
        self.title = title
        self.latest: Optional[Snapshot] = None
        self._plan = ""
        self._hint = ""

    def seed(self, snap: Optional[Snapshot]) -> None:
        """Start from the on-disk cache so peek() knows what is already shown."""
        if snap and snap.provider_id == self.id:
            self.latest = snap
            self._plan = snap.plan

    # ------------------------------------------------------------------ fetch
    def fetch(self) -> Snapshot:
        login = read_login(self.account)
        self._plan = login.plan or self._plan
        self._hint = login.hint()
        errors: list[str] = []
        meters, source, as_of, note = [], "", None, ""

        claude = cli_usage.find_claude(self.prefs.claude_cli_path)
        if claude:
            started = utcnow()
            try:
                payload = cli_usage.get_usage(self.account, claude)
                if not login.plan:
                    self._plan = plan_label(payload.get("subscription_type") or "", "") or self._plan
                # Which data is live? Claude Code shares a snapshot < 60 s old as-is; with an
                # older one it answers from that saved copy at once and writes a live
                # snapshot about a second later (observed 2026-09-28). So: use the reply if
                # the snapshot was just written, else wait briefly for the refreshed one.
                snap_at, disk_meters = local.claude_snapshot(self.account)
                if snap_at and snap_at >= started - _FRESH_WRITE_SLACK:
                    as_of = snap_at                                     # case 1: reply is live
                    meters = meters_from_rate_limits(payload["rate_limits"], as_of)
                else:
                    fresh_at, fresh = local.wait_for_fresh_snapshot(self.account, snap_at, SNAPSHOT_WAIT_SEC)
                    if fresh_at:
                        as_of, meters = fresh_at, fresh                 # case 2: refreshed snapshot
                    elif snap_at:
                        # case 3: no refresh arrived (e.g. the server rate-limited Claude Code).
                        # Only as new as the saved copy, whose per-model rows the reply may drop.
                        as_of = snap_at
                        meters = disk_meters or meters_from_rate_limits(payload["rate_limits"], as_of)
                        note = "Claude Code couldn't reach the usage server — showing its last check"
                    else:
                        as_of = utcnow()                                # case 4: no snapshot at all
                        meters = meters_from_rate_limits(payload["rate_limits"], as_of)
                if meters:
                    source = "claude-cli"
                else:
                    errors.append("Claude Code returned usage in a format this version doesn't understand")
            except RateLimited:
                raise
            except ProviderError as e:
                errors.append(str(e))
        else:
            errors.append("claude command not found")

        if not meters and self.prefs.claude_api_fallback:
            try:
                data = api.fetch(login)
                as_of = utcnow()
                meters = meters_from_rate_limits(data, as_of)
                if meters:
                    source, note = "api", ""
                else:
                    errors.append("usage API returned a format this version doesn't understand")
            except RateLimited:
                raise
            except ProviderError as e:
                errors.append(str(e))

        if not meters:
            fallback = self._best_local(self.latest)
            if fallback is not None:
                fallback.note = self._hint or (errors[0] if errors else "")
                self.latest = fallback
                return fallback
            if login.state in ("missing", "logged_out"):
                raise NotLoggedIn(login.hint())
            raise ProviderError(errors[0] if errors else "no usage data")

        snap = Snapshot(self.id, self.title, plan=self._plan, meters=meters,
                        fetched_at=as_of, source=source, note=note or self._hint)
        try:
            snap = self._overlay_statusline(snap) or snap
        except Exception as e:                       # an optional overlay must never sink a good fetch
            config.log(f"statusline overlay skipped: {type(e).__name__}: {e}")
        self.latest = snap
        return snap

    # ------------------------------------------------------------------- peek
    def peek(self) -> Optional[Snapshot]:
        newer = self._best_local(self.latest)
        if newer is None:
            return None
        self.latest = newer
        return newer

    def _best_local(self, base: Optional[Snapshot]) -> Optional[Snapshot]:
        """A snapshot newer than `base` built from local files, or None if nothing changed."""
        changed = False
        snap_at, meters = local.claude_snapshot(self.account)
        base_at = base.fetched_at if base else None
        if snap_at and meters and (base_at is None or snap_at > base_at + timedelta(seconds=1)):
            base = Snapshot(self.id, self.title, plan=self._plan or (base.plan if base else ""),
                            meters=meters, fetched_at=snap_at, source="claude-snapshot",
                            note=self._hint)
            changed = True
        overlaid = self._overlay_statusline(base)
        if overlaid is not None:
            return overlaid
        return base if changed else None

    def _overlay_statusline(self, base: Optional[Snapshot]) -> Optional[Snapshot]:
        """Session/weekly from the status line, if they were observed after `base`'s."""
        observed, sl = local.statusline_meters(self.account)
        if not observed or not sl:
            return None
        if base is None:
            return Snapshot(self.id, self.title, plan=self._plan, meters=sl, fetched_at=observed,
                            source="statusline", note=self._hint)
        out = _copy(base)
        by_key = {m.key: i for i, m in enumerate(out.meters)}
        base_newer = out.fetched_at is not None and observed <= out.fetched_at + timedelta(seconds=1)
        changed = False
        for m in sl:
            if m.expired:
                continue
            i = by_key.get(m.key)
            if i is None:
                if base_newer:
                    continue                         # newer data without this row: don't resurrect it
                out.meters.insert(0 if m.key == "session" else min(1, len(out.meters)), m)
                by_key = {mm.key: j for j, mm in enumerate(out.meters)}
                changed = True
                continue
            cur: Meter = out.meters[i]
            if cur.as_of is None or observed > cur.as_of + timedelta(seconds=1):
                out.meters[i] = dataclasses.replace(cur, percent=m.percent,
                                                    resets_at=m.resets_at or cur.resets_at,
                                                    as_of=observed, severity="")
                changed = True
        if not changed:
            return None
        if out.fetched_at is None or observed > out.fetched_at:
            out.fetched_at = observed
            out.source = "statusline"
        return out
