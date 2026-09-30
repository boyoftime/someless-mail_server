"""The webmail: a site of its own on port 17090 (the supervisor runs it beside the panel; Nginx
Proxy Manager can put webmail.example.com in front of it), made to work and look like PrivateEmail
(docs/superpowers/plans/2026-09-28-webmail-full.md). A mailbox logs in with its address and
password, on a page that looks like the panel's login, checked here against the hash the panel
keeps: never through the mail engine, which would ban 127.0.0.1 after a few wrong passwords. So
many wrong passwords in a row lock an address for a while (Settings > Miscellaneous,
webmail_lock.py). A login link can fill the address in (/login?email=..., shared from the
Mailboxes page). The mail itself comes from the engine (mail.py, jmap.py).

Its session cookie has its own name and its own key: browsers share cookies between ports of
the same host, and the admin's login mustn't be a mailbox's, or the other way round."""
import functools
import os
import re
import secrets
import time
from pathlib import Path

from flask import Flask, g, redirect, render_template, request, session, url_for
from markupsafe import Markup, escape
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError, generate_csrf
from werkzeug.middleware.proxy_fix import ProxyFix

from .. import (DEFAULT_THEME, FLOAT_ICONS, STATIC_CACHE_SECONDS, THEMES, VERSION, db, fingerprint_static_links,
                mail_password, webmail_lock, webmail_site)
from ..db import get_db
from . import accounts

WRONG ="The email or password is wrong."
LEFT_OPEN = "This page was open for a long time. Log in again."
# checked when the address isn't a mailbox, so a wrong address takes as long as a wrong password
_DUMMY_HASH = mail_password.hash_password(secrets.token_hex(16))


def _load_secret_key(data_dir):
    path = data_dir / "webmail_secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def _locked(email):
    if not webmail_lock.is_on():   # (switched off in Settings > Miscellaneous)
        return False
    row = get_db().execute("SELECT locked_until FROM webmail_tries WHERE email = ?", (email,)).fetchone()
    return bool(row and row["locked_until"] and row["locked_until"] > time.time())


def _wrong_try(email):
    """One more wrong password in a row; the last one allowed locks the address (and starts the
    count again). With the lock off, nothing is counted."""
    if not webmail_lock.is_on():
        return
    tries, minutes = webmail_lock.settings()
    database = get_db()
    database.execute("INSERT INTO webmail_tries (email) VALUES (?) ON CONFLICT (email) DO NOTHING", (email,))
    database.execute("UPDATE webmail_tries SET failures = failures + 1 WHERE email = ?", (email,))
    database.execute("UPDATE webmail_tries SET failures = 0, locked_until = ? WHERE email = ? AND failures >= ?",
                     (time.time() + minutes * 60, email, tries))
    database.commit()


def _forget_tries(email):
    database = get_db()
    database.execute("DELETE FROM webmail_tries WHERE email = ?", (email,))
    database.commit()


def _load_mailbox():
    """The mailbox this request is for: the one signed in with, while its password is the one it
    signed in with, or one on its list (accounts.py): the tab's own (/u/<id>/...), else the one
    used last. g.mailbox is it; g.owner the one signed in with; g.accounts all of them."""
    g.mailbox, g.owner, g.accounts, g.account_gone = None, None, [], False
    if request.endpoint in ("static", "healthz"):
        return
    mailbox_id = session.get("mailbox_id")
    if mailbox_id is None:
        return
    row = get_db().execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
    if row is None or row["password_version"] != session.get("password_version"):
        session.clear()   # deleted, or its password changed: log in again
        return
    g.owner = row
    g.accounts = [row, *accounts.linked(row["id"])]
    by_id = {one["id"]: one for one in g.accounts}
    asked = request.environ.get("someless.account")
    if asked is not None and asked not in by_id:
        g.account_gone = True   # (taken off the list, or its password changed, since the tab opened)
        return
    wanted = asked if asked is not None else session.get("current")
    g.mailbox = by_id.get(wanted, row)
    if asked is not None and request.method == "GET" and request.accept_mimetypes.best == "text/html":
        session["current"] = asked   # (a page opened on it: plain addresses open it next)


