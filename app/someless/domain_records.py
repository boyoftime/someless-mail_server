"""The DNS records a mail domain needs, and checking them.

Authenticating a domain takes five records at the domain provider, all safe to add straight
away:
- the Someless code (TXT): shows the domain is the admin's
- A: points mail.<domain> at this server
- SPF (TXT): lets this server send the domain's mail
- DKIM (TXT): the public half of the key that signs the domain's mail
- DMARC (TXT): tells other mail servers what to do with mail that fails those checks
Receiving the domain's mail here takes one more, MX, which moves all new mail for the domain
to this server. That one waits until the domain's mail is to move.

A domain often has mail set up already (Zoho Mail, Google Workspace, Brevo...). Each look at
its DNS notes what is there, and the records fit around it: an SPF record is extended, never
doubled; a DMARC record is kept; the MX records stay until the mail moves; and if mail.<domain>
is taken, this server takes the next free name.
"""
import base64
import ipaddress
import json
import re
import secrets
import socket
import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

import dns.exception
import dns.resolver
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .db import get_db

DKIM_SELECTOR = "someless"
AUTHENTICATING = ("code", "a", "spf", "dkim", "dmarc")  # all found: authenticated
HOST_CHOICES = ("mail", "mx", "smtp", "mail2")  # this server's name in the domain: the first free one
SPF_LOOKUP_LIMIT = 10  # DNS lookups one SPF check may take; past it the record fails everywhere

# One record to add: `host` as DNS providers take it ("@" for the domain itself). `advice`:
# how it fits with what the domain has now (`now`: those records' values).
Record = namedtuple("Record", "key title hint type host full_host value priority advice now",
                    defaults=(None, None, ()))
Advice = namedtuple("Advice", "kind text short")  # kind: edit, keep, moved or move; short: for the page's summary
# What the last look at the domain's DNS found for its mail
NOTHING_FOUND = {"mx": [], "txt": [], "spf": [], "dmarc": [], "spf_lookups": 0,
                 "here": {"A": [], "AAAA": []},  # at this server's name
                 "extra": []}  # [type, name, value]: what other services had the domain add (_left_by)


def new_keys():
    """The Someless code and a DKIM key (RSA 2048, what every mail server checks)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return {"code": secrets.token_hex(16), "dkim_selector": DKIM_SELECTOR,
            "dkim_private": private, "dkim_public": base64.b64encode(public).decode()}


def keys_for(domain_id):
    """The domain's code and key, made the first time they are needed."""
    db = get_db()
    row = db.execute("SELECT * FROM domain_keys WHERE domain_id = ?", (domain_id,)).fetchone()
    if row is None:
        made = new_keys()
        db.execute(
            "INSERT INTO domain_keys (domain_id, code, dkim_selector, dkim_private, dkim_public)"
            " VALUES (?, ?, ?, ?, ?)",
            (domain_id, made["code"], made["dkim_selector"], made["dkim_private"], made["dkim_public"]),
        )
        db.commit()
        row = db.execute("SELECT * FROM domain_keys WHERE domain_id = ?", (domain_id,)).fetchone()
    return row


def server_address(host):
    """This server's public IP address, as the way the admin opened the panel tells it: the
    address itself, or what the panel's name points to. None for a private address (the
    panel opened on the server itself, or at home)."""
    name = host[1:host.index("]")] if host.startswith("[") else host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        try:
            address = ipaddress.ip_address(socket.getaddrinfo(name, None, socket.AF_INET)[0][4][0])
        except (OSError, IndexError, ValueError):
            return None
    return str(address) if address.is_global else None


def found_in(keys):
    """What the last look at the domain's DNS found (nothing, before the first look)."""
    return {**NOTHING_FOUND, **json.loads(keys["found"])} if keys["found"] else dict(NOTHING_FOUND)


