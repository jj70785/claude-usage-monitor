# Roadmap

**Goal:** see every AI plan's usage at a glance (Claude, OpenAI Codex, Google Gemini, and
several accounts of each), right in the tray, without a browser tab.

**Order:** Linux first, then Windows, then macOS. Claude first, then Codex, then Gemini.

| Phase | What | Status |
|-------|------|--------|
| 1 | Linux (XFCE/X11) + Claude, provider architecture, safety fixes | **Done on branch `linux-multi-ai`** — see [phase-1-linux-claude.md](phase-1-linux-claude.md) |
| 2 | Windows re-test + installer refresh | Next |
| 3 | macOS re-test (+ `.app`/`.dmg`, login item) | Planned |
| 4 | Codex provider | Planned |
| 5 | Gemini provider via `agy` | Planned |
| 6 | Multiple Claude accounts / plan switcher | Planned (later) |
| — | Nice-to-haves | Backlog |

## Phase 2 — Windows

- Re-test the whole app on Windows: pystray icon per provider, flyout position, tooltip
  truncation (128 chars), notifications via `Icon.notify`, HKCU autostart through
  `config.launch_command()` (now runs `run.py` by absolute path).
- `cli_usage.find_claude()`: add Windows install locations (`claude.exe` / `claude.cmd`
  under `%USERPROFILE%\.local\bin`, npm global dirs) and check that `CREATE_NO_WINDOW`
  keeps a console from flashing.
- Status-line drop file: the hook writes `~/.cache/ai-usage-monitor/…` on every OS; confirm
  Windows resolves `~` to `%USERPROFILE%`.
- Installer autostart: make HKCU `Run` the only mechanism (drop the `{userstartup}`
  shortcut, delete it on upgrade), so the tray toggle reflects reality (known issue O10).
- Rebuild with PyInstaller (the spec no longer collects `keyring`) and Inno Setup; update
  names ("AI Usage Monitor") while keeping the `ClaudeUsageMonitor` settings folder, so
  upgrades keep their prefs.

## Phase 3 — macOS

- Re-test `tray_macos.py` (one `NSStatusItem` per provider, created in reverse so the
  first provider is leftmost).
- Keychain: the default account is `Claude Code-credentials`; other `CLAUDE_CONFIG_DIR`s
  use a hashed suffix. `account.py` only reads the default today; add the suffix rule
  before multi-account.
- Notifications use `osascript`; consider `UNUserNotificationCenter` once packaged.
- Login item (`SMAppService`) and `.app`/`.dmg` packaging.

## Phase 4 — Codex

Plan from [research/codex-usage-sources.md](../research/codex-usage-sources.md):

1. **Local rollout files first (zero network):** newest `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`,
   last `event_msg` of type `token_count` → `payload.rate_limits.{primary,secondary}`
   `{used_percent, window_minutes, resets_at}` plus `plan_type`. Label each window from
   `window_minutes` (300 → "5-hour", 10080 → "Weekly", 43200 → "30-day").
2. **`codex app-server` rate-limit read** as the live source (first-party; owns its own
   token refresh). Experimental upstream, so treat failures as normal.
3. Never refresh ChatGPT tokens ourselves (single-use refresh tokens, same as Claude).
- `CODEX_HOME` = the multi-account switch, like `CLAUDE_CONFIG_DIR`.

## Phase 5 — Gemini

Per [decision 0009](../decisions/0009-gemini-via-agy-only.md): `agy -p /usage --output-format json`
only; parse `command.data.groups[].buckets[]` (`remaining_fraction` or
`remaining_amount`, `reset_time`, `window`, `disabled`); poll ≤ every 5–10 min.

## Phase 6 — Multiple accounts / plan switcher

Requirements gathered so far:

- Show several Claude accounts side by side (one icon each, e.g. "Claude · Work").
- Add an account by pointing it at a `CLAUDE_CONFIG_DIR`; each needs its own one-time
  `/login`. Two config dirs on the same account are separate logins with separate token
  families.
- "Launch Claude on this account" (open a terminal with `CLAUDE_CONFIG_DIR=… claude`).
- **Switch accounts under running sessions without stopping agents.** A tester with two
  plans uses a tool that does this on macOS. Figure out the safe mechanism before building
  anything that writes credentials; decision 0001 (never write Claude's credentials)
  still stands unless a new decision replaces it.
- Must work on macOS (the main tester's machine).
- Optional: suggest the account with the most headroom.

## Backlog

- **StatusNotifierItem (SNI) tray backend** for Wayland and for XFCE without the opaque
  XEmbed square.
- **xfce4-genmon panel widget:** a tiny script that prints the cached
  `last_snapshots.json` as colored text; the app triggers
  `xfce4-panel --plugin-event=genmon-N:refresh:bool:true` after each update. The script
  must only read the cache (genmon runs commands synchronously in the panel process).
- Settings UI (refresh interval, thresholds, API fallback, per-provider enable).
- Packaging for Linux (`.deb` or AppImage).
- Rename the repository/package to match "AI Usage Monitor".
