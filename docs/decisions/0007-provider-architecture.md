# 0007 — Provider plug-ins with `fetch()` + `peek()` and a neutral model

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

v1 hard-coded exactly two Claude windows everywhere: a `Usage` dataclass with
`five_hour`/`weekly`, two panel sections, two tray icons, one credential path, one cache.
We need Claude now, Codex and Gemini next, and multiple Claude accounts later.

## Decision

- `model.py` defines a provider-neutral **`Snapshot`** (title, plan, list of **`Meter`**s,
  `fetched_at`, `source`, `note`). The UI, tray, cache, and notifications only see this.
- `providers/base.py` defines **`Provider`** with two calls, both made on the worker thread:
  - `fetch()`: the real read (spawns a CLI or makes a request). The app rate-limits it
    per provider (0011).
  - `peek()`: a cheap local read, run every `PEEK_SEC` (10 s), that returns a newer
    `Snapshot` only when something actually changed on disk (0008).
- Errors are typed: `RateLimited(retry_after)`, `NotLoggedIn` (the user must act), and
  `ProviderError` (a short message shown as-is).
- `providers/__init__.py:build_providers()` is the registry. Codex/Gemini add a
  subpackage and one line there.
- Provider ids are strings; accounts become ids like `claude:work`, each with its own
  `ClaudeAccount(config_dir=…)`.

## Consequences

- The panel draws any number of providers and limits. It rebuilds its layout only when
  the set of limits changes.
- `Meter.as_of` lets one snapshot mix sources (e.g. a live weekly number from the status
  line on top of an older per-model number from `get_usage`) without lying about age.
- The cache file changed from `last_usage.json` to `last_snapshots.json` (a list of
  snapshots). Old caches are ignored, not migrated; they only fed the first paint.
