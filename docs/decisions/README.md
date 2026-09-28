# Decision records

Each file records one decision: the context, what we chose, what we rejected, and the
consequences. They are short on purpose. If a decision changes, add a new record that
supersedes the old one; don't rewrite history.

| # | Decision | Status | Date |
|---|----------|--------|------|
| [0001](0001-never-refresh-claude-tokens.md) | Never refresh (or write) Claude Code's OAuth tokens | Accepted | 2026-09-28 |
| [0002](0002-claude-get-usage-primary.md) | Claude Code's `get_usage` is the primary Claude source | Accepted | 2026-09-28 |
| [0003](0003-honest-user-agent.md) | Identify as ourselves; never borrow another client's User-Agent | Accepted | 2026-09-28 |
| [0004](0004-remove-sessionkey-paste.md) | Remove "Paste session key" and the keyring dependency | Accepted | 2026-09-28 |
| [0005](0005-linux-tray-gtk-statusicon.md) | Linux tray uses native `Gtk.StatusIcon`, not pystray | Accepted | 2026-09-28 |
| [0006](0006-one-icon-per-provider.md) | One tray icon per AI, colored by its most-used limit | Accepted | 2026-09-28 |
| [0007](0007-provider-architecture.md) | Provider plug-ins with `fetch()` + `peek()` and a neutral model | Accepted | 2026-09-28 |
| [0008](0008-local-sources-and-freshness.md) | Local snapshots as free backups, trusted only by timestamp | Accepted | 2026-09-28 |
| [0009](0009-gemini-via-agy-only.md) | Gemini usage only via the Antigravity CLI (`agy -p /usage`) | Accepted (not built yet) | 2026-09-28 |
| [0010](0010-linux-paths-autostart-single-instance.md) | XDG paths, `.desktop` autostart, Unix-socket single instance | Accepted | 2026-09-28 |
| [0011](0011-rate-limit-budget.md) | Keep the client-side rate-limit budget; flyout opens don't spend it | Accepted | 2026-09-28 |
