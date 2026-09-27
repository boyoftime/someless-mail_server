"""The webmail's sign-in lock (Settings > Miscellaneous): after so many wrong passwords in a row,
an address waits so long before it can try again (webmail.py). 5 and 5 minutes to start with."""
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