def records(domain, keys, address):
    """What to add at the domain provider: the records that authenticate the domain, then
    the one that brings its mail here. Each fits with what the domain has now."""
    def make(key, title, hint, rdtype, host, value, priority=None, advice=None, now=()):
        full = domain if host == "@" else f"{host}.{domain}"
        return Record(key, title, hint, rdtype, host, full, value, priority, advice, now)

    found = found_in(keys)
    host = keys["mail_host"] or HOST_CHOICES[0]
    mail_host = f"{host}.{domain}"
    moved = None if host == HOST_CHOICES[0] else Advice(
        "moved", f"mail.{domain} is already in use, so this server takes {mail_host} instead. "
                 f"Leave mail.{domain} as it is.",
        f"This server is {mail_host}, since mail.{domain} is already in use.")
    spf_value, spf_advice, spf_now = _spf(domain, mail_host, address, found)
    dmarc_value, dmarc_advice, dmarc_now = _dmarc(domain, found)
    # mail that goes to another service now: it stays there until the domain's mail moves
    elsewhere = [] if mail_host in found["mx"] else found["mx"]
    authenticating = [
        make("code", "Someless code", "Shows that the domain is yours.",
             "TXT", "@", f"someless-code:{keys['code']}"),
        make("a", "Mail server address", f"Points {mail_host} at this server.",
             "A", host, address, advice=moved),  # no address: the page says to use the server's public one
        make("spf", "SPF record", "Lets this server send the domain's mail.",
             "TXT", "@", spf_value, advice=spf_advice, now=spf_now),
        make("dkim", "DKIM record", "Signs the domain's mail, so nobody can fake it.",
             "TXT", f"{keys['dkim_selector']}._domainkey", f"v=DKIM1; k=rsa; p={keys['dkim_public']}"),
        make("dmarc", "DMARC record", "Tells other mail servers what to do with mail that fails these checks.",
             "TXT", "_dmarc", dmarc_value, advice=dmarc_advice, now=dmarc_now),
    ]
    receiving = make("mx", "MX record", "Sends the domain's incoming mail to this server.",
                     "MX", "@", mail_host, priority=10,
                     advice=Advice("move", "When you move, delete your current MX records and add this one.",
                                   f"Mail keeps going to {_join(_receivers(elsewhere))} until you move it here.")
                     if elsewhere else None, now=elsewhere)
    return authenticating, receiving


def _spf(domain, mail_host, address, found):
    """The SPF record to have, with how to get there from the domain's own: (value, advice, now)."""
    existing = found["spf"]
    lookups = found["spf_lookups"]
    if not existing:
        return f"v=spf1 a:{mail_host} mx ~all", None, ()
    if len(existing) == 1 and _lets_in(existing[0], mail_host, address, found["mx"]):
        advice = "Keep yours: it already lets this server send."
        if lookups > SPF_LOOKUP_LIMIT:
            advice += " " + _too_many_lookups()
        return existing[0], Advice("keep", advice, "Keep your SPF record: it already lets this server send."), ()
    # Name this server by its address when its name would take the record past the lookup limit
    ours = f"ip4:{address}" if address and lookups + 1 > SPF_LOOKUP_LIMIT else f"a:{mail_host}"
    mechanisms, end, modifiers = _spf_parts(existing)
    value = " ".join(["v=spf1", *mechanisms, ours, *([end] if end else []), *modifiers])
    if len(existing) == 1:
        short = "Edit your SPF record instead of adding a second one."
        advice = (f"Edit your existing record: add {ours} to it, so it reads like the value below. "
                  "Don't add a second one: a domain can have only one SPF record. "
                  "Everything it allows now keeps working.")
    else:
        short = f"Put your {len(existing)} SPF records together into one."
        advice = (f"A domain can have only one SPF record, and {domain} has {len(existing)}, so none of "
                  "them works now. Delete them and add this one instead: it allows everything they allow.")
    if ours.startswith("ip4:"):
        advice += (f" It names this server by its IP address, since SPF allows only {SPF_LOOKUP_LIMIT} "
                   f"DNS lookups and your record already takes {lookups}.")
    if lookups + (0 if ours.startswith("ip4:") else 1) > SPF_LOOKUP_LIMIT:
        advice += " " + _too_many_lookups()
    return value, Advice("edit", advice, short), tuple(existing)


def _too_many_lookups():
    return (f"Careful: it takes more than the {SPF_LOOKUP_LIMIT} DNS lookups SPF allows, so it fails "
            "everywhere. Remove the senders you no longer use.")