def _keep_account_in_address():
    """With more than one account, a page opened at a plain address (a bookmark, a new tab) goes
    to its account's own address, so the tab keeps it whatever the others switch to."""
    if (g.mailbox is None or len(g.accounts) < 2 or "someless.account" in request.environ or request.method != "GET"
            or request.endpoint in (None, "static", "healthz", "login", "logout", "enter")
            or (request.blueprint or "") == "dav" or request.headers.get("Upgrade", "").lower() == "websocket"):
        return None
    query = request.query_string.decode("utf-8", "replace")
    return redirect(accounts.home(g.mailbox["id"]).rstrip("/") + request.path + (f"?{query}" if query else ""))


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.mailbox is None:
            # an account no longer on the list: to the webmail's own address, the account used last
            login = "/" if g.account_gone else url_for("login")
            if request.method != "GET" or request.accept_mimetypes.best == "application/json":
                return {"problem": "Log in again.", "login": login}, 401
            return redirect(login)
        return view(**kwargs)
    return wrapped


def _signed_in(row):
    from .settings import remember_login
    session.clear()
    session["mailbox_id"] = row["id"]
    session["password_version"] = row["password_version"]
    remember_login(row["id"])   # (Settings > Security lists them)
    return redirect(url_for("mail.home"))


def _added(row):
    """Add another account: the mailbox put on the list of the one signed in with (at most
    accounts.MOST), and in sight, in its own address. One on the list already: in sight."""
    from .settings import remember_login
    if row["id"] not in {one["id"] for one in g.accounts}:
        if len(g.accounts) >= accounts.MOST:
            return render_template("webmail-login.html", email=row["email"], adding=True, problem=(
                f"You can keep up to {accounts.MOST} accounts here. Take one off the list first, in the account menu.")), 400
        accounts.add(g.owner["id"], row)
    remember_login(row["id"])
    session["current"] = row["id"]
    return redirect(accounts.home(row["id"]))


def login():
    adding = g.mailbox is not None and request.values.get("add") == "1"   # (Add another account)
    if g.mailbox is not None and not adding:
        return redirect(url_for("mail.home"))
    if request.method == "GET":   # a shared link can fill the address in; a new password says so
        return render_template("webmail-login.html", email=request.args.get("email", "").strip().lower()[:254],
                               notice=session.pop("notice", None), adding=adding)
    email = request.form.get("email", "").strip().lower()[:254]
    password = request.form.get("password", "")
    if _locked(email):
        wait = webmail_lock.describe(webmail_lock.settings()[1])
        return render_template("webmail-login.html", email=email, adding=adding, problem=(
            f"Too many tries with a wrong password. Wait {wait}, then try again.")), 429
    row = get_db().execute("SELECT * FROM mailboxes WHERE email = ?", (email,)).fetchone()
    right = mail_password.password_ok(row["password_hash"] if row else _DUMMY_HASH, password)
    if not (row and right):
        if email:
            _wrong_try(email)
        return render_template("webmail-login.html", email=email, adding=adding, problem=WRONG), 400
    _forget_tries(email)
    return _added(row) if adding else _signed_in(row)


def enter():
    """Opened from the panel's Mailboxes page: its one-time ticket signs the mailbox in, and the
    address bar loses the ticket at once."""
    mailbox_id = webmail_site.take_ticket(request.args.get("ticket", ""))
    row = mailbox_id and get_db().execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
    if not row:
        return render_template("webmail-login.html", email="", problem=(
            "This link to the webmail was used already, or is too old. Open the webmail from the Mailboxes page "
            "again, or log in with the mailbox's password.")), 400
    return _signed_in(row)


