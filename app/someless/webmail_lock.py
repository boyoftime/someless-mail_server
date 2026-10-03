"""The webmail's sign-in lock (Settings > Miscellaneous): after so many wrong passwords in a row,
an address waits so long before it can try again (webmail/__init__.py, the calendar and contacts
apps: webmail/dav.py, and apps checking a password through the API: api.py), wherever the wrong
ones came from. 5 and 5 minutes to start with. It can be switched off (then wrong passwords never
make anyone wait), and an address locked now can be let in at once."""
import functools
import secrets
import time

from . import mail_password
from .db import get_db


@functools.cache
def dummy_hash():
    """A hash to check a password against when there's no mailbox at the address: as long as a
    wrong password takes, so the time taken doesn't say whether there's one."""
    return mail_password.hash_password(secrets.token_hex(16))


def check(email, password):
    """A mailbox's address and password, checked as the webmail's login does: ("ok", the mailbox's
    row), ("wrong", None) whether the address or the password is, ("locked", None), or
    ("disabled", the row), said only to the right password."""
    if locked(email):
        return "locked", None
    row = get_db().execute("SELECT * FROM mailboxes WHERE email = ?", (email,)).fetchone()
    right = mail_password.password_ok(row["password_hash"] if row else dummy_hash(), password)
    if not (row and right):
        if email:
            wrong_try(email)
        return "wrong", None
    forget_tries(email)
    return ("disabled" if row["disabled"] else "ok"), row


def locked(email):
    if not is_on():
        return False
    row = get_db().execute("SELECT locked_until FROM webmail_tries WHERE email = ?", (email,)).fetchone()
    return bool(row and row["locked_until"] and row["locked_until"] > time.time())


def seconds_left(email):
    """How long a locked address still waits, in whole seconds (at least 1)."""
    row = get_db().execute("SELECT locked_until FROM webmail_tries WHERE email = ?", (email,)).fetchone()
    return max(1, int((row["locked_until"] if row and row["locked_until"] else 0) - time.time() + 0.999))


def wrong_try(email):
    """One more wrong password in a row; the last one allowed locks the address (and starts the
    count again). With the lock off, nothing is counted."""
    if not is_on():
        return
    tries, minutes = settings()
    database = get_db()
    database.execute("INSERT INTO webmail_tries (email) VALUES (?) ON CONFLICT (email) DO NOTHING", (email,))
    database.execute("UPDATE webmail_tries SET failures = failures + 1 WHERE email = ?", (email,))
    database.execute("UPDATE webmail_tries SET failures = 0, locked_until = ? WHERE email = ? AND failures >= ?",
                     (time.time() + minutes * 60, email, tries))
    database.commit()


def forget_tries(email):
    database = get_db()
    database.execute("DELETE FROM webmail_tries WHERE email = ?", (email,))
    database.commit()

MOST_TRIES = 20
LONGEST = 24 * 60   # minutes


def settings():
    """(tries, minutes)"""
    row = get_db().execute("SELECT tries, lock_minutes FROM webmail_lock WHERE id = 1").fetchone()
    return row["tries"], row["lock_minutes"]


def save(tries, minutes):
    db = get_db()
    db.execute("UPDATE webmail_lock SET tries = ?, lock_minutes = ? WHERE id = 1", (tries, minutes))
    db.commit()


def is_on():
    return bool(get_db().execute("SELECT lock_on FROM webmail_lock WHERE id = 1").fetchone()["lock_on"])


def switch(on):
    """On or off. Either way the wrong passwords so far are forgotten, so nobody is locked the
    moment it's switched on again for tries made while it was off (or before)."""
    db = get_db()
    if bool(on) != is_on():
        db.execute("DELETE FROM webmail_tries")
    db.execute("UPDATE webmail_lock SET lock_on = ? WHERE id = 1", (1 if on else 0,))
    db.commit()


def locked_now():
    """The addresses that can't sign in now: [(address, until: a time)], by address."""
    return [(row["email"], row["locked_until"]) for row in get_db().execute(
        "SELECT email, locked_until FROM webmail_tries WHERE locked_until > ? ORDER BY email", (time.time(),))]


def unlock(email):
    """Let an address in at once, its wrong passwords forgotten; whether it was locked."""
    db = get_db()
    gone = db.execute("DELETE FROM webmail_tries WHERE email = ? AND locked_until > ?", (email, time.time())).rowcount
    db.commit()
    return bool(gone)


def describe(minutes):
    """5 minutes, 1 hour, 2 hours, 90 minutes: as the form takes it."""
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def chosen(form):
    """From the form: (tries, minutes, None), or (None, None, problem)."""
    tries, wait, unit = form.get("tries", "").strip(), form.get("wait", "").strip(), form.get("wait_unit", "")
    if not tries.isdigit() or not 1 <= int(tries) <= MOST_TRIES:
        return None, None, f"Choose from 1 to {MOST_TRIES} wrong passwords."
    if unit not in ("minutes", "hours") or not wait.isdigit():
        return None, None, "Type how long to wait as a whole number of minutes or hours."
    minutes = int(wait) * (60 if unit == "hours" else 1)
    if not 1 <= minutes <= LONGEST:
        return None, None, "Choose a wait from 1 minute to 24 hours."
    return int(tries), minutes, None
