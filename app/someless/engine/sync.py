"""Keeping Stalwart in line with the panel: the panel is where the admin changes anything;
Stalwart gets what it needs to send. A sync reads what Stalwart has, works out what it
should have, and makes only the difference, so running it again changes nothing.
Someless owns its Stalwart: every Domain but someless.internal and every Account but admin is
the panel's to make and remove. In someless.internal: an account per SMTP key, and the panel's
own; in every other domain: its mailboxes (mailboxes.py).
Any account that has logged in may send as the Senders (the send-as rule), and otherwise only
as its own address and aliases."""
import base64
import contextlib
import hashlib
import logging
import threading
import time
from pathlib import Path

from flask import current_app

from ..db import get_db
from . import (INTERNAL_DOMAIN, PANEL_ACCOUNT, SENDERS_GROUP, WEBMAIL_ACCOUNT, client, deliveries, enabled, names, remember,
               secret, state)

from .client import EngineError, EngineUnavailable

MANUAL = {"@type": "Manual"}
ACME_DIRECTORY = "https://acme-v02.api.letsencrypt.org/directory"  # Let's Encrypt
ASK_AGAIN_AFTER = 600   # seconds: Let's Encrypt allows 5 failed checks of a name an hour
RECEIVED_MOST = 104857600   # bytes: a message from another server, or sent with an SMTP key (Stalwart's own)
# What Stalwart takes, raised to let through the largest message a mailbox may send (100 MB of
# files: some 140 MB once written in a message): what the webmail uploads, and what mail apps save
# in Sent. The mailboxes' own limits are in the size rule (size_rule).
ENGINE_LIMITS = {"Jmap": {"maxUploadSize": 110000000, "uploadQuota": 500000000},
                 "Email": {"maxAttachmentSize": 110000000, "maxMessageSize": 160000000},
                 "Imap": {"maxRequestSize": 160000000}}
_thread_lock = threading.Lock()


def sha256_secret(hex_digest):
    """A password as Stalwart takes it pre-hashed: {SHA256} and the digest in base64."""
    return "{SHA256}" + base64.b64encode(bytes.fromhex(hex_digest)).decode()


def send_as_rule(senders):
    """x:MtaStageAuth.mustMatchSender: sending as a Sender needs no match; any other address has
    to be the account's own, or one of its aliases. (An address with a quote or backslash can't
    go in the rule's text: it's left out, so only its mailbox can send as it.)"""
    senders = sorted({email.lower() for email in senders})   # the engine compares addresses in lowercase
    fit = [email for email in senders if "'" not in email and "\\" not in email]
    for email in set(senders) - set(fit):
        logging.getLogger(__name__).warning("sender %s can't go in the send-as rule (a quote or backslash)", email)
    if not fit:
        return {"match": {}, "else": "true"}
    return {"match": {"0": {"if": " || ".join(f"sender == '{email}'" for email in fit), "then": "false"}}, "else": "true"}


def in_a_message(megabytes):
    """How large a message gets with so many MB of files: their base64 is a third larger, in lines
    of 76 with a line break after each, and the words and headers around them take a little more."""
    return int(megabytes * 1024 ** 2 * 4 / 3 * 78 / 76) + 1024 ** 2


def size_rule(limits):
    """x:MtaStageData.maxMessageSize: each mailbox, signed in (a mail app), sends as large a message as
    its limit lets it (limits: {address: MB}); any other message is as large as Stalwart takes. (An
    address with a quote or backslash can't go in the rule's text: it's left out, and has that.)"""
    by_limit = {}
    for email, megabytes in sorted(limits.items()):
        if "'" in email or "\\" in email:
            logging.getLogger(__name__).warning("mailbox %s can't go in the size rule (a quote or backslash)", email)
            continue
        by_limit.setdefault(megabytes, []).append(email)
    match = {str(index): {"if": " || ".join(f"authenticated_as == '{email}'" for email in emails), "then": str(in_a_message(megabytes))}
             for index, (megabytes, emails) in enumerate(sorted(by_limit.items()))}
    return {"match": match, "else": str(RECEIVED_MOST)}