def _dmarc(domain, found):
    """The DMARC record to have: (value, advice, now). The domain's own stays."""
    existing = found["dmarc"]
    if not existing:
        return "v=DMARC1; p=none", None, ()
    if len(existing) == 1:
        return existing[0], Advice("keep", f"Keep yours: {domain} already has a DMARC record, and a "
                                           "domain can have only one.", "Keep your DMARC record."), ()
    return existing[0], Advice("edit", f"{domain} has {len(existing)} DMARC records, but a domain can have "
                                       "only one, so none of them counts. Keep one and delete the rest.",
                               f"Keep one of your {len(existing)} DMARC records."), tuple(existing)


def receive_note(domain, keys):
    """What moving the domain's mail here means, as things are now."""
    found = found_in(keys)
    mail_host = _mail_host(domain, keys)
    elsewhere = _join(_receivers([server for server in found["mx"] if server != mail_host]))
    if mail_host in found["mx"] and elsewhere:
        return (f"Mail for {domain} goes both to this server and to {elsewhere}, but a domain's mail "
                "should go to one place. Until the mail engine is ready, delete this server's MX record.")
    if mail_host in found["mx"]:
        return (f"Mail for {domain} comes to this server now, but the mail engine isn't ready to receive "
                "it yet. Until it is, point the MX record back to where the mail went before.")
    if elsewhere:
        return (f"Mail for {domain} goes to {elsewhere} now. Keep those MX records until Someless Mail "
                "can receive mail: the mail engine isn't ready yet. When you move, swap them for this "
                f"one, and don't keep both, or some mail would land at {elsewhere} and some here.")
    return (f"{domain} has no MX record, so it doesn't receive mail anywhere yet. Add this one when "
            "Someless Mail can receive mail: the mail engine isn't ready yet.")


