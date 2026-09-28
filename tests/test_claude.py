"""Claude provider tests. Stdlib unittest only; run with: python3 -m unittest discover -s tests

No test touches the network, the real `claude` CLI, or real credentials: a fake `claude`
script answers the stream-json protocol, and all files live in temp dirs.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import textwrap
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_usage_monitor import config  # noqa: E402
from claude_usage_monitor.model import Meter, Snapshot, utcnow  # noqa: E402
from claude_usage_monitor.notify import ThresholdNotifier  # noqa: E402
from claude_usage_monitor.providers import NotLoggedIn, ProviderError  # noqa: E402
from claude_usage_monitor.providers.claude import ClaudeProvider, api, cli_usage, local  # noqa: E402
from claude_usage_monitor.providers.claude.account import ClaudeAccount, plan_label, read_login  # noqa: E402
from claude_usage_monitor.providers.claude.parse import meters_from_rate_limits  # noqa: E402

FUTURE = (utcnow() + timedelta(hours=2)).isoformat()
FUTURE_WEEK = (utcnow() + timedelta(days=3)).isoformat()

RATE_LIMITS = {
    "five_hour": {"utilization": 54, "resets_at": FUTURE},
    "seven_day": {"utilization": 78, "resets_at": FUTURE_WEEK},
    "limits": [
        {"kind": "session", "group": "session", "percent": 54, "severity": "normal", "resets_at": FUTURE},
        {"kind": "weekly_all", "group": "weekly", "percent": 78, "severity": "warning", "resets_at": FUTURE_WEEK},
        {"kind": "weekly_scoped", "group": "weekly", "percent": 3, "severity": "normal", "resets_at": FUTURE_WEEK,
         "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None}},
    ],
    "extra_usage": {"is_enabled": False},
}


class TempHome(unittest.TestCase):
    """Each test gets its own HOME/XDG dirs so nothing real is read or written."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        env = {"HOME": self.home, "XDG_CACHE_HOME": os.path.join(self.home, ".cache"),
               "XDG_CONFIG_HOME": os.path.join(self.home, ".config")}
        self._env = mock.patch.dict(os.environ, env)
        self._env.start()
        for k in ("CLAUDE_CONFIG_DIR", "CLAUDE_SECURESTORAGE_CONFIG_DIR"):
            os.environ.pop(k, None)
        os.makedirs(os.path.join(self.home, ".claude"), exist_ok=True)
        local._cache = local._MtimeCache()

    def tearDown(self):
        self._env.stop()
        self.tmp.cleanup()

    def write_creds(self, **over):
        blob = {"accessToken": "tok-test", "refreshToken": "ref-test",
                "expiresAt": int((time.time() + 3600) * 1000),
                "refreshTokenExpiresAt": int((time.time() + 10 * 86400) * 1000),
                "subscriptionType": "max", "rateLimitTier": "default_claude_max_5x"}
        blob.update(over)
        with open(os.path.join(self.home, ".claude", ".credentials.json"), "w") as f:
            json.dump({"claudeAiOauth": blob}, f)

    def write_claude_state(self, fetched: datetime, rate_limits=RATE_LIMITS):
        with open(os.path.join(self.home, ".claude.json"), "w") as f:
            json.dump({"cachedUsageUtilization": {"fetchedAtMs": int(fetched.timestamp() * 1000),
                                                  "utilization": rate_limits}}, f)

    def write_statusline(self, observed: datetime, five=60, week=79, config_dir=None):
        path = local.statusline_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"observed_at": int(observed.timestamp() * 1000), "config_dir": config_dir,
                       "rate_limits": {"five_hour": {"used_percentage": five, "resets_at": int(time.time()) + 3600},
                                       "seven_day": {"used_percentage": week, "resets_at": int(time.time()) + 86400 * 3}}}, f)
        # the mtime cache keys on mtime; make sure a rewrite within the same second is seen
        local._cache = local._MtimeCache()

    def fake_claude(self, body: str) -> str:
        """Write an executable stand-in for `claude` that runs `body` (Python)."""
        path = os.path.join(self.home, "fake-claude")
        with open(path, "w") as f:
            f.write(f"#!{sys.executable}\nimport json, sys, os\n" + textwrap.dedent(body))
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path


