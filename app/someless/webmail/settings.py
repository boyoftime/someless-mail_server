"""The webmail's Settings, as PrivateEmail's: a page of cards (Profile, System preferences,
Signature, Forwarding, Filters, Auto-reply, Spam management, Connect third-party apps, Security
Center), and a page each for what needs more room (Signatures, Auto-reply, Filters, Third-party
apps, Security). What's saved is the mailbox's own: its name, its preferences and signatures
here (views.py), its forwarding, auto-reply and filters here too and in the engine, as one Sieve
script (sieve.py), and its password in the panel's database and the engine.

The pages are drawn here; what's changed on them comes back as JSON (webmail-settings.js,
webmail-signatures.js, webmail-autoreply.js, webmail-filters.js), and the toast says it's done."""
import datetime
import json
import re
import time

from flask import Blueprint, g, render_template, request, session, url_for

from . import login_required, views
from . import sieve
from .compose import _own_addresses, clean_outgoing
from .jmap import MailError, for_mailbox
from .mail import _tree, reachable
from .. import mail_password
from ..db import get_db
from ..engine import sync as engine_sync

bp = Blueprint("settings", __name__, url_prefix="/settings")

NAME_MARKS = set(".-_,'()|&")
LONGEST_NAME = 128
LONGEST_SIGNATURE_NAME = 50
LONGEST_SIGNATURE = 2_000_000   # characters: its pictures are kept inside it (the page makes each at most 600px wide)
LONGEST_REPLY_SUBJECT = 1000
LONGEST_REPLY = 5000
MOST_SIGNATURES = 20
ADDRESS = re.compile(r"^[^@\s<>(),;:\"\[\]\\]+@[^@\s<>(),;:\"\[\]\\]+\.[^@\s<>(),;:\"\[\]\\]+$")
PORTS = {"imap": 993, "pop3": 995, "smtp_ssl": 465, "smtp_starttls": 587}
SHORTCUTS = [
    ("Formatting text", [("Bold", "Ctrl + B"), ("Italics", "Ctrl + I"), ("Underline", "Ctrl + U"),
                         ("Numbered list", "Ctrl + Shift + 7"), ("Bulleted list", "Ctrl + Shift + 8"),
                         ("Indent less", "Ctrl + ["), ("Indent more", "Ctrl + ]"), ("Remove formatting", "Ctrl + \\"),
                         ("Insert a link", "Ctrl + K"), ("Undo", "Ctrl + Z"), ("Redo", "Ctrl + Y")]),
    ("Actions", [("Send", "Ctrl + Enter"), ("Save as draft", "Ctrl + S"), ("Search", "/")]),
    ("Email list actions", [("Next mail", "↓"), ("Previous mail", "↑"), ("Select mail", "Shift + ↓ or ↑"),
                            ("Mark as read", "Shift + I"), ("Mark as unread", "Shift + U"), ("Delete", "Delete"),
                            ("Deselect all mails", "Esc")]),
]


def _mail():
    return for_mailbox(g.mailbox["email"])


def _who():
    email = g.mailbox["email"]
    name = views.display_name(g.mailbox["id"])
    if not name:
        sender = get_db().execute("SELECT name FROM senders WHERE lower(email) = ?", (email,)).fetchone()
        name = sender["name"] if sender else ""
    return name


def _page(template, **context):
    name = _who() or g.mailbox["email"].partition("@")[0]
    return render_template(template, email=g.mailbox["email"], name=name, initial=name[:1].upper(), **context)


def _server():
    from ..mailboxes import _server_for
    return _server_for(g.mailbox["email"].rsplit("@", 1)[1])


def _write_rules(mail=None):
    """The mailbox's auto-reply, forwarding and filters, into the engine."""
    mail = mail or _mail()
    sieve.write(mail, _tree(mail), _own_addresses())


# --- the page of cards ---