# Mail services a domain may use already, told by the names of their mail servers (the
# domain's MX records, and the names that lead mail apps to them), their SPF include, or the
# code they have a domain put in its DNS. `selectors`: the names of their signing keys (DKIM),
# where those are always the same. Services with no servers of their own only send.
MailService = namedtuple("MailService", "name servers spf code selectors", defaults=(None, ()))
MAIL_SERVICES = [
    MailService("Zoho Mail", r"(^|\.)zoho(mail|cloud)?\.[a-z]{2,3}(\.[a-z]{2})?$",
                r"(^|\.)zoho(mail|cloud)?\.[a-z]{2,3}(\.[a-z]{2})?$", r"^zoho-verification=", ("zmail", "zoho")),
    MailService("Google Workspace", r"(^|\.)(google|googlemail|googlehosted)\.com$", r"(^|\.)google(mail)?\.com$",
                None, ("google",)),
    MailService("Microsoft 365", r"(^|\.)outlook\.(com|de|cn)$|\.mx\.microsoft$",
                r"(^|\.)protection(\.partner)?\.outlook\.(com|de|cn)$", r"^ms=ms\d+$", ("selector1", "selector2")),
    MailService("Namecheap Private Email", r"(^|\.)privateemail\.com$", r"(^|\.)privateemail\.com$", None, ("default",)),
    MailService("Namecheap email forwarding", r"^eforward\d*\.registrar-servers\.com$", r"(^|\.)efwd\.registrar-servers\.com$"),
    MailService("Proton Mail", r"(^|\.)protonmail\.ch$", r"(^|\.)protonmail\.ch$", r"^protonmail-verification=",
                ("protonmail", "protonmail2", "protonmail3")),
    MailService("Fastmail", r"(^|\.)(messagingengine\.com|fastmail\.(com|fm))$", r"(^|\.)messagingengine\.com$", None,
                ("fm1", "fm2", "fm3")),
    MailService("iCloud Mail", r"(^|\.)icloud\.com$", r"(^|\.)icloud\.com$", r"^apple-domain=", ("sig1",)),
    MailService("Yandex 360", r"(^|\.)yandex\.(net|ru|com)$", r"(^|\.)yandex\.(net|ru|com)$", None, ("mail",)),
    MailService("GoDaddy email", r"(^|\.)secureserver\.net$", r"(^|\.)secureserver\.net$"),
    MailService("Hostinger email", r"(^|\.)hostinger\.[a-z.]+$", r"(^|\.)hostinger\.[a-z.]+$", None,
                ("hostingermail1", "hostingermail2", "hostingermail3")),
    MailService("Titan Email", r"(^|\.)titan\.email$", r"(^|\.)titan\.email$"),
    MailService("IONOS email", r"(^|\.)(ionos|1and1)\.[a-z.]+$|(^|\.)kundenserver\.de$",
                r"(^|\.)(ionos\.[a-z.]+|perfora\.net|kundenserver\.de)$"),
    MailService("Cloudflare Email Routing", r"(^|\.)mx\.cloudflare\.net$", r"(^|\.)mx\.cloudflare\.net$"),
    MailService("ImprovMX", r"(^|\.)improvmx\.com$", r"(^|\.)improvmx\.com$"),
    MailService("Forward Email", r"(^|\.)forwardemail\.net$", r"(^|\.)forwardemail\.net$", r"^forward-email(-port)?="),
    MailService("Migadu", r"(^|\.)migadu\.com$", r"(^|\.)migadu\.com$", r"^hosted-email-verify=", ("key1", "key2", "key3")),
    MailService("Rackspace Email", r"(^|\.)emailsrvr\.com$", r"(^|\.)emailsrvr\.com$"),
    MailService("Mimecast", r"(^|\.)mimecast\.com$", r"(^|\.)mimecast\.com$"),
    MailService("Proofpoint", r"(^|\.)pphosted\.com$", r"(^|\.)pphosted\.com$"),
    MailService("Mailgun", r"(^|\.)mailgun\.org$", r"(^|\.)mailgun\.org$"),
    MailService("SendGrid", r"(^|\.)sendgrid\.net$", r"(^|\.)sendgrid\.net$"),
    MailService("Amazon SES", r"^inbound-smtp\.[a-z0-9-]+\.amazonaws\.com$", r"(^|\.)amazonses\.com$"),
    MailService("Brevo", None, r"(^|\.)(brevo|sendinblue)\.com$", r"^(brevo|sendinblue)-code:"),
    MailService("Mailchimp", None, r"(^|\.)(mcsv\.net|mandrillapp\.com)$"),
    MailService("Postmark", None, r"(^|\.)mtasv\.net$"),
    MailService("SparkPost", None, r"(^|\.)sparkpostmail\.com$"),
    MailService("Mailjet", None, r"(^|\.)mailjet\.com$"),
    MailService("MailerSend", None, r"(^|\.)mailersend\.net$"),
    MailService("MailerLite", None, r"(^|\.)mlsend\.com$"),
    MailService("Elastic Email", None, r"(^|\.)elasticemail\.com$"),
    MailService("SMTP2GO", None, r"(^|\.)smtp2go\.com$"),
    MailService("Zoho Campaigns", None, r"(^|\.)zcsend\.net$"),
    MailService("Constant Contact", None, r"(^|\.)constantcontact\.com$"),
    MailService("HubSpot", None, r"(^|\.)hubspotemail\.net$"),
    MailService("Salesforce", None, r"(^|\.)salesforce\.com$"),
    MailService("Zendesk", None, r"(^|\.)zendesk\.com$"),
    MailService("Freshdesk", None, r"(^|\.)freshdesk\.com$"),
]
APP_NAMES = ("mail", "autodiscover", "autoconfig")  # names that often lead mail apps to a service


def _service_by(field, text):
    """The mail service a server name, SPF include or TXT code belongs to (`field`: servers, spf
    or code)."""
    return next((service for service in MAIL_SERVICES
                 if getattr(service, field) and re.search(getattr(service, field), text.rstrip("."), re.I)), None)


def _receivers(servers):
    """Who the mail servers belong to: known services by name, else by the first server's own."""
    known = [service.name for service in map(lambda server: _service_by("servers", server), servers) if service]
    return list(dict.fromkeys(known)) or servers[:1]


def _join(names):
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}" if names else ""


def _mail_host(domain, keys):
    return f"{keys['mail_host'] or HOST_CHOICES[0]}.{domain}"


