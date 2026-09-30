"""Mailboxes: inboxes at the authenticated domains, like ceo@pineloop.online. Each is an account
in the mail engine (engine/sync.py), which receives its mail on port 25 and lets mail apps read
it (IMAP, POP3) and send from it (SMTP) with its password. The panel keeps only the password's
hash (mail_password.py); the engine is given the hash too. A mailbox has a storage limit and as
many aliases as the admin likes: other addresses whose mail lands in it."""
import json
import re
import shutil
import time
from urllib.parse import quote

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for

from . import mail_password, mail_profile, webmail_site
from .auth import login_required
from .db import get_db
from .domain_records import HOST_CHOICES
from .engine import EngineError, EngineUnavailable, client, enabled, names, state
from .engine import sync as engine_sync
from .settings import FORCED_KINDS, MIN_LENGTHS, password_checks
from .webmail import views as webmail_views

bp = Blueprint("mailboxes", __name__, url_prefix="/mailboxes")

MB = 1024 ** 2
GB = 1024 ** 3
UNITS = {"GB": GB, "MB": MB}
LARGEST = 100_000 * GB   # a typo guard: no disk holds more
SEND_LIMITS = range(1, 101)   # MB: the most a message a mailbox sends may carry in files (50 to start)
# The part before the @, as mail apps and other servers handle it without surprises: letters,
# digits, dots, dashes and underscores; no dot at either end or two in a row. Kept lowercase.
LOCAL_PART = re.compile(r"(?![.])(?!.*\.\.)[a-z0-9._-]{1,64}(?<![.])")
# How mail apps connect (the Configuration details): port, and the kind of encryption
MAIL_APPS = {"imap": 993, "pop3": 995, "smtp_ssl": 465, "smtp_starttls": 587}


def size_text(size):
    """Bytes as people say them: 500 MB, 15 GB, 14.87 GB."""
    value, unit = (size / GB, "GB") if size >= GB else (size / MB, "MB")
    return f"{value:.2f}".rstrip("0").rstrip(".") + f" {unit}"


def _in_unit(size):
    """A storage limit as the Edit storage form shows it: the number and GB or MB, in GB when
    that's how it could have been typed (up to three decimals)."""
    in_gb = round(size / GB, 3)
    if size >= GB and int(in_gb * GB) == size:
        return f"{in_gb:.3f}".rstrip("0").rstrip("."), "GB"
    return f"{size / MB:.3f}".rstrip("0").rstrip("."), "MB"


def _authenticated_domains():
    return get_db().execute("SELECT id, name FROM domains WHERE authenticated = 1 ORDER BY name").fetchall()


def _storage(typed_size, unit):
    """(bytes, None), or (None, problem) when it isn't a storage limit."""
    typed_size = typed_size.strip()
    if re.fullmatch(r"\d{1,3}(,\d{3})+", typed_size):   # 1,000: a thousands separator
        typed_size = typed_size.replace(",", "")
    typed_size = typed_size.replace(",", ".")               # 1,5: a decimal comma
    if unit not in UNITS or not re.fullmatch(r"\d{1,9}(\.\d{1,3})?", typed_size):
        return None, "Type the mailbox's storage as a number, like 15, and pick GB or MB."
    size = int(float(typed_size) * UNITS[unit])
    if size < MB:
        return None, "Give the mailbox at least 1 MB of storage."
    if size > LARGEST:
        return None, "That's more storage than any server has. Type a smaller number."
    return size, None


def password_rules():
    """The mailboxes' password rules (the Password rules dialog here): apart from the admin's own
    (Settings), since they guard the mail apps' logins, open to the whole internet."""
    return get_db().execute("SELECT * FROM mailbox_password_rules WHERE id = 1").fetchone()


def _password_problem(password, confirm):
    for check in password_checks(password_rules()):
        if not check.test(password):
            return check.message.replace("New password", "The password")
    if password != confirm:
        return "The two passwords don't match. Type the same password in both."
    return None


def _address(local, domain_name, sender=False):
    """(email, domain_id, None) for a free address at an authenticated domain, or (…, problem).
    sender: it has to be one of the senders too (a mailbox is made for a sender; an alias isn't)."""
    local = local.strip().lower()
    if "@" in local:   # typed whole
        local, _, typed_domain = local.rpartition("@")
        domain_name = typed_domain or domain_name
    domain_name = domain_name.strip().lower()
    if not LOCAL_PART.fullmatch(local):
        return None, None, ("Type the part of the address before the @, like ceo: letters, digits, "
                            "dots, dashes and underscores.")
    db = get_db()
    domain = db.execute("SELECT id, authenticated FROM domains WHERE name = ?", (domain_name,)).fetchone()
    if domain is None or not domain["authenticated"]:
        return None, None, (f"{domain_name or 'That domain'} isn't one of your authenticated domains. "
                            "Authenticate it on the Domains page first.")
    email = f"{local}@{domain_name}"
    if sender and not db.execute("SELECT 1 FROM senders WHERE lower(email) = ?", (email,)).fetchone():
        return None, None, (f"{email} isn't a sender yet. Add it on the Senders page first: each mailbox "
                            "is made for one of your senders.")
    if db.execute("SELECT 1 FROM mailboxes WHERE email = ?", (email,)).fetchone():
        return None, None, f"{email} is already a mailbox."
    if db.execute("SELECT 1 FROM mailbox_aliases WHERE email = ?", (email,)).fetchone():
        return None, None, f"{email} is already an alias of a mailbox."
    return email, domain["id"], None


