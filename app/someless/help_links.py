"""Need help? Links that share a domain's records with whoever sets up its DNS (a developer, IT),
made from the domain's Authenticate page. The link opens a page of its own on the panel's address,
without a login: the records, how to add them at the domain's DNS provider, and a button to check
them. It closes once that check finds them all right, when it expires, or when it's deleted; with a
password, it asks for that first. The link is kept, for the dialog to show and copy again, and
found by its fingerprint; its password is kept only as a fingerprint."""
import hashlib
import json
import secrets
import time

from flask import Blueprint, abort, flash, get_flashed_messages, redirect, render_template, request, session, url_for

from . import domain_records, domains, mail_password
from .auth import login_required
from .db import get_db

bp = Blueprint("help_links", __name__)

EXPIRES = {"1h": 3600, "1d": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "never": None}   # seconds (domain.html's choices)
SHORTEST_PASSWORD = 6
TRIES = 5            # wrong passwords in a row before the link locks
LOCKED_FOR = 5 * 60  # seconds
CHECK_EVERY = 30     # seconds between checks from one link

# How to add records at the DNS providers most domains are at; others get the general steps
STEPS = {
    "Namecheap": ["Sign in at namecheap.com and open Domain List.",
                  "Click Manage next to {domain}, then open the Advanced DNS tab.",
                  "Under Host records, click Add New Record for each record below: pick its type, then copy its host and value."],
    "Cloudflare": ["Sign in at dash.cloudflare.com and pick {domain}.",
                   "Open DNS, then Records, and click Add record for each record below.",
                   "For the A record, turn the proxy off (DNS only, a grey cloud): mail doesn't go through Cloudflare's proxy."],
    "GoDaddy": ["Sign in at godaddy.com and open My Products.",
                "Next to {domain}, click DNS, then Add New Record for each record below."],
    "Hostinger": ["Sign in at hpanel.hostinger.com and open Domains.",
                  "Click Manage next to {domain}, then DNS / Nameservers, and add each record below."],
    "Porkbun": ["Sign in at porkbun.com and open Domain Management.",
                "Click DNS next to {domain}, and add each record below."],
}