def _uses(found, mail_host):
    """Who handles the domain's mail now: {name: {"service", "receives", "sends", "code"}}, the
    services its mail goes to first. Mail servers of no service we know go by the first one's name."""
    uses = {}

    def note(name, service, role):
        uses.setdefault(name, {"service": service, "receives": False, "sends": False, "code": False})[role] = True

    servers = [server for server in found["mx"] if server != mail_host]
    known = [service for service in map(lambda server: _service_by("servers", server), servers) if service]
    for service in known:
        note(service.name, service, "receives")
    if servers and not known:
        note(servers[0], None, "receives")
    mechanisms, _, modifiers = _spf_parts(found["spf"])
    for target in filter(None, map(_target, mechanisms + modifiers)):
        service = _service_by("spf", target)
        if service:
            note(service.name, service, "sends")
    for record in found["txt"]:
        service = _service_by("code", record)
        if service:  # a code alone shows sending only for services that do nothing else
            note(service.name, service, "code" if service.servers else "sends")
    return uses


def services(domain, keys):
    """The mail services the domain uses now: [{"name", "receives", "sends"}], receiving first."""
    return [{"name": name, "receives": use["receives"], "sends": use["sends"]}
            for name, use in _uses(found_in(keys), _mail_host(domain, keys)).items() if use["receives"] or use["sends"]]


Row = namedtuple("Row", "type host value note code", defaults=(None,))  # a record to delete; code: a value the note ends with


def cleanup(domain, keys, address):
    """What to delete for a clean setup, and when: {"now": [Row], "moving": [(service, [Row])],
    "unused": [(service, sends, [Row])], "keep": [service]}. `keep`: services that only send,
    which go on sending alongside this server."""
    found = found_in(keys)
    host = keys["mail_host"] or HOST_CHOICES[0]
    mail_host = f"{host}.{domain}"
    now = []
    if len(found["spf"]) > 1:
        now += [Row("TXT", "@", record, f"One of {len(found['spf'])} SPF records: the one on the SPF card "
                                        "takes the place of them all.") for record in found["spf"]]
    now += [Row("TXT", "_dmarc", record, "A domain can have only one DMARC record: keep the one on the DMARC card.")
            for record in found["dmarc"][1:]]
    here = found["here"]
    if address and address in here["A"]:  # the name is this server's: anything else there is in the way
        now += [Row("A", host, other, "Sends some of the mail meant for this server somewhere else.")
                for other in here["A"] if other != address]
        now += [Row("AAAA", host, other, "Delete it unless it's this server's IPv6 address: servers that use "
                                         "IPv6 would go there instead.") for other in here["AAAA"]]
    spf_value = _spf(domain, mail_host, address, found)[0]
    moving, unused, keep = [], [], []
    for name, use in _uses(found, mail_host).items():
        service = use["service"]
        if service and not service.servers:
            keep.append(name)
            continue
        rows = _left_by(service, name, found, spf_value, host) if service else []
        if use["receives"]:
            servers = [server for server in found["mx"] if server != mail_host
                       and (service is None or _service_by("servers", server) == service)]
            moving.append((name, [Row("MX", "@", server, None) for server in servers] + rows))
        elif rows:
            unused.append((name, use["sends"], rows))
    return {"now": now, "moving": moving, "unused": unused, "keep": keep}


def _left_by(service, name, found, spf_value, host):
    """What a mail service had the domain add besides its MX records: its part of the SPF
    record, its code, its signing keys, and names that lead mail apps to it."""
    rows = []
    theirs = [term for term in spf_value.split()[1:] if _target(term) and _service_by("spf", _target(term)) == service]
    if theirs:
        after = " ".join(term for term in spf_value.split() if term not in theirs)
        rows += [Row("TXT", "@", term, f"Take it out of your SPF record once {name} no longer sends for you, "
                                       "so it reads:", after) for term in theirs]
    rows += [Row("TXT", "@", record, f"Proves the domain to {name}.")
             for record in found["txt"] if service.code and re.search(service.code, record, re.I)]
    keys = {f"{selector}._domainkey" for selector in service.selectors}
    rows += [Row(rdtype, label, value, f"{name}'s signing key (DKIM).")
             for rdtype, label, value in found["extra"] if label in keys]
    rows += [Row(rdtype, label, value, f"Leads mail apps to {name}.")
             for rdtype, label, value in found["extra"]
             if label in APP_NAMES and label != host and re.search(service.servers, value, re.I)]
    return rows


