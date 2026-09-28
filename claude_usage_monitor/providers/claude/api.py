"""Fallback: call the usage endpoint directly with Claude Code's access token.

Rules (docs/decisions/0001 and 0003):
- READ the token only. Never refresh it: refresh tokens rotate, and redeeming one
  logs Claude Code out. If the token is stale, report that and wait for Claude Code.
- Identify as ourselves. We do not borrow Claude Code's User-Agent (tested 2026-09-28:
  the endpoint answers an honest User-Agent with HTTP 200).
- One request per call, no retries; 429 backs off for the server's Retry-After.
"""
from __future__ import annotations

import email.utils
import json
import ssl
import time
import urllib.error
import urllib.request
from typing import Optional

from ... import __version__, config
from ..base import NotLoggedIn, ProviderError, RateLimited
from .account import LoginInfo

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USER_AGENT = f"ai-usage-monitor/{__version__} (+https://github.com/jj70785/claude-usage-monitor)"

# Stdlib urllib uses the OS certificate store via the default SSL context, so the
# packaged Windows exe needs no bundled CA file.
_SSL_CTX = ssl.create_default_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib copies the Authorization header onto redirects, to any host and even
    https -> http. A usage GET has no business being redirected, so treat any 3xx as
    an error instead of forwarding Claude Code's token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_SSL_CTX))


def _retry_after(value: Optional[str]) -> Optional[int]:
    """Retry-After as delta-seconds or an HTTP-date."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
        return max(0, int(when.timestamp() - time.time()))
    except (TypeError, ValueError):
        return None


def fetch(login: LoginInfo) -> dict:
    if login.state != "fresh" or not login.access_token:
        raise NotLoggedIn("Claude Code's token is expired — it refreshes the next time Claude Code runs")
    req = urllib.request.Request(USAGE_URL, method="GET", headers={
        "Authorization": f"Bearer {login.access_token}",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with _OPENER.open(req, timeout=config.HTTP_TIMEOUT_SEC) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise NotLoggedIn("Claude rejected the saved token — open Claude Code to refresh it") from e
        if e.code == 429:
            raise RateLimited(_retry_after(e.headers.get("retry-after"))) from e
        raise ProviderError(f"usage API returned HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ProviderError(f"network error: {getattr(e, 'reason', e)}") from e
