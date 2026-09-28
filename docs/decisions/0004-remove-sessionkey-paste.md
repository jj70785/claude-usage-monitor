# 0004 — Remove "Paste session key" and the keyring dependency

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

v1 let users paste their `claude.ai` `sessionKey` cookie. It stored the cookie in the OS
keyring and called `claude.ai/api/organizations/{org}/usage` with a spoofed browser
User-Agent. Problems:

- Anthropic's Claude Code legal page (retrieved 2026-09-16) says developers "may not
  collect, store, or intermediate Claude.ai credentials or session tokens."
- Cloudflare blocks non-browser clients on claude.ai (403 or HTML challenge pages).
- The org picker took `memberships[0]`, which can be an API org that returns
  `permission_error`.
- The cookie was only tried when the OAuth token was *locally* expired, not when the
  server rejected it.
- `keyring` was only needed for the cookie and for the token refresh we also removed (0001).

## Decision

Delete the cookie path, the paste dialog, the tray menu item, and the `keyring`
dependency. The app stores **no credentials of any kind**.

## Consequences

- Users without Claude Code can't use the Claude provider. That's acceptable: Claude Code
  is the supported way to have a Claude subscription login on a desktop, and the app says
  "run `claude` and /login" when it's missing.
- One fewer dependency on every OS. The PyInstaller spec no longer collects `keyring` or
  `win32ctypes`.