def logout():
    session.clear()
    return redirect(url_for("login"))


def healthz():
    return "ok"


def highlight(text, query):
    """The words searched for, in bold (the search panel, webmail-search.html)."""
    words = sorted({word for word in (query or "").split() if word}, key=len, reverse=True)
    if not words or not text:
        return text
    parts = re.split("(" + "|".join(re.escape(word) for word in words) + ")", str(text), flags=re.I)
    return Markup("".join(f"<b>{escape(part)}</b>" if index % 2 else str(escape(part)) for index, part in enumerate(parts)))


def page_left_open(error):
    """A form's token not taken (its sign-in's token lasts as long as the sign-in, however long a
    page stays open; it goes with a new sign-in): signing in asks again, on the webmail's own page;
    logging out just logs out; the mail's own scripts get a fresh token, and go again with it at
    once (webmail-core.js), so nobody is stopped."""
    if request.endpoint == "logout":
        return logout()
    if request.endpoint != "login":
        return {"problem": "This page was open for a long time. Reload it and try again.", "csrf": True,
                "token": generate_csrf()}, 400
    return render_template("webmail-login.html", email=request.form.get("email", "").strip().lower()[:254],
                           problem=LEFT_OPEN), 400


def create_webmail_app(test_config=None):
    # (the package's folder is webmail/; its templates and static files are the panel's)
    app = Flask(__name__, root_path=str(Path(__file__).resolve().parent.parent))
    app.config.from_mapping(
        DATA_DIR=os.environ.get("SOMELESS_DATA_DIR", "/data/someless"),
        SESSION_COOKIE_NAME="someless_webmail",
        SESSION_COOKIE_SAMESITE="Lax",
        SEND_FILE_MAX_AGE_DEFAULT=STATIC_CACHE_SECONDS,
        MAX_CONTENT_LENGTH=30 * 1024 * 1024,   # the biggest request: attachments on their way (compose)
        WTF_CSRF_TIME_LIMIT=None,   # a page's token lasts as long as the sign-in: left open for hours, it still sends
        ENGINE_ENABLED=os.environ.get("SOMELESS_ENGINE") == "1",   # (a new password goes to the engine)
    )
    if test_config:
        app.config.update(test_config)
    data_dir = Path(app.config["DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    app.config["SECRET_KEY"] = _load_secret_key(data_dir)
    app.wsgi_app = accounts.AccountPaths(ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1))   # (/u/<id>/...)
    csrf = CSRFProtect(app)
    db.init_app(app)
    fingerprint_static_links(app)

    from . import calendar, compose, contacts, dav, mail, settings
    from .live import sock
    app.before_request(_load_mailbox)
    app.before_request(_keep_account_in_address)
    app.jinja_env.globals["account_card"] = accounts.card   # (the account card's list: webmail-top.html)
    app.add_url_rule("/login", "login", login, methods=["GET", "POST"])
    app.add_url_rule("/logout", "logout", logout, methods=["POST"])
    app.add_url_rule("/enter", "enter", enter)
    app.add_url_rule("/healthz", "healthz", healthz)
    app.register_blueprint(mail.bp)
    app.register_blueprint(compose.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(contacts.bp)
    app.register_blueprint(calendar.bp)
    app.register_blueprint(dav.bp)
    app.register_blueprint(accounts.bp)
    csrf.exempt(dav.bp)   # (calendar and contacts apps sign in with a password, and have no page to carry a token)
    sock.init_app(app)
    app.register_error_handler(CSRFError, page_left_open)
    app.add_template_filter(highlight, "highlight")

    @app.after_request
    def not_in_frames(response):
        # nobody wraps the webmail in their page; the reading pane's own frame is the page's
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        return response

    @app.context_processor
    def inject_globals():
        theme = request.cookies.get("theme")
        return {"version": VERSION, "theme": theme if theme in THEMES else DEFAULT_THEME, "float_icons": FLOAT_ICONS}

    return app
