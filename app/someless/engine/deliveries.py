"""Test emails, and what becomes of them. The panel sends through the engine like any app
(its own account, someless-panel), and Stalwart reports each delivery back here: a POST to
/engine/events from inside the container, signed with the webhook secret. Its events carry
the queue id as a number; the reply to the mail gave it in hex, which is what's kept."""
import base64
import hashlib
import hmac
import json
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from flask import Blueprint, abort, current_app, request

from ..db import get_db
from . import PANEL_ACCOUNT, secret

bp = Blueprint("engine", __name__, url_prefix="/engine")
SMTP_HOST, SMTP_PORT = "127.0.0.1", 17587
EVENTS_URL = "http://127.0.0.1:17080/engine/events"   # the panel, inside the container
QUEUED = re.compile(rb"queued with id ([0-9A-Fa-f]+)", re.I)
FINAL = {"delivery.delivered": "delivered", "delivery.dsn-perm-fail": "bounced", "delivery.rcpt-to-rejected": "bounced"}
RETRY = ("delivery.dsn-temp-fail", "delivery.rcpt-to-failed", "delivery.greeting-failed", "delivery.connect-error")
EVENTS = tuple(FINAL) + RETRY   # what the WebHook reports (engine/sync.py)
WAIT = 60   # seconds; after that, a test still on its way says so


class SendFailed(Exception):
    """The engine refused the test email; the message is its reply."""


def events_url():
    """Where Stalwart reports: the panel beside it (ENGINE_EVENTS_URL: elsewhere, for the live tests)."""
    return current_app.config.get("ENGINE_EVENTS_URL", EVENTS_URL)


def send_test(from_address, sender_id, to, subject, text):
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = from_address, to, subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=from_address.rsplit("@", 1)[1])
    message.set_content(text)
    context = ssl._create_unverified_context()   # loopback inside the container
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.starttls(context=context)
            smtp.login(PANEL_ACCOUNT, secret("panel_password"))
            code, reply = smtp.mail(from_address)
            if code >= 400:
                raise SendFailed(reply.decode("utf-8", "replace"))
            code, reply = smtp.rcpt(to)
            if code >= 400:
                raise SendFailed(reply.decode("utf-8", "replace"))
            code, reply = smtp.data(message.as_bytes())
    except smtplib.SMTPResponseException as error:
        raise SendFailed(error.smtp_error.decode("utf-8", "replace")) from error
    except (smtplib.SMTPException, OSError) as error:
        raise SendFailed(str(error)) from error
    found = QUEUED.search(reply)
    if code >= 400 or not found:
        raise SendFailed(reply.decode("utf-8", "replace"))
    queue_id = found.group(1).decode().lower()
    record(queue_id, sender_id, to)
    return queue_id


def record(queue_id, sender_id, recipient):
    now = time.time()
    db = get_db()
    db.execute("INSERT INTO deliveries (queue_id, sender_id, recipient, status, created_at, updated_at) VALUES (?, ?, ?, 'queued', ?, ?)",
               (queue_id, sender_id, recipient, now, now))
    db.commit()


def status(queue_id):
    row = get_db().execute("SELECT * FROM deliveries WHERE queue_id = ? ORDER BY id DESC LIMIT 1", (queue_id,)).fetchone()
    if row is None:
        return None
    return {"status": row["status"], "detail": row["detail"], "recipient": row["recipient"],
            "waited_long": row["status"] in ("queued", "retrying") and time.time() - row["created_at"] > WAIT}


def last_for(sender_id):
    return get_db().execute("SELECT * FROM deliveries WHERE sender_id = ? ORDER BY id DESC LIMIT 1", (sender_id,)).fetchone()


def _from_inside():
    # the socket's own address: ProxyFix keeps it here before it trusts X-Forwarded-For
    original = request.environ.get("werkzeug.proxy_fix.orig", {}).get("REMOTE_ADDR", request.environ.get("REMOTE_ADDR"))
    return original in ("127.0.0.1", "::1")


def _signed(body):
    expected = base64.b64encode(hmac.new(secret("webhook_secret").encode(), body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, request.headers.get("X-Signature", ""))


def _parse(event):
    """(queue id in hex, event type, what to tell the admin)"""
    data = event.get("data") or {}
    number = data.get("queueId")
    queue_id = format(number, "x") if isinstance(number, int) else str(number or "")
    kind = event.get("type", "")
    if kind == "delivery.delivered":
        detail = f"Delivered to {data['hostname']}" if data.get("hostname") else ""
    else:
        detail = data.get("details") or data.get("reason") or data.get("response") or ""
    return queue_id, kind, str(detail)


@bp.post("/events")
def events():
    body = request.get_data()
    if not _from_inside() or not _signed(body):
        abort(403)
    try:
        reported = json.loads(body or b"{}").get("events", [])
    except (ValueError, AttributeError):
        abort(400)
    db = get_db()
    for event in reported:
        queue_id, kind, detail = _parse(event)
        new = FINAL.get(kind) or ("retrying" if kind in RETRY else None)
        if queue_id and new:
            # a delivered or bounced test stays so; a late retry report doesn't undo it
            db.execute("UPDATE deliveries SET status = ?, detail = ?, updated_at = ? WHERE queue_id = ?"
                       " AND status NOT IN ('delivered', 'bounced')", (new, detail, time.time(), queue_id))
    db.commit()
    return "", 204
