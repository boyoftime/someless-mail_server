"""Keeping Stalwart in line with the panel: the panel is where the admin changes anything;
Stalwart gets what it needs to send. A sync reads what Stalwart has, works out what it
should have, and makes only the difference, so running it again changes nothing.
Someless owns its Stalwart: every Domain but someless.internal and every Account but admin is
the panel's to make and remove.
An address can be one account's only, so the Senders are the addresses of one group
(someless-senders), and each key's account may send as them by being in it."""
import base64
import contextlib
import hashlib
import threading
import time
from pathlib import Path

from flask import current_app

from ..db import get_db
from . import INTERNAL_DOMAIN, PANEL_ACCOUNT, SENDERS_GROUP, client, deliveries, enabled, names, remember, secret, state
from .client import EngineError, EngineUnavailable

MANUAL = {"@type": "Manual"}
ACME_DIRECTORY = "https://acme-v02.api.letsencrypt.org/directory"  # Let's Encrypt
ASK_AGAIN_AFTER = 600   # seconds: Let's Encrypt allows 5 failed checks of a name an hour
_thread_lock = threading.Lock()


def sha256_secret(hex_digest):
    """A password as Stalwart takes it pre-hashed: {SHA256} and the digest in base64."""
    return "{SHA256}" + base64.b64encode(bytes.fromhex(hex_digest)).decode()


def desired_state():
    db = get_db()
    domains = {row["name"]: row["dkim_private"] for row in db.execute(
        "SELECT domains.name, domain_keys.dkim_private FROM domains JOIN domain_keys ON domain_keys.domain_id = domains.id"
        " WHERE domains.authenticated = 1")}
    senders = [row["email"] for row in db.execute(
        "SELECT senders.email FROM senders JOIN domains ON domains.id = senders.domain_id WHERE domains.authenticated = 1"
        " ORDER BY senders.email")]
    accounts = {row["login"]: sha256_secret(row["key_hash"]) for row in db.execute(
        "SELECT login, key_hash FROM smtp_keys WHERE login IS NOT NULL AND (expires_at IS NULL OR expires_at > ?)",
        (time.time(),))}
    accounts[PANEL_ACCOUNT] = sha256_secret(hashlib.sha256(secret("panel_password").encode()).hexdigest())
    return {"domains": domains, "accounts": accounts, "senders": senders, "server_name": names.server_name(),
            "acme_directory": current_app.config.get("ENGINE_ACME_DIRECTORY", ACME_DIRECTORY),
            "webhook_secret": secret("webhook_secret")}


def reconcile(engine, desired):
    done = []
    domains = {obj["name"]: obj for obj in engine.get("Domain")}
    internal_id = domains[INTERNAL_DOMAIN]["id"]
    # domains: every authenticated one
    for name in desired["domains"]:
        if name not in domains:
            domains[name] = {"name": name, **engine.create("Domain", {
                "name": name, "dkimManagement": MANUAL, "certificateManagement": MANUAL, "dnsManagement": MANUAL})}
            done.append(f"create Domain {name}")
    # each domain's DKIM key: the one already published in its DNS
    signatures = engine.get("DkimSignature")
    signed = {(signature["domainId"], signature["selector"]) for signature in signatures}
    for name, pem in desired["domains"].items():
        if (domains[name]["id"], "someless") not in signed:
            engine.create("DkimSignature", {"@type": "Dkim1RsaSha256", "domainId": domains[name]["id"], "selector": "someless",
                                            "privateKey": {"@type": "Text", "secret": pem}})
            done.append(f"create DkimSignature {name}")
    # the server's name: what it greets other servers with
    settings = engine.get("SystemSettings", ["singleton"])[0]
    wanted = desired["server_name"] or INTERNAL_DOMAIN
    if settings.get("defaultHostname") != wanted:
        engine.update("SystemSettings", "singleton", {"defaultHostname": wanted})
        done.append(f"update SystemSettings defaultHostname {wanted}")
    # the Senders: the addresses of one group
    aliases = {}
    for email in desired["senders"]:
        local, domain = email.rsplit("@", 1)
        if domain in desired["domains"]:
            aliases[str(len(aliases))] = {"name": local, "domainId": domains[domain]["id"], "enabled": True}
    accounts = {obj["name"]: obj for obj in engine.get("Account") if obj.get("domainId") == internal_id and obj["name"] != "admin"}
    group = accounts.pop(SENDERS_GROUP, None)
    if group is None:
        group = {"aliases": aliases, **engine.create("Account", {
            "@type": "Group", "name": SENDERS_GROUP, "domainId": internal_id, "aliases": aliases})}
        done.append(f"create Account {SENDERS_GROUP}")
    elif _alias_set(group.get("aliases")) != _alias_set(aliases):
        engine.update("Account", group["id"], {"aliases": aliases})
        done.append(f"update Account {SENDERS_GROUP}")
    # accounts: one per key (and the panel's), each in the group
    member_of = {group["id"]: True}
    for login, password in desired["accounts"].items():
        if login not in accounts:
            engine.create("Account", {"@type": "User", "name": login, "domainId": internal_id,
                                      "roles": {"@type": "User"}, "permissions": {"@type": "Inherit"},
                                      "encryptionAtRest": {"@type": "Disabled"},
                                      "credentials": {"0": {"@type": "Password", "secret": password}},
                                      "memberGroupIds": member_of})
            done.append(f"create Account {login}")
        elif accounts[login].get("memberGroupIds") != member_of:
            engine.update("Account", accounts[login]["id"], {"memberGroupIds": member_of})
            done.append(f"update Account {login}")
    for login, obj in accounts.items():
        if login not in desired["accounts"]:
            engine.destroy("Account", obj["id"])
            done.append(f"destroy Account {login}")
    # delivery reports for the test emails: one WebHook, to the panel (engine/deliveries.py)
    wanted_hook = {"url": deliveries.events_url(), "eventsPolicy": "include",
                   "events": {name: True for name in deliveries.EVENTS}}
    hooks = engine.get("WebHook")
    if not hooks:
        engine.create("WebHook", {**wanted_hook, "signatureKey": {"@type": "Value", "secret": desired["webhook_secret"]}})
        done.append("create WebHook")
    elif any(hooks[0].get(field) != value for field, value in wanted_hook.items()):
        engine.update("WebHook", hooks[0]["id"], wanted_hook)
        done.append("update WebHook")
    # and no other domain (someless.internal aside); last, once no alias points at it
    for name, obj in list(domains.items()):
        if name != INTERNAL_DOMAIN and name not in desired["domains"]:
            for signature in signatures:
                if signature["domainId"] == obj["id"]:
                    engine.destroy("DkimSignature", signature["id"])
            engine.destroy("Domain", obj["id"])
            done.append(f"destroy Domain {name}")
    # last, the certificate: making the ACME account asks Let's Encrypt there and then, and
    # when that fails, everything above still counts
    problem = None
    try:
        _certificate(engine, desired, domains, settings, done)
    except EngineError as error:
        problem = error
    if done:
        engine.action("ReloadSettings")
    if problem:
        raise problem
    return done


