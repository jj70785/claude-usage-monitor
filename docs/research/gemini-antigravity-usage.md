# Gemini usage via the Antigravity CLI (`agy`)

**TLDR:** Since 2026-06-18, Google no longer serves Gemini CLI's "Login with Google" (Code Assist OAuth) for free, Google AI Pro or Google AI Ultra accounts, so for personal accounts Gemini plan usage now lives in the Antigravity CLI, `agy`. Google's terms forbid third-party tools from calling the Code Assist/Antigravity backends directly, and people have been suspended for quota-tracking extensions, so the only route this app uses is Google's own binary: `agy -p /usage --output-format json` (agy 1.1.11 or later). The monitor runs it with no stdin, no terminal, a hard timeout and a slow poll, and treats the JSON shape as "observed/expected, fields may change".

Research date: 2026-09-28. Local observations used agy 1.2.11 and gemini-cli 0.61.0 on Linux (XFCE/X11). gemini-cli source references point at `google-gemini/gemini-cli` commit `2fe7c2d3` or `main` as of 2026-09-28.

---

## Contents

1. [What changed: gemini-cli consumer OAuth ended](#1-what-changed-gemini-cli-consumer-oauth-ended-2026-06-18)
2. [Policy: never call Google's backends directly](#2-policy-never-call-googles-backends-directly)
3. [The safe route: `agy -p /usage`](#3-the-safe-route-agy--p-usage---output-format-json)
4. [Output shape (observed/expected)](#4-output-shape-observedexpected-fields-may-change)
5. [Parsing rules](#5-parsing-rules)
6. [Invocation guardrails](#6-invocation-guardrails)
7. [Freshness](#7-freshness)
8. [gemini-cli notes: `/stats` vs `/stats model`](#8-gemini-cli-notes-stats-vs-stats-model)
9. [Options considered and rejected](#9-options-considered-and-rejected)
10. [Recommended design](#10-recommended-design)
11. [Open questions](#11-open-questions)
12. [Sources](#12-sources)

---

## 1. What changed: gemini-cli consumer OAuth ended 2026-06-18

Google announced on the Google Developers Blog (2026-05-19) that *"Gemini CLI and Gemini Code Assist IDE extensions will stop serving requests for Google AI Pro and Ultra, as well as those using it free of charge"* on 2026-06-18. It also said *"Gemini CLI will remain accessible via paid Gemini and Gemini Enterprise Agent Platform API keys."* ([Google Developers Blog](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/), fetched 2026-09-28)

The Code Assist deprecation page (last updated 2026-09-02) confirms this for *"Gemini Code Assist for individuals, Google AI Pro, and Google AI Ultra"*. It adds that access *"using Gemini Code Assist Standard or Enterprise subscriptions remain unchanged"*, and that consumer users *"can migrate to the Antigravity family of products"* ([developers.google.com deprecation page](https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals), fetched 2026-09-28).

What this means for the monitor:

| Account type | Where plan usage lives now | Monitor support |
|---|---|---|
| Personal Google account (free, AI Pro, AI Ultra) | **Antigravity CLI (`agy`)** | Yes, via `agy -p /usage` |
| Code Assist Standard / Enterprise (Workspace) | gemini-cli `/stats` (interactive) | Not in v1 (see [section 8](#8-gemini-cli-notes-stats-vs-stats-model)) |
| gemini-cli with a Gemini API key | API project quotas, not a subscription plan | Out of scope |

What the failure looks like: according to CodexBar, a consumer account using the old flow now gets an HTTP 200 from `loadCodeAssist` with `ineligibleTiers[].reasonCode == "UNSUPPORTED_CLIENT"`, followed by `403 SUBSCRIPTION_REQUIRED` from the quota call ([CodexBar docs/gemini.md](https://github.com/steipete/CodexBar/blob/main/docs/gemini.md), fetched 2026-09-28). gemini-cli 0.61.0 also bundles a built-in "antigravity-support" migration skill (observed locally, 2026-09-28).

**Design consequence:** the "Gemini" provider in this app is an **Antigravity** provider. If only gemini-cli with a personal login is present, show "Gemini CLI no longer serves personal accounts; install Antigravity CLI" rather than an error.

---

## 2. Policy: never call Google's backends directly

This is the most important constraint in this document, and it is why the design looks the way it does.

**gemini-cli's terms doc** (added 2026-02-27, commit `83a3851dfd`, [docs/resources/tos-privacy.md](https://github.com/google-gemini/gemini-cli/blob/main/docs/resources/tos-privacy.md)):

> "Directly accessing the services powering Gemini CLI (for example, the Gemini Code Assist service) using third-party software, tools, or services (for example, using OpenClaw with Gemini CLI OAuth) is a violation of applicable terms and policies. Such actions may be grounds for suspension or termination of your account."

**Antigravity Additional Terms, clause 6** ([antigravity.google/terms](https://antigravity.google/terms), fetched 2026-09-28):

> "Using third party software, tools, or services to access the Service (e.g. using OpenClaw with Antigravity OAuth) is a breach of this Agreement"

The penalties named there cover *"Antigravity and/or Gemini CLI accounts"*.

**Enforcement has happened, including for read-only quota tracking.** In the Google AI Developers Forum thread [*"Account restricted without warning…"* (#122778)](https://discuss.ai.google.dev/t/account-restricted-without-warning-google-ai-ultra-oauth-via-openclaw/122778), created 2026-02-12:

- A participant wrote on 2026-02-27: *"got ban 1 week ago because i used vscode extensions to track quota."* ([page 3](https://discuss.ai.google.dev/t/account-restricted-without-warning-google-ai-ultra-oauth-via-openclaw/122778?page=3))
- Google staff then posted on 2026-03-02: *"We are currently rolling out a system-wide automated unban for all affected accounts."* (same page)
- A separate thread from 2026-06-23 reports an account disabled while using only agy and the IDE, with no stated cause ([thread #172309](https://discuss.ai.google.dev/t/appeal-request-agy-this-service-has-been-disabled-in-this-account-for-violation-of-terms-of-service/172309/2)). It is a reminder that even first-party use is not a guarantee.

**What this rules out, specifically:**

- Reading agy's or gemini-cli's OAuth tokens (from the keyring or `~/.gemini/oauth_creds.json`) and calling `cloudcode-pa.googleapis.com` or `daily-cloudcode-pa.googleapis.com` ourselves, even just for quota.
- Doing our own OAuth login against Antigravity or Gemini CLI's client.
- Calling agy's local language-server HTTPS endpoints. Since agy 1.2.2 these reject requests that lack a CSRF token (`401 missing CSRF token`) ([CodexBar PR #3685](https://github.com/steipete/CodexBar/pull/3685), 2026-09-16; [CodexBar docs/antigravity.md](https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md)). Getting that token from outside agy would mean working around a first-party control, and the call would still be the same class of third-party access.

**Caution about prior art.** Some existing tools do exactly what is ruled out above. For example, CodexBar's Gemini provider calls the Code Assist quota API with gemini-cli's credentials, and its Antigravity OAuth fallback does the same for Antigravity ([CodexBar docs/providers.md](https://github.com/steipete/CodexBar/blob/main/docs/providers.md), [docs/gemini.md](https://github.com/steipete/CodexBar/blob/main/docs/gemini.md)). Don't copy those paths. CodexBar's **agy print-mode** path is fine to learn from.

---

## 3. The safe route: `agy -p /usage --output-format json`

agy's print mode (`-p`, also `--print` / `--prompt`) runs once and exits, and `--output-format json` prints *"a single JSON envelope after the run completes"* ([antigravity.google/docs/cli/headless](https://antigravity.google/docs/cli/headless), fetched 2026-09-28).

Starting with **agy 1.1.11**, read-only slash commands such as `/usage` are answered by the CLI itself in print mode. agy's release notes for 1.1.11 say `-p "/usage"` under `--output-format json` emits a structured payload *"without starting an agent turn, spending quota, or leaving a conversation behind."* (1.1.11 entry of the release notes shipped inside agy 1.2.11, read 2026-09-28. The web changelog at [antigravity.google/changelog](https://antigravity.google/changelog) only goes back to 1.1.28 as of that date.) CodexBar independently states *"Google introduced non-interactive usage reports in 1.1.11"* and gates on that version ([docs/antigravity.md](https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md)). So does Orca ([stablyai/orca PR #23426](https://github.com/stablyai/orca/pull/23426), opened 2026-09-27).

**Version gate is mandatory.** Before 1.1.11, `/usage` in print mode was sent to the model as literal prompt text, which **spends quota** (same release notes; Orca PR #23426). Also, never pass `--disable-slash-commands`, because slash expansion must stay on.

**Each call is a live read.** agy's `/usage` docs say it *"automatically triggers a fresh check of your quotas on disk and from the backend service"* ([antigravity.google/docs/cli/commands/usage](https://antigravity.google/docs/cli/commands/usage), fetched 2026-09-28). That is good for freshness, and it is also why polling has to be slow (see [section 6](#6-invocation-guardrails)).

**What the plans look like.** Antigravity's plans page says free accounts get quota *"refreshed weekly"*, Pro is *"refreshed every five hours until weekly limit reached"*, and Ultra is *"refreshed every five hours"* with the *"Highest weekly rate limits"* ([antigravity.google/docs/plans](https://antigravity.google/docs/plans?app=cli), fetched 2026-09-28). CodexBar documents two quota groups: **"Gemini Models"** and **"Claude and GPT models"**, each with a weekly limit and a five-hour limit ([docs/antigravity.md](https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md)). Google's plans page does not describe the groups.

> Example (observed locally in an agy log, 2026-09-25): an account that used up its Gemini quota during an agent run got `RESOURCE_EXHAUSTED (429) … Individual quota reached … Resets in 167h42m`, which is about 7 days. That matches the free tier's weekly refresh, although the plan tier was inferred, not confirmed. A "5-hour" meter would have been misleading for that account.

---

## 4. Output shape (observed/expected; fields may change)

**Confidence note:** no live `agy -p /usage` output was captured for this document (a capture would have queried Google with a real account). The shape below combines three sources:

- the documented envelope fields ([headless docs](https://antigravity.google/docs/cli/headless)),
- public parsers and fixtures: [CodexBar `AntigravityCLIUsageReportTests.swift`](https://github.com/steipete/CodexBar/blob/main/Tests/CodexBarTests/AntigravityCLIUsageReportTests.swift) (fixture labeled "Synthetic"), [Orca PR #23426](https://github.com/stablyai/orca/pull/23426) and [Orca issue #22511](https://github.com/stablyai/orca/issues/22511),
- local inspection of agy 1.2.11 (not a live run).

Treat every field as optional, and **capture one real sample before finalizing the parser**.

Expected output: one line of JSON on stdout, shown pretty-printed here with illustrative values:

```json
{
  "conversation_id": "",
  "status": "SUCCESS",
  "response": "Quota:\n…human-readable table…",
  "duration_seconds": 0,
  "num_turns": 0,
  "usage": { "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "cache_read_tokens": 0, "total_tokens": 0 },
  "command": {
    "name": "usage",
    "data": {
      "groups": [
        {
          "name": "Gemini Models",
          "buckets": [
            { "id": "gemini-5h",     "name": "…", "window": "5h",     "remaining_fraction": 0.86, "reset_time": "2026-10-02T19:34:54Z" },
            { "id": "gemini-weekly", "name": "…", "window": "weekly", "remaining_fraction": 0.12, "reset_time": "2026-10-05T00:00:00Z" }
          ]
        },
        {
          "name": "Claude and GPT models",
          "buckets": [
            { "id": "3p-5h", "name": "…", "window": "5h", "disabled": true, "remaining_amount": 0 }
          ]
        }
      ]
    }
  }
}
```

| Path | Type | Notes | Confidence |
|---|---|---|---|
| `status` | string | **Uppercase** `"SUCCESS"` on success. CodexBar's parser rejects anything else. A sanitized third-party fixture ([kunchenguid/quota-axi](https://github.com/kunchenguid/quota-axi)) shows lowercase `"success"`, which conflicts, so compare case-insensitively. | Medium |
| `error` | string | Present when the run failed (documented envelope field) | Documented |
| `response` | string | Human-readable text table. **Don't parse it.** | Documented |
| `conversation_id`, `duration_seconds`, `num_turns`, `usage` | | Documented envelope fields used by agent turns. Expected to be empty or zero for `/usage`. Ignore them. | Documented |
| `command.name` | string | `"usage"` | Medium (CodexBar, Orca) |
| `command.data.description` | string, optional | Free text | Low |
| `command.data.groups[]` | array | Quota groups | Medium (CodexBar, Orca) |
| `groups[].name` | string | e.g. `"Gemini Models"`, `"Claude and GPT models"`. **Server-defined.** | Medium |
| `groups[].description` | string, optional | | Low |
| `groups[].buckets[]` | array | One per window per group | Medium |
| `buckets[].id` | string, optional | Seen in third-party reports: `gemini-5h`, `gemini-weekly`, `3p-5h`, `3p-weekly` (Orca #22511, agy 1.2.9) | Medium |
| `buckets[].name` | string | Display name | Medium |
| `buckets[].window` | string, optional | Seen as `"5h"` / `"weekly"` (CodexBar, Orca), but quota-axi's sanitized fixture uses `"5-hour"` / `"7d"`. **Server-defined; classify defensively.** | Low to medium |
| `buckets[].disabled` | bool, optional | `true` means the bucket doesn't apply to this account. Expected to be omitted when false. | Medium (CodexBar fixture) |
| `buckets[].remaining_fraction` | number, 0 to 1, optional | Fraction **remaining** (not used). Expected: may carry float noise such as `0.8600000143` instead of `0.86` (not yet seen in a live sample). | Medium |
| `buckets[].remaining_amount` | int, optional | Expected to appear instead of `remaining_fraction` when the backend reports a count. May be `0` on disabled buckets. | Low to medium |
| `buckets[].reset_time` | string, RFC 3339, optional | Expected to be omitted for disabled buckets | Medium |

**On failure** the docs say *"A run that fails to produce a response exits non-zero and writes the reason to `stderr`"* ([headless docs](https://antigravity.google/docs/cli/headless)). Stdout may still carry a JSON envelope with a non-success `status` and an `error` string. Don't depend on specific non-zero exit codes; treat "exit 0 **and** `status` is SUCCESS **and** `command.name == "usage"`" as the only success.

Known error cases worth mapping to friendly states:

| Signal | Show |
|---|---|
| stderr/`error` contains `authentication required` | "Sign in by running `agy` in a terminal" (the monitor never logs in) |
| `403`, `PERMISSION_DENIED`, `SUBSCRIPTION_REQUIRED`, `UNSUPPORTED_LOCATION` | "Account not eligible for Antigravity quota" (`UNSUPPORTED_LOCATION` reported in [razzant/claudexor#269](https://github.com/razzant/claudexor/issues/269), 2026-09-04) |
| `agy --version` < 1.1.11 | "Update Antigravity CLI" (and **don't** run `/usage`) |
| timeout / killed | "Antigravity CLI didn't respond", then back off |

`/quota` appears to be an equivalent command (Orca #22511 uses `agy -p "/quota"`). Standardize on `/usage`, which is the command CodexBar and Orca gate on.

---

## 5. Parsing rules

1. Accept only the success condition above. Otherwise produce an error state and keep the previous good reading, marked with its age.
2. For each group and each bucket:
   - If `disabled` is true, skip it (or show it grayed out as "n/a"). Never show a disabled bucket as 0% or 100%.
   - `remaining = round(remaining_fraction, 4)` when present. Otherwise use `remaining_amount` as a raw count (no percentage). Otherwise treat the bucket as unknown.
   - `used_percent = (1 - remaining) * 100`, so all providers display "percent used" the same way.
   - Parse `reset_time` as RFC 3339 with any offset. Don't assume `Z`.
3. Classify each bucket's window, in this order:
   1. the `window` string: `5h`/`5-hour`/`five_hour`… becomes 300 min; `weekly`/`7d`/`week`… becomes 10080 min;
   2. otherwise the `id` suffix (`-5h`, `-weekly`);
   3. otherwise the time from now to `reset_time` (under about 6 h suggests the 5-hour window; days suggests weekly).
   Keep the raw `window` string as the label if nothing matches, and log unknown values once. Never log whole payloads.
4. Key buckets by `(group name, id or name)`, not by array position.
5. Record agy's version with each sample, and fail closed (show "unsupported agy output") if `command.data.groups` is missing entirely.

---

## 6. Invocation guardrails

| Guardrail | How | Why |
|---|---|---|
| **Version gate** | Run `agy --version` when the binary's path or mtime changes; require ≥ 1.1.11 | Older builds send `/usage` to the model and spend quota ([section 3](#3-the-safe-route-agy--p-usage---output-format-json)) |
| **Argument list, no shell** | `["agy", "-p", "/usage", "--output-format", "json"]` | No quoting bugs, no injection |
| **stdin = `/dev/null`** | e.g. `subprocess.run(..., stdin=subprocess.DEVNULL)` | Expected (not documented, not tested live): agy reads a piped stdin into the prompt. An inherited open pipe can hang the run or turn `/usage` into `/usage <junk>`, which is rejected. |
| **No controlling terminal** | Start in a new session (`start_new_session=True` / `setsid`) | The docs say an unauthenticated run with *"no terminal"* exits with an `authentication required` error ([headless docs](https://antigravity.google/docs/cli/headless)). With a terminal it is expected to start an interactive login and wait for input, which would stall the poller and could open a browser. |
| **Private empty working directory** | A dedicated empty directory under the user's cache dir | agy is a coding agent tied to a workspace. CodexBar runs it *"in a private empty directory"* ([docs/antigravity.md](https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md)). |
| **Hard timeout** | About 90 s (CodexBar uses 90 s; Orca uses 10 s) | The docs say a run *"waits up to five minutes"* by default, but agy 1.2.6 release notes say it *"lifts the default 5-minute timeout on headless runs"* ([changelog](https://antigravity.google/changelog)). Don't rely on either; set our own. Local inspection of agy 1.2.11 suggests a startup eligibility check can wait up to about a minute before `/usage` runs (unverified), so a short timeout may cut off a healthy run. |
| **Kill the process group** | On timeout, cancel or exit, kill the whole group | agy can leave children behind. CodexBar *"stops its process group and reaps same-user processes that still carry that exact marker, including detached MCP servers"* ([docs/antigravity.md](https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md)). |
| **Cap output** | Read at most about 1 MiB of stdout | CodexBar does the same. It protects against runaway output. |
| **Slow poll** | **Every 5 to 10 min at most**, with jitter and exponential backoff on errors; poll immediately only on a user click | Every run is a full agy startup: local language server, silent re-auth from the keyring, a live quota reload against Google, logs. A tool that polled agy about every 30 s saw a silent re-auth on every run and *"recurring Antigravity authorization UI"* ([razzant/claudexor#269](https://github.com/razzant/claudexor/issues/269)). |
| **Session bus + keyring** | Run the poller inside the desktop session and pass through `DBUS_SESSION_BUS_ADDRESS` and `HOME` | agy stores credentials via *"Linux secret-service via dbus"* ([troubleshooting docs](https://antigravity.google/docs/cli/troubleshooting/)). Observed locally: no token file under `~/.gemini/antigravity-cli`. Expected: from cron or a system service without the session bus, agy can't reach the keyring and reports "authentication required". A locked keyring may pop an unlock dialog (unverified). |
| **Optionally disable self-update during probes** | `AGY_CLI_DISABLE_AUTO_UPDATE=true` in the child env. The value must be the literal `true`: `1` does not work ([google-antigravity/antigravity-cli#1046](https://github.com/google-antigravity/antigravity-cli/issues/1046), open, agy 1.2.6). | The documented switch ([troubleshooting docs](https://antigravity.google/docs/cli/troubleshooting/)). It keeps a background updater from starting on our schedule. Whether to set it is a product choice, since users may want agy to stay updated. |
| **Never read agy's logs** | Don't ingest `~/.gemini/antigravity-cli/log/*` | Observed locally (2026-09-28): agy's log files include the signed-in account's email address. Print-mode runs are expected to write their own log files too. |
| **Never log in on the user's behalf** | Show "run `agy` in a terminal to sign in" | Login is interactive and account-sensitive, and automating it is the kind of third-party access the terms forbid |

A minimal Python sketch of the spawn (illustrative, not final code):

```python
import os, signal, subprocess

def run_agy_usage(agy_path: str, workdir: str, timeout_s: int = 90) -> subprocess.CompletedProcess:
    keep = ("HOME", "PATH", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "LANG")
    env = {k: v for k, v in os.environ.items() if k in keep}
    env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "true"   # optional; must be literally "true"
    p = subprocess.Popen(
        [agy_path, "-p", "/usage", "--output-format", "json"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=workdir, env=env, start_new_session=True,   # new session = no controlling TTY
    )
    try:
        out, err = p.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)   # whole process group
        p.communicate()
        raise
    finally:
        try:
            # Clean up leftovers in the group even on success. Helpers that start
            # their own session escape this; CodexBar tags probes with an env
            # marker to find those.
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    # Real code should stream-read with a size cap instead of truncating afterward.
    return subprocess.CompletedProcess(p.args, p.returncode, out[:1 << 20], err[:64 << 10])
```

---

## 7. Freshness

Unlike Codex rollout files or Claude's statusline data, `agy -p /usage` **asks the backend every time**, so a successful result is current as of the poll. Freshness problems come from elsewhere:

- **Between polls**, the value can be up to one poll interval old. Show "as of HH:MM" in the tooltip.
- **After a failure**, keep the last good value but mark it stale. Once any bucket's `reset_time` has passed, that bucket's old value is meaningless: show "reset since last check", not the old percentage.
- **A tool may mask a failed refresh as old data.** In [razzant/claudexor#269](https://github.com/razzant/claudexor/issues/269), a failed quota refresh (`403 … UNSUPPORTED_LOCATION`) disappeared and a snapshot from weeks earlier kept being shown. The report doesn't make clear whether that stale value came from agy or from that tool's cache. Either way, the monitor should record its own `fetched_at`, trust only a successful envelope from *this* run, and never present an older value as current.

---

## 8. gemini-cli notes: `/stats` vs `/stats model`

For Code Assist Standard/Enterprise users (the only subscription users gemini-cli still serves), quota is visible inside gemini-cli:

- **`/stats`** (alias **`/usage`**) and **`/stats session`** call a quota refresh before displaying.
- **`/stats model`** only shows **cached** quota values and does **not** refresh.

Source: [`packages/cli/src/ui/commands/statsCommand.ts`](https://github.com/google-gemini/gemini-cli/blob/main/packages/cli/src/ui/commands/statsCommand.ts) (`main`, fetched 2026-09-28; the same behavior at `2fe7c2d3`). An earlier draft of this research had this backwards.

How gemini-cli gets those numbers (from its open-source code, for understanding only; **the monitor must not make these calls**, see [section 2](#2-policy-never-call-googles-backends-directly)):

- `POST https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist` returns the account tier (`free-tier`, `legacy-tier`, `standard-tier`), plus `ineligibleTiers[]` with reason codes.
- `POST …/v1internal:retrieveUserQuota` returns `buckets[]` of `{remainingAmount?, remainingFraction?, resetTime (ISO 8601), tokenType?, modelId?}`.
- gemini-cli derives a limit as `remainingAmount / remainingFraction` (or uses a 0 to 100 scale when only the fraction is present). It refreshes at startup and on `/stats`, and treats cached data older than 30 s as stale (`packages/core/src/config/config.ts`, `packages/core/src/code_assist/server.ts`, `types.ts` at `2fe7c2d3`).

For historical reference, gemini-cli's docs listed daily request caps of Code Assist individual 1,000, AI Pro 1,500, AI Ultra 2,000, free API key 250 (Flash only), Standard 1,500 and Enterprise 2,000 (`docs/resources/quota-and-pricing.md` at `2fe7c2d3`). Google Cloud's quota page (last updated 2026-09-24) now lists only Standard (1,500) and Enterprise (2,000) per user per day ([docs.cloud.google.com/gemini/docs/quotas](https://docs.cloud.google.com/gemini/docs/quotas), fetched 2026-09-28). The consumer rows no longer apply after the June 2026 change.

gemini-cli has no documented non-interactive way to print quota as JSON, so v1 of this app does not support gemini-cli quota.

---

## 9. Options considered and rejected

| Option | Why rejected |
|---|---|
| Call `cloudcode-pa` / `daily-cloudcode-pa` with the CLI's tokens | Forbidden by both Google terms docs, with suspensions on record ([section 2](#2-policy-never-call-googles-backends-directly)) |
| Call agy's local language server | CSRF-gated since 1.2.2, and still third-party access |
| Parse agy's logs (they contain quota errors such as "Resets in …") | Logs contain the signed-in email. They are also unstructured, and they only record what happened during a session. |
| Scrape the agy TUI (`/usage` panel) in a PTY | Fragile, and needs a terminal, which invites interactive login ([section 6](#6-invocation-guardrails)) |
| Count gemini-cli session files as a usage proxy (one Waybar tool does this) | Not plan usage, and gemini-cli no longer serves personal accounts |
| An agy statusline or hook feed, if one is offered | Only updates while the agy TUI is running and in use. That is the same "old data looks current" problem as a statusline bar. |
| Wrap the CodexBar CLI for Google data | Its Gemini provider and Antigravity OAuth fallback use the forbidden direct-access pattern. Only its agy print-mode path is acceptable. |

---

## 10. Recommended design

```
on poll (every 5–10 min + jitter, or on user click):
    if agy not installed:                  state = not_configured ("Install Antigravity CLI")
    elif agy --version < 1.1.11:           state = unsupported ("Update Antigravity CLI")
    else:
        run agy -p /usage --output-format json   (guardrails from section 6)
        if success:   parse (section 5); state = ok; as_of = now
        elif auth:    state = auth ("Run `agy` in a terminal to sign in")
        elif not eligible: state = not_eligible
        else:         state = error; keep last good value, marked stale; back off
render per group (Gemini Models / Claude and GPT models):
    one meter per enabled bucket, labeled by classified window ("5-hour", "Weekly"),
    showing percent USED and time until reset_time; disabled buckets hidden or "n/a"
```

Normalized record, the same shape as the Codex provider (see [codex-usage-sources.md](codex-usage-sources.md#12-recommended-design)):

```json
{
  "provider": "antigravity",
  "account": "<user nickname>",
  "plan": null,
  "status": "ok | stale | auth | not_eligible | unsupported | error | not_configured",
  "source": "agy-print",
  "as_of": "2026-09-28T12:00:00Z",
  "limits": [
    {"key": "Gemini Models/gemini-weekly", "label": "Gemini · Weekly", "used_percent": 88.0,
     "window_minutes": 10080, "resets_at": "2026-10-05T00:00:00Z"}
  ]
}
```

`plan` is `null` because `/usage` is not expected to report a plan tier (unverified). Let the user label the account instead.

---

## 11. Open questions

- **Real payload values:** the actual `window` strings, bucket `id`s, group names and whether `disabled: false` or empty `groups` ever appear. One supervised run of `agy -p /usage --output-format json`, with the output reviewed before committing it as a fixture, would settle this. The payload isn't expected to contain personal data, but review it before committing it anyway.
- **Float noise and `remaining_amount`:** confirm with a live sample whether `remaining_fraction` shows float noise and when `remaining_amount` appears instead.
- **Is `reset_time` always UTC (`Z`)?** Parse any offset regardless.
- **Latency and memory of one run** on a typical Linux desktop. Third-party reports suggest a few seconds per run; not measured here.
- **Keyring behavior** when the Secret Service collection is locked: does agy fail fast, or trigger an unlock prompt? Unverified.
- **Multiple Google accounts:** agy appears to hold one signed-in account at a time. Whether it supports separate profiles (the way `CODEX_HOME` does for Codex) was not researched.
- **Plan tier:** whether agy exposes the plan tier in a documented, non-interactive way.
- **Long-term risk:** no report was found tying a suspension to running agy's own `/usage` in print mode (searched 2026-09-28), but Google's enforcement is opaque (see the 2026-06-23 thread). Keep polling conservative.

---

## 12. Sources

Official Google sources (fetched 2026-09-28):

- Google Developers Blog, "An important update: Transitioning Gemini CLI to Antigravity CLI" (2026-05-19): <https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/>
- Gemini Code Assist consumer deprecation (last updated 2026-09-02): <https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals>
- Antigravity CLI headless mode: <https://antigravity.google/docs/cli/headless>
- Antigravity CLI `/usage` command: <https://antigravity.google/docs/cli/commands/usage>
- Antigravity CLI troubleshooting (auto-update switch, Linux Secret Service via D-Bus): <https://antigravity.google/docs/cli/troubleshooting/>
- Antigravity plans: <https://antigravity.google/docs/plans?app=cli>
- Antigravity terms, clause 6: <https://antigravity.google/terms>
- Antigravity changelog (web, 1.1.28 and later): <https://antigravity.google/changelog>
- agy release notes, 1.1.11 entry, as shipped inside agy 1.2.11 (read locally 2026-09-28)
- Google Cloud Gemini quotas (last updated 2026-09-24): <https://docs.cloud.google.com/gemini/docs/quotas>
- gemini-cli terms doc (clause added 2026-02-27, commit `83a3851dfd`): <https://github.com/google-gemini/gemini-cli/blob/main/docs/resources/tos-privacy.md>
- gemini-cli `/stats` command source: <https://github.com/google-gemini/gemini-cli/blob/main/packages/cli/src/ui/commands/statsCommand.ts>
- google-antigravity/antigravity-cli issue #1046 (auto-update env value): <https://github.com/google-antigravity/antigravity-cli/issues/1046>

Community and enforcement reports (fetched 2026-09-28):

- Google AI Developers Forum thread #122778 (created 2026-02-12; ban for quota tracking 2026-02-27; automated unban 2026-03-02): <https://discuss.ai.google.dev/t/account-restricted-without-warning-google-ai-ultra-oauth-via-openclaw/122778?page=3>
- Google AI Developers Forum thread #172309 (2026-06-23): <https://discuss.ai.google.dev/t/appeal-request-agy-this-service-has-been-disabled-in-this-account-for-violation-of-terms-of-service/172309/2>
- razzant/claudexor issue #269 (2026-09-04; 30 s polling side effects, masked refresh failure): <https://github.com/razzant/claudexor/issues/269>

Public parsers and prior art (fetched 2026-09-28):

- CodexBar Antigravity docs: <https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md>
- CodexBar Gemini docs: <https://github.com/steipete/CodexBar/blob/main/docs/gemini.md>
- CodexBar provider matrix: <https://github.com/steipete/CodexBar/blob/main/docs/providers.md>
- CodexBar agy fixture/tests: <https://github.com/steipete/CodexBar/blob/main/Tests/CodexBarTests/AntigravityCLIUsageReportTests.swift>
- CodexBar PR #3685 (agy 1.2.2 CSRF change): <https://github.com/steipete/CodexBar/pull/3685>
- Orca PR #23426 (agy print-mode usage, version gate): <https://github.com/stablyai/orca/pull/23426>
- Orca issue #22511 (bucket ids seen on agy 1.2.9): <https://github.com/stablyai/orca/issues/22511>
- quota-axi (sanitized agy fixture): <https://github.com/kunchenguid/quota-axi>

Local observations (2026-09-28, agy 1.2.11, gemini-cli 0.61.0, Linux): no agy token file on disk (keyring storage); agy logs contain the account email; one agy log recorded a weekly-reset 429 on what appears to be a free-tier account; gemini-cli bundles an Antigravity migration skill; gemini-cli settings use the personal OAuth login type.
