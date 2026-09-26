"""Ready to send? The checklist at the top of SMTP & API: what's done, and what to do next.
Engine, server name, certificate and a Sender are needed to send; port 25 and reverse DNS are
warnings (mail may go out, but land in spam or bounce)."""
import socket
import time
from collections import namedtuple
from datetime import datetime, timezone

import dns.resolver
import dns.reversename

from ..db import get_db
from . import client, enabled
from .client import EngineError, EngineUnavailable
from .names import server_name

Check = namedtuple("Check", "key title state detail")
NEEDED = ("engine", "server-name", "certificate", "sender")
_cache = {}


def port25_open():
    try:
        socket.create_connection(("gmail-smtp-in.l.google.com", 25), timeout=5).close()
        return True
    except OSError:
        return False


def reverse_name(ip):
    try:
        answer = dns.resolver.resolve(dns.reversename.from_address(ip), "PTR", lifetime=4)
        return str(answer[0]).rstrip(".").lower()
    except Exception:
        return None


def addresses_of(name):
    try:
        return [item.to_text() for item in dns.resolver.resolve(name, "A", lifetime=4)]
    except Exception:
        return []


def run_checks(address):
    name = server_name()
    found = []
    certificates = None
    if not enabled():
        found.append(Check("engine", "Mail engine running", "missing",
                           "The mail engine isn't running here: it runs in the Someless Mail container."))
    else:
        try:
            certificates = client().get("Certificate")
            found.append(Check("engine", "Mail engine running", "ok", ""))
        except (EngineUnavailable, EngineError):
            found.append(Check("engine", "Mail engine running", "missing",
                               "The mail engine isn't answering. It restarts by itself; if this lasts, restart the container."))
    if not name:
        found.append(Check("server-name", "Server name", "missing", "Authenticate a domain first: the server takes its mail name."))
    elif address and address not in _cached(f"a {name}", lambda: addresses_of(name)):
        found.append(Check("server-name", "Server name points here", "missing",
                           f"{name} doesn't point to {address} yet: add its A record on the domain's Authenticate page."))
    else:
        found.append(Check("server-name", "Server name points here", "ok", name))
    now = datetime.now(timezone.utc).isoformat()
    has_certificate = bool(name) and any(
        name in (cert.get("subjectAlternativeNames") or {}) and cert.get("notValidAfter", "") > now
        for cert in (certificates or []))
    found.append(Check("certificate", "Certificate", "ok" if has_certificate else "missing", "" if has_certificate else (
        f"Let's Encrypt checks {name or 'the server name'} on port 80. In Nginx Proxy Manager, add a proxy host for it "
        "pointing to someless-mail on port 17081, with SSL left off (Someless Mail gets this certificate itself); "
        "without a proxy, map port 80 to 17081.")))
    found.append(_cached("port25", lambda: Check("port25", "Outgoing port 25", "ok", "") if port25_open() else Check(
        "port25", "Outgoing port 25", "warning",
        "Your VPS provider blocks outgoing port 25. Ask them to open it; mail can't reach other servers until then.")))
    if name and address:
        ptr = _cached(f"ptr {address}", lambda: reverse_name(address))
        found.append(Check("reverse-dns", "Reverse DNS", "ok", "") if ptr == name else Check(
            "reverse-dns", "Reverse DNS", "warning", f"At your VPS provider, set the reverse DNS of {address} to {name}."))
    # a sender at a domain that isn't authenticated (any more) can't send: the engine doesn't have it
    has_sender = get_db().execute("SELECT 1 FROM senders JOIN domains ON domains.id = senders.domain_id"
                                  " WHERE domains.authenticated = 1 LIMIT 1").fetchone() is not None
    found.append(Check("sender", "A sender", "ok" if has_sender else "missing", "" if has_sender else (
        "Add one on the Senders page, at an authenticated domain.")))
    return found


def can_send(found):
    return all(check.state == "ok" for check in found if check.key in NEEDED)


def _cached(key, make, seconds=300):
    """Network checks (port 25, DNS) are slow: done once every few minutes, per process."""
    value, at = _cache.get(key, (None, 0))
    if time.time() - at > seconds:
        value = make()
        _cache[key] = (value, time.time())
    return value


def forget():
    """Check again: nothing cached."""
    _cache.clear()
