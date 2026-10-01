"""More than one mailbox in the webmail, as Gmail has it. Each mailbox keeps its own list of the
others added to it (Add another account: signing in to each, once); the account card lists them,
the one in sight with a tick, and a tap switches to another. Signing in to one of those itself
shows only its own list. A mailbox whose password changed since it was added, or that's gone,
drops off by itself. A list holds MOST, its own mailbox included.

Each tab keeps the account it shows in its address, /u/<id>/... (AccountPaths): Flask makes every
link on the page with it, so what another tab switches to never changes what this one shows. A
plain address (a bookmark, a new tab) opens the account used last (the session's "current").
  /accounts/unread                    each account's unread mail, for the card
  /accounts/<id>/remove               one taken off the list"""
import re
import time

from flask import Blueprint, current_app, g, session

from .. import engine
from ..db import get_db
from .jmap import Jmap, MailError, MailUnavailable

MOST = 5   # accounts on one list, its own mailbox included
PATH = re.compile(r"^/u/(\d{1,9})(/.*)?$")

bp = Blueprint("accounts", __name__, url_prefix="/accounts")


class AccountPaths:
    """/u/<id>/... is the webmail as it is, for that account: its id is noted for the request
    (someless.account) and the rest of the address is the page. With the prefix as the app's own
    root (SCRIPT_NAME), every address Flask makes for the page carries it too."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        found = PATH.match(environ.get("PATH_INFO") or "")
        if found:
            environ["someless.account"] = int(found.group(1))
            environ["SCRIPT_NAME"] = (environ.get("SCRIPT_NAME") or "") + f"/u/{found.group(1)}"
            environ["PATH_INFO"] = found.group(2) or "/"
        return self.app(environ, start_response)


def home(mailbox_id):
    """An account's own address in the webmail."""
    return f"/u/{mailbox_id}/"


def linked(owner_id):
    """The mailboxes on a mailbox's list, as they were added, while each still has the password it
    was added with, and isn't disabled (disabling.py)."""
    return get_db().execute(
        "SELECT mailboxes.* FROM webmail_accounts JOIN mailboxes ON mailboxes.id = webmail_accounts.mailbox_id"
        " WHERE webmail_accounts.owner_id = ? AND mailboxes.password_version = webmail_accounts.password_version"
        " AND mailboxes.disabled = 0"
        " ORDER BY webmail_accounts.added_at, webmail_accounts.id", (owner_id,)).fetchall()


def add(owner_id, row):
    """A mailbox put on a list (its password just given): again, with its password now."""
    database = get_db()
    database.execute("INSERT INTO webmail_accounts (owner_id, mailbox_id, password_version, added_at) VALUES (?, ?, ?, ?)"
                     " ON CONFLICT (owner_id, mailbox_id) DO UPDATE SET password_version = excluded.password_version",
                     (owner_id, row["id"], row["password_version"], time.time()))
    database.commit()


def keep(owner_id, mailbox_id, version):
    """A mailbox on the list given a new password from within it: it stays on the list."""
    database = get_db()
    database.execute("UPDATE webmail_accounts SET password_version = ? WHERE owner_id = ? AND mailbox_id = ?",
                     (version, owner_id, mailbox_id))
    database.commit()


def name_of(row):
    """The name a mailbox goes by: its own (Settings), its sender's, else what's before the @."""
    from . import views
    name = views.display_name(row["id"])
    if not name:
        sender = get_db().execute("SELECT name FROM senders WHERE lower(email) = ?", (row["email"],)).fetchone()
        name = sender["name"] if sender else ""
    return name or row["email"].partition("@")[0]


def card():
    """The accounts on the account card (a template global): the one signed in with first, then
    the ones it added; the one in sight is active."""
    from .messages import hue
    if g.get("mailbox") is None:
        return []
    shown = []
    for row in g.accounts:
        name = name_of(row)
        shown.append({"id": row["id"], "email": row["email"], "name": name, "initial": name[:1].upper(), "hue": hue(row["email"]),
                      "url": home(row["id"]), "active": row["id"] == g.mailbox["id"], "own": row["id"] == g.owner["id"]})
    return shown


def _mail_of(email):
    factory = current_app.config.get("JMAP")
    if factory:
        return factory(email)
    return Jmap(email, engine.secret("webmail_password"), current_app.config.get("ENGINE_URL", engine.API_URL))


def _unread(email):
    try:
        found = _mail_of(email).call(("Mailbox/get", {"properties": ["role", "unreadEmails"]}))[0]["list"]
    except (MailError, MailUnavailable, OSError):
        return None
    return next((box.get("unreadEmails") or 0 for box in found if box.get("role") == "inbox"), 0)


def _signed_in():
    if g.get("mailbox") is None:
        return {"problem": "Log in again.", "login": "/"}, 401
    return None


@bp.get("/unread")
def unread():
    """Each account's unread mail in its Inbox, for the card: {id: count} (one the engine didn't
    answer for is left out)."""
    refused = _signed_in()
    if refused:
        return refused
    counts = {}
    for row in g.accounts:
        count = _unread(row["email"])
        if count is not None:
            counts[str(row["id"])] = count
    return counts


@bp.post("/<int:mailbox_id>/remove")
def remove(mailbox_id):
    """One taken off the list of the mailbox signed in with (never that one itself)."""
    refused = _signed_in()
    if refused:
        return refused
    row = next((one for one in g.accounts if one["id"] == mailbox_id), None)
    if row is None or mailbox_id == g.owner["id"]:
        return {"problem": "That account can't be taken off this list."}, 400
    database = get_db()
    database.execute("DELETE FROM webmail_accounts WHERE owner_id = ? AND mailbox_id = ?", (g.owner["id"], mailbox_id))
    database.commit()
    if session.get("current") == mailbox_id:
        session["current"] = g.owner["id"]
    return {"message": f"{row['email']} was taken off this list.",
            "url": home(g.owner["id"]) if g.mailbox["id"] == mailbox_id else None}