def _is_spf(record):
    return record.lower().startswith("v=spf1") and (len(record) == 6 or record[6] == " ")


def _is_dmarc(record):
    return record.lower().replace(" ", "").startswith("v=dmarc1")


def _lets_in(record, mail_host, address, mx):
    """Whether an SPF record lets this server send (by its name, its address, or as the domain's MX)."""
    terms = {term.lower() for term in record.split()[1:]}
    allowed = {f"a:{mail_host}", f"+a:{mail_host}"} | ({f"ip4:{address}", f"+ip4:{address}"} if address else set())
    return bool(allowed & terms) or (bool({"mx", "+mx"} & terms) and mail_host in mx)


_ALL = re.compile(r"[+\-~?]?all", re.I)
_MODIFIER = re.compile(r"[a-z][a-z0-9_.-]*=", re.I)
_LOOKUP = re.compile(r"[+\-~?]?(include:|exists:|(a|mx|ptr)($|[:/]))|redirect=", re.I)


def _spf_parts(records):
    """SPF records as one: (mechanisms, the all at the end or None, modifiers). Several records
    (a mistake: then none of them works) become one that allows everything they allow."""
    mechanisms, ends, modifiers = [], [], []
    for record in records:
        for term in record.split()[1:]:
            if _ALL.fullmatch(term):
                ends.append(term)
            elif _MODIFIER.match(term) and not (len(records) > 1 and term.lower().startswith("redirect=")):
                if term.split("=", 1)[0].lower() not in {kept.split("=", 1)[0].lower() for kept in modifiers}:
                    modifiers.append(term)
            else:
                if term.lower().startswith("redirect="):  # one record can't redirect for all of them
                    term = "include:" + term.split("=", 1)[1]
                if term.lower() not in {kept.lower() for kept in mechanisms}:
                    mechanisms.append(term)
    # Records that disagree on the end: the mildest, so no sender they allow is turned away
    end = max(ends, key=lambda term: "-~?+".find(term[0]) if term[0] in "-~?+" else 3) if ends else None
    return mechanisms, end, modifiers


def _target(term):
    """The domain an include: or redirect= pulls in: None for other terms, or one built from macros."""
    match = re.match(r"[+\-~?]?include:(.+)$|redirect=(.+)$", term, re.I)
    target = match and (match.group(1) or match.group(2)).lower()
    return target if target and "%" not in target else None


def _spf_lookups(terms):
    """How many DNS lookups checking an SPF record with these terms takes, with what it
    includes. Counting stops once past the limit."""
    count, level = 0, [terms]
    for _ in range(SPF_LOOKUP_LIMIT):
        targets = []
        for level_terms in level:
            for term in level_terms:
                if _LOOKUP.match(term):
                    count += 1
                    if _target(term):
                        targets.append(_target(term))
        if count > SPF_LOOKUP_LIMIT or not targets:
            break
        answers = _ask([(target, "TXT") for target in dict.fromkeys(targets)])
        level = [next((record.split()[1:] for record in answers[(target, "TXT")] if _is_spf(record)), [])
                 for target in targets]
    return count


