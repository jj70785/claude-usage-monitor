# Claude plan usage: where the numbers can come from

**TLDR.** The app gets Claude Pro/Max plan usage by running the official `claude` binary headlessly and sending it one experimental `get_usage` control request, so Claude Code makes the network call and handles its own tokens and this app never touches a token. The `cachedUsageUtilization` snapshot in `.claude.json` is used only to tell how fresh an answer is and to show last-known values, while the statusline `rate_limits` is not displayed because it goes stale whenever Claude Code sits idle. Direct calls to `/api/oauth/usage` are off by default, and the claude.ai `sessionKey` route has been removed.

- Status: research note, written 2026-09-28.
- Claude Code versions examined: 2.1.283 and 2.1.284, on Linux (Debian 13, XFCE, X11).
- Companion doc: [claude-oauth-tokens.md](claude-oauth-tokens.md), which covers where tokens live and why this app never refreshes them.

---

## Evidence labels

Every claim in this doc carries one of these labels:

| Label | Meaning |
|---|---|
| `[D1]`, `[G2]`, `[T3]`, ... | A public source. The [Sources](#sources) list at the end gives each URL and the date it was read. |
| `[OBS]` | Observed locally on 2026-09-28: file structure on disk, or a live run of the unmodified `claude` binary. |
| `[INFERRED]` | Inferred on 2026-09-28 (Claude Code 2.1.283) from observed behavior, changelog entries and public SDK typings. Not publicly documented and not directly verified. Probably right; re-check after Claude Code updates. |
| `[UNVERIFIED]` | Reported by someone but not confirmed, or my own inference. |

This doc describes observed behavior only. It deliberately leaves out any internals of the closed-source Claude Code binary.

---

## Summary: sources, ranked

| Rank | Source | How fresh | Network calls | Policy risk | Decision |
|---|---|---|---|---|---|
| 1 | `get_usage` control request to a spawned `claude -p` | Server read on each poll (or a shared snapshot under 60 s old) | 1 GET, made by Claude Code itself | Low: unmodified official binary | **Primary source** |
| 2 | Statusline stdin `rate_limits` | As of that session's last model response | None | None | **Not displayed** |
| 3 | `cachedUsageUtilization` in `.claude.json` | As of the last time any Claude Code process read usage | None | None | **Companion**: freshness stamp and last-known fallback |
| 4 | Claude Desktop `plan-usage-history.json` | Only while Claude Desktop is running | None | None | **Not used** |
| 5 | Direct `GET https://api.anthropic.com/api/oauth/usage` | Live | 1 GET, made by this app | Medium to high: undocumented, rate-limited, invites User-Agent spoofing | **Off by default** (possible opt-in later) |
| 6 | claude.ai web route with a `sessionKey` cookie | Live | 2 GETs | High: conflicts with published policy | **Removed** |

### Why freshness drives the design

Plan usage belongs to the account, not to one program. Claude Code sessions, claude.ai in the browser, Claude Desktop, the mobile app and other machines all draw from the same 5-hour and weekly windows. A source that only watches local activity cannot see the rest. Only a read from Anthropic's server can.

The maintainer's concern, 2026-09-28: the statusline value "only updates after each message," so Claude Code can sit open for days while that number is old. A monitor that quietly shows a stale number is worse than one that shows nothing. Two rules follow:

1. Always know how old a number is, and show that age.
2. Prefer "unknown" to a number that looks current but isn't.

---

## 1. `get_usage` through the official binary (primary)

### What it is

In print mode (`-p`) with stream-JSON input, Claude Code accepts *control requests* on stdin. This is the same protocol the Agent SDKs use to drive the CLI. One of these requests, `get_usage`, returns "the structured data behind the `/usage` command": session totals plus "claude.ai plan rate-limit utilization windows (5-hour, 7-day, per-model) when available" `[D9]`.

The TypeScript Agent SDK exposes it as `usage_EXPERIMENTAL_MAY_CHANGE_DO_NOT_RELY_ON_THIS_API_YET()`. Its docs say: "this API is unstable and may change or be removed in any release without notice" `[D9]`.

Why it ranks first:

- **The official binary makes the call.** The legal page says it does not prevent "an end user from signing in to the unmodified Claude Code binary with their own Claude subscription" `[D6]`. This app sends no credentials and fakes no User-Agent.
- **Token handling stays inside Claude Code.** If the access token has expired, the spawned `claude` refreshes it under its own cross-process lock, exactly as a new terminal session would `[INFERRED]`. This app never calls the token endpoint. See [claude-oauth-tokens.md](claude-oauth-tokens.md).
- **It keeps working after long idle periods.** The statusline stops updating when Claude Code is idle, and a direct GET fails once the 8-hour access token expires. This route has neither problem.
- **It sees account-wide usage**, including claude.ai web and Desktop, because it reads the server.

### Invocation (tested)

Run it from an **empty, dedicated directory**:

```sh
claude -p \
  --input-format stream-json --output-format stream-json --verbose \
  --no-session-persistence --strict-mcp-config --setting-sources project
```

Write exactly one line to stdin, with no `initialize` request before it:

```json
{"type":"control_request","request_id":"usage-1","request":{"subtype":"get_usage","skip_behaviors":true}}
```

Then read stdout line by line until you get a `control_response` whose `request_id` matches, and close stdin. For a second account, set `CLAUDE_CONFIG_DIR=<dir>` in the child's environment.

What each piece does:

| Piece | Why |
|---|---|
| `-p` | Print (headless) mode. `--input-format` and `--output-format` only apply in print mode `[D4]`. |
| `--input-format stream-json` | Accepts newline-delimited JSON messages, including control requests, on stdin `[D4]`. Claude Code requires stream-JSON output when the input is stream-JSON `[INFERRED]`. |
| `--output-format stream-json --verbose` | Newline-delimited JSON output `[D4][D5]`. Claude Code refuses stream-JSON output in print mode without `--verbose` `[INFERRED]`. |
| `--no-session-persistence` | "sessions are not saved to disk and cannot be resumed" `[D4]`, so no transcript clutter under `projects/`. |
| `--strict-mcp-config` | "Only use MCP servers from `--mcp-config`" `[D4]`. We pass none, so no MCP servers connect. |
| `--setting-sources project` | Loads only project settings `[D4]`. In an empty directory there are none, so the user's hooks, statusline and plugins from `~/.claude/settings.json` don't run. |
| Empty working directory | "Without `--bare`, a `-p` session runs the hooks in a project's `.claude/settings.json` and connects the servers in its `.mcp.json`, even in a folder you've never trusted" `[D5]`. |
| **Not** `--bare` | Bare mode, like `CLAUDE_CODE_SIMPLE=1`, means "OAuth tokens and keychain credentials are not read" `[D3][D4]`. Plan usage then becomes unavailable. |
| `skip_behaviors: true` | Skips "the scan of local transcripts ... the scan reads every transcript touched in the last seven days". `behaviors` then comes back `null` `[D9]`. |
| No `initialize` | The official SDKs always send `initialize` first `[INFERRED]`, but the CLI answers `get_usage` without it `[OBS]`. The `initialize` reply includes the account email and organization `[INFERRED]`, so skipping it keeps personal data out of this app's process. |

Possible extra hardening, **not yet tested together with the command above**:

- `--safe-mode`, which disables customizations while "Authentication, model selection, built-in tools, and permissions work normally" `[D4]`.
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, which turns off auto-updates, telemetry and other nonessential traffic `[D3]`.
- `DISABLE_AUTOUPDATER=1` `[D3]`.
- `ENABLE_CLAUDEAI_MCP_SERVERS=false` `[D3]`.

One caveat on disabling nonessential traffic: it also stops feature-flag fetching `[D3]`. That may change which per-model rows appear. For example, 2.1.283 "Fixed the weekly Fable limit not appearing in `/usage` ... when telemetry is disabled" `[D8]`. Test before adopting.

### Live test result

Observed 2026-09-28 with Claude Code 2.1.284 `[OBS]`:

- stdout contained exactly one line, the `control_response`.
- `session.total_cost_usd` was `0` and `model_usage` was empty, so no model call was made.
- `subscription_type` was `"max"` and `rate_limits_available` was `true`.
- `rate_limits` held the legacy `five_hour` and `seven_day` windows, a `limits[]` array with three rows (`session`, `weekly_all`, and `weekly_scoped` for the model "Fable"), `model_scoped`, and `extra_usage`.
- It also held about twenty other keys. Most were code-named and `null`; a few were undocumented objects such as `spend` and `seven_day_breakdown`. The window objects carried extra null fields too.
- `behaviors` was `null`.
- No account email appeared anywhere in the output.

### Response shape

The envelope:

```json
{"type":"control_response",
 "response":{"subtype":"success","request_id":"usage-1","response":{ ... }}}
```

Treat any `subtype` other than `"success"` as a failed poll. The error envelope's exact shape was not captured `[UNVERIFIED]`.

The inner object, with **illustrative values only**:

```json
{
  "session": {"total_cost_usd": 0, "total_api_duration_ms": 0, "total_duration_ms": 0,
              "total_lines_added": 0, "total_lines_removed": 0, "model_usage": {}},
  "subscription_type": "max",
  "rate_limits_available": true,
  "rate_limits": {
    "five_hour":  {"utilization": 12, "resets_at": "2026-09-28T21:00:00.123456+00:00"},
    "seven_day":  {"utilization": 64, "resets_at": "2026-10-01T03:00:00.123456+00:00"},
    "seven_day_opus": null,
    "seven_day_sonnet": null,
    "extra_usage": {"is_enabled": false, "monthly_limit": null, "used_credits": null,
                    "utilization": null, "currency": null},
    "limits": [
      {"kind": "session",       "group": "session", "percent": 12, "severity": "normal",
       "resets_at": "2026-09-28T21:00:00.123456+00:00", "scope": null, "is_active": false},
      {"kind": "weekly_all",    "group": "weekly",  "percent": 64, "severity": "warning",
       "resets_at": "2026-10-01T03:00:00.123456+00:00", "scope": null, "is_active": true},
      {"kind": "weekly_scoped", "group": "weekly",  "percent": 0,  "severity": "normal",
       "resets_at": "2026-10-01T03:00:00.123456+00:00",
       "scope": {"model": {"display_name": "Fable"}}, "is_active": false}
    ],
    "model_scoped": [{"display_name": "Fable", "utilization": 0,
                      "resets_at": "2026-10-01T03:00:00+00:00"}]
  },
  "behaviors": null
}
```

How the published typings `[D9]` describe these fields:

- `rate_limits_available` is false "when plan rate limits do not apply (API key, Bedrock, Vertex, or missing profile scope)". In that case `rate_limits` is `null`.
- Window `utilization` is "Percentage of the window used, 0-100". `resets_at` is an ISO 8601 timestamp or `null`.
- `model_scoped` means "Per-model weekly windows from the server limits[] array, filtered by the overage-included-models allowlist ... absent when nothing is known about them (an answer served from cached data ...)".
- `extra_usage` amounts are "in minor units of `currency` (cents for USD)". That wording comes from the sibling `SDKUsageReport` type in the same file.
- `limits` is **not declared** in the `get_usage` typing, but it was present in the live reply `[OBS]`. Claude Code appears to pass through the server body `[INFERRED]`. Parse it when present, and fall back to the legacy windows and `model_scoped` when it isn't.

For field-by-field parsing rules, see [Response schema reference](#response-schema-reference).

### Caveats

1. **Experimental.** The API "may change or be removed in any release without notice" `[D9]`. Pin parser tests to real captured replies, re-run them after each Claude Code auto-update, and keep the rest of the app working when this source breaks.

2. **No freshness flag.** The reply does not say whether the server was actually asked. According to `[INFERRED]` for 2.1.283:
   - Claude Code answers from its shared snapshot, without asking the server, if that snapshot is under 60 seconds old.
   - When the usage endpoint returns 429 or an error, it falls back to the last persisted snapshot, up to 1 hour old, and drops the `limits` key.
   - If there is no snapshot, `rate_limits` is `null`.

   The 1-minute sharing is documented: "non-interactive sessions on one machine now share a read made in the last minute instead of each calling the usage endpoint" (2.1.275) `[D8]`. See the [freshness classifier](#freshness-classifier) below.

3. **Side effects.** A poll is not read-only for the config directory:
   - Claude Code writes `cachedUsageUtilization` into `.claude.json` after a successful read, at most once per 60 s `[INFERRED]`.
   - If the access token is near expiry or expired, it refreshes it. That writes `.credentials.json` and lock files `[INFERRED]`.
   - Unless nonessential traffic is disabled, it also fetches feature flags and sends telemetry `[INFERRED][D3]`.

4. **Forced token rotation on a 401.** If the usage endpoint answers 401, Claude Code refreshes the token and retries once, even when the access token was not near expiry `[INFERRED]`. Each refresh rotates the refresh token (see the tokens doc). Guard against it with this tripwire: record the `.credentials.json` mtime and `expiresAt` before each poll. If the mtime changed during a poll while `expiresAt` was more than 5 minutes away, pause polling for at least 1 hour and show a warning.

5. **Use the same binary as the user.** Spawn the `claude` on `PATH`, never an older copy bundled with an SDK or IDE extension. 2.1.277 "Fixed being unexpectedly logged out when an older Claude Code build (for example an IDE extension's bundled CLI) runs on the same machine" `[D8]`.

6. **Startup cost.** Each poll starts a full Claude Code process, which takes a few seconds of CPU. One measurement of `claude -p /usage` was about 2.4 s on 2.1.220 `[T2]`. That is fine every few minutes, not every few seconds.

7. **Accounts that can't read usage.** A `claude setup-token` token "can only make model requests" `[D2]` and lacks the profile scope, so `rate_limits_available` comes back false `[D9][T1]`.

### Freshness classifier

Record `spawnTime` before spawning. After the reply arrives, read `cachedUsageUtilization.fetchedAtMs` from the same config directory's `.claude.json` (see [§3](#3-cachedusageutilization-in-claudejson-companion)), then classify:

| Condition | State | Show |
|---|---|---|
| `rate_limits_available` is false | Unavailable (login type) | "Usage not available for this login" |
| `rate_limits` is `null` | Unavailable (fetch failed, no snapshot) | Last-known value with its age, or "unknown" |
| `fetchedAtMs >= spawnTime - 60 s` | **Fresh** | Values, "updated just now" |
| `fetchedAtMs` older than that | **Stale** (Claude Code served an old snapshot) | Values grayed, "as of N min ago" |
| `rate_limits` present but no `cachedUsageUtilization` | Unknown freshness | Values with a "freshness unknown" marker |

Weaker supporting hints:

- `limits` missing from `rate_limits` suggests a cached answer `[INFERRED]`.
- `model_scoped` absent means "an answer served from cached data" per the typings `[D9]`, although it may still show up on some cached answers `[INFERRED]`.

Never use either hint alone.

### Scheduling

These are recommendations, not measured limits:

- **5 minutes** per account by default. Polling faster than 60 s is pointless, because Claude Code answers from its under-60-second snapshot without asking the server `[D8][INFERRED]`.
- **Back off** to 15, then 30, then 60 minutes after an unavailable or stale result, and reset after a fresh one.
- **"Refresh now"** is fine, but debounce it to at most once per 60 s.
- **One poll at a time** per config directory. Wait at least 60 s for a reply, because a token refresh can include lock waits and a 30-second token request `[INFERRED]`.
- **Stopping:** close stdin, then send SIGTERM. **Never SIGKILL.** A process killed mid-refresh can leave the refresh lock held. 2.1.282 fixed "requests failing for up to a minute ... after that other process was closed or killed mid-refresh" `[D8]`.
- **Pause** while the desktop is locked or idle. Nobody is looking at the tray then.
- **The rate-limit budget is shared.** It covers the user's own `/usage` and any IDE usage meter. Over-polling makes Claude Code's own `/usage` fall back to "last-known usage bars with an 'as of' note" (2.1.208) `[D8]`.

### Alternative worth testing: `/usage` as a stream-JSON message

The same typings describe a second payload, `usage_report` (`SDKUsageReport`). It rides on the synthetic assistant message that `/usage` produces. Its rate limits are "only ever the server's current reply", and its `limits` field is "Null too while the usage fetch is failing: ... neither the row the CLI builds from rate-limit response headers ... nor its snapshot of an earlier reply appears here" `[D9]`.

That would solve the freshness problem by construction. `/usage` is a local command, and `claude -p /usage` was measured at `total_cost_usd` 0 on 2.1.220 `[T2]`. **Not tested here.** Test it before v1 to see whether it is cleaner than `get_usage` plus the classifier.

---

## 2. Statusline `rate_limits` (not displayed)

**What it is.** Claude Code pipes a JSON object to the user's `statusLine` command on stdin. Since 2.1.80 `[D8]` that object includes:

```json
"rate_limits": {
  "five_hour": {"used_percentage": 23.5, "resets_at": 1738425600},
  "seven_day": {"used_percentage": 41.2, "resets_at": 1738857600}
}
```

- `used_percentage` runs from 0 to 100.
- `resets_at` is in **Unix epoch seconds** `[D1]`.
- Behind a Claude apps gateway, a `spend_limit` window is added (2.1.251+) `[D1]`. 2.1.284 added dollar fields to it `[D8]`.

**Limits, from the docs `[D1]`:**

- It "appears only for claude.ai Pro and Max subscribers ... and only after the first API response in the session."
- "Each window ... may be independently absent, and Claude Code drops a window once its `resets_at` time passes."

**When it updates `[D1]`:** the script runs again on a new assistant message, `/compact`, a permission-mode change, a vim-mode toggle, a change to the command, a `refreshInterval` timer, a rate-limit window reaching `resets_at`, or prompt-cache expiry.

`refreshInterval` only re-runs the script. The percentages come from Claude Code's in-memory rate-limit state, which is updated from model responses `[INFERRED]`, so re-running the script doesn't make them fresher. It is still unresolved whether that state can also be seeded from Claude Code's own usage reads `[UNVERIFIED]`.

**Why it is not displayed:**

- **Idle sessions go stale.** An idle session reports numbers as old as its last model response. Usage on claude.ai, in Desktop, on another machine or in another session does not show up until this session sends a message. Two open sessions can disagree.
- **No per-model data.** It carries no per-model (weekly scoped) rows and no extra-usage data `[D1]`.
- **It is intrusive.** Using it means wrapping the user's `statusLine` command in every config directory's `settings.json`, and users often already have one. The alternative is injecting a statusline with `--settings` into sessions the app itself launches. The public prior art [github.com/Servosity/ai-tabs](https://github.com/Servosity/ai-tabs) `[T11]` does that for the terminal tabs it hosts; it reads `rate_limits` from that stdin and never touches credentials or the usage endpoint.

**Possible later use** (not planned): as a *trigger*. "A session just got a response, so poll `get_usage` now." It would never be shown as a value.

A related feature request, #39874 (opened 2026-03-27), asked Claude Code to write rate-limit headers to a local file. It was not implemented. The GitHub Actions bot, not Anthropic staff, closed it as stale ("not planned") on 2026-04-29 `[G4]`.

---

## 3. `cachedUsageUtilization` in `.claude.json` (companion)

**Where it lives.**

- Default: `~/.claude.json` in the home directory, **not** inside `~/.claude/`.
- With `CLAUDE_CONFIG_DIR` set: `<dir>/.claude.json`.
- A legacy `~/.claude/.config.json` takes precedence if it exists `[INFERRED]`.

**Shape.** Written by Claude Code, undocumented `[INFERRED]`:

```json
"cachedUsageUtilization": {
  "fetchedAtMs": 1790620000000,
  "accountUuid": "<account id>",
  "utilization": { "...": "the raw usage body: five_hour, seven_day, limits[], extra_usage, ..." }
}
```

**When it is written `[INFERRED]`.** After a successful usage read by any Claude Code process: the `/usage` dialog, the Settings Usage tab, `claude -p /usage`, or `get_usage`. It is written at most once per 60 s, and only when the account matches.

Claude Code itself ignores snapshots older than 1 hour and deletes the key when the account doesn't match. Interactive sessions do **not** read the usage endpoint in the background. They read it only when someone asks `[INFERRED]`. Before the live test the key was absent on the test machine `[OBS]`, so no session had asked recently.

**How this app uses it:**

- As the freshness stamp for `get_usage` (see the [classifier](#freshness-classifier)).
- As a zero-network, last-known value to show, with its age, when a poll fails.
- Only if `accountUuid` matches the `oauthAccount.accountUuid` in the same file. Parse only these two keys.

**Rules:**

- Never write this file. Claude Code rewrites it constantly.
- Retry once on a JSON parse error, in case you caught a partial write.
- Never log the file. `oauthAccount` contains the email address.

---

## 4. Claude Desktop `plan-usage-history.json` (not used)

Observed on the test machine `[OBS]`, with the Claude Desktop Linux package 2.7032.0 installed:

- The file is `~/.config/Claude/plan-usage-history.json`.
- Its shape is `{"version": 2, "samples": [{"t": <ms epoch>, "org": "<org id>", "u": {"fh": <int>, "sd": <int>}}]}`.
- It held 63 samples spanning about a day, with a median spacing of 15 minutes. The newest sample was about seven weeks old, because Desktop had not been running.
- `fh` and `sd` read as integer five-hour and seven-day percentages. That reading of the key names is `[UNVERIFIED]`.

It is **not used** because it updates only while Desktop runs, holds whole-number percentages only, and has no per-model rows. It could be an opportunistic extra source later.

---

## 5. Direct `GET /api/oauth/usage` (off by default)

This is what the previous version of this app did, and what most community monitors do.

### Request

```http
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <claudeAiOauth.accessToken from .credentials.json>
anthropic-beta: oauth-2025-04-20
Content-Type: application/json
```

- These are the headers Claude Code 2.1.283 sends `[INFERRED]`. CodexBar's docs list the same endpoint and beta header `[T1]`.
- The token must have the `user:profile` scope: "CLI tokens with only `user:inference` cannot call usage" `[T1]`.
- The response body has the same schema as `get_usage`'s `rate_limits` (see the [schema reference](#response-schema-reference)).
- The live response has carried `limits[]` since about 2026-07-02, while the legacy `seven_day_opus` and `seven_day_sonnet` fields have been `null` since then (one PR calls them "permanently null") `[T9][T3][G6]`.

### The token problem

The access token lives about 8 hours `[OBS]`. Claude Code refreshes it only while Claude Code is in use. This app **never** refreshes it; see [claude-oauth-tokens.md](claude-oauth-tokens.md). So after about 8 hours with no Claude Code activity, this route goes dark.

`get_usage` doesn't have this problem, because the spawned `claude` refreshes safely itself.

### Rate limiting: the evidence conflicts

Anthropic has never documented a limit for this endpoint. Community reports:

| Report | Date | Finding |
|---|---|---|
| #30930 `[G1]` | opened 2026-03-05, still open | Persistent HTTP 429 for Max users, with `retry-after: 0` and body `{"error":{"type":"rate_limit_error","message":"Rate limited. Please try again later."}}` |
| #31637 `[G2]` | opened 2026-03-06; bot-closed for inactivity 2026-06-01 | "aggressively rate limits." One commenter estimated about 5 requests per access token (a single anecdote). Another saw 429s at 10-minute polling within an hour. |
| claude-hud #173 `[T2]` | 2026-03-06 | The User-Agent picks the bucket: a custom UA always got 429, `claude-code/2.1` got 200. |
| Haletran PR #34 `[T4]` | 2026-07-05 | Without a Claude-looking UA: `retry-after` up to about 1600 s. |
| VibeCodingTracker `[T6]` | 2026-07-06 | With a `claude-cli/<ver> (external, cli)` UA: "expect 429 if polled faster than ~60s". |
| Diplomat #57 `[T5]` | 2026-08-19 | Without a Claude UA: one success about every 2 minutes; 19 of 20 burst requests got 429 with `Retry-After: 0`. |
| hass-claude-usage `[T8]` | undated | A burst caused a lockout lasting about a day that also blanked usage in Claude Code and on claude.ai `[UNVERIFIED]`. |

**Open question:** is the budget per access token, per account, per IP or per User-Agent? The reports disagree `[G2][T5]`.

Claude Code's own client treats both an HTTP 429 and a 200 carrying an in-band `rate_limit_error` body as rate-limited `[INFERRED]`. It shows last-known bars with an "as of" note (2.1.208), shares reads across processes (2.1.275), and backs off after a 429 or a rejected login (2.1.284) `[D8]`.

### User-Agent impersonation

- Claude Code sends `User-Agent: claude-cli/<version> (external, cli)` to this endpoint `[INFERRED]`.
- Many community tools send `claude-code/<version>`, and this app's earlier releases did too, with a version string that was never updated.
- Both strings impersonate the official client. In January 2026, Anthropic said it had "tightened our safeguards against spoofing the Claude Code harness" `[N1]`.

**This app will not spoof.** If direct mode is ever added, it sends an honest UA (for example `ai-usage-monitor/<version>`). That may land it in the strict bucket, which is one more reason this route is not the default.

### If direct mode is ever enabled (opt-in only)

- Use the token only while `expiresAt` is at least 60 s in the future, the stored `accessToken` is non-empty, and `user:profile` is in `scopes`.
- **Never** call the token endpoint.
- Poll at most every 5 minutes; 15 minutes is better.
- Make one attempt per tick and never retry a 429. Back off exponentially up to hours.
- Treat a 200 whose body is `{"error":{"type":"rate_limit_error",...}}` as a 429.
- On a 401, stop and wait until `.credentials.json` changes.
- Show last-known data with its age.

---

## 6. claude.ai web route with `sessionKey` (removed)

How it works `[T10][T1]`:

1. `GET https://claude.ai/api/organizations` with a `Cookie: sessionKey=<cookie value>` header.
2. Pick the organization whose `capabilities` include `"chat"`. An API-only organization returns `permission_error` `[T10]`.
3. `GET https://claude.ai/api/organizations/{org}/usage` returns the same schema.

Problems:

- **Cloudflare.** Plain HTTP clients "intermittently get a Cloudflare 403 'Just a moment...'" `[T3]`. CodexBar treats a challenge as "a network-path restriction, not a stale-cookie signal" `[T1]`. The previous app reported such 403s as "Session expired", and it picked the first organization rather than the chat-capable one.
- **Policy.** The legal page says: "developers may not collect, store, or intermediate Claude.ai credentials or session tokens — sign-in to a Claude account must complete through Anthropic's own flow" `[D6]`. A "paste your sessionKey" dialog that saves the cookie in a keyring is exactly that.

**Decision:** the previous app's "Paste session key..." feature is being removed. Users without Claude Code should install Claude Code and log in through Anthropic's own flow.

---

## Other routes considered and rejected

| Route | Why rejected |
|---|---|
| 1-token `/v1/messages` probe to read `anthropic-ratelimit-unified-*` headers | Spends inference on subscription credentials outside Claude Code. Since 2026-04-04, third-party harnesses no longer draw on subscription limits and need extra usage or an API key `[N3]`. |
| Local JSONL token counting (e.g. ccusage `[T12]`) | Estimates tokens and cost, not the server's plan percentages. Blind to web and Desktop usage. |
| Scraping the interactive `/usage` screen through a PTY (one of CodexBar's sources `[T1]`) | Fragile: the text UI changes between releases. `get_usage` gives the same data structured. |
| Usage & Cost Admin API | Covers Console API organizations only and is "unavailable for individual accounts" `[D10]`. |
| SDK rate-limit events (`SDKRateLimitEvent`, 2.1.45 `[D8]`) | Emitted only during inference. Useful only if the app hosted the Claude sessions itself. |

---

## Response schema reference

These rules apply to `get_usage`'s `rate_limits`, the direct OAuth route and the web route.

### `limits[]` (preferred)

Each row is `{kind, group, percent, severity, resets_at, scope, is_active}` `[D9][OBS]`.

| Field | Meaning |
|---|---|
| `kind` | `session`, `weekly_all` or `weekly_scoped`. "Classify a row on this, never on a label" `[D9]`. |
| `group` | `session` or `weekly`. Rows "render grouped under it, in the server's order" `[D9]`. |
| `percent` | 0-100. Clamp for display: values above 100 are possible. |
| `severity` | For example `normal`, `warning` or `critical`. The typings describe it as the server's own grading of the row for the meter color, so a client should never grade a row itself `[D9]`. Use it for tray colors, with our own gradient only as a fallback. |
| `resets_at` | ISO 8601 string or `null`. A 2026-08-17 sample shows rows without it `[G6]`. Backfill from the legacy window, or show "reset time unknown". |
| `scope` | `null`, or `{model: {display_name}}` and/or `{surface: {display_name}}`. Name weekly-scoped rows by `scope.model.display_name` ("Fable" as of 2026-09) `[OBS][T9]`. |
| `is_active` | "The server's headline pick: the row a single-value indicator shows" `[D9]`. Use it to choose the tray icon's number. |

### Legacy windows (fallback)

- `five_hour` and `seven_day` are `{utilization: 0-100 | null, resets_at: ISO | null}`. They were still populated on 2026-09-28 `[OBS]`.
- `seven_day_opus` and `seven_day_sonnet` have been `null` since about July 2026 `[T9]`.
- `extra_usage` holds money in minor units, so cents for USD `[D9]`.
- Ignore every other key; there are many, and most are code-named and null `[OBS]`.

### Units by source

| Source | Percent | Reset time |
|---|---|---|
| `get_usage`, direct OAuth, web route | 0-100 (`utilization`, `percent`) | ISO 8601 with microseconds and `+00:00` |
| Statusline | 0-100 (`used_percentage`) | Unix epoch **seconds** |
| Response headers, SDK rate-limit events | 0-1 fraction, can exceed 1 `[INFERRED]` | epoch seconds |

### Parser rules

- `null` is not 0%. Show "unknown", never a green "0%".
- Tolerate missing fields and unknown extra keys.
- Normalize all times to UTC epoch milliseconds internally.
- Keep the raw reply, minus any identifying fields, as a test fixture whenever the parser meets a new shape.

---

## Multiple accounts and `CLAUDE_CONFIG_DIR` (for later)

- **The mechanism is official.** `CLAUDE_CONFIG_DIR` is "Useful for running multiple accounts side by side: for example, `alias claude-work='CLAUDE_CONFIG_DIR=~/.claude-work claude'`" `[D3]`. It moves settings, history, plugins, `.credentials.json` `[D2]` and `.claude.json` `[INFERRED]` into that directory. Project and local settings cannot set it `[D3]`.
- **Default layout is split:** credentials live in `~/.claude/.credentials.json`, but account metadata and the usage snapshot live in `~/.claude.json` `[INFERRED]`.
- **Polling another account:** spawn `claude` with `CLAUDE_CONFIG_DIR=<dir>` in its environment, then read `<dir>/.claude.json` for the freshness stamp.
- **Labeling:** `claude auth status` prints JSON by default `[INFERRED]`. It includes `configDirectory` since 2.1.268 `[D8]`, plus the email, organization and `subscriptionType` `[INFERRED]`. Prefer a user-chosen nickname, and never log the email.
- **Independent logins.** Each directory needs its own login and gets its own token family, even for the same account `[G5]`.
- **Discovery.** Arbitrary directories can't be discovered reliably. Let the user add them, and suggest `~/.claude` and `~/.claude-*` if present.
- **macOS.** The Keychain entry is keyed per directory `[D2]`. See the tokens doc.

---

## Policy background

- **Consumer Terms** (effective 2025-10-08) bar accessing the services "through automated or non-human means, whether through a bot, script, or otherwise", except via an API key or "where we otherwise explicitly permit it" `[D7]`.
- **Claude Code legal page:** OAuth "is designed to support ordinary use of Claude Code and other native Anthropic applications". Developers "may not collect, store, or intermediate Claude.ai credentials or session tokens". The page "does not ... prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription" `[D6]`.
- **Timeline:**
  - 2026-01-09: blocks on spoofing the Claude Code harness `[N1]`.
  - 2026-02-19/20: a docs change, with mixed staff messaging `[N2]`.
  - 2026-04-04: third-party harnesses no longer draw on subscription limits `[N3]`.
- **No Anthropic statement specifically about read-only usage monitors was found** `[UNVERIFIED either way]`. This app's position is to stay on the unmodified-binary path, send no credentials of its own, and never spoof. The one real dependency is that `get_usage` is labeled experimental.

---

## Open questions

1. Does `/usage` sent over stream-JSON (`usage_report`) give a cleaner freshness guarantee than `get_usage`? It is untested.
2. Does `--safe-mode` plus `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` keep the per-model rows intact?
3. How often does the usage endpoint answer 401 for a valid token? That event triggers a forced rotation inside Claude Code.
4. Is the endpoint's rate-limit budget per token, per account or per IP?
5. What does the `get_usage` error envelope look like?

---

## Sources

Every source was read on 2026-09-28 unless another date is given.

**Official documentation and Anthropic sources**

- **[D1]** Claude Code docs, "Customize your status line": https://code.claude.com/docs/en/statusline
- **[D2]** Claude Code docs, "Authentication", including "Credential management" and "Generate a long-lived token": https://code.claude.com/docs/en/authentication
- **[D3]** Claude Code docs, "Environment variables" (`CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_SIMPLE`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, `DISABLE_AUTOUPDATER`, `ENABLE_CLAUDEAI_MCP_SERVERS`): https://code.claude.com/docs/en/env-vars
- **[D4]** Claude Code docs, "CLI reference": https://code.claude.com/docs/en/cli-reference
- **[D5]** Claude Code docs, "Run Claude Code programmatically": https://code.claude.com/docs/en/headless
- **[D6]** Claude Code docs, "Legal and compliance": https://code.claude.com/docs/en/legal-and-compliance
- **[D7]** Anthropic Consumer Terms (effective 2025-10-08): https://www.anthropic.com/legal/consumer-terms
- **[D8]** Claude Code CHANGELOG (entries 2.1.45, 2.1.80, 2.1.208, 2.1.251, 2.1.268, 2.1.275, 2.1.277, 2.1.282, 2.1.283, 2.1.284): https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
- **[D9]** `@anthropic-ai/claude-agent-sdk` 0.3.284, published typings `sdk.d.ts` (`SDKControlGetUsageRequest`, `SDKControlGetUsageResponse`, `SDKUsageReport`, `usage_EXPERIMENTAL_MAY_CHANGE_DO_NOT_RELY_ON_THIS_API_YET`): https://unpkg.com/@anthropic-ai/claude-agent-sdk@0.3.284/sdk.d.ts
- **[D10]** Claude Platform docs, "Usage and Cost API": https://platform.claude.com/docs/en/manage-claude/usage-cost-api

**anthropics/claude-code issues**

- **[G1]** #30930, "/api/oauth/usage endpoint returns persistent 429 for Claude Max users (retry-after: 0)", opened 2026-03-05, open: https://github.com/anthropics/claude-code/issues/30930
- **[G2]** #31637, "/api/oauth/usage endpoint aggressively rate limits, making usage monitoring unusable", opened 2026-03-06, closed 2026-06-01: https://github.com/anthropics/claude-code/issues/31637
- **[G4]** #39874, "Feature request: write rate-limit headers to ~/.claude/rate-limits.json", opened 2026-03-27, bot-closed as stale ("not planned") 2026-04-29: https://github.com/anthropics/claude-code/issues/39874
- **[G5]** #64336, "Multiple profile directories ... require independent re-logins despite sharing the same account", 2026-05-31: https://github.com/anthropics/claude-code/issues/64336
- **[G6]** #87419, contains a raw usage payload from 2026-08-17: https://github.com/anthropics/claude-code/issues/87419

**Third-party projects**

- **[T1]** steipete/CodexBar (MIT), `docs/claude.md`: https://github.com/steipete/CodexBar/blob/main/docs/claude.md
- **[T2]** jarrodwatts/claude-hud: issue #173 (2026-03-06, User-Agent buckets) https://github.com/jarrodwatts/claude-hud/issues/173 and PR #720 (2026-08-20, `claude -p /usage` measured at `total_cost_usd` 0 on 2.1.220) https://github.com/jarrodwatts/claude-hud/pull/720
- **[T3]** hamed-elfayome/Claude-Usage-Tracker PR #271 (2026-07-10; `limits[]` format, Cloudflare 403s): https://github.com/hamed-elfayome/Claude-Usage-Tracker/pull/271
- **[T4]** Haletran/claude-usage-extension PR #34 (2026-07-05): https://github.com/Haletran/claude-usage-extension/pull/34
- **[T5]** latekvo/Diplomat issue #57 (2026-08-19): https://github.com/latekvo/Diplomat/issues/57
- **[T6]** Mai0313/VibeCodingTracker commit d2d353a (2026-07-06): https://github.com/Mai0313/VibeCodingTracker/commit/d2d353a47dc3f30407a8139e9d88df12bdd22451
- **[T8]** trickv/hass-claude-usage README, "Rate Limit" section: https://github.com/trickv/hass-claude-usage
- **[T9]** can1357/oh-my-pi PR #4344 ("As of 2026-07-02 ... ships a generic limits[] array"): https://github.com/can1357/oh-my-pi/pull/4344
- **[T10]** dineshkruplani/Claude-Usage-Badge-Extension, `docs/PHASE1-FINDINGS.md` (web route, organization selection, sample from 2026-06-02): https://github.com/dineshkruplani/Claude-Usage-Badge-Extension/blob/main/docs/PHASE1-FINDINGS.md
- **[T11]** Servosity/ai-tabs (public; reads statusline `rate_limits` for the tabs it hosts): https://github.com/Servosity/ai-tabs
- **[T12]** ryoppippi/ccusage: https://github.com/ryoppippi/ccusage

**News coverage**

- **[N1]** VentureBeat, "Anthropic cracks down on unauthorized Claude usage by third-party harnesses", 2026-01-09: https://venturebeat.com/technology/anthropic-cracks-down-on-unauthorized-claude-usage-by-third-party-harnesses
- **[N2]** The Register, "Anthropic clarifies ban on third-party tool access to Claude", 2026-02-20: https://www.theregister.com/software/2026/02/20/anthropic-clarifies-ban-on-third-party-tool-access-to-claude/5014546
- **[N3]** TechCrunch, 2026-04-04: https://techcrunch.com/2026/04/04/anthropic-says-claude-code-subscribers-will-need-to-pay-extra-for-openclaw-support/
