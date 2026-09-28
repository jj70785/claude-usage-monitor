# Existing usage monitors

**TLDR:** Plenty of open-source tools already show AI plan usage, and most of them get their numbers by taking a CLI's login token and calling an undocumented usage endpoint, or by having the user paste a browser cookie. The few that stay inside first-party surfaces (`codex app-server`, `agy -p /usage`, Claude Code's own `/usage` and statusline JSON) are the ones this project learns from; it uses the first-party CLI routes and does not display statusline numbers. CodexBar is the most complete tool and now runs on Linux, but some of its providers use exactly the access patterns that Google's terms forbid.

- Research date: **2026-09-28**. All links were accessed that day unless another date is given.
- Stars, versions and licenses drift quickly. Re-check before you quote a number.
- For why some data sources are riskier than others, see [terms-and-policy.md](terms-and-policy.md).

## How to read this doc

### Data-source categories

Every tool below is tagged with one or more of these categories. They are listed from lowest to highest risk.

| Category | What it means |
| --- | --- |
| **First-party CLI** | Runs the provider's own, unmodified binary and reads its structured output. Examples: `codex app-server`, `agy -p /usage --output-format json`, `claude -p /usage`. |
| **Statusline stdin** | Reads the JSON that Claude Code pipes to a user-configured `statusLine` command. |
| **Local logs** | Parses session or transcript files that a CLI already writes to disk. These are mostly token counts; Codex rollout files also carry rate-limit snapshots. |
| **Borrowed token** | Reads a CLI's OAuth token from disk or the keychain, then calls a usage endpoint directly. Examples: `api.anthropic.com/api/oauth/usage`, `chatgpt.com/backend-api/wham/usage`, Google's `cloudcode-pa`. |
| **Browser cookie** | Uses a claude.ai `sessionKey` cookie (pasted by the user or captured by an in-app sign-in) against the claude.ai web API. |
| **Inference probe** | Sends a tiny model request only to read the rate-limit headers on the response. |

### Verification labels

| Label | Meaning |
| --- | --- |
| **Verified** | README or GitHub metadata checked on 2026-09-28 while writing this doc. |
| **Research** | Reported by this project's research pass on 2026-09-28 (README or GitHub API), not re-opened while writing. |
| **Unverified** | Came from a single source or a search snippet, or was not checked at all. |

## At a glance

