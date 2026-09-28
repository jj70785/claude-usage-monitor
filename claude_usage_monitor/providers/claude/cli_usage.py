"""Ask Claude Code itself for plan usage via its stream-json `get_usage` control request.

Why this is the primary source (docs/decisions/0002-claude-get-usage-primary.md):
- Claude Code does the HTTP call with its own login and refreshes its own token under
  its own lock, so we never touch a credential.
- No prompt is sent, so it costs nothing (verified: total_cost_usd 0, no model call).

Guardrails baked in:
- Spawned from an empty scratch dir with `--setting-sources project`, so no project
  hooks, settings, or .mcp.json servers load; `--strict-mcp-config` skips user MCPs.
- No `initialize` request: its reply carries the account email, which we never want.
- Only the control_response line for our request_id is parsed; nothing else is logged.
- `--bare` is NOT usable: it disables OAuth, so usage would be unavailable.
- The feature is marked experimental upstream; callers must treat failures as normal
  and fall back.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
import uuid
from typing import Optional

from ... import config
from ..base import NotLoggedIn, ProviderError
from .account import ClaudeAccount

TIMEOUT_SEC = 45
REAP_GRACE_SEC = 90       # >= Claude Code's own 30 s token request plus lock waits

_CANDIDATES = [
    "~/.local/bin/claude",
    "~/.claude/local/claude",
    "~/.npm-global/bin/claude",
    "/usr/local/bin/claude",
    "/opt/homebrew/bin/claude",
    "/usr/bin/claude",
]


def find_claude(override: str = "") -> Optional[str]:
    """Locate the claude CLI. Login sessions started from the desktop often lack
    ~/.local/bin on PATH, so check the usual install spots too."""
    if override and os.path.isfile(os.path.expanduser(override)):
        return os.path.expanduser(override)
    found = shutil.which("claude")
    if found:
        return found
    for c in _CANDIDATES:
        p = os.path.expanduser(c)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def _scratch_dir() -> str:
    d = os.path.join(config.cache_dir(), "claude-probe")
    os.makedirs(d, exist_ok=True)
    return d


def _reader(stream, q: "queue.Queue[Optional[str]]"):
    """Pump lines into `q`. The reader owns its stream and closes it at EOF: another
    thread closing a stream this thread is blocked reading would deadlock on the
    buffer lock (e.g. when a leftover helper process still holds the pipe)."""
    try:
        for line in iter(stream.readline, ""):
            q.put(line)
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass
        q.put(None)


def _signal_group(proc: subprocess.Popen, sig: int) -> None:
    """Signal the child's whole process group (it leads its own session on POSIX).
    Only called while the leader is still running, so the group ID is still ours."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(proc.pid, sig)
        else:
            proc.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _reap(proc: subprocess.Popen) -> None:
    """Let a slow `claude` finish on its own; if it truly hangs, ask it to stop.

    Never SIGKILL: a get_usage call can include Claude Code's own token refresh (lock wait
    plus a 30 s token request), and killing it mid-refresh could lose a freshly rotated
    refresh token, which logs Claude Code out (docs/decisions/0001).
    """
    try:
        proc.wait(timeout=REAP_GRACE_SEC)
    except subprocess.TimeoutExpired:
        config.log("claude usage probe still running after grace period; sending SIGTERM")
        _signal_group(proc, signal.SIGTERM)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            config.log("claude usage probe ignored SIGTERM; leaving it alone")
    # No group signal after the leader has exited: its ID could in theory be reused by
    # an unrelated process. Leftover helpers only keep a daemon reader thread waiting.


def get_usage(account: ClaudeAccount, claude_path: str) -> dict:
    """Return the get_usage payload ({subscription_type, rate_limits_available, rate_limits, ...}).

    Raises NotLoggedIn / ProviderError. Returns as soon as the reply (or the timeout)
    arrives; the child process is then closed and reaped on a background thread.
    """
    request_id = f"aum-{uuid.uuid4().hex[:12]}"
    cmd = [
        claude_path, "-p",
        "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "project",
    ]
    popen_kw = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=_scratch_dir(), env=account.env(), text=True, encoding="utf-8",
                    errors="replace", bufsize=1)
    if os.name == "posix":
        popen_kw["start_new_session"] = True      # no controlling TTY; its own process group
    else:
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(cmd, **popen_kw)
    except OSError as e:
        raise ProviderError(f"couldn't start claude: {e}") from e

    out_q: "queue.Queue[Optional[str]]" = queue.Queue()
    err_q: "queue.Queue[Optional[str]]" = queue.Queue()
    for stream, q in ((proc.stdout, out_q), (proc.stderr, err_q)):
        threading.Thread(target=_reader, args=(stream, q), name="claude-probe-io", daemon=True).start()

    req = {"type": "control_request", "request_id": request_id,
           "request": {"subtype": "get_usage", "skip_behaviors": True}}
    try:
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
    except OSError:
        pass            # it exited already; the reply loop below reports why

    deadline = time.monotonic() + TIMEOUT_SEC
    reply = None
    exited = False
    try:
        while time.monotonic() < deadline:
            try:
                line = out_q.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line is None:               # stdout closed: process exited
                exited = True
                break
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict) or msg.get("type") != "control_response":
                continue
            resp = msg.get("response") or {}
            if not isinstance(resp, dict) or resp.get("request_id") != request_id:
                continue
            reply = resp
            break
    finally:
        try:
            proc.stdin.close()             # EOF lets claude exit cleanly
        except OSError:
            pass
        threading.Thread(target=_reap, args=(proc,), name="claude-probe-reap", daemon=True).start()

    if reply is None:
        if exited:
            try:
                proc.wait(timeout=2)       # let the exit code and stderr land
            except subprocess.TimeoutExpired:
                pass
        err = _first_error_line(err_q)
        if exited and err:
            raise _classify(err)
        if not exited:
            raise ProviderError(f"Claude Code didn't answer within {TIMEOUT_SEC} s")
        raise ProviderError("Claude Code exited without answering the usage request"
                            + (f" ({err})" if err else ""))
    if reply.get("subtype") != "success":
        raise _classify(str(reply.get("error") or "usage request failed"))
    payload = reply.get("response") or {}
    if not isinstance(payload, dict) or not payload.get("rate_limits_available"):
        raise NotLoggedIn("Claude Code has no plan usage for this login — "
                          "it needs a claude.ai Pro/Max login (not an API key or cloud backend)")
    if not isinstance(payload.get("rate_limits"), dict):
        # Available in principle, but Claude Code couldn't reach the usage server and has
        # no recent snapshot (e.g. a long 429 lockout). Not a login problem; fall back.
        raise ProviderError("Claude Code couldn't reach the usage server and has no recent snapshot")
    return payload


def _first_error_line(err_q: "queue.Queue[Optional[str]]") -> str:
    lines = []
    while True:
        try:
            line = err_q.get_nowait()
        except queue.Empty:
            break
        if line is None:
            break
        if line.strip():
            lines.append(line.strip())
    # Keep it short; stderr is never logged in full (it could echo account details).
    return lines[0][:160] if lines else ""


_LOGIN_WORDS = ("not logged in", "logged out", "please run /login", "run /login", "login expired",
                "invalid api key", "oauth token", "authentication", "unauthorized", "invalid_grant")


def _classify(message: str) -> ProviderError:
    low = message.lower()
    if any(w in low for w in _LOGIN_WORDS):
        return NotLoggedIn(f"Claude Code: {message[:160]}")
    return ProviderError(f"Claude Code: {message[:160]}")
