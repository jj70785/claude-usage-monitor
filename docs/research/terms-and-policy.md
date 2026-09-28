# Provider terms and this app's risk posture

**TLDR:** None of the three providers publishes a rule written specifically for read-only usage monitors. What they do publish points one way: running the provider's own, unmodified CLI is fine, and pulling tokens out of it to call backends yourself is not (Google says so outright; Anthropic comes close). So this app gets usage from first-party CLIs wherever it can, never stores or refreshes anyone's credentials, never pretends to be another client, and treats its one direct-API fallback as a gray area.

> **Not legal advice.** This is a contributor's reading of public documents as of 2026-09-28, written to explain design decisions. It is not a legal opinion. If the answer matters to you, read the sources yourself or ask a lawyer.

- Research date: **2026-09-28**.
- Every quote below comes from a public primary source (provider terms, docs, help articles, official blogs, or provider-owned repos and forums).
- The quotes from Anthropic's legal and Agent SDK pages, the help article, Google's blog post, gemini-cli's `tos-privacy.md`, the Antigravity terms, OpenAI's app-server and auth docs, and Anthropic's Consumer Terms were re-fetched and checked word for word on 2026-09-28.
- Terms change. Anthropic's pages changed several times in 2026. Re-check before relying on any of this.

## Anthropic (Claude)

### What the terms say