@bp.get("")
@login_required
def index():
    mailbox_id = g.mailbox["id"]
    signatures = views.signatures(mailbox_id)
    return _page("webmail-settings.html", display_name=_who(), preferences=views.preferences(mailbox_id),
                 default_signature=next((one for one in signatures if one["is_default"]), None),
                 signature_count=len(signatures), rules=sieve.settings(mailbox_id),
                 filter_count=sum(1 for rule in sieve.rules(mailbox_id) if rule["enabled"]),
                 shortcuts=SHORTCUTS, server=_server(), ports=PORTS)


# --- Profile: the display name ---

def display_name_problem(name):
    if not name:
        return "A new display name is required."
    if not name.strip():
        return "Your display name can't contain only spaces."
    if len(name) >= LONGEST_NAME:
        return "Your name must be under 128 symbols."
    if any(not (character.isalnum() or character.isspace() or character in NAME_MARKS) for character in name):
        return "The only symbols allowed are: .-_,'()|&"
    return None


@bp.post("/profile")
@login_required
def profile():
    name = str((request.get_json(silent=True) or {}).get("display_name") or "")
    problem = display_name_problem(name)
    if problem:
        return {"problem": problem}, 400
    views.set_display_name(g.mailbox["id"], " ".join(name.split()))
    return {"message": "Name has been updated successfully.", "display_name": " ".join(name.split())}


# --- System preferences: the sound, notifications ---

@bp.post("/preferences")
@login_required
def preferences():
    data = request.get_json(silent=True) or {}
    if data.get("name") not in views.PREFERENCES:
        return {"problem": "Choose a preference."}, 400
    views.set_preference(g.mailbox["id"], data["name"], bool(data.get("on")))
    return {"preferences": views.preferences(g.mailbox["id"])}


# --- Forwarding ---

@bp.post("/forwarding")
@login_required
@reachable
def forwarding():
    """Forwarding on or off, where to, and whether a copy stays ({"on", "address", "keep"})."""
    data = request.get_json(silent=True) or {}
    kept = sieve.settings(g.mailbox["id"])
    address = kept["forward_to"]
    if "address" in data:
        address = str(data.get("address") or "").strip()
        if not address:
            return {"problem": "Forwarding email address field can't be empty"}, 400
        if not ADDRESS.match(address) or len(address) > 254:
            return {"problem": "Email address must be in the correct format, e.g.: example@yourdomain.com"}, 400
        if address.lower() in {own.lower() for own in _own_addresses()}:
            return {"problem": "You can't forward messages to your own mailbox, choose another one."}, 400
    on = bool(data.get("on", kept["forward_on"] if address else False))
    keep = bool(data.get("keep", kept["forward_keep"]))
    before = dict(kept)
    sieve.save_settings(g.mailbox["id"], forward_to=address, forward_on=on and bool(address), forward_keep=keep)
    try:
        _write_rules()
    except MailError:
        sieve.save_settings(g.mailbox["id"], forward_to=before["forward_to"], forward_on=before["forward_on"],
                            forward_keep=before["forward_keep"])
        return {"problem": "Failed to update forwarding settings."}, 502
    kept = sieve.settings(g.mailbox["id"])
    return {"forwarding": {"address": kept["forward_to"], "on": kept["forward_on"], "keep": kept["forward_keep"]},
            "message": "Forwarding settings have been saved"}


@bp.post("/forwarding/delete")
@login_required
@reachable
def forwarding_delete():
    sieve.save_settings(g.mailbox["id"], forward_to=None, forward_on=False)
    try:
        _write_rules()
    except MailError:
        return {"problem": "Falied to cancel forwarding."}, 502
    return {"forwarding": {"address": None, "on": False, "keep": True}, "message": "The forwarding address was deleted"}


# --- Auto-reply ---

def _when(date, clock, zone):
    """A date and time the reader typed (their own time zone), as ISO in UTC for the script."""
    moment = datetime.datetime.combine(datetime.date.fromisoformat(date), datetime.time.fromisoformat(clock))
    return moment.replace(tzinfo=zone).astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _reader_zone():
    from .messages import zone
    return zone()


