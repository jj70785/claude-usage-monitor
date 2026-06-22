"""Authentication: get a usable credential for the usage endpoint.

Primary path (zero setup): read the OAuth access token that Claude Code stores in
~/.claude/.credentials.json. If it's expired, try a refresh; if that fails, fall
back to a manually-pasted claude.ai sessionKey cookie stored in the OS keyring.

Returns an `Auth` describing HOW to call the API; usage_api.py picks the endpoint.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

from . import config

# Claude Code's public OAuth client id + token endpoint (used only if we ever need
# to refresh an expired token ourselves). Best-effort; primary path relies on
# Claude Code keeping the file fresh.
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"

DEFAULT_CC_VERSION = "2.1.178"
EXPIRY_SKEW_SEC = 60  # treat token as expired this many seconds early

SESSIONKEY_RE = re.compile(r"^sk-ant-sid\d{2}-[A-Za-z0-9_-]{40,}$")


@dataclass
class Auth:
    kind: str                      # "oauth" | "cookie"
    token: str                     # bearer access token, or sessionKey value
    org_uuid: Optional[str] = None  # only for cookie path
    subscription: Optional[str] = None  # e.g. "max", "pro"
    user_agent: str = f"claude-code/{DEFAULT_CC_VERSION}"


class AuthError(Exception):
    """No usable credential available (caller should prompt the user)."""


# --- Claude Code version (for the mandatory User-Agent) -----------------------
_cc_version_cache: Optional[str] = None


def claude_code_version() -> str:
    global _cc_version_cache
    if _cc_version_cache:
        return _cc_version_cache
    ver = DEFAULT_CC_VERSION
    # Best effort: ~/.claude/.last-update-result.json may carry the version.
    try:
        p = os.path.join(os.path.dirname(config.credentials_path()), ".last-update-result.json")
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        for k in ("version", "toVersion", "latestVersion", "currentVersion"):
            v = d.get(k)
            if isinstance(v, str) and re.match(r"\d+\.\d+\.\d+", v):
                ver = v.split()[0]
                break
    except Exception:
        pass
    _cc_version_cache = ver
    return ver


def user_agent() -> str:
    return f"claude-code/{claude_code_version()}"


# --- OAuth token from Claude Code ---------------------------------------------
def _read_oauth_blob() -> Optional[dict]:
    """Read claudeAiOauth from the credentials file (Win/Linux) or macOS Keychain."""
    # File path first (Windows/Linux, and macOS if a file exists).
    path = config.credentials_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("claudeAiOauth")
        except Exception:
            pass
    # macOS Keychain fallback.
    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True, text=True, timeout=10,
            )
            if out.returncode == 0 and out.stdout.strip():
                return json.loads(out.stdout.strip()).get("claudeAiOauth")
        except Exception:
            pass
    return None


def _refresh_oauth(refresh_token: str) -> Optional[dict]:
    """Best-effort token refresh (stdlib urllib). Stores the new blob in our OWN
    keyring entry — never overwrites Claude Code's .credentials.json. Returns the
    new blob or None.
    """
    try:
        import urllib.request
        payload = json.dumps({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": OAUTH_CLIENT_ID,
        }).encode("utf-8")
        req = urllib.request.Request(
            OAUTH_TOKEN_URL, data=payload, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": user_agent()},
        )
        with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT_SEC) as r:
            d = json.loads(r.read().decode("utf-8"))
        blob = {
            "accessToken": d.get("access_token"),
            "refreshToken": d.get("refresh_token", refresh_token),
            "expiresAt": int(time.time() * 1000) + int(d.get("expires_in", 3600)) * 1000,
        }
        if not blob["accessToken"]:
            return None
        try:
            import keyring
            keyring.set_password(config.KEYRING_SERVICE, "oauth_blob", json.dumps(blob))
        except Exception:
            pass
        return blob
    except Exception:
        return None


def _cached_refreshed_blob() -> Optional[dict]:
    try:
        import keyring
        raw = keyring.get_password(config.KEYRING_SERVICE, "oauth_blob")
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _valid(blob: Optional[dict]) -> bool:
    if not blob or not blob.get("accessToken"):
        return False
    exp = blob.get("expiresAt")
    if not exp:
        return True  # no expiry info — assume usable
    return (exp / 1000.0) > (time.time() + EXPIRY_SKEW_SEC)


# --- manual sessionKey fallback -----------------------------------------------
def get_saved_session_key() -> Optional[str]:
    try:
        import keyring
        return keyring.get_password(config.KEYRING_SERVICE, "sessionKey")
    except Exception:
        return None


def save_session_key(value: str) -> bool:
    value = (value or "").strip()
    if not SESSIONKEY_RE.match(value):
        return False
    try:
        import keyring
        keyring.set_password(config.KEYRING_SERVICE, "sessionKey", value)
        return True
    except Exception:
        return False


def clear_session_key() -> None:
    try:
        import keyring
        keyring.delete_password(config.KEYRING_SERVICE, "sessionKey")
    except Exception:
        pass


# --- public entry -------------------------------------------------------------
def get_auth() -> Auth:
    """Resolve the best available credential. Raises AuthError if none."""
    blob = _read_oauth_blob()
    sub = blob.get("subscriptionType") if blob else None

    if _valid(blob):
        return Auth("oauth", blob["accessToken"], subscription=sub, user_agent=user_agent())

    # Maybe a previous refresh of ours is still good.
    cached = _cached_refreshed_blob()
    if _valid(cached):
        return Auth("oauth", cached["accessToken"], subscription=sub, user_agent=user_agent())

    # Try to refresh using whichever refresh token we have.
    refresh_token = (blob or cached or {}).get("refreshToken")
    if refresh_token:
        new = _refresh_oauth(refresh_token)
        if _valid(new):
            return Auth("oauth", new["accessToken"], subscription=sub, user_agent=user_agent())

    # Fall back to a saved sessionKey cookie.
    sk = get_saved_session_key()
    if sk:
        return Auth("cookie", sk, user_agent=user_agent())

    raise AuthError(
        "No Claude Code login found and no saved session key. "
        "Open Claude Code once, or paste a claude.ai sessionKey."
    )
