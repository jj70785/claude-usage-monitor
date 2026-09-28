"""The provider interface every AI plugs into.

A provider has two entry points, both called from the background worker thread:

- `fetch()`: the "real" read (may spawn a CLI or hit the network). The app rate-limits
  calls per provider and never calls it more often than `min_interval_sec`.
- `peek()`: a cheap local read (files that other tools already write). Called every
  few seconds; returns a newer Snapshot only when something actually changed.
"""
from __future__ import annotations

from typing import Optional

from ..model import Snapshot


class ProviderError(Exception):
    """Generic failure; the message is shown to the user as-is, so keep it short."""


class RateLimited(ProviderError):
    """The provider asked us to back off."""

    def __init__(self, retry_after: Optional[int] = None, message: str = "rate limited"):
        super().__init__(message)
        self.retry_after = retry_after


class NotLoggedIn(ProviderError):
    """No usable login for this provider on this machine (the user has to act)."""


class Provider:
    id: str = ""
    title: str = ""
    min_interval_sec: int = 120

    def fetch(self) -> Snapshot:
        raise NotImplementedError

    def peek(self) -> Optional[Snapshot]:
        return None
