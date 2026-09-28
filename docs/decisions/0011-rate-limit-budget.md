# 0011 — Keep the client-side rate-limit budget; flyout opens don't spend it

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

The usage endpoint allows a short burst (about 5 requests) and then returns 429 with a
multi-minute `Retry-After`. Hammering it can make the lockout sticky (reports range from
5 minutes to about 24 hours). The lockout is per token, so it also blanks the user's own
`/usage` in Claude Code. `get_usage` goes through Claude Code to the same endpoint, so the
same budget applies. The evidence is messy (one README says burst of 5 and then 300 s;
public issues show `retry-after: 0` and sticky 429s), so we stay conservative.

## Decision

- Per-provider token bucket: burst 5, one token back every 65 s (v1's measured values).
- Auto refresh every 5 minutes by default (minimum 2); "Fast Update" every 90 s.
- A 429 blocks that provider for `Retry-After` (both delta-seconds and HTTP-date forms
  are now parsed; v1 only handled integers), defaulting to 300 s, and drains its bucket.
- **Opening the flyout or window no longer forces a fetch.** v1 spent a request on every
  peek; now it fetches only if the newest data is older than 90 s.
- Local sources (0008) are free and polled every 10 s.
- `tools/rate_test.py`, which deliberately triggers a 429, now refuses to run without
  `--i-understand`.

## Consequences

- Casual clicking can't burn the burst.
- While you're chatting, numbers still update continuously through local sources.
