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

# One record to add: `host` as DNS providers take it ("@" for the domain itself)
Record = namedtuple("Record", "key title hint type host full_host value priority")


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


def records(domain, keys, address):
    """What to add at the domain provider: the records that authenticate the domain, then
    the one that brings its mail here."""
    def full(host):
        return domain if host == "@" else f"{host}.{domain}"

    def make(key, title, hint, rdtype, host, value, priority=None):
        return Record(key, title, hint, rdtype, host, full(host), value, priority)

    selector = f"{keys['dkim_selector']}._domainkey"
    authenticating = [
        make("code", "Someless code", "Shows that the domain is yours.",
             "TXT", "@", f"someless-code:{keys['code']}"),
        make("a", "Mail server address", f"Points mail.{domain} at this server.",
             "A", "mail", address),  # None: the page says to use the server's public address
        make("spf", "SPF record", f"Lets this server send the domain's mail. A domain can have only "
             f"one: if it already has one, add a:mail.{domain} to it instead.",
             "TXT", "@", f"v=spf1 a:mail.{domain} mx ~all"),
        make("dkim", "DKIM record", "Signs the domain's mail, so nobody can fake it.",
             "TXT", selector, f"v=DKIM1; k=rsa; p={keys['dkim_public']}"),
        make("dmarc", "DMARC record", "Tells other mail servers what to do with mail that fails these checks.",
             "TXT", "_dmarc", "v=DMARC1; p=none"),
    ]
    receiving = make("mx", "MX record", "Sends the domain's incoming mail to this server.",
                     "MX", "@", f"mail.{domain}", priority=10)
    return authenticating, receiving


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


def check(domain, keys, address):
    """What DNS holds for each record: {key: {"state": found | missing | different, "detail"}}."""
    selector = f"{keys['dkim_selector']}._domainkey.{domain}"
    mail_host = f"mail.{domain}"
    answers = _ask([(domain, "TXT"), (mail_host, "A"), (selector, "TXT"), (f"_dmarc.{domain}", "TXT"), (domain, "MX")])
    txt = answers[(domain, "TXT")]
    mx = answers[(domain, "MX")]
    results = {}

    def note(key, state, detail=""):
        results[key] = {"state": state, "detail": detail}

    note("code", "found" if f"someless-code:{keys['code']}" in txt else "missing")

    addresses = answers[(mail_host, "A")]
    if not addresses:
        note("a", "missing")
    elif address is None or address in addresses:
        note("a", "found")
    else:
        note("a", "different", f"{mail_host} points to {', '.join(addresses)}, not to this server ({address}).")

    spf = [record for record in txt if record.lower().startswith("v=spf1")]
    if not spf:
        note("spf", "missing")
    elif len(spf) > 1:
        note("spf", "different", f"There are {len(spf)} SPF records, and a domain can have only one SPF record. "
                                 "Put everything into one.")
    else:
        terms = spf[0].lower().split()
        allowed = {f"a:{mail_host}", f"+a:{mail_host}"} | ({f"ip4:{address}", f"+ip4:{address}"} if address else set())
        if allowed & set(terms) or ("mx" in terms and mail_host in mx):
            note("spf", "found")
        else:
            note("spf", "different", f"Found “{spf[0]}”. It doesn't include this server yet: add a:{mail_host} to it.")

    published = [_dkim_key(record) for record in answers[(selector, "TXT")]]
    published = [key for key in published if key is not None]
    if keys["dkim_public"] in published:
        note("dkim", "found")
    elif published:
        note("dkim", "different", "The DKIM record there holds another key. Copy the value above again.")
    else:
        note("dkim", "missing")

    dmarc = [record for record in answers[(f"_dmarc.{domain}", "TXT")] if record.lower().replace(" ", "").startswith("v=dmarc1")]
    note("dmarc", "found" if dmarc else "missing")

    if mail_host in mx:
        note("mx", "found")
    elif mx:
        note("mx", "different", f"Mail for {domain} still goes to {mx[0]}. That's right until you move it here.")
    else:
        note("mx", "missing")
    return results


def _dkim_key(record):
    tags = dict(part.strip().split("=", 1) for part in record.split(";") if "=" in part)
    key = tags.get("p")
    return "".join(key.split()) if key else None


def authenticated(results):
    return all(results.get(key, {}).get("state") == "found" for key in AUTHENTICATING)


def save_check(domain_id, results):
    db = get_db()
    db.execute("UPDATE domain_keys SET checks = ?, checked_at = ? WHERE domain_id = ?",
               (json.dumps(results), time.time(), domain_id))
    db.execute("UPDATE domains SET authenticated = ? WHERE id = ?", (1 if authenticated(results) else 0, domain_id))
    db.commit()
