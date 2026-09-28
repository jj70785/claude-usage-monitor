# 0010 — XDG paths, `.desktop` autostart, Unix-socket single instance

- **Status:** Accepted
- **Date:** 2026-09-28

## Decision

| Concern | Linux | Windows / macOS (unchanged) |
|---------|-------|-----------------------------|
| Settings | `$XDG_CONFIG_HOME/ai-usage-monitor/prefs.json` (+ `monitor.log`) | `%APPDATA%\ClaudeUsageMonitor\` / `~/Library/Application Support/ClaudeUsageMonitor/` |
| Cache | `$XDG_CACHE_HOME/ai-usage-monitor/` (`last_snapshots.json`, `claude-probe/`) | same folder as settings |
| Status-line drop file | `$XDG_CACHE_HOME/ai-usage-monitor/claude-statusline.json` | the **same** `~/.cache/…` path, so one status-line script works everywhere |
| Start on login | `~/.config/autostart/ai-usage-monitor.desktop` (tray menu toggle) | HKCU `Run` value (Windows); not yet on macOS |
| App menu entry | `python3 -m claude_usage_monitor --install` → `~/.local/share/applications/ai-usage-monitor.desktop` | Inno Setup shortcuts (Windows) |
| Single instance | Unix socket `$XDG_RUNTIME_DIR/ai-usage-monitor.sock` (mode 0600; stale sockets from a crash are detected and replaced) | loopback TCP port 49219 (Windows) |
| Log | rotating, 512 KB × 3 | same |

## Why

- v1's TCP port 49219 sits inside Linux's ephemeral port range (32768–60999). An
  unrelated outgoing connection could hold it, making the app think it was already running
  and exit silently.
- v1's `monitor.log` grew without limit (one line per fetch, forever).
- v1's Windows dev-mode autostart ran `pythonw -m claude_usage_monitor` with no working
  directory, so it couldn't find the package. Autostart now runs `run.py` by absolute path.
