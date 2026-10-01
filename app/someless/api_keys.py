"""API keys (the API keys page): the keys apps use with the API (api.py) to manage the senders
and mailboxes. A key is shown once, when it's made: only its SHA-256 fingerprint is kept, so a
lost key can't be read back, only replaced. Each lasts as long as chosen, like the SMTP keys
(smtp.py), and says when it was last used. The guide (/api-keys/docs) explains every call."""
import secrets
import time

from flask import Blueprint, flash, make_response, redirect, render_template, request, url_for

from . import api_guide
from .auth import login_required
from .db import get_db
from .smtp import DEFAULT_EXPIRY, EXPIRIES, KEY_CHARACTERS, NAME_LIMIT, _date, _expires_at, _moment, fingerprint

bp = Blueprint("api_keys", __name__, url_prefix="/api-keys")

PREFIX = "sm_"   # so a key is easy to tell from other secrets (and to find, if it's ever pasted somewhere it shouldn't be)
LENGTH = 48


def base_url():
    """Where the API is: this panel's own address."""
    return request.url_root.rstrip("/") + "/api/s1"


def _page(status=200, typed=None, **context):
    # Every key is on the page; the ones the search doesn't match are hidden (smtp-page.js filters as you type)
    now = time.time()
    query = request.args.get("q", "").strip()
    keys = [
        {"id": row["id"], "name": row["name"], "hint": row["hint"],
         "created": _date(row["created_at"]), "created_at": _moment(row["created_at"]),
         "expires": _date(row["expires_at"]) if row["expires_at"] is not None else None,
         "expires_at": _moment(row["expires_at"]) if row["expires_at"] is not None else None,
         "used": _date(row["last_used_at"]) if row["last_used_at"] else None,
         "used_at": _moment(row["last_used_at"]) if row["last_used_at"] else None,
         "expired": row["expires_at"] is not None and row["expires_at"] <= now,
         "shown": query.lower() in row["name"].lower()}
        for row in get_db().execute("SELECT * FROM api_keys ORDER BY created_at DESC, id DESC")
    ]
    expiries = [{"value": value, "label": label, "days": days, "months": months,
                 "until": None if days is None else _date(_expires_at(value, now))}
                for value, label, days, months in EXPIRIES]
    return render_template("api-keys.html", keys=keys, query=query, expiries=expiries, base=base_url(),
                           typed=typed or {"name": "", "expiry": DEFAULT_EXPIRY}, **context), status


@bp.get("")
@login_required
def index():
    return _page()


@bp.post("")
@login_required
def create():
    """A new key: shown in the page that comes back, and never again."""
    typed = {"name": request.form.get("name", "").strip(), "expiry": request.form.get("expiry", "")}
    db = get_db()
    problem = None
    if not typed["name"]:
        problem = "Give the key a name, like the app that will use it."
    elif len(typed["name"]) > NAME_LIMIT:
        problem = f"Keep the name to {NAME_LIMIT} characters or fewer."
    elif typed["expiry"] not in [value for value, *_ in EXPIRIES]:
        problem = "Choose when the key expires."
    elif db.execute("SELECT 1 FROM api_keys WHERE lower(name) = lower(?)", (typed["name"],)).fetchone():
        problem = f"There's already a key named {typed['name']}. Give this one another name."
    if problem:
        return _page(400, typed=typed, generate_error=problem)
    key = PREFIX + "".join(secrets.choice(KEY_CHARACTERS) for _ in range(LENGTH))
    now = time.time()
    db.execute("INSERT INTO api_keys (name, key_hash, hint, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
               (typed["name"], fingerprint(key), key[-4:], now, _expires_at(typed["expiry"], now)))
    db.commit()
    response = make_response(_page(new_key=key, new_name=typed["name"]))
    response.headers["Cache-Control"] = "no-store"   # the key is in it: nothing keeps a copy
    return response


@bp.post("/<int:key_id>/delete")
@login_required
def delete(key_id):
    db = get_db()
    key = db.execute("SELECT name FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    if key:
        db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        db.commit()
        flash(f"{key['name']} was deleted.", "deleted")
    return redirect(url_for("api_keys.index"))


@bp.get("/docs")
@login_required
def docs():
    """The guide: every call beside its request (in four languages) and its response, as in Postman."""
    domain = get_db().execute("SELECT name FROM domains ORDER BY authenticated DESC, name LIMIT 1").fetchone()
    domain = domain["name"] if domain else "yourdomain.com"
    return render_template("api-docs.html", base=base_url(), groups=api_guide.calls(base_url(), domain),
                           ai_link=url_for("api.docs_text", _external=True), ai_text=api_guide.as_text(base_url()))
