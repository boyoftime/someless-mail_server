"""The API (/api/s1): an app manages the senders and the mailboxes as the panel does, with one of
the admin's API keys (api_keys.py) in the Authorization header: "Bearer <key>". JSON in and out.
Every call is checked as the panel checks it, in its words, and does all it was asked or none
of it. The panel's own login is never enough: without a key nothing answers (but the guide, in plain
text for an AI assistant), so no web page can use the API for a signed-in admin. Too many wrong keys from one address, and it has to wait."""
import datetime
import json
import re
import time

from flask import Blueprint, Response, g, jsonify, request

from . import api_guide, disabling, domain_records, domains, mail_password, mailboxes, senders
from .db import get_db
from .engine import sync as engine_sync
from .smtp import fingerprint

bp = Blueprint("api", __name__, url_prefix="/api/s1")   # (s1: the first Someless API)

TRIES = 10            # wrong keys from one address...
TRIES_WINDOW = 600    # ...within this many seconds...
WAIT = 600            # ...and it waits this long
STORAGE = re.compile(r"\s*(\d[\d.,]*)\s*(GB|MB)\s*", re.I)


class Refused(Exception):
    """A call turned down: why, in the panel's words, and its status."""

    def __init__(self, message, status=400, headers=None):
        super().__init__(message)
        self.message, self.status, self.headers = message, status, headers or {}


@bp.errorhandler(Refused)
def refused(error):
    return jsonify(error=error.message), error.status, error.headers


# --- the key -------------------------------------------------------------------------------------

@bp.before_request
def check_key():
    if request.endpoint == "api.docs_text":   # the guide, open to anyone (an AI assistant reads it)
        return
    db = get_db()
    address = request.remote_addr or ""
    now = time.time()
    tries = db.execute("SELECT * FROM api_tries WHERE address = ?", (address,)).fetchone()
    if tries and tries["locked_until"] and tries["locked_until"] > now:
        wait = int(tries["locked_until"] - now) + 1
        raise Refused(f"Too many wrong API keys from your address. Try again in {wait} seconds.", 429,
                      {"Retry-After": str(wait)})
    scheme, _, key = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not key.strip():
        raise Refused("Send your API key in the Authorization header: Bearer <your API key>. "
                      "Make one on the API keys page.", 401)
    row = db.execute("SELECT * FROM api_keys WHERE key_hash = ?", (fingerprint(key.strip()),)).fetchone()
    if row is None or (row["expires_at"] is not None and row["expires_at"] <= now):
        _wrong_key(db, address, tries, now)
        raise Refused("This API key doesn't work: it's wrong, deleted or expired. Make a new one on the API keys page.", 401)
    if tries:
        db.execute("DELETE FROM api_tries WHERE address = ?", (address,))
    db.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, row["id"]))
    db.commit()
    g.api_key = row


def _wrong_key(db, address, tries, now):
    if tries is None or now - tries["first_at"] > TRIES_WINDOW:
        db.execute("INSERT OR REPLACE INTO api_tries (address, failures, first_at, locked_until) VALUES (?, 1, ?, NULL)",
                   (address, now))
    else:
        failures = tries["failures"] + 1
        db.execute("UPDATE api_tries SET failures = ?, locked_until = ? WHERE address = ?",
                   (failures, now + WAIT if failures >= TRIES else None, address))
    db.commit()


# --- what's sent ---------------------------------------------------------------------------------

def _body(*fields):
    """The JSON object sent, with only these fields in it."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise Refused("Send a JSON object in the body, with the header Content-Type: application/json.")
    unknown = sorted(set(body) - set(fields))
    if unknown:
        raise Refused(f"{unknown[0]} isn't a field here. The fields are: {', '.join(fields)}.")
    return body


def _text(body, field, required=True):
    value = body.get(field)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise Refused(f"Give {field} as text." if value is not None else f"{field} is missing.")
    return value


def _storage(value):
    match = STORAGE.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise Refused('Give the storage as text, like "15 GB" or "500 MB".')
    size, problem = mailboxes._storage(match.group(1), match.group(2).upper())
    if problem:
        raise Refused(problem)
    return size


def _send_limit(value):
    if isinstance(value, bool) or not isinstance(value, int) or value not in mailboxes.SEND_LIMITS:
        raise Refused("Choose a send limit (send_limit_mb) from 1 to 100 MB.")
    return value


def _disable_delete(value, now=(False, False)):
    """(webmail, apps): what's sent, the rest as it is now."""
    if not isinstance(value, dict) or set(value) - {"webmail", "apps"}:
        raise Refused('Give disable_delete as {"webmail": true or false, "apps": true or false}.')
    if any(not isinstance(on, bool) for on in value.values()):
        raise Refused("disable_delete's webmail and apps are true or false.")
    return value.get("webmail", now[0]), value.get("apps", now[1])


