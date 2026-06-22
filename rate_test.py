"""Empirical rate-limit probe: hammer /api/oauth/usage as fast as possible and
report when (if) it 429s. Tells us whether the manual-refresh cooldown is needed."""
import json, os, time, urllib.request, urllib.error

CRED = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
URL = "https://api.anthropic.com/api/oauth/usage"
tok = json.load(open(CRED))["claudeAiOauth"]["accessToken"]
HDR = {
    "Authorization": f"Bearer {tok}",
    "anthropic-beta": "oauth-2025-04-20",
    "User-Agent": "claude-code/2.1.178",
    "Accept": "application/json",
}
N = 15
t0 = time.time()
limited = False
for i in range(1, N + 1):
    s = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, headers=HDR), timeout=20) as r:
            u = json.loads(r.read().decode())
        fh = u.get("five_hour", {}).get("utilization")
        print(f"#{i:2d}  t+{int((time.time()-t0)*1000):5d}ms  HTTP {r.status}  5h={fh}  ({int((time.time()-s)*1000)}ms)")
    except urllib.error.HTTPError as e:
        ra = e.headers.get("retry-after")
        print(f"#{i:2d}  t+{int((time.time()-t0)*1000):5d}ms  HTTP {e.code}  retry-after={ra}  {e.read().decode()[:100]}")
        if e.code == 429:
            print(f"==> RATE LIMITED at request #{i} ({int((time.time()-t0)*1000)}ms in)")
            limited = True
            break
print("RESULT:", "hit 429" if limited else f"{N} rapid requests OK, no 429")
