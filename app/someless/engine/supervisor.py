"""The container's main process (docker/someless-run): runs Stalwart and the panel side by side.
- the panel (gunicorn) first, so there's a page at once: on the very first start it says
  "Preparing your Someless Mail server" until Stalwart is set up (pages.py, preparing.js)
- the webmail beside it on 17090, a gunicorn of its own (webmail.py)
- then Stalwart: its first-time setup (setup.py), or a normal start, then a sync; when it
  doesn't come up, the panel says so on SMTP & API
- Stalwart started again whenever it stops, waiting longer each time it keeps stopping
- a sync every hour (keys expiring, anything that drifted), and the automatic domain
  checks when they're switched on (Settings > Miscellaneous)
- every half minute, while the server name has no certificate: whether the proxy host lets
  Let's Encrypt's check through yet, and the certificate asked for the moment it does
  (certificate.py)
- the Let's Encrypt relay on 17081: only /.well-known/acme-challenge/<token>, answered by
  Stalwart's own HTTP side on 127.0.0.1:17880, which is never published
- SIGTERM stops them all; if the panel or the webmail stops, so does everything (Docker starts
  the container again)"""
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
CERTIFICATE_EVERY = 30   # seconds: how often the server name's certificate is looked after, while it has none
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
# The webmail: the same, on its own port. main() has made the database by then, so the two never
# race to make it. Each open webmail tab keeps one thread for new mail as it comes (its WebSocket,
# webmail/live.py), so it has many, which mostly wait.
WEBMAIL_GUNICORN = ["gunicorn", "--bind", "0.0.0.0:17090", "--workers", "2", "--worker-class", "gthread",
                    "--threads", "64", "--preload", "--no-control-socket", "--access-logfile", "-",
                    "someless.webmail:create_webmail_app()"]


def backoff(attempt):
    """Seconds to wait before starting Stalwart again, the attempt-th time in a row."""
    return min(60, 2 ** attempt)


def challenge_reply(path, fetch):
    if not CHALLENGE.match(path):
        return 404, b""
    return fetch(path)


def relay_reply(path, fetch):
    """(status, content type, body): the front page (relay_page.py: the proxy host works), a
    challenge's answer, or else whose it is, in a line (what the proxy host check looks for)."""
    if path.split("?", 1)[0] == "/":
        from . import relay_page
        return 200, "text/html; charset=utf-8", relay_page.page()
    status, body = challenge_reply(path, fetch)
    if status != 200:
        return status, "text/plain", NOT_HERE
    return status, "text/plain", body


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
        status, kind, body = relay_reply(self.path, lambda path: _fetch_from_stalwart(path, self.headers.get("Host")))
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        # (open to the internet: what it sends can load, run and frame nothing)
        self.send_header("Content-Security-Policy", "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
                                                    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
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


def check_domains_if_due(app):
    """The automatic domain checks, when switched on and their time has come (domain_checks.py)."""
    from .. import domain_checks
    with app.app_context():
        if domain_checks.due():
            changed = domain_checks.run()
            for name, now in changed:
                _say(f"{name} is {'authenticated' if now else 'no longer authenticated'} (automatic domain check)")


def watch_certificate(app):
    """The server name's certificate: asked for the moment the proxy host lets Let's Encrypt's
    check through (certificate.py)."""
    from . import certificate
    with app.app_context():
        found = certificate.watch()
    if found and found.get("state") == "getting":
        _say("Let's Encrypt's check gets through: the certificate is asked for")


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

    panel = subprocess.Popen(GUNICORN)
    webmail = subprocess.Popen(WEBMAIL_GUNICORN)
    up = bring_up(app, stalwart)
    restarts = 0 if up else 1
    retry_at = time.monotonic() + (0 if up else backoff(0))
    up_since = next_sync = next_look = next_certificate = time.monotonic()
    next_sync += SYNC_EVERY
    while not stopping.is_set() and panel.poll() is None and webmail.poll() is None:
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
        if now >= next_look:   # the automatic domain checks' time, looked at every minute
            check_domains_if_due(app)
            next_look = now + 60
        if now >= next_certificate and stalwart.running():
            watch_certificate(app)
            next_certificate = time.monotonic() + CERTIFICATE_EVERY
        stopping.wait(1)

    # docker stop gives ten seconds: all are asked to stop at once
    panel.terminate()
    webmail.terminate()
    stalwart.stop(timeout=7)
    for site in (panel, webmail):
        try:
            site.wait(2)
        except subprocess.TimeoutExpired:
            site.kill()
    relay.shutdown()
    return 0 if stopping.is_set() else (panel.poll() or webmail.poll() or 1)


if __name__ == "__main__":
    sys.exit(main())
