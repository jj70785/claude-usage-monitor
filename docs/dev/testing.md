# Developing and testing

## Run from source (Linux)

```sh
sudo apt install python3-tk python3-gi gir1.2-gtk-3.0 python3-pil   # one time
python3 -m claude_usage_monitor            # window + tray
python3 -m claude_usage_monitor --tray     # tray only
python3 -m claude_usage_monitor --probe    # print usage, no GUI
python3 -m claude_usage_monitor --install  # add to the app menu (--uninstall to remove)
```

Logs: `~/.config/ai-usage-monitor/monitor.log`. They never contain tokens, emails, or raw
provider output. Keep it that way.

## Tests

```sh
python3 -m unittest discover -s tests -v
python3 -W error::ResourceWarning -m unittest discover -s tests   # also catch leaked pipes
```

- Stdlib `unittest` only; no pip installs.
- **No test may touch the network, the real `claude` CLI, or real credentials.** The
  `TempHome` base class points `HOME` and the `XDG_*` variables at a temp dir, and CLI tests
  use a fake `claude` script that speaks the stream-json protocol (`fake_claude()`).
- When you add a provider, add a `tests/test_<provider>.py` in the same style.

## Manual checks

- `python3 tools/smoke_gui.py`: runs the full app for about 9 s, prints what each provider
  loaded, and reports any Tk callback exceptions.
- **Never** run `tools/rate_test.py` against an account you care about
  ([decision 0011](../decisions/0011-rate-limit-budget.md)).

## Ground rules for contributors (and AI agents)

- Read [decisions/](../decisions/README.md) before changing how data is fetched.
  Especially: never refresh or write another tool's credentials (0001), never impersonate
  another client (0003), and never store credentials (0004).
- Keep American spelling in code, comments, and docs.
- Don't commit anything from private repositories, and never commit tokens, emails,
  account IDs, or screenshots of someone's desktop.