def _usage():
    """What each mailbox holds now, as the mail engine says: {email: bytes}. Empty when it
    can't tell (no engine here, or it doesn't answer)."""
    if not enabled():
        return {}
    try:
        engine = client()
        domains = {domain["id"]: domain["name"] for domain in engine.get("Domain")}
        return {f"{account['name']}@{domains[account['domainId']]}": account.get("usedDiskQuota") or 0
                for account in engine.get("Account") if account.get("domainId") in domains}
    except (EngineUnavailable, EngineError, KeyError, TypeError) as error:
        current_app.logger.warning("couldn't read mailbox storage from the mail engine: %s", error)
        return {}


def _free_space():
    """The server's free disk space, for the storage hint."""
    try:
        return shutil.disk_usage(current_app.config["DATA_DIR"]).free
    except OSError:
        return None


def _receive_notes(domains):
    """For each domain with mailboxes whose mail doesn't come here yet: what its MX record lacks."""
    notes = []
    for row in get_db().execute(
            "SELECT domains.id, domains.name, domain_keys.checks, domain_keys.mail_host FROM domains"
            " LEFT JOIN domain_keys ON domain_keys.domain_id = domains.id WHERE domains.name IN (%s)"
            " ORDER BY domains.name" % ",".join("?" * len(domains)), tuple(domains)):
        state_ = (json.loads(row["checks"]) if row["checks"] else {}).get("mx", {}).get("state")
        if state_ == "found":
            continue
        host = f"{row['mail_host'] or HOST_CHOICES[0]}.{row['name']}"
        if state_ == "different":
            text = (f"{row['name']}'s MX record points to other servers too, so some of its mail may land there. "
                    f"Keep only {host}.")
        elif state_ == "elsewhere":
            text = (f"Mail for {row['name']} still goes to another service. Point {row['name']}'s MX record "
                    f"to {host} to receive it here.")
        else:
            text = f"{row['name']} has no MX record yet. Add {row['name']}'s MX record, pointing to {host}, to receive its mail here."
        notes.append({"domain_id": row["id"], "text": text})
    return notes


def _page(status=200, **context):
    db = get_db()
    used = _usage()
    # Every mailbox is on the page; the ones the search doesn't match (by address or alias) are
    # hidden, so typing in the search box filters the whole list on the spot (mailboxes-page.js).
    query = request.args.get("q", "").strip()
    boxes = []
    for row in db.execute("SELECT mailboxes.*, domains.name AS domain FROM mailboxes"
                          " JOIN domains ON domains.id = mailboxes.domain_id"
                          " ORDER BY mailboxes.created_at DESC, mailboxes.id DESC"):   # (the newest on top)
        aliases = db.execute("SELECT id, email FROM mailbox_aliases WHERE mailbox_id = ? ORDER BY email",
                             (row["id"],)).fetchall()
        quota = row["quota_bytes"]
        in_use = used.get(row["email"])
        size, unit = _in_unit(quota)
        found_by = " ".join([row["email"], *(alias["email"] for alias in aliases)]).lower()
        boxes.append({
            "id": row["id"], "email": row["email"], "domain": row["domain"], "aliases": aliases,
            "found_by": found_by, "shown": query.lower() in found_by,
            "quota": size_text(quota), "size": size, "unit": unit, "send_limit": row["send_limit_mb"],
            "used": None if in_use is None else {
                "percent": min(100.0, in_use * 100 / quota), "text": size_text(in_use),
                "available": size_text(max(0, quota - in_use))},
        })
    domains = _authenticated_domains()
    # what a new mailbox can be for: the senders at authenticated domains without one yet
    free_senders = db.execute(
        "SELECT senders.name, lower(senders.email) AS email FROM senders JOIN domains ON domains.id = senders.domain_id"
        " WHERE domains.authenticated = 1 AND lower(senders.email) NOT IN (SELECT email FROM mailboxes)"
        " AND lower(senders.email) NOT IN (SELECT email FROM mailbox_aliases)"
        " ORDER BY senders.created_at DESC, senders.id DESC").fetchall()
    server = _server_for(boxes[0]["domain"]) if boxes else names.server_name()
    # the webmail's login link, to share: as it is, or with a mailbox's address filled in
    webmail_login = f"{webmail_site.address(request.host)}/login"
    webmail_links = [{"email": box["email"], "url": f"{webmail_login}?email={quote(box['email'], safe='@')}"}
                     for box in boxes]
    free = _free_space()
    return render_template(
        "mailboxes.html", mailboxes=boxes, query=query, domains=[domain["name"] for domain in domains],
        server=server, ports=MAIL_APPS, free=size_text(free) if free else None,
        webmail_login=webmail_login, webmail_links=webmail_links, free_senders=free_senders,
        rules=password_checks(password_rules()), saved_rules=password_rules(), min_length=password_rules()["min_length"],
        notes=_receive_notes(sorted({box["domain"] for box in boxes})) if boxes else [],
        sync_error=state()["sync_error"] if enabled() else None,
        opened=request.args.get("aliases", type=int), **context,
    ), status


