"""The way in for calendar and contacts apps (CalDAV, CardDAV; Thunderbird, an iPhone, DAVx⁵):
the engine's /dav/, through the webmail's own address (https://webmail.example.com/dav/...), since
the engine itself answers only inside the server. Settings > Connect third-party apps shows the
addresses.

An app signs in with the mailbox's address and password (HTTP Basic). They're checked here, as
the login page checks them, never by the engine, which would ban 127.0.0.1, and with it the whole
webmail, after a few wrong ones: so wrong passwords lock the address here too (webmail_lock.py).
A password found right is trusted for ten minutes (checking one takes a moment, and apps ask
often), until the mailbox's password changes. The request then goes on to the engine as the
mailbox (impersonation, as the webmail's own requests: jmap.py)."""
import base64
import binascii
import hashlib
import hmac
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, Response, current_app, request

from .. import engine, mail_password
from ..db import get_db

bp = Blueprint("dav", __name__)

METHODS = ["GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PROPFIND", "PROPPATCH", "MKCOL", "MKCALENDAR", "COPY", "MOVE",
           "LOCK", "UNLOCK", "REPORT", "ACL"]
PASSED = ("Content-Type", "Depth", "Destination", "Overwrite", "If", "If-Match", "If-None-Match", "Prefer", "Brief",
          "Lock-Token", "Timeout", "Accept", "Schedule-Reply")
RETURNED = ("Content-Type", "ETag", "Location", "DAV", "Allow", "Lock-Token", "Preference-Applied", "Last-Modified",
            "Content-Disposition", "Schedule-Tag", "Cache-Control", "Retry-After")
TRUSTED_FOR = 600   # seconds
TIMEOUT = 60
REALM = "Someless Mail"

_trusted = {}   # (email, a digest of the password) -> (the mailbox's password version, until when)
_trusted_lock = threading.Lock()


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None   # (the app follows them itself: /.well-known/caldav -> /dav/cal)


_opener = urllib.request.build_opener(_NoRedirects)


def _ask(status=401, text="Sign in with your email address and its password."):
    response = Response(text + "\n", status=status, mimetype="text/plain")
    if status == 401:
        response.headers["WWW-Authenticate"] = f'Basic realm="{REALM}", charset="UTF-8"'
    return response


def _credentials():
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("basic "):
        return None, None
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None, None
    email, _, password = decoded.partition(":")
    return email.strip().lower()[:254], password


def _digest(password):
    return hmac.new(current_app.config["SECRET_KEY"].encode(), password.encode(), hashlib.sha256).hexdigest()


def _password_right(row, email, password):
    """Whether the password is the mailbox's: from the ten minutes' trust, or checked."""
    key = (email, _digest(password))
    now = time.monotonic()
    with _trusted_lock:
        trusted = _trusted.get(key)
        if trusted and trusted[0] == row["password_version"] and trusted[1] > now:
            return True
    if not mail_password.password_ok(row["password_hash"], password):
        return False
    with _trusted_lock:
        for old in [one for one, (_, until) in _trusted.items() if until <= now]:
            _trusted.pop(old, None)
        _trusted[key] = (row["password_version"], now + TRUSTED_FOR)
    return True


def forget_trust():
    """(Tests; and nothing is trusted after a restart.)"""
    with _trusted_lock:
        _trusted.clear()


def _forward(method, path, headers, body):
    """The request, on to the engine: (status, headers, body)."""
    fake = current_app.config.get("DAV_FORWARD")
    if fake:
        return fake(method, path, headers, body)
    base = current_app.config.get("ENGINE_URL", engine.API_URL).rstrip("/")
    outgoing = urllib.request.Request(base + path, data=body if body else None, method=method, headers=headers)
    try:
        with _opener.open(outgoing, timeout=TIMEOUT) as answer:
            return answer.status, answer.headers, answer.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()
    except OSError:
        return 503, {"Retry-After": "30"}, b"The mail server isn't answering. Try again in a moment.\n"


@bp.route("/.well-known/caldav", methods=METHODS)
@bp.route("/.well-known/carddav", methods=METHODS)
@bp.route("/dav/", methods=METHODS, defaults={"rest": ""})
@bp.route("/dav/<path:rest>", methods=METHODS)
def proxy(rest=""):
    from . import _DUMMY_HASH, _forget_tries, _locked, _wrong_try
    from .. import webmail_lock
    if any(segment in (".", "..") for segment in request.path.split("/")):
        return _ask(400, "That address isn't one of the calendars or address books.")   # (nothing outside them)
    email, password = _credentials()
    if not email:
        return _ask()
    if _locked(email):
        wait = webmail_lock.describe(webmail_lock.settings()[1])
        return _ask(429, f"Too many tries with a wrong password. Wait {wait}, then try again.")
    row = get_db().execute("SELECT * FROM mailboxes WHERE email = ?", (email,)).fetchone()
    if row is None:
        mail_password.password_ok(_DUMMY_HASH, password)   # (as long as a wrong password takes)
        _wrong_try(email)
        return _ask()
    if not _password_right(row, email, password):
        _wrong_try(email)
        return _ask()
    if get_db().execute("SELECT 1 FROM webmail_tries WHERE email = ?", (email,)).fetchone():
        _forget_tries(email)   # (right at last: the wrong ones before it are forgotten)

    headers = {name: request.headers[name] for name in PASSED if name in request.headers}
    here = request.host_url.rstrip("/")
    if "Destination" in headers and headers["Destination"].startswith(here):   # (a copy or move: on the engine's own address)
        headers["Destination"] = current_app.config.get("ENGINE_URL", engine.API_URL).rstrip("/") + headers["Destination"][len(here):]
    login = f"{email}%{engine.WEBMAIL_ACCOUNT}@{engine.INTERNAL_DOMAIN}"
    secret = current_app.config.get("DAV_SECRET") or engine.secret("webmail_password")
    headers["Authorization"] = "Basic " + base64.b64encode(f"{login}:{secret}".encode()).decode()
    path = urllib.parse.quote(request.path, safe="/@:+,;=!$&'()*~")   # (as it came: team%20lunch.ics)
    if request.query_string:
        path += "?" + request.query_string.decode("latin-1")
    status, answer_headers, body = _forward(request.method, path, headers, request.get_data())
    response = Response(body if request.method != "HEAD" else b"", status=status)
    for name in RETURNED:
        value = answer_headers.get(name) if hasattr(answer_headers, "get") else None
        if value:
            response.headers[name] = value
    if request.method == "HEAD" and hasattr(answer_headers, "get") and answer_headers.get("Content-Length"):
        response.headers["Content-Length"] = answer_headers.get("Content-Length")
    response.headers.setdefault("Cache-Control", "no-store")
    return response