@bp.get("/auto-reply")
@login_required
def auto_reply_page():
    kept = sieve.settings(g.mailbox["id"])
    zone = _reader_zone()

    def local(iso):
        if not iso:
            return "", ""
        moment = datetime.datetime.fromisoformat(iso).astimezone(zone)
        return moment.date().isoformat(), moment.strftime("%H:%M")

    start_date, start_time = local(kept["reply_start"])
    end_date, end_time = local(kept["reply_end"])
    return _page("webmail-settings-autoreply.html", kept=kept, start_date=start_date, start_time=start_time,
                 end_date=end_date, end_time=end_time)


@bp.post("/auto-reply")
@login_required
@reachable
def auto_reply():
    """The auto-reply ({"on", "start_date", "start_time", "end_date", "end_time", "subject", "html"}),
    checked as PrivateEmail checks it, kept and written into the engine."""
    data = request.get_json(silent=True) or {}
    on = bool(data.get("on"))
    subject = " ".join(str(data.get("subject") or "").split())
    html = clean_outgoing(str(data.get("html") or ""), [])
    text = re.sub(r"<[^>]+>", "", html).strip()
    zone = _reader_zone()
    start = end = None
    if on:
        for part, label in (("start_date", "Start date"), ("start_time", "Start time"), ("end_date", "End date"),
                            ("end_time", "End time")):
            if not str(data.get(part) or "").strip():
                return {"problem": f"{label} is required."}, 400
        try:
            start = _when(data["start_date"], data["start_time"], zone)
        except ValueError:
            return {"problem": "Start date is not valid."}, 400
        try:
            end = _when(data["end_date"], data["end_time"], zone)
        except ValueError:
            return {"problem": "End date is not valid."}, 400
        if end <= start:
            return {"problem": "End date must be after start date." if data["end_date"] != data["start_date"]
                    else "End time must be after start time."}, 400
        if not text and "<img" not in html:
            return {"problem": "Message body is required."}, 400
    if len(subject) > LONGEST_REPLY_SUBJECT:
        return {"problem": "Subject must be no more than 1,000 characters."}, 400
    if len(text) > LONGEST_REPLY:
        return {"problem": "Auto-reply message must be no more than 5,000 characters."}, 400
    before = sieve.settings(g.mailbox["id"])
    sieve.save_settings(g.mailbox["id"], reply_on=on, reply_start=start, reply_end=end, reply_subject=subject, reply_html=html)
    try:
        _write_rules()
    except MailError:
        sieve.save_settings(g.mailbox["id"], **{key: before[key] for key in ("reply_on", "reply_start", "reply_end",
                                                                                 "reply_subject", "reply_html")})
        return {"problem": "Auto-reply update error"}, 502
    return {"message": "Auto-reply saved"}


# --- Signatures ---

@bp.get("/signatures")
@login_required
def signatures_page():
    return _page("webmail-settings-signatures.html", signatures=views.signatures(g.mailbox["id"]))


def _signature_input():
    data = request.get_json(silent=True) or {}
    name = " ".join(str(data.get("name") or "").split()) or "New signature"
    if len(name) > LONGEST_SIGNATURE_NAME:
        return None, "Signature name max length is 50 symbols"
    html = clean_outgoing(str(data.get("html") or ""), [])
    if len(html) > LONGEST_SIGNATURE:
        return None, "This signature is too large. Use smaller pictures, or fewer of them."
    return {"name": name, "html": html, "default": bool(data.get("default"))}, None


def _set_default(mailbox_id, signature_id):
    database = get_db()
    database.execute("UPDATE webmail_signatures SET is_default = (id = ?) WHERE mailbox_id = ?", (signature_id, mailbox_id))


