"""Where the webmail is (Settings > Miscellaneous), and the tickets that open it from the Mailboxes
page, already signed in as the mailbox: made by the panel, used once by the webmail (webmail.py)
within a minute, and kept only as fingerprints. Until an address is set, the webmail is taken to
be beside the panel, on port 17090."""
import hashlib
import ipaddress
import secrets
import time
from urllib.parse import urlsplit

from . import domain_records
from .db import get_db

PORT = 17090
TICKET_SECONDS = 60


def _fingerprint(token):
    return hashlib.sha256(token.encode()).hexdigest()


def saved():
    return get_db().execute("SELECT address FROM webmail_site WHERE id = 1").fetchone()["address"]


def beside(host):
    """The webmail beside the panel: the same server, port 17090 (plain http: it has no certificate
    of its own; Nginx Proxy Manager gives it one at its own name). A panel behind Cloudflare's proxy
    can't have it there, since the proxy doesn't carry port 17090: then it's at the server's own
    address (when DNS can tell it), and the Mailboxes page says to give the webmail one."""
    name = urlsplit(f"//{host}").hostname or "localhost"
    if domain_records.behind_proxy(host):
        name = domain_records.own_address() or name
    return f"http://{f'[{name}]' if ':' in name else name}:{PORT}"


def behind_proxy(host):
    """Whether the webmail has no address of its own while the panel is behind Cloudflare's proxy."""
    return not saved() and domain_records.behind_proxy(host)


def address(host):
    return saved() or beside(host)


def tidy(typed):
    """(address, None) as it's kept (None: beside the panel), or (None, problem)."""
    typed = typed.strip().rstrip("/")
    if not typed:
        return None, None
    if "://" not in typed:
        typed = f"https://{typed}"
    parts = urlsplit(typed)
    name = parts.hostname or ""
    try:
        is_address = bool(ipaddress.ip_address(name))
    except ValueError:
        is_address = False
    if parts.scheme not in ("http", "https") or not name or parts.query or parts.fragment or not (
            "." in name or is_address or name == "localhost"):
        return None, "Type the webmail's address, like https://webmail.example.com."
    return typed, None


def save(value):
    db = get_db()
    db.execute("UPDATE webmail_site SET address = ? WHERE id = 1", (value,))
    db.commit()


def new_ticket(mailbox_id):
    token = secrets.token_urlsafe(32)
    db = get_db()
    db.execute("DELETE FROM webmail_tickets WHERE expires_at <= ?", (time.time(),))   # the old ones go
    db.execute("INSERT INTO webmail_tickets (token_hash, mailbox_id, expires_at) VALUES (?, ?, ?)",
               (_fingerprint(token), mailbox_id, time.time() + TICKET_SECONDS))
    db.commit()
    return token


def take_ticket(token):
    """The mailbox a ticket is for, once: None when it's unknown, used or too old."""
    db = get_db()
    row = db.execute("SELECT mailbox_id, expires_at FROM webmail_tickets WHERE token_hash = ?",
                     (_fingerprint(token or ""),)).fetchone()
    if row is None:
        return None
    db.execute("DELETE FROM webmail_tickets WHERE token_hash = ?", (_fingerprint(token),))
    db.commit()
    return row["mailbox_id"] if row["expires_at"] > time.time() else None
