"""Integrated source smoke test: run the full app (worker + tray + listener + window)
for a few seconds, surface any Tk callback exceptions, then shut down.

Run from the repo root: python3 tools/smoke_gui.py
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claude_usage_monitor import app as A, singleinstance  # noqa: E402

sock = singleinstance.acquire()
assert sock is not None, "another instance is running"
app = A.App(sock, show_window_on_start=True)

errors = []
app.root.report_callback_exception = lambda e, v, t: errors.append("".join(traceback.format_exception(e, v, t)))


def report():
    for pid, snap in app.snapshots.items():
        print(pid, snap.source, [(m.key, m.percent) for m in snap.meters], "note:", app.notes.get(pid, ""))


app.root.after(8000, report)
app.root.after(9000, app.shutdown)
app.run()
print("CALLBACK ERRORS:\n" + "\n".join(errors) if errors else "GUI smoke OK - no callback exceptions")
