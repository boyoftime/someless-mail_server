"""The webmail: a little site of its own on port 17090 (the supervisor runs it beside the panel;
Nginx Proxy Manager can put webmail.example.com in front of it). A mailbox logs in with its
address and password, on a page that looks like the panel's login, checked here against the
hash the panel keeps: never through the mail engine, which would ban 127.0.0.1 after a few wrong
passwords. So many wrong passwords in a row lock an address for a while (Settings >
Miscellaneous, webmail_lock.py). A login link can fill the address in (/login?email=..., shared
from the Mailboxes page). The inbox itself is coming soon: its design shows with made-up mail
where the webmail runs with SOMELESS_WEBMAIL_PREVIEW=1 (webmail_sample.py). Its list opens with
the newest MAIL_PAGE messages, and brings the next ones as it's scrolled down (/messages); a
message opens in the reading pane, with a link of its own (/message/<id>).

Its session cookie has its own name and its own key: browsers share cookies between ports of
the same host, and the admin's login mustn't be a mailbox's, or the other way round."""
import functools
import os
import secrets
import time
from pathlib import Path

from flask import (Flask, abort, current_app, g, get_template_attribute, redirect, render_template, request,
                   session, url_for)
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from . import (DEFAULT_THEME, FLOAT_ICONS, STATIC_CACHE_SECONDS, THEMES, VERSION, db, fingerprint_static_links,
               mail_password, webmail_lock, webmail_sample, webmail_site)
from .db import get_db
from .domain_records import HOST_CHOICES
from .engine import names
from .mailboxes import size_text

WRONG = "The email or password is wrong."
MAIL_PAGE = 50   # messages at a time: the newest with the page, then more as the list is scrolled down
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
    row = get_db().execute("SELECT locked_until FROM webmail_tries WHERE email = ?", (email,)).fetchone()
    return bool(row and row["locked_until"] and row["locked_until"] > time.time())


def _wrong_try(email):
    """One more wrong password in a row; the last one allowed locks the address (and starts the
    count again)."""
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
    """The logged-in mailbox, while its password is the one it logged in with."""
    g.mailbox = None
    if request.endpoint in ("static", "healthz"):
        return
    mailbox_id = session.get("mailbox_id")
    if mailbox_id is None:
        return
    row = get_db().execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
    if row is None or row["password_version"] != session.get("password_version"):
        session.clear()   # deleted, or its password changed: log in again
        return
    g.mailbox = row


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.mailbox is None:
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped


def login():
    if g.mailbox is not None:
        return redirect(url_for("inbox"))
    if request.method == "GET":   # a shared link can fill the address in
        return render_template("webmail-login.html", email=request.args.get("email", "").strip().lower()[:254])
    email = request.form.get("email", "").strip().lower()[:254]
    password = request.form.get("password", "")
    if _locked(email):
        wait = webmail_lock.describe(webmail_lock.settings()[1])
        return render_template("webmail-login.html", email=email, problem=(
            f"Too many tries with a wrong password. Wait {wait}, then try again.")), 429
    row = get_db().execute("SELECT * FROM mailboxes WHERE email = ?", (email,)).fetchone()
    right = mail_password.password_ok(row["password_hash"] if row else _DUMMY_HASH, password)
    if not (row and right):
        if email:
            _wrong_try(email)
        return render_template("webmail-login.html", email=email, problem=WRONG), 400
    _forget_tries(email)
    session.clear()
    session["mailbox_id"] = row["id"]
    session["password_version"] = row["password_version"]
    return redirect(url_for("inbox"))


def enter():
    """Opened from the panel's Mailboxes page: its one-time ticket signs the mailbox in, and the
    address bar loses the ticket at once."""
    mailbox_id = webmail_site.take_ticket(request.args.get("ticket", ""))
    row = mailbox_id and get_db().execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
    if not row:
        return render_template("webmail-login.html", email="", problem=(
            "This link to the webmail was used already, or is too old. Open the webmail from the Mailboxes page "
            "again, or log in with the mailbox's password.")), 400
    session.clear()
    session["mailbox_id"] = row["id"]
    session["password_version"] = row["password_version"]
    return redirect(url_for("inbox"))


def logout():
    session.clear()
    return redirect(url_for("login"))


@login_required
def inbox():
    email = g.mailbox["email"]
    if not current_app.config["INBOX_PREVIEW"]:
        server = names.server_name() or f"{HOST_CHOICES[0]}.{email.rpartition('@')[2]}"
        return render_template("webmail-inbox.html", email=email, server=server)
    return _mailbox_page()


def _mailbox_page(open_message=None):
    """The inbox's design, with made-up mail, until it reads the real mail: the folders, the
    newest mail and the reading pane, with that message open in it (and its row picked out)."""
    email = g.mailbox["email"]
    sender = get_db().execute("SELECT name FROM senders WHERE lower(email) = ?", (email,)).fetchone()
    name = sender["name"] if sender else email.partition("@")[0]
    quota = g.mailbox["quota_bytes"]
    used = int(quota * webmail_sample.USED_SHARE)
    counts = {**webmail_sample.COUNTS, "inbox": _unread()}
    folders = [{"key": key, "label": label, "icon": icon, "count": counts.get(key)}
               for key, label, icon in webmail_sample.FOLDERS]
    storage = {"used": size_text(used), "quota": size_text(quota),
               "percent": f"{webmail_sample.USED_SHARE * 100:.1f}".rstrip("0").rstrip(".")}
    page, next_url = _mail_page()
    return render_template("webmail-mail.html", email=email, name=name, initial=name[:1].upper(),
                           folders=folders, messages=page, next_url=next_url, storage=storage, columns=_columns(),
                           open_message=open_message, body_doc=_body(open_message) if open_message else None)


