"""AI Usage Monitor — a lightweight tray app that shows your AI subscription plan usage
(Claude today; Codex and Gemini next) without opening a browser.

Claude data comes from Claude Code itself (its `get_usage` control request), with
read-only fallbacks. See docs/README.md.
"""

__version__ = "2.0.0.dev0"
APP_NAME = "AI Usage Monitor"
