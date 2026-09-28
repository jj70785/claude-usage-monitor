# Research notes

**TLDR:** This folder explains *why* the app reads usage the way it does: which data source it uses for each provider, which ones it refuses to use, and how it fits into a Linux desktop. The notes were researched on **2026-09-28**, and the facts in them drift fast, because CLIs auto-update and provider policies changed several times in 2026. Re-verify before you build on a claim.

The app is growing from a Claude-only tray app into a multi-AI plan-usage monitor. Providers are Claude first, then OpenAI Codex, then Google Gemini through the Antigravity CLI (`agy`). Platforms are Linux (XFCE on X11) first, then Windows, then macOS.

## Index

| Doc | What it covers |
| --- | --- |
| [claude-usage-sources.md](claude-usage-sources.md) | Every way to read Claude Pro/Max plan usage, ranked. The primary source is the experimental `get_usage` request answered by the unmodified `claude` binary. Also covers why statusline numbers are not displayed, the cached snapshot used as a freshness stamp, and the off-by-default direct API route. |
| [claude-oauth-tokens.md](claude-oauth-tokens.md) | Where Claude Code keeps its OAuth credentials for each `CLAUDE_CONFIG_DIR`. Why the app must never refresh them: refresh tokens are single-use, so a third-party refresh logs Claude Code out. How to detect "expired" and "logged out" states read-only. |
| [codex-usage-sources.md](codex-usage-sources.md) | Codex (ChatGPT plan) usage from local rollout files and from `codex app-server` → `account/rateLimits/read`. Covers window shapes by plan, `CODEX_HOME` for multiple accounts, and why `/wham/usage` is documented but never called. |
| [gemini-antigravity-usage.md](gemini-antigravity-usage.md) | Why the Google provider wraps the Antigravity CLI instead of gemini-cli after the 2026-06-18 consumer cutover. Covers the `agy -p /usage --output-format json` output, headless guardrails, and Google's ban on direct backend access. |
| [linux-xfce-desktop.md](linux-xfce-desktop.md) | How the app shows up on XFCE 4.20 / X11: tray icons, the Tk flyout, notifications, XDG autostart, single-instance handling, packages, and a possible genmon panel readout. Also covers why pystray was dropped on Linux. |
| [existing-tools.md](existing-tools.md) | The landscape of existing monitors (CodexBar, Claude-Usage-Tracker, ccusage, claude-hud, KDE/GNOME/Waybar widgets and more): their data sources, platforms and licenses, plus the patterns we adopt or avoid. |
| [terms-and-policy.md](terms-and-policy.md) | What Anthropic, OpenAI and Google publicly say about third-party access, and the app's resulting rules: first-party CLIs first, never store or refresh credentials, never impersonate a client. Not legal advice. |

## Suggested reading order

1. **terms-and-policy.md** gives the rules that constrain every other decision.
2. **The provider doc** for the provider you are touching, plus **claude-oauth-tokens.md** if you touch anything near Claude credentials.
3. **linux-xfce-desktop.md** before you change tray, flyout, autostart or packaging code.
4. **existing-tools.md** when you wonder "hasn't someone solved this already?"

## Versions these notes were written against

The table below records what was installed on the reference machine on 2026-09-28. Later versions may behave differently.

| Component | Version | Notes |
| --- | --- | --- |
| Claude Code | 2.1.283 and 2.1.284 | It auto-updated from 2.1.283 to 2.1.284 on the research day itself. |
| Codex CLI | 0.157.0 | `codex app-server` is labeled experimental. |
| Antigravity CLI (`agy`) | 1.2.11 | Self-updating. Print-mode `/usage` needs 1.1.11 or later. |
| gemini-cli | 0.61.0 | Consumer OAuth has not been served since 2026-06-18. |
| Desktop | MX Linux 25.3 (Debian 13), XFCE 4.20, X11 | Other desktops are future work. |

## Facts drift fast: re-verify

Treat every claim here as "true on 2026-09-28". Re-check it when any of these happen:

- **A CLI updates.** Claude Code and agy update themselves. Response shapes, flags and experimental APIs such as `get_usage` and `app-server` can change without notice.
  - Claude Code: re-read the [CHANGELOG](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md) and the [statusline](https://code.claude.com/docs/en/statusline) and [headless](https://code.claude.com/docs/en/headless) docs.
  - Codex: regenerate the schema with `codex app-server generate-json-schema --out <dir>`.
  - agy: capture one fresh `agy -p /usage --output-format json` sample and log `agy --version` next to it.
- **A provider changes policy.** Re-fetch the pages quoted in [terms-and-policy.md](terms-and-policy.md). Anthropic's policy moved several times in 2026: an enforcement push in January, a docs change in February, and a planned Agent SDK billing change that was put on hold in mid-June (per the help article's June 15 pause note). Google announced the end of consumer Gemini CLI access on 2026-05-19 and cut it off on 2026-06-18, with about a month's notice.
- **Prior art changes.** CodexBar's provider docs are a good early warning. They have tracked provider changes closely, for example the June 2026 Gemini consumer cutover and agy's CSRF requirement. Check [steipete/CodexBar/docs](https://github.com/steipete/CodexBar/tree/main/docs).
- **Before you quote a number.** Stars, versions, licenses and rate-limit anecdotes all go stale.

When you re-verify something, update the doc and its date. Don't leave an old date on a fact you just re-checked.

## Conventions for these docs

This repo is **public**, so the rules below are strict.

- **Every factual claim has a label.** Use one of:
  - a source (URL plus date),
  - "observed locally, `<date>`",
  - "unverified".
  Keep confidence honest: say "one user report" when that is all there is.
- **Observed behavior only for closed-source binaries.** Describe what a CLI does, citing official docs, changelogs, public issues and open-source code (openai/codex, google-gemini/gemini-cli and CodexBar are open source). Never publish byte offsets, minified function names or disassembly details of closed binaries. Anthropic's Consumer Terms also prohibit reverse engineering its services.
- **No secrets or personal data.** That means no tokens, keys, cookies, email addresses, account, org or user UUIDs, process IDs, or real home-directory paths (write `~`). Usage percentages are fine only as clearly labeled examples.
- **No private sources.** Cite only public repositories and pages.
- **Style.**
  - American spelling.
  - A 2-3 sentence TLDR at the top of each doc.
  - Short paragraphs and tables where they help.
  - Write for a future contributor or AI coding agent who needs the *why*, not just the *what*.