# --------------------------------------------------------------------------- parse
class ParseTests(unittest.TestCase):
    def test_limits_rows_preferred_and_ordered(self):
        ms = meters_from_rate_limits(RATE_LIMITS, utcnow())
        self.assertEqual([m.key for m in ms], ["session", "weekly", "weekly:Fable"])
        self.assertEqual(ms[1].severity, "warning")
        self.assertTrue(ms[0].primary and ms[1].primary and not ms[2].primary)
        self.assertEqual(ms[2].label, "Weekly · Fable")

    def test_legacy_only(self):
        ms = meters_from_rate_limits({"five_hour": {"utilization": 10, "resets_at": FUTURE},
                                      "seven_day_opus": {"utilization": 5}}, None)
        self.assertEqual([m.key for m in ms], ["session", "weekly:Opus"])

    def test_garbage_is_ignored(self):
        self.assertEqual(meters_from_rate_limits({"limits": [None, {"kind": "session"}, {"percent": "x"}]}, None), [])
        self.assertEqual(meters_from_rate_limits("nope", None), [])

    def test_extra_usage_only_when_enabled(self):
        data = dict(RATE_LIMITS, extra_usage={"is_enabled": True, "utilization": 12})
        self.assertIn("extra", [m.key for m in meters_from_rate_limits(data, None)])

    def test_plan_labels(self):
        self.assertEqual(plan_label("max", "default_claude_max_5x"), "Max 5x")
        self.assertEqual(plan_label("max", "default_claude_max_20x"), "Max 20x")
        self.assertEqual(plan_label("pro", ""), "Pro")


# --------------------------------------------------------------------------- model
class ModelTests(unittest.TestCase):
    def test_expired_meter_excluded_from_worst(self):
        past = utcnow() - timedelta(minutes=1)
        snap = Snapshot("claude", "Claude", meters=[Meter("session", "5h", 99, resets_at=past),
                                                    Meter("weekly", "wk", 40, resets_at=utcnow() + timedelta(days=1))])
        self.assertEqual(snap.worst().key, "weekly")
        self.assertIn("reset", snap.meters[0].reset_text())

    def test_roundtrip(self):
        snap = Snapshot("claude", "Claude", plan="Max 5x", meters=meters_from_rate_limits(RATE_LIMITS, utcnow()),
                        fetched_at=utcnow(), source="claude-cli")
        again = Snapshot.from_dict(json.loads(json.dumps(snap.to_dict())))
        self.assertEqual([(m.key, m.percent) for m in again.meters], [(m.key, m.percent) for m in snap.meters])
        self.assertEqual(again.plan, "Max 5x")


# --------------------------------------------------------------------------- account
class AccountTests(TempHome):
    def test_fresh_stale_logged_out_missing(self):
        acct = ClaudeAccount()
        self.assertEqual(read_login(acct).state, "missing")
        self.write_creds()
        info = read_login(acct)
        self.assertEqual((info.state, info.plan), ("fresh", "Max 5x"))
        self.write_creds(expiresAt=int((time.time() - 10) * 1000))
        self.assertEqual(read_login(acct).state, "stale")
        self.write_creds(accessToken="", expiresAt=0)          # what Claude Code does after invalid_grant
        self.assertEqual(read_login(acct).state, "logged_out")

    def test_login_expiry_hint(self):
        self.write_creds(refreshTokenExpiresAt=int((time.time() + 86400) * 1000))
        self.assertIn("expires in", read_login(ClaudeAccount()).hint())

    def test_config_dir_paths_and_env(self):
        acct = ClaudeAccount(config_dir="/x/claude-work")
        self.assertEqual(acct.credentials_path(), "/x/claude-work/.credentials.json")
        self.assertEqual(acct.state_path(), "/x/claude-work/.claude.json")
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-should-not-leak"}):
            env = acct.env()
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], "/x/claude-work")


# --------------------------------------------------------------------------- cli protocol
_GOOD_CLI = """
req = json.loads(sys.stdin.readline())
assert req["request"]["subtype"] == "get_usage", req
print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
print(json.dumps({"type": "control_response", "response": {"subtype": "success",
      "request_id": req["request_id"], "response": {"subscription_type": "max",
      "rate_limits_available": True, "rate_limits": RL}}}), flush=True)
sys.stdin.read()   # wait for EOF like the real CLI
"""