def desired_state():
    db = get_db()
    # authenticated domains, and any with mailboxes: those stay, or their mail would go
    domains = {row["name"]: row["dkim_private"] for row in db.execute(
        "SELECT domains.name, domain_keys.dkim_private FROM domains JOIN domain_keys ON domain_keys.domain_id = domains.id"
        " WHERE domains.authenticated = 1 OR domains.id IN (SELECT domain_id FROM mailboxes UNION SELECT domain_id FROM mailbox_aliases)")}
    mailboxes = {}
    for row in db.execute("SELECT * FROM mailboxes ORDER BY email").fetchall():
        aliases = [alias["email"] for alias in db.execute(
            "SELECT email FROM mailbox_aliases WHERE mailbox_id = ? ORDER BY email", (row["id"],))]
        mailboxes[row["email"]] = {"id": row["id"], "quota": row["quota_bytes"], "secret": row["password_hash"],
                                   "version": row["password_version"], "aliases": aliases, "send_limit": row["send_limit_mb"],
                                   "keep_mail": bool(row["no_delete_apps"])}
    senders = [row["email"] for row in db.execute(
        "SELECT senders.email FROM senders JOIN domains ON domains.id = senders.domain_id WHERE domains.authenticated = 1"
        " ORDER BY senders.email")]
    accounts = {row["login"]: sha256_secret(row["key_hash"]) for row in db.execute(
        "SELECT login, key_hash FROM smtp_keys WHERE login IS NOT NULL AND (expires_at IS NULL OR expires_at > ?)",
        (time.time(),))}
    accounts[PANEL_ACCOUNT] = sha256_secret(hashlib.sha256(secret("panel_password").encode()).hexdigest())
    accounts[WEBMAIL_ACCOUNT] = sha256_secret(hashlib.sha256(secret("webmail_password").encode()).hexdigest())
    return {"domains": domains, "accounts": accounts, "senders": senders, "mailboxes": mailboxes,
            "server_name": names.server_name(),
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
    # who may send as whom: any account that has logged in, as the Senders (the send-as rule)
    rule = send_as_rule(desired["senders"])
    if engine.get("MtaStageAuth", ["singleton"])[0].get("mustMatchSender") != rule:
        engine.update("MtaStageAuth", "singleton", {"mustMatchSender": rule})
        done.append("update the send-as rule")
    # how large a message each mailbox may send (the Mailboxes page), and what Stalwart takes, raised to fit
    rule = size_rule({email: box["send_limit"] for email, box in desired["mailboxes"].items()})
    if engine.get("MtaStageData", ["singleton"])[0].get("maxMessageSize") != rule:
        engine.update("MtaStageData", "singleton", {"maxMessageSize": rule})
        done.append("update the size rule")
    for kind, wanted in ENGINE_LIMITS.items():
        now = engine.get(kind, ["singleton"])[0]
        change = {field: value for field, value in wanted.items() if now.get(field) != value}
        if change:
            engine.update(kind, "singleton", change)
            done.append(f"update {kind} limits")
    everyone = engine.get("Account")
    # accounts in someless.internal: one per key, and the panel's
    accounts = {obj["name"]: obj for obj in everyone if obj.get("domainId") == internal_id and obj["name"] != "admin"}
    group = accounts.pop(SENDERS_GROUP, None)   # how Senders were done before the send-as rule
    for login, password in desired["accounts"].items():
        if login not in accounts:
            engine.create("Account", _internal_account(login, internal_id, password))
            done.append(f"create Account {login}")
        elif accounts[login].get("memberGroupIds"):
            engine.update("Account", accounts[login]["id"], {"memberGroupIds": {}})
            done.append(f"update Account {login}")
        elif login == WEBMAIL_ACCOUNT and not _may_impersonate(accounts[login]):
            engine.update("Account", accounts[login]["id"], {"permissions": IMPERSONATE})
            done.append(f"update Account {login}")
    for login, obj in accounts.items():
        if login not in desired["accounts"]:
            engine.destroy("Account", obj["id"])
            done.append(f"destroy Account {login}")
    if group is not None:
        engine.destroy("Account", group["id"])
        done.append(f"destroy Account {SENDERS_GROUP}")
    # mailboxes: the accounts in every other domain (the engine's own admin has none)
    failures = _mailboxes(engine, desired, domains, internal_id, everyone, done)
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
    if failures or problem:
        raise failures[0] if failures else problem
    return done


def _mailboxes(engine, desired, domains, internal_id, everyone, done):
    """The mailboxes' accounts, in an order the engine takes: an address is on one account only,
    so first the accounts that go (deleted, or made again: a new account, without the old one's
    mail) and the aliases that leave, then the rest. A mailbox the engine refuses doesn't hold up
    the others: the refusals come back, for the end of the sync."""
    failures = []

    def attempt(what, call):
        try:
            call()
            done.append(what)
        except EngineError as error:
            failures.append(error)

    domain_names = {obj["id"]: name for name, obj in domains.items()}
    boxes = {f"{obj['name']}@{domain_names[obj['domainId']]}": obj for obj in everyone
             if obj.get("domainId") in domain_names and obj["domainId"] != internal_id}
    wanted = desired["mailboxes"]
    for email, obj in list(boxes.items()):
        if email not in wanted or not _same_mailbox(obj, wanted[email]):
            attempt(f"destroy mailbox {email}", lambda: engine.destroy("Account", obj["id"]))
            del boxes[email]
    aliases = {email: _aliases(box, domains) for email, box in wanted.items()}
    for email, obj in boxes.items():   # aliases leaving, before any other mailbox takes them
        had = list((obj.get("aliases") or {}).values())
        kept = [alias for alias in had if (alias["name"], alias["domainId"]) in _alias_set(aliases[email])]
        if len(kept) != len(had):
            obj["aliases"] = {str(index): alias for index, alias in enumerate(kept)}
            attempt(f"update mailbox {email} aliases", lambda: engine.update("Account", obj["id"], {"aliases": obj["aliases"]}))
    for email, box in wanted.items():   # (attempt() runs each call at once: the lambdas see this round's values)
        local, domain = email.rsplit("@", 1)
        note = _mailbox_note(box)
        quotas = {"maxDiskQuota": box["quota"]}
        permissions = KEEP_MAIL if box.get("keep_mail") else INHERIT
        if email not in boxes:
            attempt(f"create mailbox {email}", lambda: engine.create("Account", {
                **_user(local, domains[domain]["id"], box["secret"]), "quotas": quotas, "aliases": aliases[email],
                "description": note, "permissions": permissions}))
            continue
        obj = boxes[email]
        change = {}
        if obj.get("quotas") != quotas:
            change["quotas"] = quotas
        if _kept_from(obj.get("permissions")) != _kept_from(permissions):
            change["permissions"] = permissions
        if _alias_set(obj.get("aliases")) != _alias_set(aliases[email]):
            change["aliases"] = aliases[email]
        if obj.get("description") != note:   # a new password
            change["credentials"] = {"0": {"@type": "Password", "secret": box["secret"]}}
            change["description"] = note
        if change:
            attempt(f"update mailbox {email}", lambda: engine.update("Account", obj["id"], change))
    return failures


def _aliases(box, domains):
    aliases = {}
    for alias in box["aliases"]:
        alias_local, alias_domain = alias.rsplit("@", 1)
        aliases[str(len(aliases))] = {"name": alias_local, "domainId": domains[alias_domain]["id"], "enabled": True}
    return aliases


def _mailbox_note(box):
    """On the engine's account: which mailbox it is, and which of its passwords it has."""
    return f"someless mailbox {box['id']}, password {box['version']}"


def _same_mailbox(obj, box):
    """Whether the engine's account is this mailbox, not an older one at the same address."""
    return (obj.get("description") or "").startswith(f"someless mailbox {box['id']},")


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


IMPERSONATE = {"@type": "Merge", "enabledPermissions": {"impersonate": True}}
INHERIT = {"@type": "Inherit"}
# Disable delete, in mail apps (the Mailboxes page): a mailbox whose mail is kept, whatever an app
# asks. It can't erase a message over IMAP (expunge) or POP (delete), nor a folder (IMAP delete).
# The webmail (JMAP) keeps its own rule (webmail/mail.py), and its drafts are saved over as usual.
KEEP_MAIL = {"@type": "Merge", "disabledPermissions": {"imapExpunge": True, "imapDelete": True, "pop3Dele": True}}


def _kept_from(permissions):
    """What an account's permissions keep it from: the ones switched off (none, inherited)."""
    permissions = permissions or {}
    if permissions.get("@type") not in ("Merge", "Replace"):
        return set()
    return {name for name, off in (permissions.get("disabledPermissions") or {}).items() if off}


def _internal_account(login, domain_id, password):
    """An account in someless.internal: a key's, the panel's, or the webmail's, which may act for
    the mailboxes (their owners are signed in to the webmail) and only from inside the container."""
    account = _user(login, domain_id, password)
    if login == WEBMAIL_ACCOUNT:
        account["permissions"] = IMPERSONATE
        account["credentials"]["0"]["allowedIps"] = {"127.0.0.1": True}
    return account


def _may_impersonate(obj):
    permissions = obj.get("permissions") or {}
    return permissions.get("@type") in ("Merge", "Replace") and (permissions.get("enabledPermissions") or {}).get("impersonate")


def _user(name, domain_id, secret):
    return {"@type": "User", "name": name, "domainId": domain_id,
            "roles": {"@type": "User"}, "permissions": {"@type": "Inherit"},
            "encryptionAtRest": {"@type": "Disabled"},
            "credentials": {"0": {"@type": "Password", "secret": secret}}}


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
