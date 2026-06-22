"""Claude Usage Monitor — a lightweight system-tray app that shows your
claude.ai subscription plan usage (5-hour session window + weekly limit)
without opening a browser.

Data comes from the (unofficial) endpoint GET https://api.anthropic.com/api/oauth/usage,
authenticated with the OAuth token that Claude Code stores locally.
"""

__version__ = "1.0.0"
APP_NAME = "Claude Usage Monitor"
