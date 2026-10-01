"""Disabling a sender and its mailbox: they share an address, so they're disabled and enabled
together, from either one (the Senders and Mailboxes pages, the API). A disabled sender can't be
sent as (the engine's send-as rule leaves it out); a disabled mailbox can't be signed in to (the
engine refuses mail apps; the webmail and calendar apps refuse it themselves), and, with Refuse new
mail, takes none: it bounces (engine/sync.py). Enabled again, both work as before, mail and all."""
from .db import get_db
from .engine import sync as engine_sync

NOTICE = "This mailbox is disabled. Ask the person who looks after your mail server."


def set_disabled(email, disabled, refuse_mail=False):
    """The sender and the mailbox at this address, disabled or enabled. refuse_mail: while disabled,
    new mail to the mailbox bounces (enabling stops that too)."""
    db = get_db()
    db.execute("UPDATE senders SET disabled = ? WHERE lower(email) = lower(?)", (int(disabled), email))
    db.execute("UPDATE mailboxes SET disabled = ?, refuse_mail = ? WHERE email = lower(?)",
               (int(disabled), int(bool(disabled and refuse_mail)), email))
    db.commit()
    engine_sync.after_change()


def sender_disabled(email):
    row = get_db().execute("SELECT disabled FROM senders WHERE lower(email) = lower(?)", (email,)).fetchone()
    return bool(row and row["disabled"])


def disabled_problem(email):
    """Why nothing new can be done with this address (a mailbox made for it), or None."""
    if sender_disabled(email):
        return f"{email} is disabled. Enable it on the Senders page first."
    return None