| Tool | Providers | Platforms | Data source | License | Label |
| --- | --- | --- | --- | --- | --- |
| [CodexBar](#codexbar) | 87 providers, including Claude, Codex, Gemini, Antigravity | macOS app; Linux Qt 6 app plus CLI | Mixed: borrowed token, first-party CLI, cookies (cookie import is macOS only) | MIT | Verified |
| [Claude-Usage-Tracker](#claude-usage-tracker) | Claude | macOS 14+ | Browser cookie, borrowed token, per-profile launchers | MIT | Verified |
| [Usage4Claude](#usage4claude) | Claude, Codex | macOS 13+ | Browser cookie or in-app browser OAuth; Codex via OpenAI API | MIT | Verified |
| [ClaudeBar](#claudebar) | 20+ | macOS 15+ | Provider CLIs and APIs | MIT | Verified |
| [ccusage](#ccusage) | Claude Code, Codex, Gemini CLI, Antigravity, many more | Cross-platform (Node) | Local logs (tokens and cost) | MIT | Verified |
| [Claude-Code-Usage-Monitor](#claude-code-usage-monitor) | Claude | Cross-platform (Python) | Local logs plus estimated limits | MIT | Research |
| [claude-hud](#claude-hud) | Claude | macOS, Linux, Windows (Node or Bun) | Statusline stdin only | MIT | Verified |
| [Servosity/ai-tabs](#servosityai-tabs-prior-art) | Claude (usage), Codex (tokens) | Windows, macOS, Linux (Electron) | Statusline stdin; local logs | MIT | Verified |
| [KDE, GNOME, Waybar, tray widgets](#linux-desktop-widgets) | Varies | Linux | Mostly borrowed token | Mostly MIT | Mixed |
| [codex-quota-linux](#codex-quota-linux) | Codex | Linux (AppIndicator tray) | Not read-only: switches accounts and sends requests | MIT | Verified (see status note) |

Nothing XFCE-specific turned up in the 2026-09-28 search (Research). The XFCE options, a genmon panel item or a StatusNotifier tray icon, are covered in [linux-xfce-desktop.md](linux-xfce-desktop.md).

## Cross-platform, multi-provider

### CodexBar

[steipete/CodexBar](https://github.com/steipete/CodexBar): MIT, Swift, about 22,000 stars, v0.68.0 released 2026-09-27 (Research, GitHub API).

- **Platforms.** The main app is a macOS menu-bar app. Linux gets a separate "Qt 6 desktop app" (C++/QML) plus the Swift `codexbar` CLI, which ships as glibc and musl tarballs, on the AUR as `codexbar-cli`, and via Homebrew.
  - The [Linux README](https://github.com/steipete/CodexBar/blob/main/Integrations/Linux/README.md) (Verified) requires "glibc 2.39+ and Qt 6.4+" and says "Ubuntu 24.04 and Debian 13 meet these floors."
  - It also says "The Swift `codexbar` CLI owns provider fetching and authentication" and "There is no desktop auto-updater or distro repository package yet."
- **Machine-readable output.** `codexbar usage --format json` and `codexbar serve` (GET `/usage` on 127.0.0.1:8080) ([docs/cli.md](https://github.com/steipete/CodexBar/blob/main/docs/cli.md), Research). Four KDE plasmoids and at least one Waybar module are thin wrappers around this CLI.
- **Claude.** Borrowed OAuth token, web cookies, or a PTY scrape of the interactive `/usage` screen, plus the Admin API for API spend ([docs/claude.md](https://github.com/steipete/CodexBar/blob/main/docs/claude.md), Research).
  - Multiple accounts are supported through `tokenAccounts`, a `cswap` adapter, and a comma-separated `CLAUDE_CONFIG_DIR`.
  - The docs describe a compact layout for four or more accounts: an active card plus one-line rows sorted by remaining headroom.
- **Codex.** On macOS the order is the OAuth `/wham/usage` endpoint first, then the `codex app-server` RPC. The Linux desktop app delegates to the CLI, whose `--source auto` order for Codex is the web dashboard, then CLI RPC. Browser-cookie import works only on macOS, so on Linux the Codex numbers most likely come through `codex app-server` (Research; this is an inference from the docs).
- **Gemini and Antigravity.** The Gemini provider calls Google's `retrieveUserQuota` directly and refreshes Google tokens itself using the gemini-cli OAuth client ([docs/gemini.md](https://github.com/steipete/CodexBar/blob/main/docs/gemini.md), Research). For Antigravity, the primary path launches `agy` and talks to its local language server; on agy 1.2.2 and later it falls back to `agy -p /usage --output-format json`, and there is also an OAuth fallback ([docs/antigravity.md](https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md), Research).

**What we learn:**

- **The architecture works.** One CLI owns fetching and emits JSON, and small UI front ends render it. The KDE and Waybar wrappers prove that split.
- **Credential hygiene.** Its Codex docs state that "CodexBar never publishes refreshed native tokens into auth.json" ([docs/codex.md](https://github.com/steipete/CodexBar/blob/main/docs/codex.md), Research).
- **Scraping the TUI is a last resort.** CodexBar treats a PTY scrape of Codex's `/status` as a "Manual/debug parser only", because the bare `codex` TUI "can start interactive auth and open browser tabs" (docs/codex.md, Research).
- **Adopting CodexBar also adopts its risks.** Its Gemini provider and its Antigravity OAuth fallback call Google's backend directly with borrowed credentials. Google's terms explicitly forbid that pattern (see [terms-and-policy.md](terms-and-policy.md#google-gemini-cli-and-antigravity)). Using CodexBar as a backend is only as safe as the sources you allow it to use.
- **Window labels must come from the provider.** CodexBar's Antigravity parser reads group and bucket names and window strings from `agy`'s output. Its test fixture is labeled synthetic (Research).

## macOS menu-bar apps (Claude-focused)

These do not run on Linux, but they have hit most of the Claude-specific problems first.

### Claude-Usage-Tracker

[hamed-elfayome/Claude-Usage-Tracker](https://github.com/hamed-elfayome/Claude-Usage-Tracker): MIT, Swift/SwiftUI, macOS 14+ (Verified).

- **Data sources (Verified).**
  - A claude.ai sessionKey, via in-app browser sign-in or manual extraction, used against `GET https://claude.ai/api/organizations/{org_id}/usage`.
  - Claude Code OAuth, detected automatically.
  - API Console credentials for cost data.
- **Multiple accounts.** "Unlimited profiles" with "isolated credentials and settings per account", plus per-profile terminal launchers that set an isolated `CLAUDE_CONFIG_DIR` (Verified; per the research, the launchers arrived in v3.3.0 on 2026-08-29).
- **[PR #271](https://github.com/hamed-elfayome/Claude-Usage-Tracker/pull/271)** (2026-07-10), Research:
  - Plain URLSession requests to claude.ai intermittently get a Cloudflare 403 "Just a moment...".
  - Per-model weekly limits now arrive in a `limits[]` array (`weekly_scoped`, currently named "Fable"), while the older per-model fields are null.
  - The PR adds a "CLI OAuth usage probe" that "parses the unified rate-limit headers from 429 responses". That is an inference probe.
- **[Release v3.2.0](https://github.com/hamed-elfayome/Claude-Usage-Tracker/releases/tag/v3.2.0)** (2026-07-12) fixed the app redeeming Claude Code's refresh token, which logged Claude Code out (Research).

**What we learn:** One `CLAUDE_CONFIG_DIR` per account is the right multi-account model. The cookie route fights Cloudflare. Refreshing a borrowed token breaks the CLI that owns it. The v3.2.0 fix and this project's own history (see [claude-oauth-tokens.md](claude-oauth-tokens.md)) are two independent examples.

### Usage4Claude

[f-is-h/Usage4Claude](https://github.com/f-is-h/Usage4Claude): MIT, Swift/SwiftUI, macOS 13+ (Verified).

- **Data sources.** Claude via "Session Key or OAuth browser login"; Codex "through OpenAI's API". It supports several Claude accounts and orgs plus separate Codex accounts, and stores credentials in the Keychain (Verified).

**What we learn:** Users do want several accounts per provider. Collecting and storing a claude.ai session key, however, is the pattern that Anthropic's legal page says developers "may not" follow. This project deliberately does not offer it (see [terms-and-policy.md](terms-and-policy.md)).

### ClaudeBar

[tddworks/ClaudeBar](https://github.com/tddworks/ClaudeBar): MIT, Swift, macOS 15+ (Verified).

- It "retrieves quota information by running provider-specific CLIs and APIs" for 20+ providers (Verified, summarized from the README).
- Name collision: a different repo, `andresreibel/ClaudeBar`, now redirects to `andresreibel/AIBar`, whose license GitHub reports as NOASSERTION (Research).

## Local-log counters

### ccusage

[ryoppippi/ccusage](https://github.com/ryoppippi/ccusage): MIT per the README footer (Verified). The research pass saw GitHub report the license as "Other", so check the LICENSE file before copying code.

- It analyzes "local usage data from coding agent CLIs". For Claude Code that means the JSONL transcripts under `~/.claude/projects` (Research).
- It reports tokens and estimated cost, with a "5-Hour Blocks Report" (`ccusage blocks`) (Verified).
- It now covers Codex (`ccusage codex daily`), Gemini CLI, Antigravity and many others (Verified).
- It shows no server-side plan percentage (Verified: not mentioned in the README).

### Claude-Code-Usage-Monitor

[Maciek-roboblog/Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor): Python, MIT (Research).

- It counts tokens from the JSONL transcripts and estimates limits with a P90 heuristic (Research).
- [Issue #202](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/202) (2026-04-11) proposes adding the OAuth usage endpoint and recommends polling it no faster than every 180 seconds (Research).

**What we learn from both:** Local logs measure your own token burn. They cannot tell you the plan percentage, because plan limits live on the server and also count usage from the web app, the mobile and desktop apps, and other machines. Estimated limits are not real limits. This project may later use local logs for token charts, but never as the source of plan percentages.

## Statusline-based

### claude-hud

[jarrodwatts/claude-hud](https://github.com/jarrodwatts/claude-hud): MIT, a Claude Code statusline plugin that needs Node.js 18+ or Bun. About 26,000 stars (Research).

- README (Verified): "Usage display is **enabled by default** when Claude Code provides subscriber `rate_limits` data on stdin."
- README (Verified): "ClaudeHUD is local-only by design. It does not make network requests, scrape credentials, or call undocumented Claude APIs."
- It can write the stdin `rate_limits` to a local snapshot for other tools (`display.externalUsageWritePath`) and read one back (`display.externalUsagePath`) (Verified).
- [Issue #173](https://github.com/jarrodwatts/claude-hud/issues/173) (2026-03-06, from the era when it still polled directly) traced constant HTTP 429s from the usage endpoint to its User-Agent (Research).
- [PR #720](https://github.com/jarrodwatts/claude-hud/pull/720) (open, created 2026-08-20) would read the usage snapshot Claude Code caches in `~/.claude.json` and optionally spawn `claude -p /usage`. A reviewer measured that spawn at `total_cost_usd` 0 and about 2.4 s on Claude Code 2.1.220 (Research; not re-measured on current versions).

### Servosity/ai-tabs (prior art)

[Servosity/ai-tabs](https://github.com/Servosity/ai-tabs): MIT. Its README calls it an "Electron-based tab manager for AI coding-agent terminals" for Windows, macOS and Linux (Verified).

- **Claude.** It wires a `statusLine` command into the Claude sessions it launches. That command forwards Claude Code's statusline JSON to the app's local server, as documented in its README (Verified).
  - It reads `rate_limits.five_hour` and `rate_limits.seven_day` (`used_percentage` 0-100, `resets_at` in epoch seconds) and shows them as small "5h" / "7d" percentage pills ([lib/statusline/rate-limits.js](https://github.com/Servosity/ai-tabs/blob/master/lib/statusline/rate-limits.js), Research).
  - It never reads credentials and never calls a usage endpoint (Research).
- **Codex.** It reads token counts from Codex rollout files but not their rate-limit fields (Research).
- **Gemini.** No usage support (Research).

**What we learn:** The statusline route needs no credentials and no network. But the data is only as fresh as the last model response in that session (see the next section), and when a payload has no `rate_limits`, the pills simply vanish.

### Why statusline data is not enough

- **When the field exists.** Claude Code's [statusline docs](https://code.claude.com/docs/en/statusline) say `rate_limits` appears only for Pro and Max subscribers (or behind a Claude apps gateway), only after the first API response in a session, and that Claude Code "drops a window once its resets_at time passes."
- **When it updates.** It updates when that session gets a model response. The maintainer observed on 2026-09-28 that an open but idle session keeps showing the numbers from its last message.
- **What that means in practice.** After 3 idle days, the 5-hour window is gone. The 7-day figure is 3 days old and misses everything used since then on claude.ai, the desktop and mobile apps, other sessions and other machines.
- **Project decision (2026-09-28).** This app does **not** display statusline-derived numbers as current usage. Claude sources are covered in [claude-usage-sources.md](claude-usage-sources.md).
- **Gotcha if a statusline wrapper is ever added.** A user can configure only one `statusLine` command per config dir, so a wrapper has to call the user's existing statusline command and pass its output through. Otherwise the user's own statusline goes blank.

## Linux desktop widgets

None of these target XFCE. Most read the Claude Code token from `~/.claude/.credentials.json` and call `api.anthropic.com/api/oauth/usage` (borrowed token). Licenses marked MIT were confirmed through the GitHub API by the research pass unless noted.

### KDE Plasma

| Project | Data source | License | Notes |
| --- | --- | --- | --- |
| [p3kj/plasma-applet-claudemeter](https://github.com/p3kj/plasma-applet-claudemeter) | Borrowed token (reads `~/.claude/.credentials.json`) | Not checked | Plasma 6. "One widget per config folder" is unverified. |
| [burakgon/ai-usage-kde-widget](https://github.com/burakgon/ai-usage-kde-widget) | Borrowed token | MIT | A Python stdlib helper writes one JSON snapshot; the plasmoid only renders it. |
| [AltairInglorious/brainusage](https://github.com/AltairInglorious/brainusage) | Not checked | MIT | GNOME 45-49 and KDE Plasma 5/6. |
| codexbar-kde ([example](https://github.com/adrianorocha-dev/codexbar-kde)), codexbar-plasmoid, codexbar-plasma, CodexBar-KDE | Wraps the `codexbar` CLI | Not checked | Four separate projects (Research). |
| [izll/plasma-claude-usage](https://github.com/izll/plasma-claude-usage) | Borrowed token | Not checked | Says the endpoint allows about 4 requests per 5 minutes (undated, unverified). |
| [MrSchrodingers/claude-usage-widget](https://github.com/MrSchrodingers/claude-usage-widget) | Browser cookie | Not checked | KDE/Tauri. Unverified. |

### GNOME Shell

| Project | Data source | License | Notes |
| --- | --- | --- | --- |
| [dvdstelt/ClaudeCodeUsage](https://github.com/dvdstelt/ClaudeCodeUsage) | Borrowed token; also an in-app claude.ai sign-in | Not checked | The in-app sign-in is the pattern the legal page prohibits. |
| [didmar/agents-usage-indicator](https://github.com/didmar/agents-usage-indicator) | Borrowed tokens for Claude, Codex and Gemini | MIT | Calls each provider's remote API using local auth files. |
| [HansRobo/coding-agent-rate-limit-indicator](https://github.com/HansRobo/coding-agent-rate-limit-indicator) | Mixed; runs its own Antigravity OAuth login | MIT | GNOME 45+; Claude, Codex, Antigravity, GLM. |
| [MostafaAlyy/ai-agent-usage](https://github.com/MostafaAlyy/ai-agent-usage) | **First-party CLI** for Codex (`codex -s read-only -a untrusted app-server`) | MIT | A collector writes `~/.local/state/agent-usage/usage.json` and the UI only renders it. Good reference design. |
| DarkPhilosophy/claude-codex-usage-monitor, FranciscoKnebel/gnome-provider-limits | Not checked | Not checked | Listed by the research pass only. |
| [dilbery/CC_Usage](https://github.com/dilbery/CC_Usage) | Borrowed token | Not checked | GNOME AppIndicator. Unverified. |

### Waybar

| Project | Data source | License | Notes |
| --- | --- | --- | --- |
| [NihilDigit/waybar-ai-usage](https://github.com/NihilDigit/waybar-ai-usage) | Not checked | MIT | About 55 stars. |
| [komagata/ai-quota-waybar](https://github.com/komagata/ai-quota-waybar) | **First-party CLI** for Codex (app-server `initialize` + `account/rateLimits/read`) | MIT | For Gemini it counts today's session files. |
| [rodrigo-sntg/omarchy-ai-usage](https://github.com/rodrigo-sntg/omarchy-ai-usage) | Mixed; Gemini via the Cloud quota API using `oauth_creds.json` | MIT | Claude, Codex, Gemini, Antigravity. The Gemini path is the direct access Google forbids. |
| [benwyrosdick/openusage-waybar](https://github.com/benwyrosdick/openusage-waybar) | Not checked | MIT | README calls it a Linux-only fork of [robinebers/openusage](https://github.com/robinebers/openusage) (MIT, about 4,300 stars). |
| [mryll/codexbar](https://github.com/mryll/codexbar), [Marouan-chak/codexbar-waybar](https://github.com/Marouan-chak/codexbar-waybar) | Bash; the latter wraps the `codexbar` CLI | MIT / not checked | |
| [thrawny/quotabar](https://github.com/thrawny/quotabar) | Not checked | MIT | Rust. |
| [gelzinn/ai-status](https://github.com/gelzinn/ai-status) | Antigravity via `agy` in a PTY | MIT | TypeScript. |
| [merely04/ai-gauge](https://github.com/merely04/ai-gauge) | Falls back to Codex rollout JSONL | MIT | |
| LeonardoGodoy/ai-usagebar | Not checked | Not checked | |
| Janicklin/claude-usage-waybar, marcelomogami/claude-usage | Borrowed token | Not checked | Unverified. |
| linsomniac/claude-usage-waybar | Not checked | **No license** | Do not copy code. |
| melleq/waybar-claude-usage | Reads claude-hud's cache | Not checked | Unverified. |

### Standalone tray apps

| Project | Data source | License | Notes |
| --- | --- | --- | --- |
| [achton/claude-monitor-linux](https://github.com/achton/claude-monitor-linux) | Borrowed token | Not checked | Go tray plus CLI with Waybar/tmux output; single account (Research). |
| [Kabilan108/claude-bar](https://github.com/Kabilan108/claude-bar) | Borrowed token | Not checked | Rust StatusNotifierItem tray (ksni) plus GTK4. "60 s poll with backoff" is unverified. |
| [codex-quota-linux](#codex-quota-linux) | See below | MIT | Not read-only. |

### codex-quota-linux

- **Original repo gone.** The research pass found `YudongN/codex-quota-linux` (a Python AppIndicator tray), but that repo returned **404** from both the GitHub web and API on 2026-09-28 (Research).
- **Same-named repo.** [ydxrobot/codex-quota-linux](https://github.com/ydxrobot/codex-quota-linux) (MIT, created 2026-08-08 per the research pass) is live and describes itself as a "Minimal Linux tray utility for monitoring and switching Codex account quota" (Verified). Its README does not say whether it is the same project re-homed (Unverified).
- **It is not read-only** (Verified from its README):
  - It keeps per-account copies of Codex credentials under `.runtime/accounts/<Alias>/auth.json`.
  - It switches the main Codex login with `./codex-quota switch <Alias>`.
  - Its `activate-window` command will "Send a tiny Codex request under selected saved accounts to activate their rolling quota windows", which spends a little quota.

**What we learn:** Account switching and window "warming" rewrite credentials and spend quota. Both are out of scope for this app, which only reads.

## Other evidence about the Claude usage endpoint

These projects are not monitors we would copy, but their reports explain the rate-limit behavior described in [claude-usage-sources.md](claude-usage-sources.md). Every item is a single community report (Research unless noted):

- **User-Agent matters.** [Haletran/claude-usage-extension PR #34](https://github.com/Haletran/claude-usage-extension/pull/34) (2026-07-05): without a Claude Code-style User-Agent, 429s came with `retry-after` up to about 1,600 s; with one, requests succeeded.
- **Even slow polling can 429.** [altansaid/QDock commit fd25b11](https://github.com/altansaid/QDock/commit/fd25b1102d3fc61a2febe8184d053ddf4608ad2f) (2026-07-16) saw escalating 429s at 5-minute polling with its own User-Agent.
- **Bursts fail.** [latekvo/Diplomat #57](https://github.com/latekvo/Diplomat/issues/57) (measured 2026-08-19): 19 of 20 burst requests got 429 with `Retry-After: 0`, and about one success every 2 minutes.
- **Lockouts can be long.** [trickv/hass-claude-usage](https://github.com/trickv/hass-claude-usage) (Home Assistant integration): its README reports a burst lockout lasting about 24 hours (Unverified).
- **Refresh races.** [george-vice/ccusage-mqtt](https://github.com/george-vice/ccusage-mqtt) documents a race when a third party redeems single-use refresh tokens.
- **Anthropic's own tracker.** [anthropics/claude-code #30930](https://github.com/anthropics/claude-code/issues/30930) (opened 2026-03-05) shows a persistent 429 with `retry-after: 0`. [#31637](https://github.com/anthropics/claude-code/issues/31637) (opened 2026-03-06) was closed by a bot for inactivity on 2026-06-01, with no fix.

## Patterns we adopt and patterns we avoid

### Adopt

1. **First-party binaries as the data source.** Examples: MostafaAlyy/ai-agent-usage and komagata/ai-quota-waybar (`codex app-server`); CodexBar, [stablyai/orca PR #23426](https://github.com/stablyai/orca/pull/23426) (2026-09-27) and [kunchenguid/quota-axi](https://github.com/kunchenguid/quota-axi) (`agy -p /usage --output-format json`); claude-hud PR #720 (`claude -p /usage`).
2. **Collector and renderer split.** A background collector writes a snapshot file and the panel or tray only renders it. The UI never blocks on the network or on a spawned CLI (MostafaAlyy/ai-agent-usage, burakgon/ai-usage-kde-widget).
3. **One normalized record per provider and account.** MostafaAlyy/ai-agent-usage's README uses `{schemaVersion, id, name, available, status: ok|not_configured|auth|error, plan, limits:[{key, label, percent, resetsAt, group}], balance, updatedAt}`. That covers Claude's windows, Codex's primary/secondary/additional windows, and Antigravity's groups (Research).
4. **Labels come from the provider.** Codex reports `window_minutes`. A free-plan sample showed a single 30-day window, not 5h/weekly. `agy` reports its own window strings. Never hardcode "5h" and "weekly".
5. **Always show an "as of" time.** Local and cached data go stale. When `resets_at` is in the past, the window has reset. A missing window means "unknown", not 0%.
6. **One config dir per account.** `CLAUDE_CONFIG_DIR` and `CODEX_HOME` are the providers' own multi-account mechanisms (Claude-Usage-Tracker, CodexBar).
7. **Never write provider credential files** (CodexBar's stated rule).

### Avoid

1. **Refreshing a borrowed token.** Claude and Codex refresh tokens are single-use, so a monitor that redeems one logs the real CLI out (Claude-Usage-Tracker v3.2.0, ccusage-mqtt). See [claude-oauth-tokens.md](claude-oauth-tokens.md).
2. **Spoofing another client's User-Agent** to get a gentler rate-limit bucket.
3. **Collecting claude.ai session cookies**, whether pasted or captured by an in-app sign-in.
4. **Inference probes** that spend subscription quota to read headers.
5. **Calling Google's Code Assist or Antigravity backend directly** with borrowed tokens.
6. **Tight polling loops.** Poll every few minutes at most, add jitter, and back off on 429s, including 429s that say `retry-after: 0`.
7. **Scraping interactive TUIs** when a structured, non-interactive mode exists.

## Open questions

- Licenses not checked: p3kj/plasma-applet-claudemeter, dvdstelt/ClaudeCodeUsage, achton/claude-monitor-linux, Kabilan108/claude-bar, the four codexbar KDE wrappers, and several Waybar modules listed above.
- Whether `ydxrobot/codex-quota-linux` is the same project as the removed `YudongN/codex-quota-linux`.
- Whether any maintained XFCE-native monitor exists. The search on 2026-09-28 found none, but a search can miss projects.
- The exact rate-limit budget of the Claude usage endpoint (per token, per account, per IP or per User-Agent). The community reports above conflict.
