"""Print what the monitor sees right now, without the GUI (same as `--probe`).

Never prints tokens or account details.
"""
from claude_usage_monitor.app import main

if __name__ == "__main__":
    main(["--probe"])
