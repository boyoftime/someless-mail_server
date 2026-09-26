"""The container's main process (docker/someless-run): runs Stalwart and the panel side by side.
- Stalwart first: its first-time setup (setup.py), or a normal start, then a sync
- then the panel (gunicorn), even when Stalwart didn't come up: the panel says so on SMTP & API
- Stalwart started again whenever it stops, waiting longer each time it keeps stopping
- a sync every hour (keys expiring, anything that drifted)
- the Let's Encrypt relay on 17081: only /.well-known/acme-challenge/<token>, answered by
  Stalwart's own HTTP side on 127.0.0.1:17880, which is never published
- SIGTERM stops both; if the panel stops, so does everything (Docker starts the container again)"""
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .client import EngineError, EngineUnavailable

CHALLENGE = re.compile(r"^/\.well-known/acme-challenge/[A-Za-z0-9_-]+$")
NOT_HERE = b"Someless Mail: nothing here but Let's Encrypt's checks.\n"   # the README's troubleshooting looks for it
STALWART_DATA = "/data/stalwart"
RELAY_PORT = 17081
SYNC_EVERY = 3600      # seconds
FORGIVEN_AFTER = 300   # seconds up before a stop counts as the first again
# --preload builds the app once before the workers start, so first-start setup
# (secret key, default admin) runs exactly once.
# --worker-class gthread: browsers open connections ahead of time and may leave them idle.
# Threaded workers set those aside until they send something; plain workers would sit on
# them until killed for "timing out", and the request caught in them got gunicorn's bare
# "Internal Server Error" page.
# --no-control-socket: we don't use gunicornc, and its socket would need a home folder.
GUNICORN = ["gunicorn", "--bind", "0.0.0.0:17080", "--workers", "2", "--worker-class", "gthread", "--threads", "4",
            "--preload", "--no-control-socket", "--access-logfile", "-", "someless:create_app()"]


def backoff(attempt):
    """Seconds to wait before starting Stalwart again, the attempt-th time in a row."""
    return min(60, 2 ** attempt)


def challenge_reply(path, fetch):
    if not CHALLENGE.match(path):
        return 404, b""
    return fetch(path)


def _fetch_from_stalwart(path, host):
    request = urllib.request.Request(f"http://127.0.0.1:17880{path}", headers={"Host": host or "localhost"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read(4096)
    except urllib.error.HTTPError as error:
        return error.code, b""
    except (OSError, ValueError):   # ValueError: a Host header urllib won't send (a line break in it)
        return 503, b""


class _Relay(BaseHTTPRequestHandler):
    timeout = 10   # seconds: 17081 is open to the internet; a connection that says nothing is dropped

    def do_GET(self):
        status, body = challenge_reply(self.path, lambda path: _fetch_from_stalwart(path, self.headers.get("Host")))
        if status != 200:
            body = NOT_HERE
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _say(message):
    print(f"[someless] {message}", file=sys.stderr, flush=True)


def bring_up(app, stalwart):
    """Stalwart's first-time setup (or a normal start), then a sync. False, and Stalwart
    stopped, when it didn't come up; the next try is the supervisor's."""
    from . import setup, sync
    try:
        with app.app_context():
            setup.run(stalwart)
            sync.run()
    except (EngineUnavailable, EngineError, OSError, KeyError) as error:
        _say(f"the mail engine didn't start: {error}")
        stalwart.stop()
        return False
    _say("the mail engine is running")
    return True


def main():
    from someless import create_app

    from . import sync
    from .process import Stalwart

    app = create_app()
    stalwart = Stalwart(os.environ.get("SOMELESS_STALWART", "/usr/local/bin/stalwart"), STALWART_DATA)
    relay = ThreadingHTTPServer(("0.0.0.0", RELAY_PORT), _Relay)
    threading.Thread(target=relay.serve_forever, daemon=True).start()
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())

    up = bring_up(app, stalwart)
    panel = subprocess.Popen(GUNICORN)
    restarts = 0 if up else 1
    retry_at = time.monotonic() + (0 if up else backoff(0))
    up_since = next_sync = time.monotonic()
    next_sync += SYNC_EVERY
    while not stopping.is_set() and panel.poll() is None:
        now = time.monotonic()
        if stalwart.running():
            if restarts and now - up_since > FORGIVEN_AFTER:
                restarts = 0
            if now >= next_sync:
                with app.app_context():
                    sync.run()
                next_sync = now + SYNC_EVERY
        elif now >= retry_at:
            _say("the mail engine stopped; starting it again")
            if bring_up(app, stalwart):
                up_since = time.monotonic()
            retry_at = time.monotonic() + backoff(restarts)
            restarts += 1
        stopping.wait(1)

    # docker stop gives ten seconds: both are asked to stop at once
    panel.terminate()
    stalwart.stop(timeout=7)
    try:
        panel.wait(2)
    except subprocess.TimeoutExpired:
        panel.kill()
    relay.shutdown()
    return 0 if stopping.is_set() else (panel.returncode or 1)


if __name__ == "__main__":
    sys.exit(main())
