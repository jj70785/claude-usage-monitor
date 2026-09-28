# 0009 — Gemini usage only via the Antigravity CLI (`agy -p /usage`)

- **Status:** Accepted (not implemented yet; Phase 5 in the [roadmap](../plans/roadmap.md))
- **Date:** 2026-09-28

## Context

- Google closed the consumer "Login with Google" path for Gemini CLI on 2026-06-18;
  Gemini CLI now runs on API keys only. Consumer plans (Google AI Pro/Ultra) moved to
  Antigravity.
- Google's terms forbid third-party direct access to the backends behind Gemini CLI and
  Antigravity, and there are public reports of accounts banned for quota-tracking
  extensions.
- Antigravity's CLI (`agy`, 1.1.11 and later) has `agy -p /usage --output-format json`,
  which its changelog says prints quota "without starting an agent turn, spending quota,
  or leaving a conversation behind."

Details: [research/gemini-antigravity-usage.md](../research/gemini-antigravity-usage.md).

## Decision

The Gemini provider will only ever run `agy -p /usage --output-format json` (and possibly
`/credits`). It will never read Google OAuth tokens or call Google endpoints itself.

Invocation guardrails: stdin from `/dev/null`, a new session with no controlling TTY
(otherwise an unauthenticated run can open a browser and block), gate on
`agy --version` ≥ 1.1.11, poll no more than every 5–10 minutes with jitter, and never read
agy's log files (they contain the signed-in email).

## Consequences

- Same pattern as Claude: the vendor's own CLI owns the login.
- Bucket and window names come from the server and change without notice. The parser
  must classify them defensively and show unknown ones as-is.
