# 0006 — One tray icon per AI, colored by its most-used limit

- **Status:** Accepted (chosen by the project owner, 2026-09-28)
- **Date:** 2026-09-28

## Context

v1 showed two icons for Claude alone: signal bars for the 5-hour window and a ring for
weekly. With Codex, Gemini, and later several Claude accounts, that becomes 6+ icons.
Options considered: one icon per AI (chosen); one icon for everything; two icons per AI
(status quo).

## Decision

Each provider/account gets one icon, drawn by `icons.ring_image()`:

- **Arc** = the provider's most-used live limit (`Snapshot.worst()`), colored
  green → yellow → red.
- **Center number** = that percentage (`!!` at 100% or more; `–` with no data).
- **Track** carries a faint provider tint (Claude orange, Codex gray, Gemini blue), so
  icons side by side are tellable apart.
- **Grayed out** when the data is older than 20 minutes (`STALE_AFTER_SEC`).
- **Hover** shows every limit with its reset time; **click** opens the flyout with all
  bars for all providers.

## Consequences

- The panel stays small as providers are added.
- A limit that has already reset (its `resets_at` is in the past) is ignored for the
  color and number until fresh data arrives, so a stale "97%" can't haunt the icon.
- Per-model limits (e.g. "Weekly · Fable") count toward the icon too. That's the honest
  "closest to blocking you" number, but it could surprise someone who only cares about
  the all-models limit. Revisit if it does.
