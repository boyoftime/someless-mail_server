"""The webmail's sign-in lock (Settings > Miscellaneous): after so many wrong passwords in a row,
an address waits so long before it can try again (webmail/__init__.py, and the calendar and
contacts apps: webmail/dav.py). 5 and 5 minutes to start with. It can be switched off (then
wrong passwords never make anyone wait), and an address locked now can be let in at once."""
import time

from .db import get_db

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