# Who runs a domain's DNS, told by the names of its name servers. The records go there.
PROVIDERS = [
    (r"(^|\.)(registrar-servers|namecheaphosting)\.com$", "Namecheap"),
    (r"(^|\.)cloudflare\.com$", "Cloudflare"),
    (r"(^|\.)google\.com$", "Google"),
    (r"(^|\.)domaincontrol\.com$", "GoDaddy"),
    (r"\.awsdns-\d+\.", "Amazon Route 53"),
    (r"(^|\.)digitalocean\.com$", "DigitalOcean"),
    (r"(^|\.)googledomains\.com$", "Google Cloud DNS"),
    (r"(^|\.)hetzner\.(com|de)$", "Hetzner"),
    (r"(^|\.)ovh\.(net|ca)$", "OVHcloud"),
    (r"(^|\.)gandi\.net$", "Gandi"),
    (r"(^|\.)porkbun\.com$", "Porkbun"),
    (r"(^|\.)name\.com$", "Name.com"),
    (r"(^|\.)(dns-parking|hostinger)\.com$", "Hostinger"),
    (r"(^|\.)ui-dns\.(com|de|org|biz)$", "IONOS"),
    (r"(^|\.)azure-dns\.(com|net|org|info)$", "Azure DNS"),
    (r"(^|\.)wixdns\.net$", "Wix"),
    (r"(^|\.)squarespacedns\.com$", "Squarespace"),
    (r"(^|\.)linode\.com$", "Linode"),
    (r"(^|\.)vultr\.com$", "Vultr"),
    (r"(^|\.)dyna-ns\.net$", "Dynadot"),
    (r"(^|\.)dnsowl\.com$", "NameSilo"),
    (r"(^|\.)hover\.com$", "Hover"),
    (r"(^|\.)name-services\.com$", "eNom"),
    (r"(^|\.)dnsimple\.com$", "DNSimple"),
    (r"(^|\.)vercel-dns\.com$", "Vercel"),
    (r"(^|\.)contabo\.net$", "Contabo"),
    (r"(^|\.)he\.net$", "Hurricane Electric"),
    (r"(^|\.)zoho\.com$", "Zoho"),
]


def dns_provider(domain):
    """Who runs the domain's DNS: a name we know, else its first name server, else None.
    A subdomain without name servers of its own uses its parent domain's."""
    labels = domain.split(".")
    for start in range(len(labels) - 1):  # example.co.uk, then co.uk, never the top level alone
        servers = sorted(server.rstrip(".").lower() for server in _answers(".".join(labels[start:]), "NS"))
        if servers:
            for pattern, name in PROVIDERS:
                if any(re.search(pattern, server) for server in servers):
                    return name
            return servers[0]
    return None


def _answers(name, rdtype):
    try:
        return lookup(name, rdtype)
    except Exception:
        return []


def lookup(name, rdtype):
    """The answers to one DNS question, as text: none if there are none, or if DNS
    doesn't answer in time."""
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 4.0
    try:
        answer = resolver.resolve(name, rdtype)
    except dns.exception.DNSException:
        return []
    if rdtype == "TXT":
        return [b"".join(item.strings).decode("utf-8", "replace") for item in answer]
    if rdtype == "MX":
        return [str(item.exchange).rstrip(".").lower() for item in sorted(answer, key=lambda item: item.preference)]
    return [item.to_text() for item in answer]


def _ask(questions):
    """All the DNS questions at once (so a slow DNS costs seconds, not minutes)."""
    with ThreadPoolExecutor(max_workers=len(questions)) as pool:
        return dict(zip(questions, pool.map(lambda question: _answers(*question), questions)))