@bp.post("/signatures")
@login_required
def signature_create():
    signature, problem = _signature_input()
    if problem:
        return {"problem": problem}, 400
    mailbox_id = g.mailbox["id"]
    database = get_db()
    if database.execute("SELECT COUNT(*) FROM webmail_signatures WHERE mailbox_id = ?", (mailbox_id,)).fetchone()[0] >= MOST_SIGNATURES:
        return {"problem": f"A mailbox can have {MOST_SIGNATURES} signatures at most."}, 400
    first = not database.execute("SELECT 1 FROM webmail_signatures WHERE mailbox_id = ?", (mailbox_id,)).fetchone()
    made = database.execute("INSERT INTO webmail_signatures (mailbox_id, name, html, is_default, created_at) VALUES (?, ?, ?, 0, ?)",
                            (mailbox_id, signature["name"], signature["html"], time.time())).lastrowid
    if signature["default"] or first:
        _set_default(mailbox_id, made)
    database.commit()
    return {"message": "Your signature has been added.", "signatures": views.signatures(mailbox_id), "id": made}


def _own_signature(signature_id):
    return get_db().execute("SELECT * FROM webmail_signatures WHERE id = ? AND mailbox_id = ?",
                            (signature_id, g.mailbox["id"])).fetchone()


@bp.post("/signatures/<int:signature_id>")
@login_required
def signature_update(signature_id):
    if _own_signature(signature_id) is None:
        return {"problem": "That signature isn't there any more."}, 404
    signature, problem = _signature_input()
    if problem:
        return {"problem": problem}, 400
    database = get_db()
    database.execute("UPDATE webmail_signatures SET name = ?, html = ? WHERE id = ?", (signature["name"], signature["html"], signature_id))
    if signature["default"]:
        _set_default(g.mailbox["id"], signature_id)
    else:
        database.execute("UPDATE webmail_signatures SET is_default = 0 WHERE id = ?", (signature_id,))
    database.commit()
    return {"message": "Your changes have been saved successfully.", "signatures": views.signatures(g.mailbox["id"])}


@bp.post("/signatures/<int:signature_id>/default")
@login_required
def signature_default(signature_id):
    signature = _own_signature(signature_id)
    if signature is None:
        return {"problem": "That signature isn't there any more."}, 404
    _set_default(g.mailbox["id"], signature_id)
    get_db().commit()
    return {"message": f"{signature['name']} has been set as the default signature", "signatures": views.signatures(g.mailbox["id"])}


@bp.post("/signatures/<int:signature_id>/delete")
@login_required
def signature_delete(signature_id):
    signature = _own_signature(signature_id)
    if signature is None:
        return {"problem": "That signature isn't there any more."}, 404
    database = get_db()
    database.execute("DELETE FROM webmail_signatures WHERE id = ?", (signature_id,))
    database.commit()
    return {"message": f"{signature['name']} was deleted.", "signatures": views.signatures(g.mailbox["id"])}


# --- Filters ---

def _folder_choices(tree):
    return [{"id": folder["id"], "key": folder["key"], "label": tree.path(folder), "depth": folder["depth"],
             "role": folder["role"] or ""} for folder in tree.list if folder["role"] not in ("drafts", "sent")]


@bp.get("/filters")
@login_required
@reachable
def filters_page():
    tree = _tree(_mail())
    return _page("webmail-settings-filters.html", rules=sieve.rules(g.mailbox["id"]), folders=_folder_choices(tree),
                 folder_names={folder["id"]: tree.path(folder) for folder in tree.list})


