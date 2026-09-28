# Codex (ChatGPT plan) usage sources

**TLDR:** A Codex CLI signed in with a ChatGPT plan exposes plan usage in three places: the local session "rollout" files (no network needed, but only updated when you send Codex a message), OpenAI's `codex app-server` JSON-RPC method `account/rateLimits/read` (first-party, and it handles its own token refresh), and the undocumented `chatgpt.com/backend-api/wham/usage` endpoint. The monitor reads rollout files first while they are fresh, falls back to `app-server` when they go stale, and says "no recent data" rather than showing an old number as if it were current. It never calls `/wham/usage` and never refreshes or rewrites Codex's tokens, because Codex refresh tokens are single-use.

Research date: 2026-09-28. Local observations used Codex CLI 0.157.0 on Linux. Source-code references point at `openai/codex` commit `368e5eae` (fetched 2026-09-28) unless another commit is named.

---

## Contents

1. [Why freshness is the main design problem](#1-why-freshness-is-the-main-design-problem)
2. [Source comparison](#2-source-comparison)
3. [Credentials: `auth.json`](#3-credentials-authjson-field-names-only)
4. [Multiple accounts: `CODEX_HOME`](#4-multiple-accounts-codex_home)
5. [Source A: local rollout JSONL](#5-source-a-local-rollout-jsonl-zero-network)
6. [Source B: `codex app-server`](#6-source-b-codex-app-server--accountratelimitsread)
7. [Source C: `/wham/usage` (reference only)](#7-source-c-whamusage-reference-only)
8. [Token refresh: why we never do it](#8-token-refresh-why-the-monitor-never-does-it)
9. [Things not to do](#9-things-not-to-do)
10. [Prior art: CodexBar and others](#10-prior-art-codexbar-and-other-linux-tools)
11. [Policy posture](#11-policy-posture)
12. [Recommended design](#12-recommended-design)
13. [Open questions](#13-open-questions)
14. [Sources](#14-sources)

---

## 1. Why freshness is the main design problem

Codex writes rate-limit numbers into its local session files only when a model turn gets a response. If you haven't sent Codex a message in three days, the newest number on disk is three days old. It also knows nothing about usage from other places that draw on the same plan, such as Codex on another machine, the IDE extension or Codex cloud tasks. (That last point is an inference from how the data is sourced, see [section 5](#5-source-a-local-rollout-jsonl-zero-network). It has not been tested.)

A usage bar that shows "7% used" from three days ago looks exactly like a bar that shows "7% used" right now, and that is misleading. So the design rule for this provider is:

> **Only show a Codex percentage as current when it is fresh.** If the local data is stale, get a fresh reading from `codex app-server`. If that isn't possible, show "no recent data" and put the last-seen value and its age in the tooltip. Never show the old value as the headline number.

The rest of this document explains where each number comes from and why that rule leads to the design in [section 12](#12-recommended-design).

---

## 2. Source comparison

| Source | Network? | Fresh when? | Who refreshes tokens? | Stability | Role in this app |
|---|---|---|---|---|---|
| **A. Rollout JSONL** under `$CODEX_HOME/sessions` | None | Only right after a local Codex turn | Not needed | Undocumented file format; has been stable across recent versions, but may change | **First**, gated by a freshness check |
| **B. `codex app-server`** → `account/rateLimits/read` | Yes, done by Codex itself | Every call (it queries the backend) | Codex, under its own rules | Documented, but the `app-server` command is labeled experimental | **Second**, used when A is stale |
| **C. `GET /backend-api/wham/usage`** | Yes, done by us | Every call | Nobody, unless we do it (which we must not) | Undocumented, no auth contract | **Not used.** Documented here for reference only |
| `/status` in the Codex TUI | Yes | Every call | Codex | Screen scraping | **Not used** (see [section 9](#9-things-not-to-do)) |

---

## 3. Credentials: `auth.json` (field names only)

Codex caches its login in `$CODEX_HOME/auth.json`, which defaults to `~/.codex/auth.json`. OpenAI's docs say: *"treat `~/.codex/auth.json` like a password: it contains access tokens."* ([learn.chatgpt.com/docs/auth](https://learn.chatgpt.com/docs/auth), fetched 2026-09-28)

**Top-level fields** (from `codex-rs/login/src/auth/storage.rs`, and confirmed as key names only against a local file on 2026-09-28):

| Field | Meaning |
|---|---|
| `auth_mode` | `"chatgpt"` for a ChatGPT-plan login. API-key logins use a different mode. |
| `OPENAI_API_KEY` | API key, or `null` for ChatGPT logins |
| `tokens.id_token` | JWT |
| `tokens.access_token` | JWT used as the Bearer token |
| `tokens.refresh_token` | **Single-use** refresh token (see [section 8](#8-token-refresh-why-the-monitor-never-does-it)) |
| `tokens.account_id` | ChatGPT account/workspace ID |
| `last_refresh` | ISO timestamp of the last token refresh |
| optional: `agent_identity`, `personal_access_token`, `bedrock_api_key`, `bedrock_access_keys` | Other auth modes |

**The file may not exist at all.** The `cli_auth_credentials_store` setting in `config.toml` accepts `file | keyring | auto | ephemeral`. With `keyring` (or `auto` when a keyring is available), credentials live in the OS credential store and there is no `auth.json` ([learn.chatgpt.com/docs/auth](https://learn.chatgpt.com/docs/auth), fetched 2026-09-28). This is one more reason to prefer `app-server` (Source B), which reads whatever store Codex is configured to use.

**Plan label without a network call.** The JWTs carry a claim namespace `https://api.openai.com/auth` that includes `chatgpt_plan_type`, plus subscription dates such as `chatgpt_subscription_active_until` (observed locally 2026-09-28, claim names only; also described in [CodexBar docs/codex.md](https://github.com/steipete/CodexBar/blob/main/docs/codex.md)). Rollout events and `app-server` responses already carry `plan_type`/`planType`, so the monitor doesn't need to decode JWTs at all. If it ever does, it must decode locally, never log the token, and never send it anywhere.

**Token lifetimes (observed locally, 2026-09-28, from `exp - iat` claims):** the access token lives about 10 days and the id_token about 1 hour. Treat these as observations, not guarantees.

---

## 4. Multiple accounts: `CODEX_HOME`

Codex keeps everything (login, config, sessions) under one directory, `CODEX_HOME`, which defaults to `~/.codex` ([learn.chatgpt.com/docs/auth](https://learn.chatgpt.com/docs/auth), fetched 2026-09-28). One directory holds one login at a time, so **to monitor several ChatGPT accounts, use one `CODEX_HOME` per account** (for example `~/.codex`, `~/.codex-work`).

For each configured home, the monitor:

- reads rollouts from `<home>/sessions/` (and `<home>/archived_sessions/`)
- spawns `app-server` with `CODEX_HOME=<home>` in its environment
- labels the account from `planType`/`plan_type` and a user-chosen nickname. `account/read` also returns the account email, but the monitor should not display or log it by default.

CodexBar does the same thing with a list of "profile homes" (`providers[].codexProfileHomePaths` in `~/.codexbar/config.json`). It notes that *"Profile homes are not copied, reauthenticated, or removed by CodexBar"* ([CodexBar docs/codex.md](https://github.com/steipete/CodexBar/blob/main/docs/codex.md), fetched 2026-09-28). That is a good rule to copy.

**Gotcha:** if you call `/wham/usage` directly (which we don't), the `ChatGPT-Account-Id` header must match that home's `tokens.account_id`. Otherwise you get another workspace's numbers (source: `codex-rs/backend-client/src/client.rs`).

---

## 5. Source A: local rollout JSONL (zero network)

### Where

`$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl`, plus older sessions in `$CODEX_HOME/archived_sessions/` (observed locally 2026-09-28; the same paths are listed in [CodexBar docs/codex.md](https://github.com/steipete/CodexBar/blob/main/docs/codex.md)).

### What

Each file is JSON Lines. Lines with `type: "event_msg"` and `payload.type: "token_count"` carry a `rate_limits` block. Here is an illustrative line, reformatted, with example values from a free-plan account observed 2026-09-28:

```json
{
  "timestamp": "2026-09-25T19:56:49.126Z",
  "type": "event_msg",
  "payload": {
    "type": "token_count",
    "info": {
      "total_token_usage": { "...": "..." },
      "last_token_usage": { "...": "..." },
      "model_context_window": 0
    },
    "rate_limits": {
      "limit_id": "codex",
      "limit_name": null,
      "primary":   { "used_percent": 7.0, "window_minutes": 43200, "resets_at": 1792952017 },
      "secondary": null,
      "credits":   { "has_credits": false, "unlimited": false, "balance": null },
      "individual_limit": null,
      "spend_control_reached": null,
      "plan_type": "free",
      "rate_limit_reached_type": null
    }
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `limit_id` | string | Bucket ID, `"codex"` for the main bucket |
| `limit_name` | string or null | Optional display label |
| `primary` / `secondary` | object or null | A rate-limit window. Either can be `null`. |
| `.used_percent` | **float**, 0 to 100 | Percent of the window used |
| `.window_minutes` | int | Window length. **Label windows from this value** (see below). |
| `.resets_at` | int, Unix seconds | When the window resets |
| `credits` | object | `has_credits`, `unlimited`, `balance` |
| `plan_type` | string | e.g. `"free"`. Paid values unverified locally. |
| `rate_limit_reached_type` | string or null | Set when a limit has been hit |

### Where the numbers come from, and why they go stale

Codex fills this block from the model response: either the `x-codex-primary-used-percent` / `-window-minutes` / `-reset-at` response headers (and their `secondary` equivalents), or a `codex.rate_limits` stream event (`codex-rs/codex-api/src/rate_limits.rs`). **No response means no new line.** The value on disk is therefore "what the server said at the end of your last local Codex turn". Nothing updates it while Codex sits idle, and usage from other machines or surfaces doesn't show up until your next local turn. (The staleness follows directly from the code. The "other surfaces" part is an inference: ChatGPT-plan limits are shared across Codex surfaces per [learn.chatgpt.com/docs/pricing](https://learn.chatgpt.com/docs/pricing), fetched 2026-09-28.)

### Window shapes vary by plan: never hardcode "5h / weekly"

| Plan | What was seen | Confidence |
|---|---|---|
| Free | One `primary` window of **43200 minutes (30 days)**, `secondary: null` | Observed locally, 2026-09-28 (91 events across 5 files, all identical in shape) |
| Plus / Pro / Business | Probably `primary` = 300 min (5 hours) and `secondary` = 10080 min (weekly) | **Unverified.** OpenAI's pricing page gives per-5-hour ranges and says "weekly limits may also apply" ([learn.chatgpt.com/docs/pricing](https://learn.chatgpt.com/docs/pricing), fetched 2026-09-28), and CodexBar's docs assume the same shape. |

Label windows from `window_minutes`:

```python
def window_label(minutes: int) -> str:
    known = {300: "5-hour", 10080: "Weekly", 43200: "30-day"}
    if minutes in known:
        return known[minutes]
    if minutes % 1440 == 0:
        return f"{minutes // 1440}-day"
    if minutes % 60 == 0:
        return f"{minutes // 60}-hour"
    return f"{minutes}-min"
```

### Reading rollouts efficiently and safely

- Pick the newest rollout by modification time, then read it **backwards from the end** for the last `token_count` line that has `rate_limits`. Don't parse whole files on every poll.
- **Don't peek at a fixed number of bytes from the start.** The first line (`session_meta`) was about 19 KB in local files (observed 2026-09-28). A fixed 16 KB head read cuts it in half and fails to parse.
- **`session_meta` contains account identifiers** (`creator_account_id`, `creator_user_id`, observed locally as key names). The monitor never needs them, so it must never log or display them.
- `info` and `rate_limits` can be `null` on some lines. Skip those lines instead of failing.
- If `resets_at` is in the past, the window has reset since the reading was taken. The old percentage is now meaningless (not zero, and not the old value).

### Freshness gate (design choice, not a Codex rule)

Treat a rollout reading as **fresh** only if its line `timestamp` is recent. A threshold of around 10 minutes is a reasonable default, and it should be user-configurable. Otherwise the reading is **stale**: fall through to Source B. The threshold is a product decision. The point is that it exists.

---

## 6. Source B: `codex app-server` → `account/rateLimits/read`

`codex app-server` is OpenAI's own JSON-RPC interface, the one the Codex IDE extension uses. The default transport is stdio with newline-delimited JSON ([learn.chatgpt.com/docs/app-server](https://learn.chatgpt.com/docs/app-server), fetched 2026-09-28). It is the **documented** way for other programs to read ChatGPT rate limits. Codex does the network call and **owns token refresh**, so the monitor never touches tokens.

### Status: documented, but "experimental"

- The docs say: *"The app-server command and WebSocket transport are experimental and aren't supported for production workloads."* The docs also say: *"If you are automating jobs or running Codex in CI, use the Codex SDK instead."* ([learn.chatgpt.com/docs/app-server](https://learn.chatgpt.com/docs/app-server), fetched 2026-09-28)
- `codex --help` on 0.157.0 lists `app-server [experimental]` (observed locally 2026-09-28).
- The rate-limit methods themselves are on the **stable** protocol surface, not behind the `experimentalApi` capability (`codex-rs/app-server-protocol/src/protocol/common.rs`).
- Practical meaning: expect field changes between Codex releases. Parse leniently, ignore unknown fields, and keep Source A as the zero-dependency path.

### Invocation

```
CODEX_HOME=<home> codex -s read-only -a never app-server
```

`-s read-only -a never` (read-only sandbox, never ask for approval) is how CodexBar starts it ([CodexBar docs/codex.md](https://github.com/steipete/CodexBar/blob/main/docs/codex.md), fetched 2026-09-28). Another open-source tool, [MostafaAlyy/ai-agent-usage](https://github.com/MostafaAlyy/ai-agent-usage), uses `-s read-only -a untrusted`. The monitor never starts a thread or turn, so it never sends a model request.

Process hygiene (design choices):

- Spawn with an argument list, never a shell string.
- Start it in its own process group and set a hard timeout (for example 20 to 30 seconds). On timeout or exit, kill the **whole group**.
- Stop it gently first: close stdin, send SIGTERM, and use SIGKILL only if it doesn't exit within a few seconds. `app-server` may refresh the token while it runs, and a process killed between receiving a rotated single-use refresh token and saving it could lose the login. That risk is unverified for Codex; Claude Code had a related kill-mid-refresh lock bug (see [claude-usage-sources.md](claude-usage-sources.md#scheduling)).
- Set stdin/stdout as pipes, and don't let it inherit a TTY.
- Cache the result, and don't spawn more often than every few minutes (see [section 12](#12-recommended-design)).

### Message sequence

Adapted from the official docs; replace the `clientInfo` values with this app's own name:

```jsonc
// → handshake (required once per connection)
{"method":"initialize","id":0,"params":{"clientInfo":{"name":"ai_usage_monitor","title":"AI Usage Monitor","version":"0.1.0"}}}
{"method":"initialized"}

// → optional: auth state and plan (response includes email, so don't log it)
{"method":"account/read","id":1,"params":{"refreshToken":false}}

// → the rate limits
{"method":"account/rateLimits/read","id":2,"params":{"excludeResetCreditDetails":true}}
```

Example response shape, adapted from the official docs example (values illustrative; `credits: null` reflects `excludeResetCreditDetails: true`, since the docs say `credits` is null "when only the count is known"):

```json
{
  "id": 2,
  "result": {
    "rateLimits": {
      "limitId": "codex",
      "limitName": null,
      "primary":   { "usedPercent": 25, "windowDurationMins": 15, "resetsAt": 1730947200 },
      "secondary": null,
      "rateLimitReachedType": null
    },
    "rateLimitsByLimitId": {
      "codex":       { "limitId": "codex", "primary": { "usedPercent": 25, "windowDurationMins": 15, "resetsAt": 1730947200 }, "secondary": null },
      "codex_other": { "limitId": "codex_other", "limitName": "codex_other", "primary": { "usedPercent": 42, "windowDurationMins": 60, "resetsAt": 1730950800 }, "secondary": null }
    },
    "rateLimitResetCredits": { "availableCount": 2, "credits": null }
  }
}
```

Field notes from the docs and protocol source (`codex-rs/app-server-protocol/src/protocol/v2/account.rs`):

- `rateLimits` is the backward-compatible single-bucket view. `rateLimitsByLimitId` is the multi-bucket view keyed by `limitId`. **Prefer `rateLimitsByLimitId` when present**, because a plan can have more than one metered bucket.
- `usedPercent` is an **integer** here (rounded from the underlying float). `windowDurationMins` is the window length. `resetsAt` is Unix seconds.
- `planType` and `credits` appear inside a snapshot when the server provides them.
- Other response fields: `ordinaryUsageAllowed`, `accountId` and `rateLimitUpsell`. Ignore anything you don't need.
- A notification, `account/rateLimits/updated`, is pushed whenever limits change. It is only useful if the monitor keeps the process running. Spawning per poll is simpler and is the recommended starting point.

To pin behavior to the installed Codex version, generate its schema with `codex app-server generate-json-schema --out ./schemas` (documented; `--out` is required on 0.157.0, observed locally).

### What it does under the hood

`account/rateLimits/read` still hits the same backend usage endpoint as Source C, but through Codex's own code, with Codex's own token handling and identity. CodexBar notes that app-server errors can include a `wham/usage` JSON body in the error text ([CodexBar docs/codex.md](https://github.com/steipete/CodexBar/blob/main/docs/codex.md), fetched 2026-09-28).

When the user is signed out, `account/read` returns `{"account": null, "requiresOpenaiAuth": true}`, per the docs' examples. In that case, and whenever the rate-limit read fails with an auth error, the monitor should show "Sign in to Codex again" and **never** try to log in itself. (The docs' login methods, such as `account/login/start`, exist for host apps that own the login UI; a usage monitor isn't one of those.)

---

## 7. Source C: `/wham/usage` (reference only)

The monitor does **not** call this endpoint. It is documented here so contributors understand what Source B does under the hood, and why we don't call it directly.

**Request** (`codex-rs/backend-client/src/client/rate_limit_resets.rs`, `client.rs`):

```
GET https://chatgpt.com/backend-api/wham/usage
Authorization: Bearer <tokens.access_token>
ChatGPT-Account-Id: <tokens.account_id>
User-Agent: <client name>
```

If the configured base URL does not contain `/backend-api`, the path is `{base}/api/codex/usage` instead. Codex can also send an `X-OpenAI-Fedramp` header for FedRAMP accounts.

**Response schema** (`codex-rs/codex-backend-openapi-models/src/models/*.rs`):

| Field | Notes |
|---|---|
| `plan_type` | string |
| `rate_limit.allowed`, `rate_limit.limit_reached` | booleans |
| `rate_limit.primary_window`, `rate_limit.secondary_window` | `{used_percent: int, limit_window_seconds, reset_after_seconds, reset_at}`. **Seconds, not minutes.** Codex converts by rounding up: `ceil(s / 60)`. |
| `credits` | `{has_credits, unlimited, balance: string, approx_local_messages[], approx_cloud_messages[]}` |
| `additional_rate_limits[]` | `{limit_name, metered_feature, rate_limit, normal_model_slug?}`, extra per-feature or per-model buckets |
| `rate_limit_reached_type` | `{type}` |
| also | `spend_control`, `rate_limit_reset_credits.available_count`, `account_id`, `user_id`, `rate_limit_upsell` |

**Why not use it directly:**

1. It is undocumented. OpenAI hasn't published an auth contract for third-party clients using ChatGPT-plan tokens. [openai/codex#36886](https://github.com/openai/codex/issues/36886) (opened 2026-08-04, no maintainer reply as of 2026-09-28) asks this for the Responses endpoint, and the same gap applies here.
2. It needs the access token, which means reading `auth.json` (which may not exist, see [section 3](#3-credentials-authjson-field-names-only)). When the token expires, the only fix is a refresh, and we must not refresh (see [section 8](#8-token-refresh-why-the-monitor-never-does-it)).
3. Sending Codex's own client identity would impersonate the CLI. Codex treats the `codex_cli_rs` originator as first-party (`codex-rs/login/src/auth/default_client.rs`). The app-server docs instead ask integrations to identify themselves with `clientInfo.name`.

---

## 8. Token refresh: why the monitor never does it

How Codex refreshes (source: `codex-rs/login/src/auth/manager.rs`, `codex-rs/login/src/oauth/client.rs`):

- It sends `POST https://auth.openai.com/oauth/token` with a **JSON body** (`grant_type: "refresh_token"`, `client_id`, `refresh_token`). This is not form-encoded: the source comment says *"ChatGPT refresh uses JSON; authorization-code and gateway grants use form encoding."*
- It refreshes proactively when the access token's JWT `exp` is within **5 minutes**. A second rule (refresh if `last_refresh` is older than 8 days) applies **only as a fallback** when the JWT expiry can't be parsed.
- **Refresh tokens are single-use.** Codex has explicit error messages for a refresh token that "was already used" and one that "was revoked".

Consequence: if a monitor redeems the refresh token and doesn't atomically write the new pair back to the right store, the user's next Codex run fails and they have to log in again. Writing back safely means racing Codex itself, possibly across several running Codex processes. CodexBar made the same call: *"CodexBar never publishes refreshed native tokens into `auth.json`"* ([CodexBar docs/codex.md](https://github.com/steipete/CodexBar/blob/main/docs/codex.md), fetched 2026-09-28).

**Rule for this app:** never refresh or write Codex credentials. Read-only access, and delegate to `app-server` (Source B), which owns refresh. OpenAI's docs say managed ChatGPT sessions refresh automatically during normal use ([learn.chatgpt.com/docs/auth](https://learn.chatgpt.com/docs/auth)). The same rule applies to other agents' credential files (Claude, Gemini): the monitor is a guest in those files, not their owner.

---

## 9. Things not to do

| Don't | Why |
|---|---|
| Refresh or rewrite `auth.json` | Single-use refresh tokens; logs the user out ([section 8](#8-token-refresh-why-the-monitor-never-does-it)) |
| Scrape `/status` from the Codex TUI | Screen scraping is fragile, and bare `codex` can start interactive auth and open browser tabs. CodexBar treats it as *"Manual/debug parser only"* ([CodexBar docs/codex.md](https://github.com/steipete/CodexBar/blob/main/docs/codex.md)). |
| Send tiny model requests to "start" a window | Spends the user's quota. At least one Linux tool did this (see [section 10](#10-prior-art-codexbar-and-other-linux-tools)). |
| Show a stale rollout value as current | The user's own complaint: data from days ago looks current ([section 1](#1-why-freshness-is-the-main-design-problem)) |
| Log `auth.json`, JWTs, `account/read` emails, or `session_meta` account IDs | Secrets and identifiers; this repo is public and users paste logs into issues |
| Use a spoofed Codex `User-Agent`/originator | Impersonates the first-party client ([section 7](#7-source-c-whamusage-reference-only)) |

---

## 10. Prior art: CodexBar and other Linux tools

**[steipete/CodexBar](https://github.com/steipete/CodexBar)** (MIT, v0.68.0 released 2026-09-27; checked 2026-09-28) is the most complete multi-provider usage monitor. On Linux it ships:

- a Swift `codexbar` CLI (glibc and musl tarballs, AUR `codexbar-cli`, Homebrew), and
- a Qt 6 / QML desktop app that **delegates all fetching to the CLI**. It needs glibc 2.39+ and Qt 6.4+ and has no auto-updater (`Integrations/Linux/README.md`).

How it gets Codex data on Linux: the CLI's `--source auto` order for Codex is web dashboard, then CLI RPC (`app-server`) or PTY (`docs/providers.md`). Browser-cookie import is macOS-only (`docs/cli.md`), so **on Linux, Codex data most likely comes from `codex app-server`** unless the user picks `--source oauth` (which calls `/wham/usage`). This is an inference from CodexBar's docs, not tested. Outputs are `codexbar usage --format json` and `codexbar serve` (HTTP `GET /usage` on 127.0.0.1). Its rules worth copying: never write `auth.json`, never launch the bare TUI in the background, and bound every subprocess.

Other open-source Linux tools checked 2026-09-28 (all MIT per GitHub metadata):

| Tool | Codex source | Note |
|---|---|---|
| [MostafaAlyy/ai-agent-usage](https://github.com/MostafaAlyy/ai-agent-usage) (GNOME) | `app-server` (`account/read`, `account/rateLimits/read`) | Collector writes a JSON snapshot; UI only renders it. A good split. |
| [komagata/ai-quota-waybar](https://github.com/komagata/ai-quota-waybar) (Waybar) | `app-server` | Bash implementation of the handshake |
| [merely04/ai-gauge](https://github.com/merely04/ai-gauge) | Rollout JSONL as a fallback | |
| [Servosity/ai-tabs](https://github.com/Servosity/ai-tabs) | Reads rollout `token_count` events for per-session token totals and context size | Does not read the `rate_limits` block (as of 2026-09-28) |
| ydxrobot/codex-quota-linux (a copy of a repo that now returns 404) | n/a | **Not read-only**: rewrites the Codex auth file to switch accounts and sends small Codex requests to start windows. Don't copy. |

---

## 11. Policy posture

- OpenAI publishes no rule against third-party tools reading ChatGPT-plan usage. An OpenAI engineer described the terms and code license as *"quite permissive"* in [openai/codex discussion #8338](https://github.com/openai/codex/discussions/8338) (comment dated 2026-02-09). OpenAI's CEO publicly endorsed signing in to a third-party agent (OpenClaw) with a ChatGPT subscription ([x.com/sama/status/2050357911915028689](https://x.com/sama/status/2050357911915028689), 2026-05-01).
- On the other hand, `/wham/usage` has no published contract (see [section 7](#7-source-c-whamusage-reference-only)), and OpenAI's docs say to treat `auth.json` like a password.
- The documented integration surface is `app-server`, which asks clients to identify themselves via `clientInfo.name`. Using it is the lowest-risk option, and it's the one we use.
- "Sign in with ChatGPT" for partner apps (beta, 2026) shares only name, email and profile picture. It is **not** a usage API ([help.openai.com article 20001410](https://help.openai.com/en/articles/20001410-sign-in-with-chatgpt); the page returned 403 to automated fetch, so this is confirmed via search snippets only).

---

## 12. Recommended design

```
for each configured CODEX_HOME:
    1. A = newest rollout token_count.rate_limits in <home>/sessions (+ archived_sessions)
       if A exists and A.timestamp is within FRESH_MAX (default ~10 min):
            show A  (source = "local", as_of = A.timestamp)
            continue
    2. if `codex` is installed and last app-server poll was > MIN_POLL ago (default 5 min):
            B = app-server account/rateLimits/read   (own process group, 20-30 s timeout)
            if B ok: show B (source = "app-server", as_of = now); cache it; continue
            if B says re-auth needed: show "Sign in to Codex again"; continue
    3. no fresh data:
            headline: "no recent data" (not a percentage)
            tooltip: "last seen 7% of 30-day window, 3 days ago" (example)
            if A.resets_at < now: tooltip says "window has reset since"
```

Why this order:

- **Rollout first** costs nothing (no process, no network) and is exact while the user is actively using Codex, which is exactly when they care most.
- **app-server second** gives a real, current number when the user has been away, without the monitor ever holding or refreshing a token. It costs one short-lived process per poll.
- **No `/wham/usage`**, because it would force us to either refresh tokens (unsafe) or go blind whenever the access token expires.
- **Explicit "no recent data" state**, because an old number shown as current is worse than no number.

**Normalized output per window**, which fits Codex, Claude and Antigravity alike. The shape is adapted from MostafaAlyy/ai-agent-usage's README:

```json
{
  "provider": "codex",
  "account": "<user nickname for this CODEX_HOME>",
  "plan": "free",
  "status": "ok | stale | auth | error | not_configured",
  "source": "local | app-server",
  "as_of": "2026-09-28T12:00:00Z",
  "limits": [
    {"key": "codex/primary", "label": "30-day", "used_percent": 7.0,
     "window_minutes": 43200, "resets_at": "2026-10-25T18:13:37Z"}
  ]
}
```

Normalize `used_percent` to a float from 0 to 100 (the rollout gives a float, app-server an int). Store `resets_at` as an ISO-8601 UTC string (both Codex sources give Unix seconds).

---

## 13. Open questions

- **Paid-plan window shapes.** Do Plus/Pro accounts report `primary` = 300 min and `secondary` = 10080 min in late 2026? Not verified: only a free account was available locally. The window-labeling code above doesn't depend on the answer.
- **Values of `limit_id` and `plan_type` across plans**, and which extra buckets appear in `rateLimitsByLimitId` (for example, per-model buckets). Unverified.
- **Account switches inside one `CODEX_HOME`.** After a logout and login as a different account, the newest rollout may belong to the previous account. Matching `session_meta` identifiers against the current login in memory might solve this, but that is unverified. Until then, a freshness gate plus the `app-server` fallback limits the damage.
- **`app-server` startup cost and side effects** on 0.157.0 (time to first response, whether it starts configured MCP servers, what it writes under `$CODEX_HOME`). Not measured.
- **Long-term stability** of `account/rateLimits/read` while `app-server` is labeled experimental.

---

## 14. Sources

Official documentation (all fetched 2026-09-28):

- Codex authentication and credential storage: <https://learn.chatgpt.com/docs/auth>
- Codex app-server protocol, including "Rate limits (ChatGPT)" and the experimental notice: <https://learn.chatgpt.com/docs/app-server>
- Codex pricing and limits: <https://learn.chatgpt.com/docs/pricing>

Open-source code, `openai/codex` at commit `368e5eae` (Apache-2.0, fetched 2026-09-28):

- `codex-rs/login/src/auth/storage.rs`: `auth.json` fields
- `codex-rs/login/src/auth/manager.rs`, `codex-rs/login/src/oauth/client.rs`: refresh behavior, single-use errors
- `codex-rs/login/src/auth/default_client.rs`: originator
- `codex-rs/backend-client/src/client.rs`, `.../client/rate_limit_resets.rs`: `/wham/usage` URL and headers
- `codex-rs/codex-backend-openapi-models/src/models/`: `/wham/usage` schema
- `codex-rs/codex-api/src/rate_limits.rs`: response headers and stream events that feed rollouts
- `codex-rs/app-server-protocol/src/protocol/common.rs`, `.../v2/account.rs`: app-server methods and types

Third-party (fetched 2026-09-28):

- CodexBar Codex provider docs: <https://github.com/steipete/CodexBar/blob/main/docs/codex.md> (commit `b4335754`)
- CodexBar Linux integration: <https://github.com/steipete/CodexBar/tree/main/Integrations/Linux>
- openai/codex discussion #8338: <https://github.com/openai/codex/discussions/8338>
- openai/codex issue #36886: <https://github.com/openai/codex/issues/36886>

Local observations (2026-09-28, Codex CLI 0.157.0, Linux): `auth.json` key names and JWT claim names (no values recorded), rollout event shapes, free-plan 30-day window, `codex --help` / `codex app-server --help` output.
