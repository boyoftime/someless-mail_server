"""Ready to send? The checklist at the top of SMTP & API: what's done, and what to do next.
Engine, server name, certificate and a Sender are needed to send; port 25 and reverse DNS are
warnings (mail may go out, but land in spam or bounce), and so are the ports mail comes in on
(25, and 993 and 995 for mail apps): asked from here, by the server name, the way the world asks,
and whoever answers has to say what the mail engine itself says. Also what the server name
itself needs, for Settings > Mail server name (name_checks)."""
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.request
from collections import namedtuple
from datetime import datetime, timezone

import dns.reversename

from ..db import get_db
from ..domain_records import fresh_lookup
from . import client, enabled
from .client import EngineError, EngineUnavailable
from .names import server_name
from .supervisor import NOT_HERE

Check = namedtuple("Check", "key title state detail")
NEEDED = ("engine", "server-name", "certificate", "sender")
# The ports mail comes in on: key, title, port on the server, port in the container, TLS from the
# start, and the docker-compose.yml line that publishes it
INCOMING = (
    ("port25-in", "Incoming port 25", 25, 25, False, '"25:25"', "Other mail servers can't reach this server, so no mail comes in."),
    ("imap", "IMAP port 993", 993, 17993, True, '"993:17993"', "Mail apps can't reach IMAP here."),
    ("pop3", "POP3 port 995", 995, 17995, True, '"995:17995"', "Mail apps can't reach POP3 here."),
)
_cache = {}


def port25_open():
    try:
        socket.create_connection(("gmail-smtp-in.l.google.com", 25), timeout=5).close()
        return True
    except OSError:
        return False


def greeting(host, port, tls):
    """The first line a mail server says when it's reached (with TLS first, for 993 and 995), or
    None when nothing answers."""
    try:
        with socket.create_connection((host, port), timeout=4) as raw:
            with (ssl._create_unverified_context().wrap_socket(raw) if tls else raw) as conn:   # noqa: S323 (who answers, not trust)
                conn.settimeout(4)
                line = conn.recv(512).split(b"\r\n", 1)[0]
    except (OSError, ValueError):
        return None
    return line.decode(errors="replace") or None


def reaches_us(host, port, inside, tls):
    """Whether the port on the server leads to the mail engine: what answers there says what the
    engine says on its own port in the container, not another server's words."""
    theirs = greeting(host, port, tls)
    return theirs is not None and theirs == greeting("127.0.0.1", inside, tls)


def _incoming(host):
    """The checks of the ports mail comes in on, asked side by side (a closed one takes seconds)."""
    with ThreadPoolExecutor(len(INCOMING)) as pool:
        reached = list(pool.map(lambda port: reaches_us(host, port[2], port[3], port[4]), INCOMING))
    found = []
    for (key, title, port, _, _, mapping, why), ok in zip(INCOMING, reached):
        found.append(Check(key, title, "ok", "") if ok else Check(key, title, "warning", (
            f"{why} Add {mapping} under ports in docker-compose.yml and run docker compose up -d, "
            f"then open it in your firewall: sudo ufw allow {port}/tcp.")))
    return found


def reverse_name(ip):
    """The name the IP address answers with (PTR), from the VPS provider's own name servers:
    a change at the provider shows at once."""
    try:
        name = dns.reversename.from_address(ip).to_text(omit_final_dot=True)
    except Exception:
        return None
    found = fresh_lookup(name, "PTR")
    return found[0].rstrip(".").lower() if found else None


def addresses_of(name):
    """Where the name points (A), from its domain's own name servers: a record just added
    shows at once."""
    return fresh_lookup(name, "A")


def relay_answers(url):
    """Whether the challenge relay (supervisor.py) is what answers at this address: it says
    so in every answer that isn't a real challenge's."""
    try:
        with urllib.request.urlopen(url, timeout=4) as response:
            body = response.read(300)
    except urllib.error.HTTPError as error:
        body = error.read(300)
    except (OSError, ValueError):
        return False
    return NOT_HERE.strip() in body