def look(domain, keys, address):
    """One round of DNS questions about the domain: (host, found, results).

    host: this server's name in the domain, kept once chosen: the first of HOST_CHOICES that
    nothing else uses. found: what the domain has for mail now (NOTHING_FOUND's keys).
    results: whether each record to add is there, {key: {"state", "detail"}}; state is found,
    missing or different (and for MX, elsewhere: the mail goes to another service still)."""
    host = keys["mail_host"]
    # Before a name is chosen, ask about every choice, and about a made-up name that only a
    # wildcard record (*.domain) answers: a name answering just like it is still free.
    labels = [host] if host else [*HOST_CHOICES, f"someless-{secrets.token_hex(4)}"]
    selector = f"{keys['dkim_selector']}._domainkey.{domain}"
    questions = [(domain, "TXT"), (domain, "MX"), (f"_dmarc.{domain}", "TXT"), (selector, "TXT")]
    questions += [(f"{label}.{domain}", rdtype) for label in labels for rdtype in ("A", "AAAA", "CNAME")]
    questions += [(f"{label}.{domain}", "CNAME") for label in APP_NAMES]
    answers = _ask(list(dict.fromkeys(questions)))

    def at(label):
        return tuple(tuple(sorted(answers[(f"{label}.{domain}", rdtype)])) for rdtype in ("A", "AAAA", "CNAME"))

    def free(label):  # nothing else lives there: nothing at all, this server, or only the wildcard
        return not any(at(label)) or address in at(label)[0] or at(label) == at(labels[-1])

    if not host:
        host = next((label for label in HOST_CHOICES if free(label)), HOST_CHOICES[0])
    mail_host = f"{host}.{domain}"

    txt = answers[(domain, "TXT")]
    mx = answers[(domain, "MX")]
    spf = [record for record in txt if _is_spf(record)]
    dmarc = [record for record in answers[(f"_dmarc.{domain}", "TXT")] if _is_dmarc(record)]
    found = {"mx": mx, "txt": txt, "spf": spf, "dmarc": dmarc,
             "here": {"A": answers[(mail_host, "A")], "AAAA": answers[(mail_host, "AAAA")]},
             "extra": [["CNAME", label, target.rstrip(".")] for label in APP_NAMES if label != host
                       for target in answers[(f"{label}.{domain}", "CNAME")]]}
    # The signing keys of the services found, where their names are known. A key that a CNAME
    # leads to is listed as that CNAME, the record the domain has.
    selectors = [f"{name}._domainkey" for use in _uses(found, mail_host).values() if use["service"]
                 for name in use["service"].selectors]
    if selectors:
        keyed = _ask([(f"{label}.{domain}", rdtype) for label in selectors for rdtype in ("CNAME", "TXT")])
        for label in selectors:
            aliases = [["CNAME", label, target.rstrip(".")] for target in keyed[(f"{label}.{domain}", "CNAME")]]
            found["extra"] += aliases or [["TXT", label, value] for value in keyed[(f"{label}.{domain}", "TXT")]]
    mechanisms, _, modifiers = _spf_parts(spf)
    found["spf_lookups"] = _spf_lookups(mechanisms + modifiers) if spf else 0

    results = {}

    def note(key, state, detail=""):
        results[key] = {"state": state, "detail": detail}

    note("code", "found" if f"someless-code:{keys['code']}" in txt else "missing")

    addresses = answers[(mail_host, "A")]
    others = [other for other in addresses if other != address]
    if not addresses:
        note("a", "missing")
    elif address is None or not others:
        note("a", "found")
    elif address in addresses:
        note("a", "different", f"{mail_host} points to this server and also to {', '.join(others)}. "
                               "Delete the other address, or some mail goes there.")
    else:
        note("a", "different", f"{mail_host} points to {', '.join(addresses)}, not to this server ({address}).")

    # How to put an SPF or DMARC record right is on its card (records())
    if not spf:
        note("spf", "missing")
    else:
        note("spf", "found" if len(spf) == 1 and _lets_in(spf[0], mail_host, address, mx) else "different")

    published = [_dkim_key(record) for record in answers[(selector, "TXT")]]
    published = [key for key in published if key is not None]
    if keys["dkim_public"] in published:
        note("dkim", "found")
    elif published:
        note("dkim", "different", "The DKIM record there holds another key. Copy the value above again.")
    else:
        note("dkim", "missing")

    note("dmarc", "missing" if not dmarc else "found" if len(dmarc) == 1 else "different")

    if mail_host in mx:
        note("mx", "found" if mx == [mail_host] else "different")
    else:
        note("mx", "elsewhere" if mx else "missing")
    return host, found, results


def _dkim_key(record):
    tags = dict(part.strip().split("=", 1) for part in record.split(";") if "=" in part)
    key = tags.get("p")
    return "".join(key.split()) if key else None


def authenticated(results):
    return all(results.get(key, {}).get("state") == "found" for key in AUTHENTICATING)


def save(domain_id, host, found, results=None):
    """Keep what a look at DNS found, and with `results`, how the records checked out."""
    db = get_db()
    db.execute("UPDATE domain_keys SET mail_host = ?, found = ? WHERE domain_id = ?", (host, json.dumps(found), domain_id))
    if results is not None:
        db.execute("UPDATE domain_keys SET checks = ?, checked_at = ? WHERE domain_id = ?",
                   (json.dumps(results), time.time(), domain_id))
        db.execute("UPDATE domains SET authenticated = ? WHERE id = ?", (1 if authenticated(results) else 0, domain_id))
    db.commit()
