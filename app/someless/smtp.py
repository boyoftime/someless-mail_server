"""SMTP (the SMTP & API page): how apps and websites send mail through this server. Each of
the admin's SMTP keys has its own login (logins.py), and the key is its password. A key is
shown once, when it's made: only its SHA-256 fingerprint is kept, so a lost key can't be read
back, only replaced. The mail engine gets each key's login and fingerprint (engine/sync.py);
the checklist at the top says whether it's ready to send (engine/checks.py)."""
import calendar
import datetime
import hashlib
import secrets
import string
import time

from flask import Blueprint, flash, make_response, redirect, render_template, request, url_for

from . import domain_records, engine, smtp_guide
from .auth import login_required
from .db import get_db
from .engine import checks, names
from .engine import sync as engine_sync
from .logins import make_login

bp = Blueprint("smtp", __name__, url_prefix="/smtp")

PORT = 587  # where mail apps send (SMTP submission, with STARTTLS)
VARIANTS = {"standard": 64, "short": 15}  # a key's length
KEY_CHARACTERS = string.ascii_letters + string.digits  # nothing that trips up copying or typing
# How long a key lasts: value, label, and days or calendar months
EXPIRIES = [("7d", "7 days", 7, 0), ("14d", "14 days", 14, 0), ("1m", "1 month", 0, 1),
            ("3m", "3 months", 0, 3), ("6m", "6 months", 0, 6), ("1y", "1 year", 0, 12),
            ("never", "No expiration", None, None)]
DEFAULT_EXPIRY = "1y"
NAME_LIMIT = 60


def fingerprint(key):
    return hashlib.sha256(key.encode()).hexdigest()


def key_works(key):
    """Whether a key is one of the SMTP keys, and hasn't expired."""
    row = get_db().execute("SELECT expires_at FROM smtp_keys WHERE key_hash = ?", (fingerprint(key),)).fetchone()
    return row is not None and (row["expires_at"] is None or row["expires_at"] > time.time())


def _after(start, days, months):
    """start (a datetime) moved on by days, or by calendar months (Jan 31 + 1 month: Feb 28)."""
    if not months:
        return start + datetime.timedelta(days=days)
    month = start.month - 1 + months
    year, month = start.year + month // 12, month % 12 + 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


def _date(when):
    """A date as the server sees it: what shows until local-time.js puts it in the admin's time zone."""
    moment = datetime.datetime.fromtimestamp(when)
    return f"{moment:%b} {moment.day}, {moment.year}"


def _moment(when):
    """The moment itself, for <time datetime>, which local-time.js reads."""
    return datetime.datetime.fromtimestamp(when, datetime.timezone.utc).isoformat(timespec="seconds")


def _expires_at(expiry, now):
    for value, _, days, months in EXPIRIES:
        if value == expiry:
            return None if days is None else _after(datetime.datetime.fromtimestamp(now), days, months).timestamp()
    raise ValueError(expiry)


def _server_name():
    """The name mail apps reach this server by: the server name (engine/names.py, the one its
    certificate is for), else the address the panel was opened at."""
    name = names.server_name()
    if name:
        return name
    host = request.host
    return host[:host.index("]") + 1] if host.startswith("[") else host.rsplit(":", 1)[0]


def _page(status=200, typed=None, **context):
    # Every key is on the page; the ones the search doesn't match are hidden, so typing in
    # the search box can filter the whole list on the spot (smtp-page.js).
    now = time.time()
    query = request.args.get("q", "").strip()
    db = get_db()
    keys = [
        {"id": row["id"], "name": row["name"], "hint": row["hint"], "variant": row["variant"],
         "created": _date(row["created_at"]), "created_at": _moment(row["created_at"]),
         "expires": _date(row["expires_at"]) if row["expires_at"] is not None else None,
         "expires_at": _moment(row["expires_at"]) if row["expires_at"] is not None else None,
         "expired": row["expires_at"] is not None and row["expires_at"] <= now,
         "login": row["login"], "shown": query.lower() in row["name"].lower()}
        for row in db.execute("SELECT * FROM smtp_keys ORDER BY created_at DESC, id DESC")
    ]
    expiries = [{"value": value, "label": label, "days": days, "months": months,
                 "until": None if days is None else _date(_expires_at(value, now))}
                for value, label, days, months in EXPIRIES]
    found = checks.run_checks(domain_records.server_address(request.host))
    return render_template(
        "smtp.html", keys=keys, query=query, server=_server_name(), port=PORT, expiries=expiries,
        checks=found, can_send=checks.can_send(found), server_names=names.server_names(), server_name=names.server_name(),
        engine_error=engine.state()["sync_error"] if engine.enabled() else None,
        typed=typed or {"name": "", "variant": "standard", "expiry": DEFAULT_EXPIRY}, **context,
    ), status