def _save_rule(rule_id=None):
    data = request.get_json(silent=True) or {}
    mail = _mail()
    tree = _tree(mail)
    try:
        rule = sieve.check(data, {folder["id"] for folder in tree.list})
    except sieve.RuleProblem as problem:
        return {"problem": str(problem)}, 400
    database = get_db()
    stored = json.dumps({key: rule[key] for key in ("operator", "conditions", "actions", "stop")})
    if rule_id is None:
        if database.execute("SELECT COUNT(*) FROM webmail_rules WHERE mailbox_id = ?", (g.mailbox["id"],)).fetchone()[0] >= sieve.MOST_RULES:
            return {"problem": f"A mailbox can have {sieve.MOST_RULES} filters at most."}, 400
        last = database.execute("SELECT COALESCE(MAX(position), 0) FROM webmail_rules WHERE mailbox_id = ?", (g.mailbox["id"],)).fetchone()[0]
        database.execute("INSERT INTO webmail_rules (mailbox_id, position, name, enabled, rule) VALUES (?, ?, ?, ?, ?)",
                         (g.mailbox["id"], last + 1, rule["name"], int(rule["enabled"]), stored))
        message = "New filter was created! You can find your new filter at the end of the list."
    else:
        database.execute("UPDATE webmail_rules SET name = ?, enabled = ?, rule = ? WHERE id = ?",
                         (rule["name"], int(rule["enabled"]), stored, rule_id))
        message = "The filter has been updated successfully."
    try:
        _write_rules(mail)
    except MailError as error:
        database.rollback()
        return {"problem": f"The mail server didn't take the filter: {error}"}, 502
    database.commit()
    return {"message": message, "rules": sieve.rules(g.mailbox["id"])}


def _own_rule(rule_id):
    return get_db().execute("SELECT * FROM webmail_rules WHERE id = ? AND mailbox_id = ?", (rule_id, g.mailbox["id"])).fetchone()


@bp.post("/filters")
@login_required
@reachable
def filter_create():
    return _save_rule()


@bp.post("/filters/<int:rule_id>")
@login_required
@reachable
def filter_update(rule_id):
    if _own_rule(rule_id) is None:
        return {"problem": "That filter isn't there any more."}, 404
    return _save_rule(rule_id)


@bp.post("/filters/<int:rule_id>/toggle")
@login_required
@reachable
def filter_toggle(rule_id):
    if _own_rule(rule_id) is None:
        return {"problem": "That filter isn't there any more."}, 404
    on = bool((request.get_json(silent=True) or {}).get("enabled"))
    database = get_db()
    database.execute("UPDATE webmail_rules SET enabled = ? WHERE id = ?", (int(on), rule_id))
    try:
        _write_rules()
    except MailError:
        database.rollback()
        return {"problem": "An error has occured while updaing the rule."}, 502
    database.commit()
    return {"rules": sieve.rules(g.mailbox["id"])}


@bp.post("/filters/delete")
@login_required
@reachable
def filter_delete():
    ids = [int(one) for one in (request.get_json(silent=True) or {}).get("ids") or [] if str(one).isdigit()]
    if not ids:
        return {"problem": "Choose a filter first."}, 400
    database = get_db()
    for rule_id in ids:
        database.execute("DELETE FROM webmail_rules WHERE id = ? AND mailbox_id = ?", (rule_id, g.mailbox["id"]))
    try:
        _write_rules()
    except MailError:
        database.rollback()
        return {"problem": "An error has occured while deleting the rule(-s)."}, 502
    database.commit()
    return {"message": "The filter has been removed." if len(ids) == 1 else "The selected filters have been removed.",
            "rules": sieve.rules(g.mailbox["id"])}


@bp.post("/filters/order")
@login_required
@reachable
def filter_order():
    ids = [int(one) for one in (request.get_json(silent=True) or {}).get("ids") or [] if str(one).isdigit()]
    database = get_db()
    for position, rule_id in enumerate(ids, start=1):
        database.execute("UPDATE webmail_rules SET position = ? WHERE id = ? AND mailbox_id = ?", (position, rule_id, g.mailbox["id"]))
    try:
        _write_rules()
    except MailError:
        database.rollback()
        return {"problem": "An error has occured while updaing the rule."}, 502
    database.commit()
    return {"rules": sieve.rules(g.mailbox["id"])}


# --- Help center ---