def _server_for(domain):
    """The name mail apps connect to: the mail server name, or mail.<domain> before there's one."""
    return names.server_name() or f"{HOST_CHOICES[0]}.{domain}"


def _mailbox(mailbox_id):
    mailbox = get_db().execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
    if mailbox is None:
        abort(404)
    return mailbox


def _typed(*fields):
    return {field: request.form.get(field, "") for field in fields}


@bp.get("")
@login_required
def index():
    return _page()


@bp.post("")
@login_required
def create():
    typed = _typed("email", "storage", "unit")   # the sender it's for, picked in the dialog
    email, domain_id, problem = _address(typed["email"], "", sender=True)
    size = None
    if not problem:
        size, problem = _storage(typed["storage"], typed["unit"])
    if not problem:
        problem = _password_problem(request.form.get("password", ""), request.form.get("confirm", ""))
    if problem:
        return _page(400, create_problem=problem, typed=typed)
    db = get_db()
    db.execute("INSERT INTO mailboxes (email, domain_id, quota_bytes, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
               (email, domain_id, size, mail_password.hash_password(request.form["password"]), time.time()))
    db.commit()
    engine_sync.after_change()
    flash(f"{email} was created.", "added")
    return redirect(url_for("mailboxes.index"))


@bp.post("/password-rules")
@login_required
def change_password_rules():
    """Saved from the Password rules dialog; mailboxes-page.js asks for JSON, so the dialog it
    was opened from stays open with what was typed in it."""
    wants_json = request.accept_mimetypes.best == "application/json"
    min_length = request.form.get("min_length", "")
    if not min_length.isdigit() or int(min_length) not in MIN_LENGTHS:
        problem = "Pick a minimum length from 1 to 12."
        return ({"problem": problem}, 400) if wants_json else _page(400, rules_problem=problem)
    db = get_db()
    db.execute("UPDATE mailbox_password_rules SET min_length = ?, require_letters = ?, require_numbers = ?,"
               " require_special = ? WHERE id = 1", (int(min_length), *(kind in request.form for kind in FORCED_KINDS)))
    db.commit()
    if wants_json:
        return jsonify(min_length=int(min_length), message="Mailbox password rules saved.",
                       rules=[{"key": check.key, "label": check.label} for check in password_checks(password_rules())])
    flash("Mailbox password rules saved.", "success")
    return redirect(url_for("mailboxes.index"))


@bp.post("/<int:mailbox_id>/webmail")
@login_required
def open_webmail(mailbox_id):
    """The mailbox's webmail, in a new tab, already signed in: a one-time ticket, used within a
    minute (webmail_site.py)."""
    _mailbox(mailbox_id)
    return redirect(f"{webmail_site.address(request.host)}/enter?ticket={webmail_site.new_ticket(mailbox_id)}")


@bp.get("/<int:mailbox_id>/profile")
@login_required
def profile(mailbox_id):
    """The mailbox as a configuration profile, for an iPhone or a Mac (mail_profile.py)."""
    return _profile(_mailbox(mailbox_id))


@bp.get("/<int:mailbox_id>/profile-link")
@login_required
def profile_link(mailbox_id):
    """A new link to the profile, with its QR code for the iPhone's camera: good for an hour."""
    _mailbox(mailbox_id)
    url = url_for("mailboxes.profile_by_link", token=mail_profile.new_link(mailbox_id), _external=True)
    return {"url": url, "qr": mail_profile.qr_code(url)}


@bp.get("/profile/<token>")
def profile_by_link(token):
    """The profile, on the iPhone that scanned the code: no login, while the link lasts."""
    mailbox_id = mail_profile.link_for(token)
    if mailbox_id == "expired":
        abort(410)
    mailbox = mailbox_id and get_db().execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
    if not mailbox:
        abort(404)
    return _profile(mailbox)


