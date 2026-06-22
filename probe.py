"""One-off probe: confirm the usage endpoint works on THIS machine.
Uses the app's real auth (OAuth token from the Claude Code keychain entry on macOS, or
the credentials file on Windows/Linux), calls the usage API, prints parsed usage.
Does NOT print the token itself."""
import sys

from claude_usage_monitor import auth, usage_api


def main():
    try:
        a = auth.get_auth()
    except auth.AuthError as e:
        print(f"NO CREDENTIALS: {e}")
        return 1

    try:
        u = usage_api.fetch(a)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1

    print(f"plan={u.plan}")
    print("\nMAPPED:")
    for w, label in ((u.five_hour, "5-hour session"), (u.weekly, "Weekly (all models)")):
        if not w:
            print(f"  {label}: (null / not present)")
            continue
        print(f"  {label}: {w.percent:.0f}% used | resets_in={w.reset_in_text()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
