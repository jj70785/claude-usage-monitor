"""Where a Claude Code account lives on disk, and what state its login is in.

READ-ONLY by design. Claude Code's refresh tokens are single-use and rotate: if we ever
redeemed one, Claude Code's own copy would die and every Claude Code session on that
config dir would be logged out. So this module reads, and never refreshes or writes.
See docs/decisions/0001-never-refresh-claude-tokens.md.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

LOGIN_EXPIRY_WARN_SEC = 3 * 86400     # Claude Code itself warns 3 days before a login expires

TIER_LABELS = {
    "default_claude_max_5x": "Max 5x",
    "default_claude_max_20x": "Max 20x",
}
PLAN_LABELS = {"max": "Max", "pro": "Pro", "team": "Team", "enterprise": "Enterprise", "free": "Free"}


# Variables that would make a `claude` child report something other than this plan's
# usage: API-key or third-party-cloud backends, an inference-only setup-token, and markers
# a parent Claude Code session leaves in the environment of anything it launches.
_SCRUB_ENV = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_PID",
)


def normalize_dir(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return os.path.abspath(os.path.expanduser(path)).rstrip(os.sep) or os.sep


@dataclass
class ClaudeAccount:
    """One Claude Code login.

    `config_dir=None` means "the ambient account": whatever `claude` would use when run
    from this environment, i.e. $CLAUDE_CONFIG_DIR if set, else ~/.claude. Every path and
    the child process's environment go through `effective_dir`, so the files we read and
    the account `claude` reports on can never disagree.
    """
    config_dir: Optional[str] = None

    @property
    def effective_dir(self) -> Optional[str]:
        return normalize_dir(self.config_dir) or normalize_dir(os.environ.get("CLAUDE_CONFIG_DIR"))

    @property
    def home(self) -> str:
        return self.effective_dir or os.path.join(os.path.expanduser("~"), ".claude")

    def credentials_path(self) -> str:
        # CLAUDE_SECURESTORAGE_CONFIG_DIR relocates just the credentials file (ambient account only).
        secure = os.environ.get("CLAUDE_SECURESTORAGE_CONFIG_DIR") if self.config_dir is None else None
        return os.path.join(normalize_dir(secure) or self.home, ".credentials.json")

    def state_path(self) -> str:
        """Claude Code's app-state file: ~/.claude.json by default, <dir>/.claude.json otherwise."""
        if self.effective_dir:
            return os.path.join(self.effective_dir, ".claude.json")
        return os.path.join(os.path.expanduser("~"), ".claude.json")

    def env(self) -> dict:
        """Environment for a `claude` child process that should act as this account."""
        env = dict(os.environ)
        for k in _SCRUB_ENV:
            env.pop(k, None)
        if self.effective_dir:
            env["CLAUDE_CONFIG_DIR"] = self.effective_dir
        else:
            env.pop("CLAUDE_CONFIG_DIR", None)
        return env


@dataclass
class LoginInfo:
    state: str                        # "fresh" | "stale" | "logged_out" | "missing"
    plan: str = ""                    # "Max 5x"
    access_token: str = ""            # only for the read-only API fallback; never logged
    expires_at: float = 0.0           # epoch seconds
    login_expires_at: float = 0.0     # epoch seconds (refresh token expiry)

    def hint(self) -> str:
        """What the user should do, if anything."""
        if self.state == "missing":
            return "Claude Code isn't logged in on this machine — run `claude` and /login"
        if self.state == "logged_out":
            return "Claude Code is logged out — run `claude` and /login"
        if self.login_expires_at and self.login_expires_at - time.time() < LOGIN_EXPIRY_WARN_SEC:
            days = max(0, int((self.login_expires_at - time.time()) // 86400))
            return f"Claude login expires in {days} day{'s' if days != 1 else ''} — run /login in Claude Code"
        return ""


def plan_label(subscription: str, tier: str = "") -> str:
    if tier in TIER_LABELS:
        return TIER_LABELS[tier]
    sub = (subscription or "").lower()
    return PLAN_LABELS.get(sub, sub.title())


def _keychain_blob(account: ClaudeAccount) -> Optional[dict]:
    """macOS: Claude Code keeps credentials in the Keychain. Only the default account's
    service name ('Claude Code-credentials') is known for sure; other config dirs use a
    suffixed name, so they are skipped until Phase 3 verifies the rule on a Mac."""
    if sys.platform != "darwin" or account.effective_dir:
        return None
    try:
        out = subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return json.loads(out.stdout.strip()).get("claudeAiOauth")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def _read_blob(account: ClaudeAccount) -> Optional[dict]:
    path = account.credentials_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                blob = json.load(f).get("claudeAiOauth")
            return blob if isinstance(blob, dict) else None
        except (OSError, ValueError, AttributeError):
            return None
    return _keychain_blob(account)


def read_login(account: ClaudeAccount) -> LoginInfo:
    blob = _read_blob(account)
    if not blob:
        return LoginInfo("missing")
    plan = plan_label(blob.get("subscriptionType") or "", blob.get("rateLimitTier") or "")
    token = blob.get("accessToken") or ""
    exp = float(blob.get("expiresAt") or 0) / 1000.0
    login_exp = float(blob.get("refreshTokenExpiresAt") or 0) / 1000.0
    if not token or not exp:
        # After a failed refresh Claude Code blanks the token and zeroes expiresAt.
        return LoginInfo("logged_out", plan=plan)
    state = "fresh" if exp > time.time() + 60 else "stale"
    return LoginInfo(state, plan=plan, access_token=token, expires_at=exp, login_expires_at=login_exp)