**Consumer Terms of Service** ([anthropic.com/legal/consumer-terms](https://www.anthropic.com/legal/consumer-terms), effective October 8, 2025). The prohibited-uses list includes:

- Item 7: "Except when you are accessing our Services via an Anthropic API Key or where we otherwise explicitly permit it, to access the Services through automated or non-human means, whether through a bot, script, or otherwise."
- Item 3: "To decompile, reverse engineer, disassemble, or otherwise reduce our Services to human-readable form..." This is one reason these docs describe *observed behavior* and cite public sources instead of publishing internals of Anthropic's binaries.

**Claude Code "Legal and compliance" page** ([code.claude.com/docs/en/legal-and-compliance](https://code.claude.com/docs/en/legal-and-compliance)), section "Authentication and credential use":

- "**OAuth authentication** is intended exclusively for purchasers of Claude Free, Pro, Max, Team, and Enterprise subscription plans and is designed to support ordinary use of Claude Code and other native Anthropic applications."
- "Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, or Max plan credentials on behalf of their users. Moreover, developers may not collect, store, or intermediate Claude.ai credentials or session tokens — sign-in to a Claude account must complete through Anthropic's own flow."
- "Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription..."
- "Anthropic reserves the right to take measures to enforce these restrictions and may do so without prior notice."
- From the same page's "Acceptable use" section: "Advertised usage limits for Pro and Max plans assume ordinary, individual usage of Claude Code and the Agent SDK."

**Agent SDK overview** ([code.claude.com/docs/en/agent-sdk/overview](https://code.claude.com/docs/en/agent-sdk/overview)):

- "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK."
- Branding: "Your product should maintain its own branding and not appear to be Claude Code or any Anthropic product."

**Help article "Use the Claude Agent SDK with your Claude plan"** ([support.claude.com/en/articles/15036540](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), last updated 2026-06-16):

- It describes a planned monthly credit that would cover "Claude Agent SDK usage in your own projects", "the `claude -p` command in Claude Code", and "third-party apps that authenticate with your Claude subscription through the Agent SDK".
- The plan is on hold: "We're pausing the changes to Claude Agent SDK usage described below. For now, nothing has changed: Claude Agent SDK, `claude -p`, and third-party app usage still draw from your subscription's usage limits."
- Why this matters here: if the app spawns `claude -p` to read usage, that falls into this "Agent SDK usage" bucket. The usage read itself is not supposed to make a model call (see below), so it should draw nothing. Re-check this article if the paused change resumes.

**Documented multi-account and credential facts** that the app relies on:

- `CLAUDE_CONFIG_DIR` is "Useful for running multiple accounts side by side" ([env-vars docs](https://code.claude.com/docs/en/env-vars), fetched 2026-09-28 by the research pass).
- On Linux, credentials live in `.credentials.json` inside the config dir with mode 0600 ([authentication docs, credential management](https://code.claude.com/docs/en/authentication#credential-management), research pass 2026-09-28).
- Tokens from `claude setup-token` "can only make model requests" (same page), so they cannot read plan usage.

### What Anthropic does not say

- As of 2026-09-28 the research pass found **no statement specific to read-only usage monitors**, whether allowing or forbidding them.
- The usage endpoint that many tools call (`GET https://api.anthropic.com/api/oauth/usage`) is **not documented**. Its rate limits are known only from community reports (see [existing-tools.md](existing-tools.md#other-evidence-about-the-claude-usage-endpoint)).
- **Enforcement history (secondary reporting, not a primary source).**
  - VentureBeat ([2026-01-09](https://venturebeat.com/technology/anthropic-cracks-down-on-unauthorized-claude-usage-by-third-party-harnesses)) quoted Anthropic as having "tightened our safeguards against spoofing the Claude Code harness", and reported that mistaken automatic bans were reversed.
  - The Register ([2026-02-20](https://www.theregister.com/software/2026/02/20/anthropic-clarifies-ban-on-third-party-tool-access-to-claude/5014546)) covered the February 2026 docs change that added the "Authentication and credential use" section. It quoted an Anthropic staff member saying that third-party harnesses using Claude subscriptions are prohibited. Other outlets reported softer staff comments about personal, local use (for example [aiHola, 2026-02-20](https://aihola.com/article/anthropic-claude-oauth-ban-walkback)), so the messaging was mixed.

### How this project reads it

| Access pattern | Reading | Why |
| --- | --- | --- |
| The **unmodified `claude` binary** answers a usage request: the experimental `get_usage` control request of the stream-json SDK protocol, or non-interactive `claude -p /usage` | **Lowest risk** | The legal page explicitly does not prevent "an end user from signing in to the unmodified Claude Code binary". The app never touches a token; Claude Code does its own auth and refresh. |
| Reading local files Claude Code already writes (for example a cached usage snapshot) | Low risk, but **undocumented** | No network call and no credential. The file formats can change without notice. |
| Statusline stdin `rate_limits` | Low risk, **not used for display** | Documented and credential-free. But it is only as fresh as the last message in that session, so the project decided on 2026-09-28 not to show it. See [existing-tools.md](existing-tools.md#why-statusline-data-is-not-enough). |
| **Direct GET `/api/oauth/usage`** with Claude Code's access token, read-only | **Gray area; off by default** | It is scripted access (Consumer Terms item 7) that uses an OAuth token outside "Claude Code and other native Anthropic applications". Reading the token could count as "collect". No model call is made and no quota is spent, but no Anthropic text blesses it either. |
| Refreshing Claude Code's token | **Never** | It breaks Claude Code: refresh tokens are single-use and rotate. It also means intermediating a credential. See [claude-oauth-tokens.md](claude-oauth-tokens.md). |
| Pasting or capturing a claude.ai `sessionKey` cookie | **Never (removed)** | "developers may not collect, store, or intermediate Claude.ai credentials or session tokens". |
| A 1-token model request just to read rate-limit headers | **Never** | Third-party inference on subscription credentials. That is the thing the Agent SDK note and the legal page restrict, and it spends quota. |
| Sending a Claude Code-style User-Agent | **Never** | Impersonating the official client is the "spoofing" pattern Anthropic enforced against. |

About `get_usage`:

- It is **experimental**. The published TypeScript Agent SDK typings expose it under a name that says so: `usage_EXPERIMENTAL_MAY_CHANGE_DO_NOT_RELY_ON_THIS_API_YET` ([`@anthropic-ai/claude-agent-sdk` 0.3.284 `sdk.d.ts`](https://unpkg.com/@anthropic-ai/claude-agent-sdk@0.3.284/sdk.d.ts), as cited in [claude-usage-sources.md](claude-usage-sources.md)).
- **It spends no quota.** Observed locally on 2026-09-28 with Claude Code 2.1.284, a single test run reported `total_cost_usd` 0 and empty model usage, so no model call was made. See [claude-usage-sources.md](claude-usage-sources.md#live-test-result).
- Invocation details and guardrails are in [claude-usage-sources.md](claude-usage-sources.md).

## OpenAI (Codex)

### What the published docs say

**Codex authentication docs** ([learn.chatgpt.com/docs/auth](https://learn.chatgpt.com/docs/auth)):

- "Treat `~/.codex/auth.json` like a password: it contains access tokens. Don't commit it, paste it into tickets, or share it in chat."
- Credentials can live in `auth.json` under `CODEX_HOME` or in the OS credential store: "`keyring` stores credentials in your operating system credential store and fails if it is unavailable. `auto` uses the OS credential store when available, otherwise falls back to `auth.json`."
- The page says nothing about third-party tools using these tokens (checked 2026-09-28).

**Codex app-server docs** ([learn.chatgpt.com/docs/app-server](https://learn.chatgpt.com/docs/app-server)):

- It documents `account/rateLimits/read` as a supported method.
- "The app-server command and WebSocket transport are experimental and aren't supported for production workloads."
- "Use `clientInfo.name` to identify your client for the OpenAI Compliance Logs Platform."
- "If you are automating jobs or running Codex in CI, use the Codex SDK instead."

**Codex pricing docs** ([learn.chatgpt.com/docs/pricing](https://learn.chatgpt.com/docs/pricing), research pass 2026-09-28) point users to the usage dashboard at `chatgpt.com/codex/settings/usage` and to `/status` in the TUI.

**Open-source client code** ([openai/codex](https://github.com/openai/codex), Apache-2.0, `codex-rs/login/src/auth/default_client.rs` at commit 368e5eae, research pass 2026-09-28):

- Codex identifies itself with the originator `codex_cli_rs` and treats only that value as first-party.
- The login code has an explicit error for a refresh token that "was already used", which confirms that refresh tokens are single-use.

### OpenAI's silence

- The research pass found **no written OpenAI rule** about third-party tools reading Codex usage. It did **not** review the full OpenAI Terms of Use (Unverified).
- The usage endpoint behind Codex (`chatgpt.com/backend-api/wham/usage`) is undocumented.
- Public signals lean permissive, but none of them is a contract:
  - In [openai/codex discussion #8338](https://github.com/openai/codex/discussions/8338), an OpenAI team member wrote on 2026-02-09 that "our terms of use and code license are quite permissive, and OSS projects like OpenCode are doing things similar...".
  - [openai/codex issue #36886](https://github.com/openai/codex/issues/36886) (opened 2026-08-04) asks for "a documented auth contract for third-party clients using a ChatGPT subscription". It is about the Responses endpoint, not usage, and had no maintainer reply as of 2026-09-28.

### How this project reads it

| Access pattern | Reading | Why |
| --- | --- | --- |
| `codex app-server` → `account/rateLimits/read`, with our own `clientInfo.name` | **Lowest risk** | This is OpenAI's documented integration surface, and Codex handles its own tokens. Caveat: it is labeled experimental. |
| Reading `rate_limits` from local rollout files (`~/.codex/sessions/**/rollout-*.jsonl`) | Low risk | No network and no credential. The data is stale while Codex is idle. |
| Direct GET `/wham/usage` with the `auth.json` access token, read-only | **Gray area; the app does not call it** | Undocumented. The docs say to treat the file "like a password", though nothing in writing forbids it. `app-server` reaches the same data through first-party code, so a direct call buys nothing. [codex-usage-sources.md](codex-usage-sources.md) documents it for reference only. |
| Refreshing the token or writing `auth.json` | **Never** | Refresh tokens are single-use, so a third-party refresh logs the Codex CLI out. |
| Sending the `codex_cli_rs` originator or a Codex User-Agent | **Never** | Impersonates the first-party client. |

## Google (Gemini CLI and Antigravity)

### What the terms say

**Google Developers Blog, "An important update: Transitioning Gemini CLI to Antigravity CLI"** ([developers.googleblog.com](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/), published 2026-05-19):

- "On June 18, 2026, Gemini CLI and Gemini Code Assist IDE extensions will stop serving requests" for "Google AI Pro and Ultra, as well as those using it free of charge using Gemini Code Assist for individuals".
- Unaffected: "Gemini CLI or our IDE extensions via a Gemini Code Assist Standard or Enterprise license". Also, "Gemini CLI will remain accessible via paid Gemini and Gemini Enterprise Agent Platform API keys".
- Replacement: "Google Antigravity...which includes a brand-new terminal experience: Antigravity CLI" (the `agy` binary).
- Google's [deprecation page](https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals) (last updated 2026-09-02, research pass) confirms the cutover and says Standard and Enterprise "remain unchanged".

**gemini-cli's own terms page** ([docs/resources/tos-privacy.md](https://github.com/google-gemini/gemini-cli/blob/main/docs/resources/tos-privacy.md), clause added in commit `83a3851dfd` on 2026-02-27):

> "Directly accessing the services powering Gemini CLI (for example, the Gemini Code Assist service) using third-party software, tools, or services (for example, using OpenClaw with Gemini CLI OAuth) is a violation of applicable terms and policies. Such actions may be grounds for suspension or termination of your account."

**Antigravity terms, clause 6** ([antigravity.google/terms](https://antigravity.google/terms), no effective date shown):

> "Using third party software, tools, or services to access the Service (e.g. using OpenClaw with Antigravity OAuth) is a breach of this Agreement. Such actions may be grounds for suspension or termination of your Antigravity and/or Gemini CLI accounts."

**Enforcement on Google's own forum** ([Google AI Developers Forum thread 122778](https://discuss.ai.google.dev/t/account-restricted-without-warning-google-ai-ultra-oauth-via-openclaw/122778), created 2026-02-12; research pass):

- Users reported account restrictions after using third-party tools with Google OAuth.
- One user wrote on 2026-02-27 that they "got ban 1 week ago because i used vscode extensions to track quota". This is a single user report.
- On 2026-03-02 a Google staff member announced "a system-wide automated unban for all affected accounts".
- In a [separate appeal thread](https://discuss.ai.google.dev/t/appeal-request-agy-this-service-has-been-disabled-in-this-account-for-violation-of-terms-of-service/172309/2) (2026-06-23), a user reports an account disabled while using only `agy` and the IDE. The cause is unknown (Unverified).

### How this project reads it

Google is the one provider that forbids direct backend access in writing, and it has enforced that rule against quota trackers at least once. So:

| Access pattern | Reading | Why |
| --- | --- | --- |
| Spawn the first-party `agy -p /usage --output-format json` | **Lowest risk (the only source we use)** | It is the first-party binary. agy's changelog for 1.1.11 says print-mode `/usage` returns a structured payload "without starting an agent turn, spending quota, or leaving a conversation behind". Observed in the changelog bundled with agy 1.2.11; CodexBar's docs cite [antigravity.google/changelog](https://antigravity.google/changelog). |
| Calling `cloudcode-pa` / `daily-cloudcode-pa` with tokens read from `~/.gemini/oauth_creds.json` or the keyring | **Never** | This is exactly what `tos-privacy.md` and Antigravity clause 6 forbid. |
| Calling agy's local language-server HTTPS API | **Never** | It needs a CSRF token since agy 1.2.2 ([CodexBar docs/antigravity.md](https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md), research pass), and scraping one would mean working around a first-party control. |
| gemini-cli usage for consumer accounts | **Not supported** | Consumer tiers stopped being served on 2026-06-18. |

- **Polling etiquette.** A tool that ran `agy -p` about every 30 seconds saw a silent re-auth on each run and "recurring Antigravity authorization UI" ([razzant/claudexor #269](https://github.com/razzant/claudexor/issues/269), 2026-09-04). This app polls agy no more than every 5-10 minutes. Details are in [gemini-antigravity-usage.md](gemini-antigravity-usage.md).

## The app's risk posture

These rules apply to every provider and override convenience.

### Sources by risk, per provider

This table ranks **risk**, not fetch order. The order in which the app actually reads sources is chosen per provider for freshness and cost. For example, the Codex provider reads a fresh rollout file before it spawns `app-server`. See [claude-usage-sources.md](claude-usage-sources.md) and [codex-usage-sources.md](codex-usage-sources.md).

| Provider | First-party CLI (lowest risk) | Local files (no network) | Gray-area fallback | Never |
| --- | --- | --- | --- | --- |
| Claude | Unmodified `claude`: `get_usage` (experimental, the primary source) | Cached usage snapshot that Claude Code writes (undocumented; used for freshness and last-known values) | Direct GET `/api/oauth/usage`, read-only, **off by default** | Token refresh, `sessionKey` cookies, inference probes, a Claude Code User-Agent |
| Codex | `codex app-server` → `account/rateLimits/read` | Rollout JSONL `rate_limits` | None (`/wham/usage` is documented for reference but not called) | Token refresh, writing `auth.json`, the `codex_cli_rs` originator |
| Gemini | `agy -p /usage --output-format json` | None | None | Any direct Google backend call, reading Google tokens, agy's local API |

### Rules

1. **Prefer first-party CLIs.** When the provider's own binary answers, the provider's code handles auth, refresh, locking and rate limiting. The app sees only the result.
2. **Never store credentials.** The app does not copy tokens into its own config, keyring or cache, and never logs them. A token read for the direct fallback lives in memory for one request.
3. **Never refresh credentials.** If a borrowed access token is expired, the app shows the data as stale and asks the user to open the provider's CLI. It does not redeem a refresh token. For Claude and Codex, refresh tokens are single-use: redeeming one logs out every CLI session on that account.
4. **Never write provider files.** That includes `.credentials.json`, `~/.claude.json`, `~/.codex/auth.json` and any keyring entry. The CLIs rewrite these files concurrently under their own locks.
5. **Never impersonate another client.** The app sends its own honest User-Agent (and, for Codex, its own `clientInfo.name`), never a Claude Code, Codex or Antigravity identity.
   - The cost: public reports say requests without a Claude Code-style User-Agent land in a stricter rate-limit bucket on `/api/oauth/usage` ([existing-tools.md](existing-tools.md#other-evidence-about-the-claude-usage-endpoint)). We accept slower or failed fallback reads rather than spoof.
6. **The direct API fallback is a documented gray area.** Only the Claude provider has one (`/api/oauth/usage`), and it is **off by default**. If a user turns it on:
   - It reads the token file read-only, fresh on each attempt, and only uses an access token that has not expired.
   - It polls slowly (every few minutes at most, with jitter) and backs off hard on HTTP 429, including a 200 response whose body is a `rate_limit_error`.
   - It shows last-known data with an "as of" time instead of retrying.
   - The UI should say plainly that this is an unofficial endpoint.
7. **No cookie paste.** The original prototype had a "Paste session key..." feature for claude.ai cookies. The multi-AI rewrite removes it: storing a `sessionKey` is what Anthropic's legal page says developers "may not" do, and Cloudflare intermittently blocks non-browser clients on claude.ai anyway ([Claude-Usage-Tracker PR #271](https://github.com/hamed-elfayome/Claude-Usage-Tracker/pull/271), 2026-07-10).
8. **No inference probes, ever.** The app never sends a model request to learn about usage.
9. **Poll politely.** Cache results, poll every few minutes at most, add jitter, back off on errors, and remember that the user's own `/usage` checks can share the same rate-limit budget.
10. **Protect privacy in output.** CLI output and CLI log files can contain the signed-in account's email address and org identifiers. Parse only the fields you need, and never log raw CLI output or copy CLI logs into bug reports.
11. **Spawn CLIs defensively.** Run them from an empty temporary directory so project hooks and MCP configs do not load. Give them stdin from `/dev/null` unless the protocol needs a pipe (Claude's `get_usage` and `codex app-server` do; `agy -p` must not get one). Use a timeout, and kill the whole process group. Exception: never SIGKILL a spawned `claude`, because a process killed mid-refresh can leave Claude Code's refresh lock held; close stdin and send SIGTERM instead ([claude-usage-sources.md](claude-usage-sources.md#scheduling)). Use the flags each CLI offers to skip session files and non-essential startup work. The exact flags are in the per-provider docs.

### Naming and trademarks (gotcha)

- Anthropic's legal page restricts using the Claude Code or Anthropic names or logos "as part of your own product, feature, or company name". That sentence sits under the section for products that preinstall or run Claude Code.
- The same page says "Any other use of Anthropic's names or logos is governed by our [Trademark Guidelines](https://www.anthropic.com/legal/trademark-guidelines)". The Agent SDK page adds that a product "should maintain its own branding and not appear to be Claude Code or any Anthropic product".
- This repo started as `claude-usage-monitor`. Now that it covers several providers, a neutral product name, with plain-text lines such as "works with Claude Code, Codex and Antigravity CLI" and no provider logos, avoids the question entirely.
- **Unverified:** the research pass did not read Anthropic's, OpenAI's or Google's trademark guidelines.

## Open questions

- No provider has said anything specific about read-only usage monitors. If one does, update this doc first.
- `get_usage` has been observed spending no quota in only one test run (Claude Code 2.1.284, 2026-09-28). `claude -p /usage` has not been tested here. Re-check both after Claude Code updates.
- The full OpenAI Terms of Use were not reviewed.
- Whether slow, honest-User-Agent polling of `/api/oauth/usage` is tolerated in practice, or rate-limited into uselessness, is unknown.
- Whether Anthropic's paused Agent SDK credit change resumes, and how `claude -p` usage reads would be counted if it does.