def relay_reached(name):
    """Whether Let's Encrypt's check of the name gets through to Someless Mail (the proxy
    host, or port 80 mapped to 17081)."""
    return relay_answers(f"http://{name}/.well-known/acme-challenge/someless-check")


def _certificates():
    """The engine's certificates; None when it isn't there to ask."""
    if not enabled():
        return None
    try:
        return client().get("Certificate")
    except (EngineUnavailable, EngineError):
        return None


def _has_certificate(name, certificates):
    now = datetime.now(timezone.utc).isoformat()
    return bool(name) and any(name in (cert.get("subjectAlternativeNames") or {}) and cert.get("notValidAfter", "") > now
                              for cert in (certificates or []))


def name_checks(address):
    """What the server name needs, each with how it stands: its A record, the proxy host
    Let's Encrypt comes through, reverse DNS (when the panel knows its public address) and
    the certificate. Empty without a server name."""
    name = server_name()
    if not name:
        return []
    found = []
    if address and address not in _cached(f"a {name}", lambda: addresses_of(name)):
        found.append(Check("server-name", "Points to this server", "missing",
                           f"Add its A record on the domain's Authenticate page, pointing to {address}."))
    else:
        found.append(Check("server-name", "Points to this server", "ok", f"{name} leads to this server."))
    if _cached(f"relay {name}", lambda: relay_reached(name)):
        found.append(Check("proxy-host", "Proxy host", "ok",
                           f"{name} → http://someless-mail:17081, SSL off: Let's Encrypt's check gets through."))
    else:   # the page lists the proxy host's settings under it
        found.append(Check("proxy-host", "Proxy host", "missing",
                           "In Nginx Proxy Manager, add a proxy host with these settings. "
                           "Without a proxy, map port 80 to 17081 instead."))
    if address:
        ptr = _cached(f"ptr {address}", lambda: reverse_name(address))
        found.append(Check("reverse-dns", "Reverse DNS", "ok", f"{address} answers with {name}.") if ptr == name else Check(
            "reverse-dns", "Reverse DNS", "warning", f"At your VPS provider, set the reverse DNS of {address} to {name}."))
    if _has_certificate(name, _certificates()):
        found.append(Check("certificate", "Certificate", "ok", "From Let's Encrypt. Someless Mail renews it by itself."))
    else:
        found.append(Check("certificate", "Certificate", "missing",
                           "Let's Encrypt gives it once the proxy host works. Then click Check again."))
    return found


def run_checks(address):
    name = server_name()
    found = []
    certificates = None
    engine_up = False
    if not enabled():
        found.append(Check("engine", "Mail engine running", "missing",
                           "The mail engine isn't running here: it runs in the Someless Mail container."))
    else:
        try:
            certificates = client().get("Certificate")
            found.append(Check("engine", "Mail engine running", "ok", ""))
            engine_up = True
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
    has_certificate = _has_certificate(name, certificates)
    found.append(Check("certificate", "Certificate", "ok" if has_certificate else "missing", "" if has_certificate else (
        f"Let's Encrypt checks {name or 'the server name'} on port 80. In Nginx Proxy Manager, add a proxy host for it: "
        "scheme http, forward hostname someless-mail, forward port 17081, SSL left off (Someless Mail gets this "
        "certificate itself). Without a proxy, map port 80 to 17081.")))
    found.append(_cached("port25", lambda: Check("port25", "Outgoing port 25", "ok", "") if port25_open() else Check(
        "port25", "Outgoing port 25", "warning",
        "Your VPS provider blocks outgoing port 25. Ask them to open it; mail can't reach other servers until then.")))
    if engine_up and (name or address):   # with the engine down, nothing would answer anyway
        found.extend(_cached(f"incoming {name or address}", lambda: _incoming(name or address)))
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