class CliTests(TempHome):
    def test_get_usage_roundtrip(self):
        path = self.fake_claude(f"RL = json.loads({json.dumps(json.dumps(RATE_LIMITS))})\n" + _GOOD_CLI)
        payload = cli_usage.get_usage(ClaudeAccount(), path)
        self.assertTrue(payload["rate_limits_available"])
        self.assertEqual(payload["rate_limits"]["limits"][0]["percent"], 54)

    def test_ignores_other_request_ids(self):
        path = self.fake_claude(f"RL = json.loads({json.dumps(json.dumps(RATE_LIMITS))})\n" + """
req = json.loads(sys.stdin.readline())
print(json.dumps({"type": "control_response", "response": {"subtype": "success", "request_id": "someone-else",
      "response": {"rate_limits_available": True, "rate_limits": {}}}}), flush=True)
""" + _GOOD_CLI.split("\n", 2)[2])
        payload = cli_usage.get_usage(ClaudeAccount(), path)
        self.assertEqual(payload["rate_limits"]["limits"][1]["percent"], 78)

    def test_unavailable_means_not_logged_in(self):
        path = self.fake_claude("""
req = json.loads(sys.stdin.readline())
print(json.dumps({"type": "control_response", "response": {"subtype": "success", "request_id": req["request_id"],
      "response": {"rate_limits_available": False, "rate_limits": None}}}), flush=True)
""")
        with self.assertRaises(NotLoggedIn):
            cli_usage.get_usage(ClaudeAccount(), path)

    def test_error_reply_and_early_exit(self):
        path = self.fake_claude("""
req = json.loads(sys.stdin.readline())
print(json.dumps({"type": "control_response", "response": {"subtype": "error", "request_id": req["request_id"],
      "error": "Unknown control request"}}), flush=True)
""")
        with self.assertRaises(ProviderError):
            cli_usage.get_usage(ClaudeAccount(), path)
        crash = self.fake_claude("sys.stderr.write('boom: not logged in\\n'); sys.exit(1)\n")
        with self.assertRaises(NotLoggedIn):
            cli_usage.get_usage(ClaudeAccount(), crash)

    def test_timeout_kills_hung_cli(self):
        path = self.fake_claude("import time\ntime.sleep(60)\n")
        with mock.patch.object(cli_usage, "TIMEOUT_SEC", 1.5):
            t = time.monotonic()
            with self.assertRaises(ProviderError):
                cli_usage.get_usage(ClaudeAccount(), path)
            self.assertLess(time.monotonic() - t, 15)

    def test_runs_in_scratch_dir_with_safe_flags(self):
        path = self.fake_claude("""
req = json.loads(sys.stdin.readline())
print(json.dumps({"type": "control_response", "response": {"subtype": "success", "request_id": req["request_id"],
      "response": {"rate_limits_available": True, "rate_limits": {"argv": sys.argv[1:], "cwd": os.getcwd(),
      "has_key": "ANTHROPIC_API_KEY" in os.environ}}}}), flush=True)
""")
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-x"}):
            rl = cli_usage.get_usage(ClaudeAccount(), path)["rate_limits"]
        self.assertIn("--strict-mcp-config", rl["argv"])
        self.assertNotIn("--bare", rl["argv"])
        self.assertEqual(os.listdir(rl["cwd"]), [])            # empty dir: no project hooks/MCP
        self.assertFalse(rl["has_key"])


# --------------------------------------------------------------------------- api fallback
class ApiTests(unittest.TestCase):
    def test_retry_after_formats(self):
        self.assertEqual(api._retry_after("120"), 120)
        future = datetime.now(timezone.utc) + timedelta(seconds=300)
        from email.utils import format_datetime
        self.assertAlmostEqual(api._retry_after(format_datetime(future, usegmt=True)), 300, delta=3)
        self.assertIsNone(api._retry_after("soon"))

    def test_never_calls_with_stale_token(self):
        from claude_usage_monitor.providers.claude.account import LoginInfo
        with mock.patch("urllib.request.urlopen") as op:
            with self.assertRaises(NotLoggedIn):
                api.fetch(LoginInfo("stale", access_token="t"))
            op.assert_not_called()

    def test_honest_user_agent(self):
        self.assertTrue(api.USER_AGENT.startswith("ai-usage-monitor/"))
        self.assertNotIn("claude-code", api.USER_AGENT)
        self.assertNotIn("claude-cli", api.USER_AGENT)