def _certificate(engine, desired, domains, settings, done):
    """The server name's certificate: Let's Encrypt, HTTP-01 answered through the challenge
    relay; and the default one, for clients that don't say which name they want."""
    server_name = desired["server_name"]
    if not server_name or not desired["acme_directory"]:
        return
    server_domain = server_name.split(".", 1)[1]
    providers = engine.get("AcmeProvider")
    if providers:
        provider = providers[0]["id"]
    else:
        provider = engine.create("AcmeProvider", {"challengeType": "Http01", "directory": desired["acme_directory"],
                                                  "contact": {f"postmaster@{server_domain}": True}})["id"]
        done.append("create AcmeProvider")
    for name, obj in domains.items():
        if name == INTERNAL_DOMAIN or name not in desired["domains"]:
            continue
        want = ({"@type": "Automatic", "acmeProviderId": provider, "subjectAlternativeNames": {server_name: True}}
                if name == server_domain else MANUAL)
        if obj.get("certificateManagement") != want:
            engine.update("Domain", obj["id"], {"certificateManagement": want})
            done.append(f"update Domain {name} certificate")
    for certificate in engine.get("Certificate"):
        if server_name in (certificate.get("subjectAlternativeNames") or {}):
            if settings.get("defaultCertificateId") != certificate["id"]:
                engine.update("SystemSettings", "singleton", {"defaultCertificateId": certificate["id"]})
                engine.action("ReloadTlsCertificates")
                done.append("update SystemSettings defaultCertificateId")
            break


def ask_for_certificate():
    """A new certificate order for the server name, now. Stalwart orders one by itself only
    when the domain first turns Automatic, and after a failed check (the proxy host not there
    yet) waits longer and longer, up to hours; so "Check again" asks once more, not more than
    every 10 minutes. True when an order went in."""
    server_name = names.server_name()
    if not enabled() or not server_name or not current_app.config.get("ENGINE_ACME_DIRECTORY", ACME_DIRECTORY):
        return False
    asked = state()["certificate_asked_at"]
    if asked and time.time() - asked < ASK_AGAIN_AFTER:
        return False
    try:
        engine = client()
        if any(server_name in (certificate.get("subjectAlternativeNames") or {}) for certificate in engine.get("Certificate")):
            return False   # it's in; Stalwart renews it by itself
        server_domain = server_name.split(".", 1)[1]
        domain = next((obj for obj in engine.get("Domain") if obj["name"] == server_domain), None)
        if domain is None or (domain.get("certificateManagement") or {}).get("@type") != "Automatic":
            return False   # the next sync sets it up, and that orders one
        engine.create("Task", {"@type": "AcmeRenewal", "domainId": domain["id"]})
    except (EngineUnavailable, EngineError) as error:
        current_app.logger.warning("couldn't ask for a certificate: %s", error)
        return False
    remember(certificate_asked_at=time.time())
    return True


def _alias_set(aliases):
    return {(alias["name"], alias["domainId"]) for alias in (aliases or {}).values()}


@contextlib.contextmanager
def _lock():
    """One sync at a time: across gunicorn's workers and the hourly one (a file lock), and
    within a process (a thread lock)."""
    path = Path(current_app.config["DATA_DIR"]) / "engine.lock"
    with _thread_lock, open(path, "a") as handle:
        try:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        except ImportError:   # Windows (development): the thread lock is enough
            pass
        yield


def run():
    """Bring Stalwart in line. Never raises: a failure is kept for the page, and the next sync
    (after the next change, or the hourly one) tries again."""
    try:
        with _lock():
            done = reconcile(client(), desired_state())
    except (EngineUnavailable, EngineError, KeyError) as error:
        remember(sync_error=str(error))
        current_app.logger.warning("mail engine sync failed: %s", error)
        return False
    except Exception as error:   # a reply nobody expected: the admin's change is saved all the same
        remember(sync_error=str(error) or type(error).__name__)
        current_app.logger.exception("mail engine sync failed")
        return False
    remember(synced_at=time.time(), sync_error=None)
    if done:
        current_app.logger.info("mail engine sync: %s", "; ".join(done))
    return True


def after_change():
    """What the views call after a change the engine needs to know about."""
    if enabled():
        run()
