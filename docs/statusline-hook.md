# Optional: Claude Code status-line hook

**What it does:** Claude Code hands your status-line script your plan usage (5-hour and
weekly) every time it redraws, even if your status line doesn't display it. This small
function saves those numbers to a file that AI Usage Monitor reads as a free backup
source. **Your status line looks exactly the same.**

**Why it's optional:** the monitor's main source is Claude Code's own `get_usage`
([decision 0002](decisions/0002-claude-get-usage-primary.md)). The hook just lets the tray
update the moment you get a response, at zero cost, and covers the case where `get_usage`
ever breaks.

**Staleness:** the status line only gets new numbers after a model response. The hook
records *when that response happened* (the transcript's modification time), not when the
line was redrawn. The monitor only uses the numbers if they're newer than what it already
has ([decision 0008](decisions/0008-local-sources-and-freshness.md)). A Claude Code window
left idle for days can't push old numbers.

## Add it

1. Paste this function into your status-line script (Python), above `main()`:

```python
def save_plan_usage(input_data):
    """Save the 5-hour/weekly plan usage Claude Code passes to this script, so AI Usage
    Monitor (github.com/jj70785/claude-usage-monitor) can use it as a free backup source.
    Never changes what the status line shows, and can't break it (all errors ignored)."""
    try:
        rl = input_data.get('rate_limits')
        if not isinstance(rl, dict) or not rl:
            return
        # When Claude Code last got a response in this session: an idle session keeps
        # redrawing old numbers, so the redraw time would lie about freshness.
        tp = input_data.get('transcript_path')
        observed_ms = int((os.path.getmtime(tp) if tp and os.path.exists(tp) else datetime.now().timestamp()) * 1000)
        base = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
        path = os.path.join(base, 'ai-usage-monitor', 'claude-statusline.json')
        try:
            with open(path, encoding='utf-8') as f:
                if json.load(f).get('observed_at', 0) > observed_ms:
                    return          # another session already saved something newer
        except (OSError, ValueError):
            pass
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'rate_limits': rl, 'observed_at': observed_ms,
                       'config_dir': os.environ.get('CLAUDE_CONFIG_DIR') or None}, f)
        os.replace(tmp, path)
    except Exception:
        pass
```

2. Call it first thing in `main()`, right after you parse stdin:

```python
def main():
    input_data = json.load(sys.stdin)   # or however your script reads it
    save_plan_usage(input_data)
    ...
```

It needs `import json, os` and `from datetime import datetime` at the top (most status-line
scripts already have them).

## File format

`~/.cache/ai-usage-monitor/claude-statusline.json` (the same path on every OS;
`$XDG_CACHE_HOME` is respected):

```json
{
  "rate_limits": {
    "five_hour": {"used_percentage": 68, "resets_at": 1790647199},
    "seven_day": {"used_percentage": 80, "resets_at": 1790823599}
  },
  "observed_at": 1790625250566,
  "config_dir": null
}
```

`rate_limits` is passed through exactly as Claude Code provides it (documented at
<https://code.claude.com/docs/en/statusline>, available since Claude Code 2.1.80, Pro/Max
plans only). `config_dir` keeps different Claude accounts apart.