# --------------------------------------------------------------------------- provider merge
class ProviderTests(TempHome):
    def provider(self, **prefs):
        p = config.Prefs(**prefs)
        return ClaudeProvider(p)

    def test_cli_success_is_live_when_claude_wrote_snapshot(self):
        self.write_creds()
        prov = self.provider(claude_api_fallback=False)

        def fake_get_usage(acct, path):
            self.write_claude_state(utcnow())                  # the real CLI writes this on success
            return {"subscription_type": "max", "rate_limits_available": True, "rate_limits": RATE_LIMITS}
        with mock.patch.object(cli_usage, "find_claude", return_value="/bin/true"), \
                mock.patch.object(cli_usage, "get_usage", side_effect=fake_get_usage):
            snap = prov.fetch()
        self.assertEqual((snap.source, snap.plan, snap.note), ("claude-cli", "Max 5x", ""))
        self.assertEqual(snap.worst().percent, 78)

    def test_cli_answer_from_old_snapshot_is_flagged(self):
        self.write_creds()
        self.write_claude_state(utcnow() - timedelta(minutes=40))
        prov = self.provider(claude_api_fallback=False)
        with mock.patch.object(cli_usage, "find_claude", return_value="/bin/true"), \
                mock.patch.object(cli_usage, "get_usage", return_value={
                    "rate_limits_available": True, "rate_limits": RATE_LIMITS}):
            snap = prov.fetch()
        self.assertIn("last check", snap.note)
        self.assertTrue(snap.is_stale(config.STALE_AFTER_SEC))

    def test_falls_back_to_api_then_never_refreshes(self):
        self.write_creds(expiresAt=int((time.time() - 5) * 1000))    # stale token
        prov = self.provider(claude_api_fallback=True)
        with mock.patch.object(cli_usage, "find_claude", return_value=None), \
                mock.patch("urllib.request.urlopen") as op:
            with self.assertRaises(ProviderError):
                prov.fetch()
            op.assert_not_called()          # stale token: no request, and certainly no refresh

    def test_api_fallback_used_when_cli_fails(self):
        self.write_creds()
        prov = self.provider(claude_api_fallback=True)
        with mock.patch.object(cli_usage, "find_claude", return_value="/bin/true"), \
                mock.patch.object(cli_usage, "get_usage", side_effect=ProviderError("boom")), \
                mock.patch.object(api, "fetch", return_value=RATE_LIMITS):
            snap = prov.fetch()
        self.assertEqual(snap.source, "api")

    def test_everything_fails_but_local_snapshot_exists(self):
        self.write_creds()
        self.write_claude_state(utcnow() - timedelta(minutes=5))
        prov = self.provider(claude_api_fallback=False)
        with mock.patch.object(cli_usage, "find_claude", return_value=None):
            snap = prov.fetch()
        self.assertEqual(snap.source, "claude-snapshot")

    def test_missing_login_raises_with_hint(self):
        prov = self.provider(claude_api_fallback=True)
        with mock.patch.object(cli_usage, "find_claude", return_value=None):
            with self.assertRaises(NotLoggedIn) as cm:
                prov.fetch()
        self.assertIn("/login", str(cm.exception))

    def test_peek_picks_up_newer_snapshot_and_statusline(self):
        self.write_creds()
        prov = self.provider()
        old = utcnow() - timedelta(minutes=10)
        prov.seed(Snapshot("claude", "Claude", plan="Max 5x", meters=meters_from_rate_limits(RATE_LIMITS, old),
                           fetched_at=old, source="claude-cli"))
        self.assertIsNone(prov.peek())                          # nothing newer on disk
        self.write_claude_state(utcnow() - timedelta(minutes=2))
        snap = prov.peek()
        self.assertEqual(snap.source, "claude-snapshot")
        self.write_statusline(utcnow(), five=61, week=79)
        snap = prov.peek()
        self.assertEqual(snap.source, "statusline")
        self.assertEqual({m.key: m.percent for m in snap.meters}["session"], 61)
        self.assertIn("weekly:Fable", [m.key for m in snap.meters])   # scoped meters survive the overlay
        self.assertIsNone(prov.peek())                          # stable: no change, no new snapshot

    def test_old_statusline_never_overrides_newer_data(self):
        self.write_creds()
        prov = self.provider()
        now = utcnow()
        prov.seed(Snapshot("claude", "Claude", meters=meters_from_rate_limits(RATE_LIMITS, now), fetched_at=now))
        self.write_statusline(now - timedelta(days=3), five=5, week=10)   # idle session, 3 days old
        self.assertIsNone(prov.peek())

    def test_statusline_for_other_account_ignored(self):
        self.write_statusline(utcnow(), config_dir="/somewhere/else")
        self.assertEqual(local.statusline_meters(ClaudeAccount()), (None, []))


# --------------------------------------------------------------------------- notifications
class NotifierTests(unittest.TestCase):
    def test_once_per_threshold_per_window(self):
        sent = []
        n = ThresholdNotifier(sender=lambda t, m, u: sent.append((t, u)))
        prefs = config.Prefs()
        reset = utcnow() + timedelta(hours=1)

        def snap(p):
            return Snapshot("claude", "Claude", meters=[Meter("session", "5-hour session", p, resets_at=reset,
                                                              primary=True)])
        n.check(snap(50), prefs)
        n.check(snap(81), prefs)
        n.check(snap(85), prefs)
        n.check(snap(96), prefs)
        n.check(snap(97), prefs)
        self.assertEqual([u for _, u in sent], ["normal", "critical"])
        prefs.notify_on_warn = False
        n.check(Snapshot("claude", "Claude", meters=[Meter("session", "x", 99, resets_at=reset + timedelta(hours=5),
                                                           primary=True)]), prefs)
        self.assertEqual(len(sent), 2)


if __name__ == "__main__":
    unittest.main()
