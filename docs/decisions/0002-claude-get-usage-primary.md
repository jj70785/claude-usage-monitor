# 0002 — Claude Code's `get_usage` is the primary Claude source

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

We need Claude Pro/Max plan usage (5-hour session, weekly, per-model weekly limits)
reliably, without handling credentials ourselves (0001). The options, ranked in
[research/claude-usage-sources.md](../research/claude-usage-sources.md):

1. Claude Code's stream-json control request `get_usage`.
2. Claude Code's status-line `rate_limits` field.
3. Claude Code's saved snapshot, `cachedUsageUtilization` in `.claude.json`.
4. Calling `GET https://api.anthropic.com/api/oauth/usage` ourselves with Claude Code's token.
5. The claude.ai web API with a `sessionKey` cookie.

## Decision

Use `get_usage` first. The app spawns:

```
claude -p --input-format stream-json --output-format stream-json --verbose \
       --no-session-persistence --strict-mcp-config --setting-sources project
```

from an **empty scratch directory**, writes exactly one line:

```json
{"type":"control_request","request_id":"aum-…","request":{"subtype":"get_usage","skip_behaviors":true}}
```

reads stdout until the `control_response` with our `request_id`, then closes stdin so
Claude Code exits. Code: `providers/claude/cli_usage.py`.

Tested live on 2026-09-28 with Claude Code 2.1.284: the reply had the full `rate_limits`
object, `total_cost_usd: 0`, no model call, and in about 1.3 s end to end.

Fallback order when it fails: direct API with the token, read-only (can be turned off with
the pref `claude_api_fallback`), then the newest local snapshot (0008).

## Guardrails

- **No `initialize` request.** Its reply includes the account email; we never want PII.
- **Empty working directory + `--setting-sources project` + `--strict-mcp-config`:** no
  project hooks, no `.mcp.json` servers, no user MCP servers get started.
- **Not `--bare`.** It looks faster, but it disables OAuth, so usage becomes unavailable.
- **`ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` are removed** from the child's
  environment, so Claude Code reports plan usage instead of switching to API billing.
- **Only our `control_response` line is parsed**; stdout is never logged, and stderr only
  contributes a truncated first line to error messages.
- 45-second timeout, then kill.

## Consequences

- Claude Code owns login, token refresh, and the HTTP call. We never touch a credential.
- It also works after the access token has expired, because Claude Code refreshes it.
  (Expected from its code, **not yet observed** — see [bugs/known-issues.md](../bugs/known-issues.md).)
- Upstream marks it experimental (the Agent SDK names it
  `usage_EXPERIMENTAL_MAY_CHANGE_DO_NOT_RELY_ON_THIS_API_YET`). Every failure is treated as
  normal and falls through to the fallbacks; the parser tolerates missing and unknown
  fields.
- The reply has no freshness flag. When the server rate-limits Claude Code, it answers
  from its saved snapshot (up to about an hour old). We detect that by checking whether
  Claude Code rewrote `cachedUsageUtilization` during our call; if not, we label the data
  with the snapshot's age (0008).
- Each check starts a Claude Code process for about 1–2 s. At the default 5-minute
  interval that's negligible.
- Multi-account support later is just `CLAUDE_CONFIG_DIR=<dir>` in the child's
  environment (`ClaudeAccount.env()`).
