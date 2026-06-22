"""PyInstaller entry point (a plain script, since -m packages aren't entry points)."""
from claude_usage_monitor.app import main

if __name__ == "__main__":
    main()