def _profile(mailbox):
    email = mailbox["email"]
    return mail_profile.download(email, _server_for(email.rsplit("@", 1)[1]), MAIL_APPS)


@bp.post("/<int:mailbox_id>/password")
@login_required
def change_password(mailbox_id):
    mailbox = _mailbox(mailbox_id)
    problem = _password_problem(request.form.get("password", ""), request.form.get("confirm", ""))
    if problem:
        return _page(400, password_problem=problem, for_mailbox=mailbox)
    db = get_db()
    # a new version: the sync gives the engine the new hash (it can't tell hashes apart itself)
    db.execute("UPDATE mailboxes SET password_hash = ?, password_version = password_version + 1 WHERE id = ?",
               (mail_password.hash_password(request.form["password"]), mailbox_id))
    db.commit()
    engine_sync.after_change()
    flash(f"{mailbox['email']}'s password was changed. Mail apps signed in with the old one ask for the new one.", "success")
    return redirect(url_for("mailboxes.index"))


@bp.post("/<int:mailbox_id>/storage")
@login_required
def change_storage(mailbox_id):
    mailbox = _mailbox(mailbox_id)
    typed = _typed("storage", "unit")
    size, problem = _storage(typed["storage"], typed["unit"])
    if problem:
        return _page(400, storage_problem=problem, for_mailbox=mailbox, typed=typed)
    db = get_db()
    db.execute("UPDATE mailboxes SET quota_bytes = ? WHERE id = ?", (size, mailbox_id))
    db.commit()
    engine_sync.after_change()
    flash(f"{mailbox['email']} now has {size_text(size)} of storage.", "success")
    return redirect(url_for("mailboxes.index"))


@bp.post("/<int:mailbox_id>/sending")
@login_required
def change_sending(mailbox_id):
    """How large a message the mailbox may send, in MB of files (the webmail, and mail apps through the
    engine's size rule: engine/sync.py)."""
    mailbox = _mailbox(mailbox_id)
    typed = request.form.get("limit", "").strip()
    limit = int(typed) if typed.isdigit() else 0
    if limit not in SEND_LIMITS:
        return _page(400, sending_problem="Choose a size from 1 to 100 MB.", for_mailbox=mailbox, typed={"limit": typed})
    db = get_db()
    db.execute("UPDATE mailboxes SET send_limit_mb = ? WHERE id = ?", (limit, mailbox_id))
    db.commit()
    engine_sync.after_change()
    flash(f"{mailbox['email']} can now send up to {limit} MB at a time.", "success")
    return redirect(url_for("mailboxes.index"))


@bp.post("/<int:mailbox_id>/aliases")
@login_required
def add_alias(mailbox_id):
    mailbox = _mailbox(mailbox_id)
    typed = _typed("local", "domain")
    email, domain_id, problem = _address(typed["local"], typed["domain"])
    if problem:
        return _page(400, alias_problem=problem, opened=mailbox_id, typed=typed)
    db = get_db()
    db.execute("INSERT INTO mailbox_aliases (mailbox_id, email, domain_id, created_at) VALUES (?, ?, ?, ?)",
               (mailbox_id, email, domain_id, time.time()))
    db.commit()
    engine_sync.after_change()
    flash(f"Mail to {email} now lands in {mailbox['email']}.", "added")
    return redirect(url_for("mailboxes.index", aliases=mailbox_id))   # its aliases stay open


@bp.post("/<int:mailbox_id>/aliases/<int:alias_id>/delete")
@login_required
def delete_alias(mailbox_id, alias_id):
    db = get_db()
    alias = db.execute("SELECT email FROM mailbox_aliases WHERE id = ? AND mailbox_id = ?", (alias_id, mailbox_id)).fetchone()
    if alias:
        db.execute("DELETE FROM mailbox_aliases WHERE id = ?", (alias_id,))
        db.commit()
        engine_sync.after_change()
        flash(f"{alias['email']} was deleted.", "deleted")
    return redirect(url_for("mailboxes.index", aliases=mailbox_id))


@bp.post("/<int:mailbox_id>/delete")
@login_required
def delete(mailbox_id):
    db = get_db()
    mailbox = db.execute("SELECT email FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
    if mailbox:
        db.execute("DELETE FROM mailbox_aliases WHERE mailbox_id = ?", (mailbox_id,))
        webmail_views.forget(mailbox_id)
        db.execute("DELETE FROM mailboxes WHERE id = ?", (mailbox_id,))
        db.commit()
        engine_sync.after_change()   # the engine deletes the account, and the mail in it
        flash(f"{mailbox['email']} was deleted, with its mail.", "deleted")
    return redirect(url_for("mailboxes.index"))