def _fingerprint(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _wants_json():
    return request.accept_mimetypes.best == "application/json"


def _ago(when):
    return domains._ago(when)


def _within(seconds):
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds + 120 >= size:   # a day just made is "1 day", not "24 hours"
            count = round(seconds / size)
            return f"{count} {unit}{'s' if count != 1 else ''}"
    return "a minute"


def _describe(row):
    """A link as the dialog lists it: how far it got, and until when it works."""
    now = time.time()
    expired = row["expires_at"] is not None and row["expires_at"] <= now
    if row["authenticated_at"]:
        state, text = "authenticated", f"Authenticated {_ago(row['authenticated_at'])}"
    elif expired:
        state, text = "expired", "Expired"
    elif row["opened_at"]:
        times = f"{row['opens']} time{'s' if row['opens'] != 1 else ''}"
        state, text = "opened", f"Opened {times}, last {_ago(row['opened_at'])}"
    else:
        state, text = "new", "Not opened yet"
    if row["authenticated_at"]:
        until = "Closed: the domain is authenticated"
    elif row["expires_at"] is None:
        until = "Never expires"
    elif expired:
        until = "Doesn't open any more"
    else:
        until = f"Expires in {_within(row['expires_at'] - now)}"
    return {"id": row["id"], "state": state, "state_text": text, "until": until, "password": bool(row["password_hash"]),
            "made": _ago(row["created_at"]), "url": row["url"], "shown": row["shown"]}


def list_html(domain_id):
    rows = get_db().execute("SELECT * FROM help_links WHERE domain_id = ? ORDER BY id DESC", (domain_id,)).fetchall()
    return render_template("help-links-list.html", links=[_describe(row) for row in rows], domain_id=domain_id)


def count(domain_id):
    return get_db().execute("SELECT COUNT(*) FROM help_links WHERE domain_id = ?", (domain_id,)).fetchone()[0]


def _domain(domain_id):
    domain = get_db().execute("SELECT * FROM domains WHERE id = ?", (domain_id,)).fetchone()
    if domain is None:
        abort(404)
    return domain


# The admin's side: the dialog on the Authenticate page (help-links.js)

@bp.get("/domains/<int:domain_id>/help-links")
@login_required
def list_links(domain_id):
    _domain(domain_id)
    return {"html": list_html(domain_id), "count": count(domain_id)}


@bp.post("/domains/<int:domain_id>/help-links")
@login_required
def create(domain_id):
    _domain(domain_id)
    expires = request.form.get("expires", "")
    password = request.form.get("password", "") if request.form.get("password_on") else None
    problem = None
    if expires not in EXPIRES:
        problem = "Choose when the link expires."
    elif password is not None and len(password) < SHORTEST_PASSWORD:
        problem = f"Give the link a password of at least {SHORTEST_PASSWORD} characters, or switch the password off."
    if problem:
        if _wants_json():
            return {"problem": problem}, 400
        flash(problem, "not-authenticated")
        return redirect(url_for("domains.authenticate", domain_id=domain_id))
    token = secrets.token_urlsafe(24)
    url = url_for("help_links.page", token=token, _external=True)
    now = time.time()
    lasts = EXPIRES[expires]
    db = get_db()
    db.execute("INSERT INTO help_links (domain_id, token_hash, url, password_hash, created_at, expires_at)"
               " VALUES (?, ?, ?, ?, ?, ?)",
               (domain_id, _fingerprint(token), url, password and mail_password.hash_password(password),
                now, now + lasts if lasts else None))
    db.commit()
    if _wants_json():
        return {"url": url, "html": list_html(domain_id), "count": count(domain_id)}
    flash(f"Share this link: {url}", "success")   # without JavaScript: on the board
    return redirect(url_for("domains.authenticate", domain_id=domain_id))


@bp.post("/domains/<int:domain_id>/help-links/<int:link_id>/delete")
@login_required
def delete(domain_id, link_id):
    _domain(domain_id)
    db = get_db()
    db.execute("DELETE FROM help_links WHERE id = ? AND domain_id = ?", (link_id, domain_id))
    db.commit()
    if _wants_json():
        return {"html": list_html(domain_id), "count": count(domain_id)}
    return redirect(url_for("domains.authenticate", domain_id=domain_id))


# The shared side: the page the link opens (help.html), no login

def _link(token):
    return get_db().execute("SELECT * FROM help_links WHERE token_hash = ?", (_fingerprint(token),)).fetchone()


def _open(row):
    """The link and its domain while the link works: (row, domain), or (None, None)."""
    if row is None or (row["expires_at"] is not None and row["expires_at"] <= time.time() and not row["authenticated_at"]):
        return None, None
    domain = get_db().execute("SELECT * FROM domains WHERE id = ?", (row["domain_id"],)).fetchone()
    return (row, domain) if domain else (None, None)


def _unlocked(row):
    return not row["password_hash"] or row["id"] in session.get("help_unlocked", [])


def _render(status=200, **context):
    boards = {"not-authenticated": "Not authenticated yet", "wait": "One moment", "wrong": "Couldn't open the link"}
    messages = [(boards.get(category, "Done"), message) for category, message in get_flashed_messages(with_categories=True)]
    return render_template("help.html", theme="light", messages=messages, **context), status


@bp.get("/help/<token>")
def page(token):
    row, domain = _open(_link(token))
    if row is None:
        return _render(404 if _link(token) is None else 410, state="gone", title="Ask for a new link")
    if row["authenticated_at"] or domain["authenticated"]:
        celebrate = session.pop("help_celebrate", None) == row["id"]
        return _render(state="done", domain=domain, celebrate=celebrate, title=f"{domain['name']} is authenticated")
    if not _unlocked(row):
        return _render(state="locked", domain=domain, token=token, title="This link has a password")
    db = get_db()
    db.execute("UPDATE help_links SET opens = opens + 1, opened_at = ? WHERE id = ?", (time.time(), row["id"]))
    db.commit()
    keys = domain_records.keys_for(domain["id"])
    address = domain_records.server_address(request.host)
    authenticating, receiving = domain_records.records(domain["name"], keys, address)
    provider = domain["provider"]
    steps = [step.format(domain=domain["name"]) for step in STEPS.get(provider, [])] or [
        f"Sign in where {domain['name']}'s DNS is managed{f' ({provider})' if provider else ''}: usually where the domain was bought.",
        "Open the domain's DNS settings (called DNS, DNS records or Zone editor), and add each record below."]
    return _render(state="open", domain=domain, token=token, provider=provider, steps=steps,
                   records=authenticating, receiving=receiving, checks=json.loads(keys["checks"]) if keys["checks"] else {},
                   receive_tip=domain_records.receive_tip(domain["name"], keys),
                   checked_ago=_ago(keys["checked_at"]) if keys["checked_at"] else None,
                   title=f"Set up {domain['name']}'s mail records")


@bp.post("/help/<token>/unlock")
def unlock(token):
    row, domain = _open(_link(token))
    if row is None or not row["password_hash"]:
        return redirect(url_for("help_links.page", token=token))
    db = get_db()
    if row["locked_until"] and row["locked_until"] > time.time():
        return _render(429, state="locked", domain=domain, token=token, title="This link has a password",
                       problem=f"Too many tries with a wrong password. Wait {LOCKED_FOR // 60} minutes, then try again.")
    if mail_password.password_ok(row["password_hash"], request.form.get("password", "")):
        db.execute("UPDATE help_links SET failures = 0 WHERE id = ?", (row["id"],))
        db.commit()
        session["help_unlocked"] = [*session.get("help_unlocked", []), row["id"]][-20:]
        return redirect(url_for("help_links.page", token=token))
    failures = row["failures"] + 1
    db.execute("UPDATE help_links SET failures = ?, locked_until = ? WHERE id = ?",
               (0 if failures >= TRIES else failures, time.time() + LOCKED_FOR if failures >= TRIES else row["locked_until"], row["id"]))
    db.commit()
    return _render(400, state="locked", domain=domain, token=token, title="This link has a password",
                   problem="That's not the link's password. Ask whoever shared it.")


@bp.get("/help/<token>/zone")
def zone(token):
    """The records as a zone file, while the link's page shows them."""
    row, domain = _open(_link(token))
    if row is None:
        abort(404)
    if not _unlocked(row) or row["authenticated_at"] or domain["authenticated"]:
        return redirect(url_for("help_links.page", token=token))
    return domains.zone_download(domain, request.host)


@bp.post("/help/<token>/check")
def check(token):
    row, domain = _open(_link(token))
    if row is None or not _unlocked(row) or row["authenticated_at"] or domain["authenticated"]:
        return redirect(url_for("help_links.page", token=token))
    waited = time.time() - (row["checked_at"] or 0)
    if waited < CHECK_EVERY:
        flash(f"Checked a moment ago: try again in {int(CHECK_EVERY - waited) + 1} seconds.", "wait")
        return redirect(url_for("help_links.page", token=token))
    db = get_db()
    db.execute("UPDATE help_links SET checked_at = ? WHERE id = ?", (time.time(), row["id"]))
    db.commit()
    still = domains.check_now(domain, request.host)
    if still is None:
        db.execute("UPDATE help_links SET authenticated_at = ? WHERE id = ?", (time.time(), row["id"]))
        db.commit()
        session["help_celebrate"] = row["id"]   # the page celebrates, once
    else:
        flash(still, "not-authenticated")
    return redirect(url_for("help_links.page", token=token))