def _aliases(value, email):
    """[(alias, domain_id)], each a free address at an authenticated domain."""
    if not isinstance(value, list) or not all(isinstance(alias, str) for alias in value):
        raise Refused('Give the aliases as a list of addresses, like ["orders@example.com"].')
    found = []
    for alias in value:
        address, domain_id, problem = mailboxes._address(alias, "")
        if not problem and address == email:
            problem = f"{address} is the mailbox's own address, not an alias."
        if not problem and address in [taken for taken, _ in found]:
            problem = f"{address} is in the list twice."
        if problem:
            raise Refused(problem)
        found.append((address, domain_id))
    return found


def _disabling(body, disabled_now, refuse_now):
    """(disabled, refuse_mail) as sent, the rest as it is now; None when neither is sent (disabling.py)."""
    if "disabled" not in body and "refuse_mail" not in body:
        return None
    for field in ("disabled", "refuse_mail"):
        if field in body and not isinstance(body[field], bool):
            raise Refused(f"{field} is true or false.")
    disabled = body.get("disabled", disabled_now)
    refuse = body.get("refuse_mail", refuse_now if disabled else False)
    if refuse and not disabled:
        raise Refused('refuse_mail works only while it\'s disabled: send "disabled": true with it.')
    return disabled, refuse


def _password(value):
    problem = mailboxes._password_problem(value, value)
    if problem:
        raise Refused(problem)
    return mail_password.hash_password(value)


# --- what's answered -----------------------------------------------------------------------------

def _moment(when):
    return datetime.datetime.fromtimestamp(when, datetime.timezone.utc).isoformat(timespec="seconds")


def _sender(sender_id):
    row = get_db().execute("SELECT senders.*, domains.name AS domain FROM senders JOIN domains ON domains.id = senders.domain_id"
                           " WHERE senders.id = ?", (sender_id,)).fetchone()
    if row is None:
        raise Refused(f"There's no sender with the id {sender_id}.", 404)
    return row


def _sender_json(row):
    return {"id": row["id"], "name": row["name"], "email": row["email"], "domain": row["domain"],
            "has_mailbox": senders._has_mailbox(row["email"]), "disabled": bool(row["disabled"]),
            "created_at": _moment(row["created_at"])}


def _mailbox(mailbox_id):
    row = get_db().execute(
        "SELECT mailboxes.*, domains.name AS domain, senders.name AS name FROM mailboxes"
        " JOIN domains ON domains.id = mailboxes.domain_id LEFT JOIN senders ON lower(senders.email) = mailboxes.email"
        " WHERE mailboxes.id = ?", (mailbox_id,)).fetchone()
    if row is None:
        raise Refused(f"There's no mailbox with the id {mailbox_id}.", 404)
    return row


def _mailbox_json(row, used=None):
    aliases = [alias["email"] for alias in get_db().execute(
        "SELECT email FROM mailbox_aliases WHERE mailbox_id = ? ORDER BY email", (row["id"],))]
    in_use = (mailboxes._usage() if used is None else used).get(row["email"])
    return {"id": row["id"], "email": row["email"], "name": row["name"], "domain": row["domain"],
            "storage": mailboxes.size_text(row["quota_bytes"]), "storage_bytes": row["quota_bytes"], "used_bytes": in_use,
            "send_limit_mb": row["send_limit_mb"],
            "disable_delete": {"webmail": bool(row["no_delete_webmail"]), "apps": bool(row["no_delete_apps"])},
            "aliases": aliases, "disabled": bool(row["disabled"]), "refuse_mail": bool(row["refuse_mail"]),
            "created_at": _moment(row["created_at"])}


def _changed():
    get_db().commit()
    engine_sync.after_change()


# --- the guide -----------------------------------------------------------------------------------

@bp.get("/docs.md")
def docs_text():
    """The whole guide in plain text, for an AI assistant helping someone connect their app: no
    key needed, and none of the admin's own domains in it (api_guide.py)."""
    return Response(api_guide.as_text(request.url_root.rstrip("/") + bp.url_prefix), mimetype="text/markdown")


# --- domains -------------------------------------------------------------------------------------