def _columns():
    """The widths the folders and the mail were dragged to (webmail-resize.js keeps them in the
    wm_columns cookie), for the page to come with them: CSS, or None to start as it does."""
    parts = request.cookies.get("wm_columns", "").split(",")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    side, mail = (int(part) for part in parts)
    if not (100 <= side <= 2000 and 100 <= mail <= 4000):   # webmail-app.css keeps them in their limits
        return None
    return f"--wm-side-width: {side}px; --wm-list-width: {mail}px"


# What's been read, for this session: the made-up mail stays as it is (the mail engine will keep
# this for real mail, on each message)
def _read():
    return set(session.get("preview_read", []))


def _as_read(messages):
    read = _read()
    return [{**message, "unread": False} if message["id"] in read else message for message in messages]


def _unread():
    read = _read()
    return sum(1 for message in webmail_sample.MESSAGES if message["unread"] and message["id"] not in read)


def _body(message):
    """What the message says, as a page of its own for the reading pane's frame (webmail-body.html)."""
    return render_template("webmail-body.html", blocks=message["body"])


@login_required
def message(message_id):
    """A message, open in the reading pane: on the whole page (its link, a refresh), or just the
    pane for webmail-read.js, {"html", "subject", "unread"}. Opening it marks it read."""
    if not current_app.config["INBOX_PREVIEW"]:
        abort(404)   # no mail to show yet
    found = webmail_sample.BY_ID.get(message_id)
    if found is None:
        abort(404)
    if found["unread"] and message_id not in _read():
        session["preview_read"] = [*session.get("preview_read", []), message_id]
    found = {**found, "unread": False}
    if request.accept_mimetypes.best == "application/json":
        view = get_template_attribute("webmail-read.html", "message_view")
        return {"html": str(view(found, g.mailbox["email"], _body(found))), "subject": found["subject"],
                "unread": _unread()}
    return _mailbox_page(found)


def _mail_page(after=None):
    """The next MAIL_PAGE messages, newest first: after the one with that id (from the start without
    one), and where the ones after them come from (None at the end). None for an id that isn't in
    the list. (The mail engine pages the same way: from a message on, by its id.)"""
    messages = webmail_sample.MESSAGES
    start = 0
    if after is not None:
        start = next((place + 1 for place, message in enumerate(messages) if message["id"] == after), None)
        if start is None:
            return None, None
    page = _as_read(messages[start:start + MAIL_PAGE])
    more = start + MAIL_PAGE < len(messages)
    return page, url_for("messages", after=page[-1]["id"]) if more else None


@login_required
def messages():
    """The next piece of the list, as the page shows it (webmail-list.js): {"html", "next"}."""
    if not current_app.config["INBOX_PREVIEW"]:
        abort(404)   # no mail to show yet
    page, next_url = _mail_page(request.args.get("after"))
    if page is None:
        abort(400)   # not a message in the list
    row = get_template_attribute("webmail-message.html", "message_row")
    return {"html": "".join(str(row(message, index, True)) for index, message in enumerate(page)), "next": next_url}


def healthz():
    return "ok"


def page_left_open(error):
    """A form's token runs out after an hour: signing in asks again, on the webmail's own page;
    logging out just logs out."""
    if request.endpoint == "logout":
        return logout()
    return render_template("webmail-login.html", email=request.form.get("email", "").strip().lower()[:254],
                           problem=LEFT_OPEN), 400


def create_webmail_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATA_DIR=os.environ.get("SOMELESS_DATA_DIR", "/data/someless"),
        SESSION_COOKIE_NAME="someless_webmail",
        SESSION_COOKIE_SAMESITE="Lax",
        SEND_FILE_MAX_AGE_DEFAULT=STATIC_CACHE_SECONDS,
        INBOX_PREVIEW=os.environ.get("SOMELESS_WEBMAIL_PREVIEW") == "1",   # the inbox's design, with made-up mail
    )
    if test_config:
        app.config.update(test_config)
    data_dir = Path(app.config["DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    app.config["SECRET_KEY"] = _load_secret_key(data_dir)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    CSRFProtect(app)
    db.init_app(app)
    fingerprint_static_links(app)

    app.before_request(_load_mailbox)
    app.add_url_rule("/login", "login", login, methods=["GET", "POST"])
    app.add_url_rule("/logout", "logout", logout, methods=["POST"])
    app.add_url_rule("/enter", "enter", enter)
    app.add_url_rule("/", "inbox", inbox)
    app.add_url_rule("/messages", "messages", messages)
    app.add_url_rule("/message/<message_id>", "message", message)
    app.add_url_rule("/healthz", "healthz", healthz)
    app.register_error_handler(CSRFError, page_left_open)

    @app.after_request
    def not_in_frames(response):
        response.headers.setdefault("X-Frame-Options", "DENY")   # nobody wraps the login in their page
        return response

    @app.context_processor
    def inject_globals():
        theme = request.cookies.get("theme")
        return {"version": VERSION, "theme": theme if theme in THEMES else DEFAULT_THEME, "float_icons": FLOAT_ICONS}

    return app
