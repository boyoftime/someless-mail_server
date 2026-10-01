"""The server name's certificate, as soon as it can be had. While there's none, whether Let's
Encrypt's check gets through to Someless Mail (the proxy host, or port 80) is looked at again and
again: by the container every half minute (supervisor.py), and by an open SMTP & API or Mail server
name page (certificate-watch.js). The moment it gets through, the certificate is asked for at once,
without waiting for a click or for Stalwart's own next try, which can be hours away: then the check
can pass, so it costs none of Let's Encrypt's few failed checks an hour."""
from . import checks, enabled, names, remember, state
from . import sync

WAITING = ("Let's Encrypt checks {name} on port 80. In Nginx Proxy Manager, add a proxy host for it: scheme http, "
           "forward hostname someless-mail, forward port 17081, SSL left off. It's asked for by itself as soon as "
           "that works.")
GETTING = "The proxy host works: Let's Encrypt is being asked for it now. It usually takes a minute or two."
DONE = "From Let's Encrypt. Someless Mail renews it by itself."


def watch():
    """{"state": none, waiting, getting or ok; "title"; "detail"}, having asked for the certificate
    if Let's Encrypt's check has just started getting through."""
    name = names.server_name()
    if not enabled() or not name:
        return {"state": "none", "title": "Certificate", "detail": "Authenticate a domain first: the server takes its mail name."}
    if checks._has_certificate(name, checks._certificates()):
        return {"state": "ok", "title": "Certificate", "detail": DONE}
    reachable = checks.relay_reached(name)
    was = bool(state()["certificate_relay_ok"])
    if reachable != was:
        remember(certificate_relay_ok=int(reachable))
    if not reachable:
        return {"state": "waiting", "title": "Certificate", "detail": WAITING.format(name=name)}
    sync.ask_for_certificate(now=not was)   # just started working: at once; else at most every 10 minutes
    return {"state": "getting", "title": "Certificate", "detail": GETTING}


def relay_seen():
    """Whether Let's Encrypt's check got through at the last look (for the pages' own checklists)."""
    return bool(state()["certificate_relay_ok"])
