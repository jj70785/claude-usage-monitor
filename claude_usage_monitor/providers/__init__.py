"""Provider registry. Codex and Gemini (via the Antigravity `agy` CLI) plug in here next;
see docs/plans/roadmap.md."""
from __future__ import annotations

from ..config import Prefs
from .base import NotLoggedIn, Provider, ProviderError, RateLimited
from .claude import ClaudeProvider

__all__ = ["Provider", "ProviderError", "RateLimited", "NotLoggedIn", "build_providers"]


def build_providers(prefs: Prefs) -> list[Provider]:
    return [ClaudeProvider(prefs)]