def _domain(name):
    row = get_db().execute("SELECT * FROM domains WHERE name = ?", (domains.tidy(name),)).fetchone()
    if row is None:
        raise Refused(f"There's no domain {name} here. Add it with POST /domains.", 404)
    return row


def _domain_json(row):
    """The domain, with the DNS records to add at its domain provider (as the Authenticate page
    shows them, each fitting what the domain has now) and how each one last checked."""
    keys = domain_records.keys_for(row["id"])
    authenticating, receiving = domain_records.records(row["name"], keys, domain_records.server_address(request.host))
    checks = json.loads(keys["checks"]) if keys["checks"] else {}
    return {"id": row["id"], "name": row["name"], "authenticated": bool(row["authenticated"]), "provider": row["provider"],
            "records": [{"key": record.key, "title": record.title, "purpose": record.hint, "type": record.type,
                         "host": record.host, "full_host": record.full_host, "value": record.value,
                         "priority": record.priority, "state": checks.get(record.key, {}).get("state", "not checked"),
                         "note": record.advice.text if record.advice else _no_address(record)}
                        for record in [*authenticating, receiving]],
            "checked_at": _moment(keys["checked_at"]) if keys["checked_at"] else None}


def _no_address(record):
    """The A record's note when the API was called by a private address (the server itself, at
    home): this server's public IP address can't be told from it."""
    if record.key == "a" and not record.value:
        return ("Use this server's public IP address: the API was called by a private address, so it can't tell. "
                "Call it by the panel's public address to have it filled in.")
    return None


def _look(row):
    """DNS asked again about the domain, unless it was a moment ago, as its Authenticate page does:
    the records to add fit what it has now (a check counts it again, too)."""
    keys = domain_records.keys_for(row["id"])
    if domain_records.out_of_date(keys):
        host, found, results = domain_records.look(row["name"], keys, domain_records.server_address(request.host))
        domain_records.save(row["id"], host, found, results if keys["checks"] else None)
        engine_sync.after_change()


@bp.get("/domains")
def list_domains():
    """Every domain, saying whether it's authenticated: senders and mailboxes can be at those."""
    return {"domains": [{"name": row["name"], "authenticated": bool(row["authenticated"])}
                        for row in get_db().execute("SELECT name, authenticated FROM domains ORDER BY name")]}


@bp.post("/domains")
def add_domain():
    domain_id, problem = domains.add_domain(_text(_body("name"), "name"))
    if problem:
        raise Refused(problem)
    row = get_db().execute("SELECT * FROM domains WHERE id = ?", (domain_id,)).fetchone()
    _look(row)
    return {"domain": _domain_json(row)}, 201


@bp.get("/domains/<name>")
def get_domain(name):
    row = _domain(name)
    _look(row)
    return {"domain": _domain_json(_domain(name))}


@bp.post("/domains/<name>/authenticate")
def authenticate_domain(name):
    """Its records looked up in DNS now, as Authenticate this email domain does: authenticated
    when they're all there, else what's still to add or fix."""
    row = _domain(name)
    still = domains.check_now(row, request.host)
    return {"domain": _domain_json(_domain(name)), "message": still or f"{row['name']} is authenticated."}


@bp.delete("/domains/<name>")
def delete_domain(name):
    """With its senders; not while it has mailboxes or aliases (their mail would stop)."""
    problem = domains.remove(_domain(name)["id"])
    if problem:
        raise Refused(problem)
    return {"deleted": True}


# --- senders -------------------------------------------------------------------------------------

@bp.get("/senders")
def list_senders():
    ids = [row["id"] for row in get_db().execute("SELECT id FROM senders ORDER BY created_at DESC, id DESC")]
    return {"senders": [_sender_json(_sender(sender_id)) for sender_id in ids]}


@bp.post("/senders")
def add_sender():
    body = _body("name", "email")
    name, email, domain_id, problem = senders._checked({"name": _text(body, "name", False) or "",
                                                        "email": _text(body, "email", False) or ""})
    if problem:
        raise Refused(problem)
    sender_id = get_db().execute("INSERT INTO senders (name, email, domain_id, created_at) VALUES (?, ?, ?, ?)",
                                 (name, email, domain_id, time.time())).lastrowid
    _changed()
    return {"sender": _sender_json(_sender(sender_id))}, 201


@bp.get("/senders/<int:sender_id>")
def get_sender(sender_id):
    return {"sender": _sender_json(_sender(sender_id))}


