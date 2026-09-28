# Claude Code OAuth tokens: storage, lifetimes, and why this app never refreshes

**TLDR.** Claude Code stores its subscription login in `~/.claude/.credentials.json` on Linux and Windows (the Keychain on macOS), with an access token that lasts about 8 hours. The refresh token is **single-use and rotating**: when any other program redeems it, Claude Code's own copy dies, and every Claude Code session on that config directory is forced back to `/login`. So this app is strictly read-only: it never calls the token endpoint, never writes credential files, and instead shows distinct credential states such as fresh, token stale, login expiring, login expired and logged out.

- Status: research note, written 2026-09-28.
- Claude Code versions examined: 2.1.283 and 2.1.284, on Linux.
- Companion doc: [claude-usage-sources.md](claude-usage-sources.md), which covers how usage is actually read without touching tokens.

---

## Evidence labels

These match the companion doc:

| Label | Meaning |
|---|---|
| `[D2]`, `[G1]`, `[T1]`, ... | A public source; see [Sources](#sources) for the URL and the date it was read. |
| `[OBS]` | Observed locally on 2026-09-28: file structure and timestamps only, never secret values. |
| `[INFERRED]` | Inferred on 2026-09-28 (Claude Code 2.1.283) from observed behavior, changelog entries and public SDK typings. Not publicly documented and not directly verified. Probably right; re-check after Claude Code updates. |
| `[UNVERIFIED]` | Reported but not confirmed, or inference. |

No token values, account identifiers or email addresses appear in this doc. None were printed during the research.

---

## 1. Where the tokens live

### Per platform

| Platform | Location | Source |
|---|---|---|
| Linux | `~/.claude/.credentials.json`, file mode `0600`. There is no libsecret/keyring storage. | `[D2]`, `[OBS]` |
| Windows | `%USERPROFILE%\.claude\.credentials.json`, protected by the user profile's access controls | `[D2]` |
| macOS | Keychain, generic-password service `Claude Code-credentials`. Falls back to `~/.claude/.credentials.json` (0600) "When the Keychain rejects the write, such as when it's locked in an SSH session" | `[D2]`, `[T1]` |
| Any, with `CLAUDE_CONFIG_DIR=<dir>` | `<dir>/.credentials.json`. On macOS the Keychain entry is also keyed "to that directory too, so a session with a different `CLAUDE_CONFIG_DIR` reads a different entry" | `[D2]` |

### The macOS per-directory Keychain name

With `CLAUDE_CONFIG_DIR` set, users report Keychain items named `Claude Code-credentials-<8 hex characters>` `[G7]`. The suffix seems to be derived from a hash of the config directory path `[INFERRED]`. This was not verified on a Mac.

Public issues also report that these items pile up and are not reused: #83832, #84275, #90527 `[G7]`. Claude Code rewrites the item on refresh and resets its access-control grant, which re-triggers Keychain password prompts for other apps (#94491 `[G8]`, and `[T1]`). On Claude Code 2.1.x the item "may contain only MCP server OAuth state (`mcpOAuth`) with no `claudeAiOauth`" `[T1]`.

**Consequence:** on macOS this app should not read the Keychain at all. The `get_usage` route in the companion doc lets Claude Code read its own item.

### `CLAUDE_SECURESTORAGE_CONFIG_DIR`

This is undocumented. It does not appear on the env-vars page `[D3]`. It seems to move the credentials directory separately from the config directory, and to switch on the per-directory Keychain suffix `[INFERRED]`. A per-account monitor that ever resolves credential paths itself should honor it. That is one more reason to let the `claude` binary resolve paths instead.

### File structure

The file on Linux, with values redacted `[OBS]`:

```json
{
  "claudeAiOauth": {
    "accessToken":           "<redacted>",
    "refreshToken":          "<redacted>",
    "expiresAt":             1790000000000,
    "refreshTokenExpiresAt": 1790400000000,
    "scopes": ["user:file_upload", "user:inference", "user:mcp_servers",
               "user:plugins", "user:profile", "user:sessions:claude_code"],
    "subscriptionType": "max",
    "rateLimitTier":    "default_claude_max_5x"
  },
  "mcpOAuth": { "...": "OAuth state for each MCP server; never read this" }
}
```

- `expiresAt` and `refreshTokenExpiresAt` are **milliseconds** since the Unix epoch `[OBS]`.
- `user:profile` is the scope the usage endpoint requires `[T1]`.
- A `claude setup-token` token is not stored in this file. It "can only make model requests" `[D2]`, and its scope is inference-only `[INFERRED]`.

Related files Claude Code manages next to it `[INFERRED]`:

- `.storage-write` serializes credential writes.
- `.oauth_refresh.lock` serializes token refreshes across processes.
- Account metadata (`oauthAccount`: email, organization, account ID) and the usage snapshot live in `.claude.json`. By default that file is `~/.claude.json` in the home directory. With `CLAUDE_CONFIG_DIR` set, it is `<dir>/.claude.json`.

---

## 2. Lifetimes

### Access token: about 8 hours

On 2026-09-28, `expiresAt` was exactly 8.00 hours after the credentials file was last written `[OBS]`. Claude Code refreshes the access token proactively shortly before expiry, but only while a Claude Code process is running and needs it `[INFERRED]`. After 8 idle hours the stored access token is simply expired. That is normal and harmless: the next Claude Code process refreshes it.

### Refresh token (the login): observed about 5.5 days out

`refreshTokenExpiresAt` was about 133.7 hours (about 5.5 days) after the last write `[OBS]`. That is a single sample. **It is unverified** whether this deadline moves forward on each refresh or is fixed from the original `/login`.

Claude Code's documented behavior around login expiry `[D2]`:

- **Warning.** "When the login you created with `/login` is within three days of expiring, Claude Code shows a warning at startup: `Your login expires in 3 days · run /login to renew`". This needs v2.1.203 or later. Before v2.1.217 the warning came five days out.
- **Expiry.** "Once the stored login expires and can't be refreshed, each model request fails with `Login expired · Please run /login` until you sign in again."
- **Status check.** `/status` shows a `Login` row reading `Expired — log in again` (v2.1.210+).

Whether that three-day warning is computed from `refreshTokenExpiresAt` is likely but `[UNVERIFIED]`.

### `claude setup-token`

It mints a one-year token that is printed but not saved. You use it through `CLAUDE_CODE_OAUTH_TOKEN` `[D2]`. It is inference-only, so plan usage is unavailable for such sessions `[D9 in the companion doc][T1]`.

---

## 3. How a refresh works

This section is for understanding only. **This app never does this.**

Claude Code 2.1.283 refreshes by POSTing JSON to `https://platform.claude.com/v1/oauth/token` `[INFERRED]`. The body has:

- `grant_type: "refresh_token"`
- the current `refresh_token`
- Claude Code's public OAuth client ID
- a space-separated `scope`

The response carries a new `access_token`, a **new `refresh_token`**, `expires_in` and `refresh_token_expires_in` `[INFERRED]`.

A sanitized capture posted publicly in #54443 (comment of 2026-05-01) shows the same URL, method and `grant_type` `[G2]`.

**The old URL.** Many community tools, and this app's earlier releases, still post to `https://console.anthropic.com/v1/oauth/token`. Claude Code 2.1.283 no longer references that host `[INFERRED]`. It is **not a safe dead end**, though. A 2026-03-07 comment on #31637 suggested refreshing through `console.anthropic.com` after every 429, and a reply the same day reported that this broke Claude Code's own refreshing `[G3]`. So that host still rotated tokens in March 2026. Treat it as working and dangerous.

---

## 4. Refresh tokens are single-use and rotate

Anthropic has not documented this. The evidence comes from users, the changelog and observed behavior. It is consistent, though:

| Evidence | Date | What it shows |
|---|---|---|
| #43392 `[G1]` | 2026-04-04 | Parallel agents each refresh with the same stored token: "The first one to succeed invalidates the refresh token (OAuth refresh tokens are single-use)". The rest get `invalid_grant`, wipe the credentials, and die with "Not logged in · Please run /login". |
| #54443 `[G2]` | opened 2026-04-28; capture 2026-05-01 | A MITM capture shows the refresh rejected with `HTTP 400 error=invalid_grant error_description="Refresh token not found or invalid"`. The credentials file was then rewritten with an empty refresh token. |
| #54443 follow-up `[G2]` | 2026-06-01 | An external file-based refresher "fires cleanly but does NOT stop the logout cascade". Rotating the token "strands" sessions that are already running and hold the old refresh token in memory. |
| #31637 comments `[G3]` | 2026-03-07 | A comment suggested refreshing through `console.anthropic.com` on every 429 and itself warned that refresh tokens are one-time use. A reply the same day said the workaround "breaks claude code's own refreshing, and forces me to re-login every few minutes". |
| #80585 `[G4]` | 2026-07-23 | Concurrent local sessions "race on OAuth refresh-token rotation", causing a near-daily forced `/login`. |
| Claude-Usage-Tracker v3.2.0 `[T3]` | 2026-07-12 | A monitor fixed this exact bug: "the app refreshed the active account's OAuth tokens behind Claude Code's back (consuming its refresh token)". |
| Claude Code CHANGELOG `[D8]` | 2026 | A string of race fixes: 2.1.81 ("multiple concurrent Claude Code sessions requiring repeated re-authentication when one session refreshes its OAuth token"), 2.1.126, 2.1.136 ("a concurrent credential write could overwrite a freshly-rotated OAuth token"), 2.1.248, 2.1.277, 2.1.282. |

### Why a third-party refresh logs Claude Code out

1. Claude Code and the third-party app both read the same refresh token from `.credentials.json`.
2. The app redeems it. The server issues a new pair and invalidates the old refresh token.
3. The app keeps the new pair somewhere Claude Code doesn't look (the previous version of this app kept it in its own keyring entry). Or it writes the pair back, but already-running Claude Code sessions still hold the old token in memory.
4. Claude Code's next refresh presents the old token and gets `400 invalid_grant` `[G2]`.
5. Claude Code clears the stored login. Every session on that config directory now needs `/login` `[G1][G2]`.

### What Claude Code does after `invalid_grant`

- **2.1.283:** it blanks `accessToken` and `refreshToken` to `""` and sets `expiresAt` to `0` `[INFERRED]`. It does this only if the stored refresh token is still the one that was rejected, so a stale process cannot wipe a newer rotation `[INFERRED]`.
- **2.1.126:** in #54443, only the refresh token was blanked, and the access token was kept `[G2]`.

**Consequence for this app:** an empty `accessToken` or `refreshToken`, or `expiresAt == 0`, means **logged out**. It does not mean "expired, wait for a refresh".

### How Claude Code coordinates its own refreshes

This is relevant because the companion doc's `get_usage` route spawns `claude`, and that process may refresh. According to `[INFERRED]` for 2.1.283:

- Before refreshing, a process re-reads `.credentials.json` when its modification time has changed, and adopts a newer token written by another process.
- Refreshes are serialized with a cross-process lock file. The winner re-reads under the lock and saves with a compare-and-swap, and losers adopt the winner's result. The changelog confirms the takeover of a lock held by a dead process (2.1.282) and the retryable error instead of a login screen (2.1.248) `[D8]`.
- **A 401 from the usage endpoint forces a refresh even when the access token isn't near expiry.** That rotates the refresh token for no good reason. The companion doc describes a tripwire for it.

In short, refreshing is safe only when Claude Code does it itself, and even Claude Code needed half a dozen releases to get the races right. A read-only monitor gains nothing by joining in.

---

## 5. The rule for this app

**Never refresh. Read-only. Always.**

1. **Never call the token endpoint.** This applies to `platform.claude.com`, `console.anthropic.com`, and any future URL, "just once" or "only when expired" included.
2. **Never write** `.credentials.json`, `.claude.json`, or the macOS Keychain item.
3. **Never copy tokens** into this app's own storage (keyring, cache, logs, crash reports).
4. **Read fresh on every poll.** Stat the file and re-parse it when its modification time changes. Retry once on a JSON parse error, in case a write was in progress.
5. **Parse only `claudeAiOauth`**, and only the fields you need. For status that means `expiresAt`, `refreshTokenExpiresAt`, `scopes` and `subscriptionType`. Read `accessToken` only if the opt-in direct mode exists, and only to check that it is non-empty. Never touch `mcpOAuth`.
6. **Let Claude Code do all refreshing.** The only refresher is Claude Code: the user's own sessions, or the unmodified `claude` process the app spawns for `get_usage`, which uses Claude Code's own lock.
7. **On macOS, don't read the Keychain.** Use the spawned-binary route.

Earlier releases of this app broke rules 1, 3 and 7. `claude_usage_monitor/auth.py` had a `_refresh_oauth()` that redeemed Claude Code's refresh token against the old console URL and kept the rotated result only in the app's keyring. It also hard-coded the default Keychain service name. That code is being removed.

---

## 6. UI states

These are derived from `.credentials.json` alone, with no network calls. They are shown per account, next to the usage values.

| State | Condition, checked in this order | What to show | User action |
|---|---|---|---|
| **Not logged in** | File missing, or no `claudeAiOauth` | "Not logged in to Claude Code" | Run `claude` and log in |
| **Logged out** | `accessToken` or `refreshToken` is `""`, or `expiresAt == 0` (blanked after `invalid_grant` `[INFERRED]`) | "Logged out: run `/login` in Claude Code" | `/login` |
| **Login expired** | `refreshTokenExpiresAt <= now` | "Login expired: run `/login`" (mirrors `Login expired · Please run /login` `[D2]`) | `/login` |
| **Login expiring** | `refreshTokenExpiresAt - now < 3 days` (Claude Code's own threshold `[D2]`) | Normal values, plus a warning badge: "Login expires in N days" | `/login` soon |
| **Token stale** | `expiresAt <= now + 60 s`, refresh token still valid | Normal values; a note only on hover | None. Claude Code, including the spawned `get_usage` process, refreshes on next use `[INFERRED]`. The opt-in direct mode must skip polling in this state. |
| **Fresh** | None of the above | Normal values | None |

Usage availability is reported separately (see the companion doc). It is not a credential state:

- `get_usage` returns `rate_limits_available: false` for inference-only tokens, API keys and similar logins. Show "Usage not available for this login."
- A missing `user:profile` scope predicts this before any poll.

Pseudocode:

```python
def credential_state(c, now_ms):
    o = (c or {}).get("claudeAiOauth")
    if not o:
        return "not_logged_in"
    if not o.get("accessToken") or not o.get("refreshToken") or not o.get("expiresAt"):
        return "logged_out"
    rt_exp = o.get("refreshTokenExpiresAt")
    if rt_exp and rt_exp <= now_ms:
        return "login_expired"
    if rt_exp and rt_exp - now_ms < 3 * 24 * 3600 * 1000:
        return "login_expiring"
    if o["expiresAt"] <= now_ms + 60_000:
        return "token_stale"
    return "fresh"
```

Notes:

- `claude auth status` exits with status 1 when not logged in `[INFERRED]`. It is a possible cross-check that needs no parsing, but it prints the email, so never log its output.
- **Multiple accounts.** Each `CLAUDE_CONFIG_DIR` has its own login and its own token family, even for the same account (#64336 `[G5]`). Track state per directory.

---

## Open questions

1. Does `refreshTokenExpiresAt` slide forward on each refresh, or is it fixed from `/login`? Watch it across a few refreshes.
2. Is Claude Code's three-day login warning computed from `refreshTokenExpiresAt`?
3. On macOS with `CLAUDE_CONFIG_DIR`, which of several accumulated `Claude Code-credentials-<hex>` items is the live one? This only matters if the app ever reads the Keychain, which it should not.

---

## Sources

Every source was read on 2026-09-28 unless another date is given.

**Official documentation**

- **[D2]** Claude Code docs, "Authentication", sections "Credential management", "Renew an expiring login", "Authentication precedence" and "Generate a long-lived token": https://code.claude.com/docs/en/authentication
- **[D3]** Claude Code docs, "Environment variables" (`CLAUDE_CONFIG_DIR` documented; `CLAUDE_SECURESTORAGE_CONFIG_DIR` absent): https://code.claude.com/docs/en/env-vars
- **[D8]** Claude Code CHANGELOG (entries 2.1.81, 2.1.126, 2.1.136, 2.1.248, 2.1.277, 2.1.282): https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md

**anthropics/claude-code issues**

- **[G1]** #43392, "OAuth token refresh race condition when running multiple Claude Code agents in parallel", 2026-04-04: https://github.com/anthropics/claude-code/issues/43392
- **[G2]** #54443, "OAuth refresh returns 400 after early 401 before local expiresAt; concurrent sessions forced to /login", opened 2026-04-28; MITM capture in the 2026-05-01 comment; external-refresher follow-up 2026-06-01: https://github.com/anthropics/claude-code/issues/54443
- **[G3]** #31637, two comments of 2026-03-07: the refresh-on-429 workaround and the report that it broke Claude Code's refreshing: https://github.com/anthropics/claude-code/issues/31637
- **[G4]** #80585, "Multiple concurrent local sessions race on OAuth refresh-token rotation → near-daily forced /login", 2026-07-23: https://github.com/anthropics/claude-code/issues/80585
- **[G5]** #64336, "Multiple profile directories ... require independent re-logins despite sharing the same account", 2026-05-31: https://github.com/anthropics/claude-code/issues/64336
- **[G7]** macOS Keychain item naming and accumulation:
  - #84275 (2026-08-05, `Claude Code-credentials-<8 hex>` with `CLAUDE_CONFIG_DIR` set): https://github.com/anthropics/claude-code/issues/84275
  - #83832 (2026-08-04): https://github.com/anthropics/claude-code/issues/83832
  - #90527 (2026-08-29): https://github.com/anthropics/claude-code/issues/90527
- **[G8]** #94491, "macOS: token refresh rewrites Claude Code-credentials in place and drops its keychain ACL", 2026-09-15: https://github.com/anthropics/claude-code/issues/94491

**Third-party projects**

- **[T1]** steipete/CodexBar (MIT), `docs/claude.md` (Keychain item, `user:profile` requirement, ACL resets, `mcpOAuth`-only items): https://github.com/steipete/CodexBar/blob/main/docs/claude.md
- **[T3]** hamed-elfayome/Claude-Usage-Tracker release v3.2.0, 2026-07-12: https://github.com/hamed-elfayome/Claude-Usage-Tracker/releases/tag/v3.2.0

**Companion doc**

- **[D9 in the companion doc]** Agent SDK typings for `rate_limits_available`; see [claude-usage-sources.md](claude-usage-sources.md#sources).
