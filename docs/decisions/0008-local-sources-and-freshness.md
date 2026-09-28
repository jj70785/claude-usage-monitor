# 0008 — Local snapshots as free backups, trusted only by timestamp

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

Some local files already contain plan usage, and reading them costs nothing:

| File | Written by | Contents | Freshness signal |
|------|-----------|----------|------------------|
| `~/.claude.json` → `cachedUsageUtilization` | Claude Code, whenever anything asks it for usage (`/usage`, settings, our `get_usage`) | full `rate_limits` | `fetchedAtMs` |
| `~/.cache/ai-usage-monitor/claude-statusline.json` | our optional status-line hook ([statusline-hook.md](../statusline-hook.md)) | 5-hour + weekly only | transcript mtime |
| `~/.config/Claude/plan-usage-history.json` | the Claude Desktop app | 5-hour + weekly %, no reset times | sample time |

The project owner pointed out the status line's big weakness: it only updates when you
send a message. A Claude Code window left open for 3 days keeps redrawing 3-day-old
numbers.

## Decision

- Read `cachedUsageUtilization` and the status-line drop file in `peek()`, re-reading a
  file only when its mtime changes.
- **Newest wins, per limit.** A local value replaces what's shown only if its timestamp
  is newer than that limit's `as_of`. A status-line row is never *added* to a snapshot
  that is newer than the status-line observation.
- **Age is tracked per limit.** One fresh row (say, the status line's session number)
  can't make an hours-old per-model row look current: stale rows get "as of …" in amber,
  the icon grays when the number it shows is old, and alerts never fire on old numbers.
- The status-line hook records **when Claude Code last got a real model response**: the
  timestamp of the last non-synthetic, non-error assistant entry in the transcript. It
  doesn't use the redraw time or the transcript's mtime, which `/model`, `/clear`, or a
  submitted prompt also bump. With no response yet in the session, it writes nothing, and
  it refuses to overwrite a newer observation from another session.
- **Future timestamps are rejected** (anything more than 10 s ahead of now: clock steps,
  dual-boot RTC skew), because they would win every "newest" comparison and never go stale.
- Malformed drop files are ignored, and the optional overlay can never sink a good fetch.
- Limits whose `resets_at` has passed are shown as "reset — waiting for fresh data" and
  ignored for the icon.
- Data older than 20 minutes is shown as "as of …" in amber, and the icon is grayed.
- **Claude Desktop's history file is not used.** On the dev machine it was last written
  weeks earlier and has no reset times, so it adds risk without adding coverage.
- The status line is **not** modified to display usage (the owner's call): its numbers
  can be days old, and the tray already shows live ones.

## Consequences

- While you're chatting, the tray moves with every response, at zero cost.
- A long-idle Claude Code window can never make the tray show old numbers as current.
- Status-line data is scoped to its `CLAUDE_CONFIG_DIR`, so a second account's session
  can't overwrite the first account's numbers.