@bp.get("")
@login_required
def index():
    return _page()


@bp.post("")
@login_required
def generate():
    """A new key: shown in the page that comes back, and never again."""
    typed = {"name": request.form.get("name", "").strip(), "variant": request.form.get("variant", ""),
             "expiry": request.form.get("expiry", "")}
    db = get_db()
    problem = None
    if not typed["name"]:
        problem = "Give the key a name, like the app or website that will use it."
    elif len(typed["name"]) > NAME_LIMIT:
        problem = f"Keep the name to {NAME_LIMIT} characters or fewer."
    elif typed["variant"] not in VARIANTS:
        problem = "Choose Standard or Short."
    elif typed["expiry"] not in [value for value, *_ in EXPIRIES]:
        problem = "Choose when the key expires."
    elif db.execute("SELECT 1 FROM smtp_keys WHERE lower(name) = lower(?)", (typed["name"],)).fetchone():
        problem = f"There's already a key named {typed['name']}. Give this one another name."
    if problem:
        return _page(400, typed=typed, generate_error=problem)
    key = "".join(secrets.choice(KEY_CHARACTERS) for _ in range(VARIANTS[typed["variant"]]))
    now = time.time()
    login = make_login(typed["name"], {row[0] for row in db.execute("SELECT login FROM smtp_keys")})
    db.execute("INSERT INTO smtp_keys (name, key_hash, hint, variant, created_at, expires_at, login) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (typed["name"], fingerprint(key), key[-4:], typed["variant"], now, _expires_at(typed["expiry"], now), login))
    db.commit()
    engine_sync.after_change()
    response = make_response(_page(new_key=key, new_name=typed["name"], new_login=login))
    response.headers["Cache-Control"] = "no-store"  # the key is in it: nothing keeps a copy
    return response


@bp.post("/server-name")
@login_required
def choose_server_name():
    chosen = request.form.get("server_name", "")
    if chosen in names.server_names():
        engine.remember(server_name=chosen)
        engine_sync.after_change()
        flash(f"The server is {chosen} now.", "success")
    return redirect(url_for("smtp.index"))


@bp.post("/checks")
@login_required
def check_again():
    checks.forget()
    engine_sync.ask_for_certificate()   # the proxy host may be there now (README, Step 5)
    return redirect(url_for("smtp.index"))


@bp.get("/docs")
@login_required
def docs():
    """The guide: sending through this server from code, in six languages."""
    db = get_db()
    # the examples send from one of the admin's domains: an authenticated one if there is one
    domain = db.execute("SELECT name FROM domains ORDER BY authenticated DESC, name LIMIT 1").fetchone()
    sender = f"hello@{domain['name'] if domain else 'yourdomain.com'}"
    return render_template("smtp-docs.html", server=_server_name(), port=PORT,
                           examples=smtp_guide.examples(_server_name(), PORT, sender))


@bp.post("/<int:key_id>/delete")
@login_required
def delete(key_id):
    db = get_db()
    key = db.execute("SELECT name FROM smtp_keys WHERE id = ?", (key_id,)).fetchone()
    if key:
        db.execute("DELETE FROM smtp_keys WHERE id = ?", (key_id,))
        db.commit()
        engine_sync.after_change()
        flash(f"{key['name']} was deleted.", "deleted")
    return redirect(url_for("smtp.index"))
