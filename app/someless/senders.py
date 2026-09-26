"""Senders: the names and addresses mail goes out from, like PineLoop INC
<no-reply@pineloop.online>. An address can be a sender only at one of the admin's domains, once
it's authenticated (the Domains page), so other mail servers trust mail from it."""
import json
import re
import time

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .auth import login_required
from .db import get_db

bp = Blueprint("senders", __name__, url_prefix="/senders")

NAME_LIMIT = 70
# The part before the @: letters, digits and the usual signs, no dot at either end or two in a row
LOCAL_PART = re.compile(r"(?!\.)(?!.*\.\.)[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]{1,64}(?<!\.)")


def _authenticated_domains():
    return [row["name"] for row in get_db().execute("SELECT name FROM domains WHERE authenticated = 1 ORDER BY name")]


def _checked(typed, sender_id=None):
    """The sender as typed, tidied up: (name, email, domain_id, None), or (…, problem) when it
    can't be one."""
    db = get_db()
    name, email = typed["name"].strip(), typed["email"].strip()
    local, at, domain = email.rpartition("@")
    domain = domain.lower()
    if not name:
        return None, None, None, "Give the sender a name: what people see their mail come from."
    if len(name) > NAME_LIMIT:
        return None, None, None, f"Keep the name to {NAME_LIMIT} characters or fewer."
    if not at or not LOCAL_PART.fullmatch(local) or "." not in domain:
        return None, None, None, "Type an email address, like no-reply@yourdomain.com."
    row = db.execute("SELECT id, authenticated FROM domains WHERE name = ?", (domain,)).fetchone()
    if row is None:
        return None, None, None, (f"{domain} isn't one of your domains. Add it on the Domains page and "
                                  "authenticate it, then come back to add this sender.")
    if not row["authenticated"]:
        return None, None, None, (f"{domain} isn't authenticated yet. Authenticate it on the Domains page "
                                  "first, then come back to add this sender.")
    email = f"{local}@{domain}"
    if db.execute("SELECT 1 FROM senders WHERE lower(email) = lower(?) AND id != ?", (email, sender_id or 0)).fetchone():
        return None, None, None, f"{email} is already a sender."
    return name, email, row["id"], None


def _form(status=200, sender=None, typed=None, problem=None):
    return render_template(
        "sender-form.html", sender=sender, typed=typed or {"name": "", "email": ""}, problem=problem,
        domains=_authenticated_domains(),
    ), status


def _sender(sender_id):
    sender = get_db().execute("SELECT * FROM senders WHERE id = ?", (sender_id,)).fetchone()
    if sender is None:
        abort(404)
    return sender


@bp.get("")
@login_required
def index():
    # Every sender is on the page; the ones the search doesn't match are hidden, so typing in
    # the search box can filter the whole list on the spot (senders-page.js).
    query = request.args.get("q", "").strip()
    senders = []
    for row in get_db().execute(
            "SELECT senders.*, domains.name AS domain, domains.authenticated, domain_keys.checks FROM senders"
            " JOIN domains ON domains.id = senders.domain_id LEFT JOIN domain_keys ON domain_keys.domain_id = domains.id"
            " ORDER BY senders.name, senders.email"):
        checks = json.loads(row["checks"]) if row["checks"] else {}
        senders.append({
            "id": row["id"], "name": row["name"], "email": row["email"], "domain": row["domain"],
            "ready": bool(row["authenticated"]),
            "dkim": checks.get("dkim", {}).get("state") == "found",
            "dmarc": checks.get("dmarc", {}).get("state") == "found",
            "shown": query.lower() in f"{row['name']} {row['email']}".lower(),
        })
    return render_template("senders.html", senders=senders, query=query,
                           authenticated=bool(_authenticated_domains()))


@bp.get("/new")
@login_required
def new():
    return _form()


@bp.post("")
@login_required
def add():
    typed = {"name": request.form.get("name", ""), "email": request.form.get("email", "")}
    name, email, domain_id, problem = _checked(typed)
    if problem:
        return _form(400, typed=typed, problem=problem)
    db = get_db()
    db.execute("INSERT INTO senders (name, email, domain_id, created_at) VALUES (?, ?, ?, ?)",
               (name, email, domain_id, time.time()))
    db.commit()
    flash(f"{name} <{email}> was added.", "added")
    return redirect(url_for("senders.index"))


@bp.get("/<int:sender_id>/edit")
@login_required
def edit(sender_id):
    sender = _sender(sender_id)
    return _form(sender=sender, typed={"name": sender["name"], "email": sender["email"]})


@bp.post("/<int:sender_id>")
@login_required
def update(sender_id):
    sender = _sender(sender_id)
    typed = {"name": request.form.get("name", ""), "email": request.form.get("email", "")}
    name, email, domain_id, problem = _checked(typed, sender_id)
    if problem:
        return _form(400, sender=sender, typed=typed, problem=problem)
    db = get_db()
    db.execute("UPDATE senders SET name = ?, email = ?, domain_id = ? WHERE id = ?", (name, email, domain_id, sender_id))
    db.commit()
    flash(f"{name} <{email}> was saved.", "success")
    return redirect(url_for("senders.index"))


@bp.post("/<int:sender_id>/delete")
@login_required
def delete(sender_id):
    db = get_db()
    sender = db.execute("SELECT name, email FROM senders WHERE id = ?", (sender_id,)).fetchone()
    if sender:
        db.execute("DELETE FROM senders WHERE id = ?", (sender_id,))
        db.commit()
        flash(f"{sender['name']} <{sender['email']}> was deleted.", "deleted")
    return redirect(url_for("senders.index"))
