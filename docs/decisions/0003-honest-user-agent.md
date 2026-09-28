# 0003 — Identify as ourselves; never borrow another client's User-Agent

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

v1 sent `User-Agent: claude-code/<version>` to the usage API, believing the endpoint
required it. That also got the version wrong: it looked for keys that don't exist in
`.last-update-result.json`, so it always sent the stale default `2.1.178`. Real Claude
Code sends `claude-cli/<version> (external, cli)` to `api.anthropic.com`; `claude-code/…`
is what it uses for MCP transports. Anthropic's published policy targets third-party tools
that pose as its own apps. See [research/terms-and-policy.md](../research/terms-and-policy.md).

## Decision

The direct-API fallback sends:

```
User-Agent: ai-usage-monitor/<version> (+https://github.com/jj70785/claude-usage-monitor)
```

Tested 2026-09-28: `GET /api/oauth/usage` with this User-Agent returned **HTTP 200** with
the full payload.

## Consequences

- The app is honest about what it is, which lowers account risk.
- If Anthropic ever rejects unknown User-Agents, the fallback fails cleanly and the app
  keeps using `get_usage` (0002) and local snapshots (0008). We will **not** "fix" that by
  impersonating Claude Code.
- A unit test pins this (`ApiTests.test_honest_user_agent`).
