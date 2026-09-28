# Phase 1 — Linux + Claude

- **Branch:** `linux-multi-ai`
- **Started / landed:** 2026-09-28
- **Target:** MX Linux 25.3 (Debian 13), XFCE 4.20 on X11, Python 3.13, Claude Code 2.1.28x.

## Scope

1. Run on Linux, with a native tray (decision [0005](../decisions/0005-linux-tray-gtk-statusicon.md)),
   the flyout, the pop-out window, notifications, autostart, and an app-menu entry.
2. Replace the Claude data path with `get_usage` + read-only fallbacks
   ([0001](../decisions/0001-never-refresh-claude-tokens.md),
   [0002](../decisions/0002-claude-get-usage-primary.md),
   [0003](../decisions/0003-honest-user-agent.md),
   [0004](../decisions/0004-remove-sessionkey-paste.md),
   [0008](../decisions/0008-local-sources-and-freshness.md)).
3. Generalize everything for N providers and N limits
   ([0006](../decisions/0006-one-icon-per-provider.md),
   [0007](../decisions/0007-provider-architecture.md)).
4. Fix the v1 bugs listed in [bugs/known-issues.md](../bugs/known-issues.md).
5. Write down research, decisions, and plans (this `docs/` tree).

Out of scope: Codex, Gemini, multiple accounts, Windows/macOS re-testing (phases 2–6).

## What changed (file map)

| File | Change |
|------|--------|
| `model.py` | **New.** `Meter`, `Snapshot`, time helpers, tooltip text |
| `providers/base.py`, `providers/__init__.py` | **New.** Provider interface + registry |
| `providers/claude/{__init__,account,cli_usage,api,local,parse}.py` | **New.** Claude provider (replaces `auth.py` + `usage_api.py`) |
| `icons.py` | **New.** Ring + number tray icon renderer (shared by all trays) |
| `tray_linux.py` | **New.** Native GTK tray |
| `notify.py` | **New.** Notifications + once-per-threshold logic |
| `singleinstance.py` | **New.** Unix socket (Linux/macOS), TCP (Windows) |
| `linux_desktop.py` | **New.** `.desktop` launcher, autostart entry, icon export |
| `app.py` | Rewritten orchestration: per-provider schedule, peek loop, CLI flags |
| `panel.py`, `popup.py` | Dynamic sections; Linux flyout opens next to the pointer |
| `config.py` | XDG paths, rotating log, Linux autostart, new prefs |
| `tray.py`, `tray_macos.py` | Ported to the one-icon-per-provider API (**untested** on those OSes) |
| `auth.py`, `usage_api.py` | **Deleted** (token refresh, cookie path, keyring) |
| `rate_test.py` | **Deleted** (hammered the endpoint; impersonated Claude Code) |
| `tests/test_claude.py` | **New.** 44 unit tests, including a fake `claude` CLI |

## Verification done (2026-09-28)

- `python3 -m unittest discover -s tests`: 44 tests pass, including under
  `-W error::ResourceWarning`.
- A six-lens code review (concurrency, provider logic, subprocess, security/privacy, UI,
  cross-platform), with every finding checked by a skeptical verifier: 35 confirmed
  findings, all medium/low, all fixed (known-issues R1–R20) except the pre-existing
  Windows installer autostart issue (O10, Phase 2).
- Live: `get_usage` answers from Claude Code's saved snapshot first and refreshes it about
  1 s later. The app waits for that refresh, so a check shows data "just now".
- `python3 probe.py`: live read through Claude Code in about 1.3 s: Max 5x, 5-hour,
  weekly, and "Weekly · Fable" limits.
- The direct API with the honest User-Agent returned HTTP 200.
- GUI smoke test (`tools/smoke_gui.py`) on XFCE: tray icon visible in the vertical deskbar
  (ring + "80"), window renders all three limits, flyout opens next to the pointer and
  toggles closed, no Tk callback exceptions.
- The status-line hook was tested with sample input: output byte-identical, drop file
  written, empty input handled.

## Not verified yet

- `get_usage` when Claude Code's access token has **expired** (expected: Claude Code
  refreshes it itself). Check after the token's 8-hour window lapses with no Claude Code
  running: the monitor should keep working and `~/.claude/.credentials.json` should get a
  new mtime written by Claude Code.
- Right-click menu, "Start on login" toggle, and notifications were exercised in code
  paths and unit tests, but not clicked through by hand yet.
- Windows and macOS (phases 2–3).
