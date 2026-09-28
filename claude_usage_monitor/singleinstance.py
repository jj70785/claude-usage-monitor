"""Single-instance lock + "show your window" channel.

A second launch doesn't start a duplicate: it connects to the running instance, sends
SHOW, and exits. Linux/macOS use a Unix socket in the per-user runtime dir (the old TCP
port 49219 sits inside Linux's ephemeral port range, so an unrelated connection could
hold it). Windows keeps the loopback TCP port.
"""
from __future__ import annotations

import os
import socket
import tempfile
from typing import Optional

from . import config

_LOCK_PORT = 49219


def _sock_path() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    uid = os.getuid() if hasattr(os, "getuid") else 0
    name = f"{config.LINUX_ID}.sock" if os.environ.get("XDG_RUNTIME_DIR") else f"{config.LINUX_ID}-{uid}.sock"
    return os.path.join(base, name)


def acquire() -> Optional[socket.socket]:
    """Return a listening socket if we're the only instance, else None."""
    if os.name == "nt":
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", _LOCK_PORT))    # no SO_REUSEADDR: must fail if running
            s.listen(5)
            return s
        except OSError:
            s.close()
            return None
    path = _sock_path()
    if os.path.exists(path):
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(1.5)
            probe.connect(path)
            return None                             # a live instance answered
        except OSError:
            try:
                os.unlink(path)                     # stale socket from a crash
            except OSError:
                return None
        finally:
            probe.close()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.bind(path)
        os.chmod(path, 0o600)
        s.listen(5)
        return s
    except OSError:
        s.close()
        return None


def signal_show() -> None:
    try:
        if os.name == "nt":
            c = socket.create_connection(("127.0.0.1", _LOCK_PORT), timeout=2)
        else:
            c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            c.settimeout(2)
            c.connect(_sock_path())
        c.sendall(b"SHOW")
        c.close()
    except OSError:
        pass


def release(s: Optional[socket.socket]) -> None:
    if s is None:
        return
    try:
        s.close()
    except OSError:
        pass
    if os.name != "nt":
        try:
            os.unlink(_sock_path())
        except OSError:
            pass
