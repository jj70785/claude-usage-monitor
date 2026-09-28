# 0001 — Never refresh (or write) Claude Code's OAuth tokens

- **Status:** Accepted
- **Date:** 2026-09-28
- **Supersedes:** the v1 behavior in `auth.py` (`_refresh_oauth`)

## Context

Claude Code keeps a short-lived access token (about 8 hours) and a refresh token in
`~/.claude/.credentials.json` (Linux/Windows) or the macOS Keychain. v1 of this app, when
it found the access token expired, redeemed Claude Code's refresh token itself and kept
the new tokens in its own keyring entry, never writing them back.

Claude subscription refresh tokens are **single-use and rotate**. Redeeming one
invalidates the copy Claude Code holds. Claude Code's next refresh then fails with
`invalid_grant`, it blanks the stored tokens, and **every Claude Code session on that
config dir is logged out** — including sessions running agents. Public reports:
anthropics/claude-code issues #54443 and #43392. One user who ran an external refresher
that *did* write the new tokens back still hit the logout cascade, because running
sessions hold the old refresh token in memory. Details:
[research/claude-oauth-tokens.md](../research/claude-oauth-tokens.md).

v1 also posted to the old `console.anthropic.com` token URL; current Claude Code uses
`platform.claude.com`. Whether the old URL still rotated tokens was contradictory in the
research, which is exactly why "maybe it's harmless" wasn't good enough.

## Decision

The app treats Claude credentials as **read-only**:

- It never calls the OAuth token endpoint, and there is no code path that could.
- It never writes Claude Code's credential file or Keychain entry.
- It reads the access token only for the optional direct-API fallback (0002, 0003), and
  only while the token is still fresh.
- Keeping the token fresh is Claude Code's job. Our primary source (0002) asks Claude Code
  itself, which refreshes under its own lock when needed.

## Consequences

- No more surprise logouts caused by the monitor.
- When Claude Code hasn't run for about 8 hours, the direct-API fallback goes quiet. The
  primary source still works, because it launches Claude Code, and Claude Code refreshes.
- The UI distinguishes login states (`account.py`): **fresh**, **stale** (token expired,
  Claude Code will refresh it), **logged out** (Claude Code blanked the tokens: run
  `/login`), **missing** (never logged in), and **login expiring** (refresh token ends
  within 3 days).
- Tests assert the stale-token path makes no HTTP request at all
  (`tests/test_claude.py::ProviderTests::test_falls_back_to_api_then_never_refreshes`).