@bp.patch("/senders/<int:sender_id>")
def change_sender(sender_id):
    sender = _sender(sender_id)
    body = _body("name", "email", "disabled", "refuse_mail")
    name, email = _text(body, "name", False), _text(body, "email", False)
    typed = {"name": sender["name"] if name is None else name, "email": sender["email"] if email is None else email}
    name, email, domain_id, problem = senders._checked(typed, sender_id)
    if not problem and email.lower() != sender["email"].lower() and senders._has_mailbox(sender["email"]):
        problem = f"{sender['email']} has a mailbox, so its address stays as it is. Delete its mailbox first to change it."
    if problem:
        raise Refused(problem)
    has_mailbox = senders._has_mailbox(sender["email"])
    refusing = get_db().execute("SELECT refuse_mail FROM mailboxes WHERE email = lower(?)", (sender["email"],)).fetchone()
    disabling_to = _disabling(body, bool(sender["disabled"]), bool(refusing and refusing["refuse_mail"]))
    if disabling_to and disabling_to[1] and not has_mailbox:
        raise Refused(f"refuse_mail is for a mailbox, and {sender['email']} has none.")
    get_db().execute("UPDATE senders SET name = ?, email = ?, domain_id = ? WHERE id = ?", (name, email, domain_id, sender_id))
    _changed()
    if disabling_to:   # (its mailbox with it: disabling.py)
        disabling.set_disabled(email, *disabling_to)
    return {"sender": _sender_json(_sender(sender_id))}


@bp.delete("/senders/<int:sender_id>")
def delete_sender(sender_id):
    sender = _sender(sender_id)
    if senders._has_mailbox(sender["email"]):   # its mailbox (and the mail in it) goes first, on purpose
        raise Refused(f"{sender['name']} <{sender['email']}> has a mailbox. Delete its mailbox first, then the sender.")
    get_db().execute("DELETE FROM senders WHERE id = ?", (sender_id,))
    _changed()
    return {"deleted": True}


# --- mailboxes -----------------------------------------------------------------------------------

@bp.get("/mailboxes")
def list_mailboxes():
    used = mailboxes._usage()   # (asked of the mail engine once for them all)
    ids = [row["id"] for row in get_db().execute("SELECT id FROM mailboxes ORDER BY created_at DESC, id DESC")]
    return {"mailboxes": [_mailbox_json(_mailbox(mailbox_id), used) for mailbox_id in ids]}


