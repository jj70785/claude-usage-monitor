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
| F14 | `tools/rate_test.py` could be run by accident against a real account (long lockouts). | Medium | Requires `--i-understand`. |