@bp.get("/help")
@login_required
def help_page():
    return _page("webmail-settings-help.html", server=_server(), ports=PORTS, dav=request.host_url.rstrip("/") + "/dav/")


# --- Connect third-party apps ---

@bp.get("/apps")
@login_required
def apps_page():
    base = request.host_url.rstrip("/")
    email = g.mailbox["email"]
    return _page("webmail-settings-apps.html", server=_server(), ports=PORTS, dav=base + "/dav/",
                 calendar_server=f"{base}/dav/cal/{email}/", contacts_server=f"{base}/dav/card/{email}/")


@bp.get("/apps/profile")
@login_required
def apps_profile():
    """The iPhone's, iPad's or Mac's way in: a profile that sets up the Mail app (mail_profile.py)."""
    from .. import mail_profile
    return mail_profile.download(g.mailbox["email"], _server(), PORTS)


# --- Security Center: the password, and where the mailbox logged in from ---

@bp.get("/security")
@login_required
def security_page():
    from ..mailboxes import password_rules
    from ..settings import password_checks
    logins = get_db().execute("SELECT at, address, agent FROM webmail_logins WHERE mailbox_id = ? ORDER BY at DESC LIMIT 20",
                              (g.mailbox["id"],)).fetchall()
    rules = password_rules()
    return _page("webmail-settings-security.html", logins=[_login_row(row) for row in logins],
                 checks=password_checks(rules), min_length=rules["min_length"])


def _login_row(row):
    from .messages import full_time
    stamp = datetime.datetime.fromtimestamp(row["at"], datetime.timezone.utc).isoformat()
    agent = row["agent"] or ""
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Chrome/", "Chrome"), ("Firefox/", "Firefox"),
                                           ("Safari/", "Safari")) if key in agent), "A browser")
    system = next((name for key, name in (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"),
                                          ("Mac OS", "macOS"), ("Linux", "Linux")) if key in agent), "")
    return {"when": full_time(stamp), "address": row["address"] or "", "device": f"{browser} on {system}" if system else browser}


@bp.post("/password")
@login_required
def password():
    """A new password for the mailbox ({"current", "password", "confirm"}), as PrivateEmail's "Save &
    log out": the webmail logs out, to log in again with it (the login page says so); mail apps
    ask for it next time."""
    from ..mailboxes import _password_problem
    data = request.get_json(silent=True) or {}
    row = get_db().execute("SELECT * FROM mailboxes WHERE id = ?", (g.mailbox["id"],)).fetchone()
    if not mail_password.password_ok(row["password_hash"], str(data.get("current") or "")):
        return {"problem": "Your current password is wrong."}, 400
    new, confirm = str(data.get("password") or ""), str(data.get("confirm") or "")
    problem = _password_problem(new, confirm)
    if problem:
        return {"problem": problem}, 400
    if new == data.get("current"):
        return {"problem": "The new password is the one you have. Choose another."}, 400
    database = get_db()
    database.execute("UPDATE mailboxes SET password_hash = ?, password_version = password_version + 1 WHERE id = ?",
                     (mail_password.hash_password(new), row["id"]))
    database.commit()
    engine_sync.after_change()
    session.clear()
    session["notice"] = "Your password was changed. Log in with the new one."
    return {"message": "Your password was changed. Log in again with the new one.", "login": url_for("login")}


def remember_login(mailbox_id):
    """A login, for Security's list: when, from where, with what."""
    database = get_db()
    database.execute("INSERT INTO webmail_logins (mailbox_id, at, address, agent) VALUES (?, ?, ?, ?)",
                     (mailbox_id, time.time(), request.remote_addr, (request.headers.get("User-Agent") or "")[:300]))
    database.execute("DELETE FROM webmail_logins WHERE mailbox_id = ? AND id NOT IN "
                     "(SELECT id FROM webmail_logins WHERE mailbox_id = ? ORDER BY at DESC LIMIT 50)", (mailbox_id, mailbox_id))
    database.commit()
