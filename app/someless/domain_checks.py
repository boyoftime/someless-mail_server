"""Automatic domain checks (Settings > Miscellaneous): every domain's DNS records looked at again
on a schedule, as "Authenticate this email domain" does, so a record deleted at the registrar
is noticed by itself: the domain goes back to not authenticated, and the mail engine stops
sending as it. A domain whose records have all appeared gets authenticated the same way.
Off until the admin switches it on. The container's supervisor runs it when it's due
(engine/supervisor.py)."""
import time

from . import domain_records
from .db import get_db

PRESETS = (60, 120, 360, 720, 1440)   # minutes (1, 2, 6, 12 hours, 1 day), offered as choices; any other is custom
LONGEST = 30 * 24 * 60                 # minutes: a custom time is from 1 minute up to 30 days


def settings():
    return get_db().execute("SELECT * FROM domain_checks WHERE id = 1").fetchone()


def save(enabled, every_minutes):
    db = get_db()
    db.execute("UPDATE domain_checks SET enabled = ?, every_minutes = ? WHERE id = 1", (1 if enabled else 0, every_minutes))
    db.commit()


def remember_address(address):
    """This server's public IP address, as the panel last saw it (opened by it, or by a name
    pointing to it): the A record check compares with it, and a scheduled check has no page
    to learn it from."""
    if address and address != settings()["server_address"]:
        db = get_db()
        db.execute("UPDATE domain_checks SET server_address = ? WHERE id = 1", (address,))
        db.commit()


def describe(minutes):
    """A number of minutes as people say it: 45 minutes, 6 hours, 1 day and 6 hours."""
    days, rest = divmod(minutes, 24 * 60)
    hours, minutes = divmod(rest, 60)
    parts = [f"{count} {unit}{'s' if count != 1 else ''}"
             for count, unit in ((days, "day"), (hours, "hour"), (minutes, "minute")) if count]
    return ", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else "".join(parts)


def due():
    row = settings()
    return bool(row["enabled"]) and (row["last_run"] is None or time.time() - row["last_run"] >= row["every_minutes"] * 60)


def run():
    """Look at every domain's records again. The domains whose authentication changed, with
    how it stands now: [(name, authenticated)]."""
    from .engine import sync as engine_sync
    db = get_db()
    address = settings()["server_address"]
    changed = []
    for row in db.execute("SELECT id, name, authenticated FROM domains ORDER BY name").fetchall():
        try:
            host, found, results = domain_records.look(row["name"], domain_records.keys_for(row["id"]), address)
        except Exception:   # DNS not answering: the next check tries again
            continue
        domain_records.save(row["id"], host, found, results)
        now = domain_records.authenticated(results)
        if now != bool(row["authenticated"]):
            changed.append((row["name"], now))
    db.execute("UPDATE domain_checks SET last_run = ? WHERE id = 1", (time.time(),))
    db.commit()
    if changed:
        engine_sync.after_change()   # a domain no longer authenticated leaves the engine, a new one joins it
    return changed