@bp.post("/mailboxes")
def add_mailbox():
    """A mailbox with every option the panel has; with name, its sender too, when there's none yet."""
    body = _body("email", "name", "password", "storage", "send_limit_mb", "disable_delete", "aliases")
    db = get_db()
    typed = _text(body, "email")
    if disabling.disabled_problem(typed.strip()):   # (a disabled sender gets no mailbox)
        raise Refused(disabling.disabled_problem(typed.strip()))
    name = _text(body, "name", False)
    sender = db.execute("SELECT id FROM senders WHERE lower(email) = lower(?)", (typed.strip(),)).fetchone()
    new_sender = None
    if name is not None:   # the sender's name: a new sender, or a new name for the one there
        sender_name, sender_email, sender_domain, problem = senders._checked({"name": name, "email": typed},
                                                                             sender["id"] if sender else None)
        if problem:
            raise Refused(problem)
        new_sender = (sender_name, sender_email, sender_domain)
    email, domain_id, problem = mailboxes._address(typed, "", sender=new_sender is None)
    if problem:
        raise Refused(problem)
    password = _password(_text(body, "password"))
    size = _storage(body.get("storage"))
    send_limit = _send_limit(body.get("send_limit_mb", 50))
    webmail, apps = _disable_delete(body.get("disable_delete", {}))
    aliases = _aliases(body.get("aliases", []), email)
    now = time.time()
    if new_sender and sender:
        db.execute("UPDATE senders SET name = ? WHERE id = ?", (new_sender[0], sender["id"]))
    elif new_sender:
        db.execute("INSERT INTO senders (name, email, domain_id, created_at) VALUES (?, ?, ?, ?)", (*new_sender, now))
    mailbox_id = db.execute(
        "INSERT INTO mailboxes (email, domain_id, quota_bytes, password_hash, created_at, send_limit_mb, no_delete_webmail,"
        " no_delete_apps) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (email, domain_id, size, password, now, send_limit, int(webmail), int(apps))).lastrowid
    for alias, alias_domain in aliases:
        db.execute("INSERT INTO mailbox_aliases (mailbox_id, email, domain_id, created_at) VALUES (?, ?, ?, ?)",
                   (mailbox_id, alias, alias_domain, now))
    _changed()
    return {"mailbox": _mailbox_json(_mailbox(mailbox_id))}, 201


@bp.get("/mailboxes/<int:mailbox_id>")
def get_mailbox(mailbox_id):
    return {"mailbox": _mailbox_json(_mailbox(mailbox_id))}


@bp.patch("/mailboxes/<int:mailbox_id>")
def change_mailbox(mailbox_id):
    """Only what's sent changes; all of it, or (with a problem) none of it."""
    mailbox = _mailbox(mailbox_id)
    body = _body("password", "storage", "send_limit_mb", "disable_delete", "disabled", "refuse_mail")
    disabling_to = _disabling(body, bool(mailbox["disabled"]), bool(mailbox["refuse_mail"]))
    password = _password(_text(body, "password")) if "password" in body else None
    size = _storage(body["storage"]) if "storage" in body else mailbox["quota_bytes"]
    send_limit = _send_limit(body["send_limit_mb"]) if "send_limit_mb" in body else mailbox["send_limit_mb"]
    webmail, apps = _disable_delete(body.get("disable_delete", {}),
                                    (bool(mailbox["no_delete_webmail"]), bool(mailbox["no_delete_apps"])))
    db = get_db()
    db.execute("UPDATE mailboxes SET quota_bytes = ?, send_limit_mb = ?, no_delete_webmail = ?, no_delete_apps = ? WHERE id = ?",
               (size, send_limit, int(webmail), int(apps), mailbox_id))
    if password:   # a new version: the sync gives the engine the new hash (mailboxes.py)
        db.execute("UPDATE mailboxes SET password_hash = ?, password_version = password_version + 1 WHERE id = ?",
                   (password, mailbox_id))
    _changed()
    if disabling_to:   # (its sender with it: disabling.py)
        disabling.set_disabled(mailbox["email"], *disabling_to)
    return {"mailbox": _mailbox_json(_mailbox(mailbox_id))}


@bp.post("/mailboxes/password")
def reset_password():
    """A new password for the mailbox at this address: for someone who has forgotten theirs (the
    app makes sure it's them). Given twice, as the panel asks it; the webmail and the mail apps
    signed in with the old one ask for the new one."""
    body = _body("email", "password", "confirm_password")
    email = _text(body, "email").strip().lower()
    mailbox = get_db().execute("SELECT id FROM mailboxes WHERE email = ?", (email,)).fetchone()
    if mailbox is None:
        raise Refused(f"There's no mailbox at {email}.", 404)
    password, confirm = _text(body, "password"), _text(body, "confirm_password")
    problem = mailboxes._password_problem(password, confirm)
    if problem:
        raise Refused(problem)
    get_db().execute("UPDATE mailboxes SET password_hash = ?, password_version = password_version + 1 WHERE id = ?",
                     (mail_password.hash_password(password), mailbox["id"]))
    _changed()
    return {"mailbox": _mailbox_json(_mailbox(mailbox["id"]))}


@bp.delete("/mailboxes/<int:mailbox_id>")
def delete_mailbox(mailbox_id):
    """With its aliases and all the mail in it; its sender stays."""
    _mailbox(mailbox_id)
    mailboxes.remove(mailbox_id)
    return {"deleted": True}


@bp.post("/mailboxes/<int:mailbox_id>/aliases")
def add_alias(mailbox_id):
    mailbox = _mailbox(mailbox_id)
    [(alias, domain_id)] = _aliases([_text(_body("email"), "email")], mailbox["email"])
    get_db().execute("INSERT INTO mailbox_aliases (mailbox_id, email, domain_id, created_at) VALUES (?, ?, ?, ?)",
                     (mailbox_id, alias, domain_id, time.time()))
    _changed()
    return {"mailbox": _mailbox_json(_mailbox(mailbox_id))}, 201


@bp.delete("/mailboxes/<int:mailbox_id>/aliases/<alias>")
def delete_alias(mailbox_id, alias):
    mailbox = _mailbox(mailbox_id)
    db = get_db()
    if not db.execute("SELECT 1 FROM mailbox_aliases WHERE mailbox_id = ? AND email = ?", (mailbox_id, alias.lower())).fetchone():
        raise Refused(f"{alias} isn't an alias of {mailbox['email']}.", 404)
    db.execute("DELETE FROM mailbox_aliases WHERE mailbox_id = ? AND email = ?", (mailbox_id, alias.lower()))
    _changed()
    return {"mailbox": _mailbox_json(_mailbox(mailbox_id))}
