"""Integrated source smoke test: run the full app (worker + tray + listener +
window) for a few seconds, surface any callback exceptions, then shut down."""
import traceback
from claude_usage_monitor import app as A

sock = A._try_bind()
assert sock is not None, "single-instance port busy — is the app running?"
app = A.App(sock, show_window_on_start=True)

errors = []
app.root.report_callback_exception = lambda e, v, t: errors.append("".join(traceback.format_exception(e, v, t)))

app.root.after(2800, lambda: print("after fetch -> note:", repr(app.note), "| usage:",
                                   None if not app.last_usage else
                                   (app.last_usage.plan, app.last_usage.five_hour.percent)))
app.root.after(6000, app.shutdown)
app.run()
print("CALLBACK ERRORS:\n" + "\n".join(errors) if errors else "GUI smoke OK — no callback exceptions")
