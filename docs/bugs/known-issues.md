# Known issues and bug log

Newest first within each section. When fixing something, move it to **Fixed** with the
commit or branch.

## Open

| # | Issue | Impact | Notes / next step |
|---|-------|--------|-------------------|
| O1 | `get_usage` after token expiry not yet observed | Unknown until tested | Expected to work (Claude Code refreshes on use). Test plan in [phase-1](../plans/phase-1-linux-claude.md#not-verified-yet). |
| O2 | `get_usage` is experimental upstream | Could break on a Claude Code update | Fallbacks cover it (API, local snapshots). Re-run `python3 probe.py` after Claude Code updates; it auto-updates often (2.1.283 → 2.1.284 on 2026-09-28). |
| O3 | `Gdk-CRITICAL … gdk_window_thaw_toplevel_updates` logged once at startup | Cosmetic (stderr only) | Comes from `Gtk.StatusIcon` embedding. Harmless; goes away with an SNI backend. |
| O4 | XFCE draws the XEmbed tray icon on an opaque square | Cosmetic | Same as other legacy icons (nm-applet, Notes, Clipman). SNI backend (roadmap backlog). |
| O5 | No Wayland tray | Linux Wayland users get no icon | `Gtk.StatusIcon` is X11-only. SNI backend (backlog). The window still works. |
| O6 | Windows and macOS trays not re-tested after the rewrite | May break | Phases 2 and 3. |
| O7 | The status line reports usage only after a model response | Status-line data can be old | Handled by timestamps ([0008](../decisions/0008-local-sources-and-freshness.md)); listed here so nobody "fixes" it by trusting redraw time. |
| O8 | Per-model limits count toward the icon color | Might surprise | By design ([0006](../decisions/0006-one-icon-per-provider.md)); revisit on feedback. |
| O9 | Notifications re-fire once after an app restart | Minor | Fired thresholds live in memory only. Persist if it's annoying. |
| O10 | Windows installer's Startup-folder shortcut is invisible to the "Start on login" toggle; enabling the toggle too causes a double launch (pre-existing, from v1) | Windows | Phase 2: make HKCU Run the only mechanism, drop the `{userstartup}` shortcut, and delete it on upgrade. |
| O11 | `get_usage` answers from Claude Code's saved snapshot first (observed 2026-09-28) | Handled | The app waits up to 4 s for the refreshed snapshot ([0002](../decisions/0002-claude-get-usage-primary.md)). If a Claude Code update changes this timing, checks may show one poll's lag, which gets labeled, not hidden. |

## Fixed on `linux-multi-ai` (2026-09-28)

Bugs found in v1 (commit `98a4863`) during the research review:

| # | Bug (v1) | Severity | Fix |
|---|----------|----------|-----|
| F1 | **Token refresh could log Claude Code out.** `auth._refresh_oauth` redeemed Claude Code's single-use refresh token and kept the result in its own keyring, so Claude Code's next refresh failed and every session on that config dir was signed out. Without `keyring` installed, it retried on *every* fetch. | Critical | Removed; credentials are read-only ([0001](../decisions/0001-never-refresh-claude-tokens.md)). |
| F2 | Refresh posted to the stale `console.anthropic.com` token URL and omitted `scope`. | High | Moot (no refresh). |
| F3 | User-Agent impersonated Claude Code (`claude-code/…`) and always sent a stale version, because version sniffing read nonexistent keys. | High | Honest User-Agent ([0003](../decisions/0003-honest-user-agent.md)). |
| F4 | "Paste session key" stored a claude.ai session cookie (prohibited by Anthropic's terms). Its org picker used `memberships[0]` (can be an API org → `permission_error`), and it was never tried after a server-side 401. | High | Feature removed ([0004](../decisions/0004-remove-sessionkey-paste.md)). |
| F5 | Opening the flyout or window forced a fetch every time, burning the ~5-request burst. | Medium | Fetch only if the data is older than 90 s ([0011](../decisions/0011-rate-limit-budget.md)). |
| F6 | `Retry-After` in HTTP-date form was ignored. | Low | Both forms parsed (`api._retry_after`). |
| F7 | Unsynchronized `_fetching` / `_manual_pending` flags could double-fetch on a race. | Low | Worker owns scheduling; manual refresh is an `Event`. |
| F8 | Single-instance TCP port 49219 is inside Linux's ephemeral range → possible silent no-start. | Medium (Linux) | Unix socket on Linux/macOS ([0010](../decisions/0010-linux-paths-autostart-single-instance.md)). |
| F9 | `monitor.log` grew without limit. | Low | Rotating log, 512 KB. |
| F10 | Windows dev-mode autostart (`pythonw -m claude_usage_monitor`) had no working directory, so it couldn't import the package. | Low | Runs `run.py` by absolute path. |
| F11 | No Linux autostart; the tray menu said "Start on Windows login" on every OS. | Medium (Linux) | `.desktop` autostart; menu says "Start on login". |
| F12 | UI and data model hard-coded two Claude windows; per-model weekly limits and extra usage were parsed but dropped. | Medium | Neutral `Snapshot`/`Meter` model ([0007](../decisions/0007-provider-architecture.md)). |
| F13 | `config.py` comment said the endpoint limits "if polled faster than ~120–180 s", contradicting the 65/70 s constants. | Doc | Constants and comments reconciled (auto ≥ 120 s, fast 90 s, bucket 5 / 65 s). |
| F14 | `tools/rate_test.py` could be run by accident against a real account (long lockouts), and it still sent Claude Code's User-Agent. | Medium | Deleted. |

### Found by the multi-lens code review of this branch (2026-09-28), all fixed

35 findings confirmed by adversarial verification (none critical/high); duplicates merged:

| # | Bug | Fix |
|---|-----|-----|
| R1 | A timed-out `claude` was SIGKILLed after 53 s, possibly in the middle of Claude Code's own token refresh (logout risk). Only the leader was killed; a surviving helper holding the pipes could freeze the worker thread indefinitely. | No SIGKILL: return right away, then a background reaper waits 90 s and sends SIGTERM to the group; reader threads own their pipes. |
| R2 | An inherited `CLAUDE_CONFIG_DIR` made the app read `~/.claude` while `claude` answered for another dir (wrong login state, ignored local sources). | One `effective_dir` for all paths and the child env. |
| R3 | `CLAUDE_CODE_OAUTH_TOKEN`, Bedrock/Vertex/Foundry switches, and `ANTHROPIC_BASE_URL` reached the child. | Scrubbed. |
| R4 | `rate_limits: null` (server unreachable) was reported as "not logged in". | Split from `rate_limits_available: false`. |
| R5 | A reply parsed to zero limits wiped good data and skipped the backups. | Counts as a failure. |
| R6 | Answers served from the saved snapshot dropped the per-model rows that were on disk. | Use the disk copy. |
| R7 | One fresh status-line row made old per-model rows look current (icon not grayed, alerts on old data). | Per-limit age everywhere. |
| R8 | Status-line rows could be inserted into a newer snapshot; future-dated or malformed drop files could win or crash a fetch. | Guards + try/except around the overlay. |
| R9 | The hook's freshness came from transcript mtime (also bumped by `/model`, `/clear`, prompts) or fell back to "now". | Last real assistant timestamp; no fallback. |
| R10 | The usage API call followed redirects, which would forward the bearer token to any host. | Redirects disabled. |
| R11 | A Refresh-flag race could wedge the button on "Refreshing…"; a refresh during the startup fetch spent a second request. | Clear-if-set, join in-flight checks, 180 s watchdog. |
| R12 | No way to quit if the tray can't be shown (Wayland, no GTK); `--tray` autostart invisible. | Tray health check → window with Quit. |
| R13 | Flyout placement used the whole X screen (straddled monitors) and could grow off-screen. | Icon geometry + monitor work area from GTK; re-clamp on growth. |
| R14 | Saved window position could be off-screen after a monitor change; reopening a visible window made it jump. | Bounds check; don't reposition a visible window. |
| R15 | Windows: threshold alerts went nowhere (notify-send/osascript only); tooltip cut mid-line at 128 chars, losing the age and the note. | Alerts via the tray balloon on Windows; tooltips trimmed by whole lines in priority order. |
| R16 | Fast Update ran every 120 s, not the documented 90 s. | Provider floor = 90 s. |
| R17 | `.desktop` `Exec=` wasn't escaped (`%`, quotes, `$`). | Spec-compliant escaping. |
| R18 | Socket fallback used a predictable name in shared `/tmp`. | Private cache dir. |
| R19 | Icon showed an oversized "100" at 99.5–99.9%. | Caps at 99; `!!` only at 100%. |
| R20 | Tests could read real credentials / hit the network on Windows (`USERPROFILE`) and macOS (Keychain). | Harness patches both and blocks all HTTP. |
