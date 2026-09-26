"""Two-factor authentication: after the password, logging in also asks for the 6-digit PIN
from an authenticator app (Google Authenticator, Microsoft Authenticator, Authy...).

The PINs are standard time-based one-time passwords (RFC 6238): the app and the server
share a secret, and each works out the PIN for every 30 seconds from it. The settings
page shows the secret as a QR code for the app to scan (settings.py has the routes).
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

import click
import segno
from flask import g
from flask.cli import AppGroup

from .db import get_db

ISSUER = "Someless Mail"  # the name the authenticator app shows
STEP_SECONDS = 30
MAX_WRONG_PINS = 5  # in a row; then no PIN is taken for a while, so none can be guessed
LOCK_SECONDS = 5 * 60

clock = time.time  # the tests move time on


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode()


def current_step():
    return int(clock() // STEP_SECONDS)


def code_at(secret, step):
    """The PIN for one 30-second step, worked out the way authenticator apps do."""
    digest = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"


def _row():
    return get_db().execute("SELECT * FROM two_factor WHERE id = 1").fetchone()


def secret():
    """The secret in use, or None while two-factor authentication is off."""
    return _row()["secret"]


def pending_secret():
    """The secret being set up (shown as a QR code), if any."""
    row = _row()
    return row["pending_secret"] if row["secret"] is None else None


def check(pin, against):
    """Is `pin` the current PIN for the secret `against`? Returns "ok", "wrong" or "locked".
    A PIN works only once, the one just before and just after also count (clocks drift),
    and after too many wrong PINs in a row none is taken for a while."""
    db = get_db()
    row = _row()
    now = clock()
    if row["locked_until"] > now:
        return "locked"
    pin = "".join(pin.split())  # some apps show it as "123 456"
    step = current_step()
    for candidate in (step - 1, step, step + 1):
        if candidate > row["last_step"] and hmac.compare_digest(code_at(against, candidate), pin):
            db.execute("UPDATE two_factor SET last_step = ?, failures = 0 WHERE id = 1", (candidate,))
            db.commit()
            return "ok"
    failures = row["failures"] + 1
    if failures >= MAX_WRONG_PINS:
        db.execute("UPDATE two_factor SET failures = 0, locked_until = ? WHERE id = 1", (now + LOCK_SECONDS,))
        db.commit()
        return "locked"
    db.execute("UPDATE two_factor SET failures = ? WHERE id = 1", (failures,))
    db.commit()
    return "wrong"


def state():
    """What the settings card shows: on, being set up (with the QR code and the key to
    type in by hand), or off."""
    row = _row()
    pending = row["pending_secret"] if row["secret"] is None else None
    return {
        "on": row["secret"] is not None,
        "pending": pending is not None,
        "key": " ".join(pending[i:i + 4] for i in range(0, len(pending), 4)) if pending else "",
        "qr": _qr_code(pending) if pending else "",
    }


def _qr_code(secret):
    account = quote(f"{ISSUER}:{g.admin['username']}")
    uri = f"otpauth://totp/{account}?secret={secret}&issuer={quote(ISSUER)}"
    # dark on light, as scanners expect, whatever the theme
    return segno.make(uri, error="m").svg_inline(scale=4, border=2, dark="#0f1a3d", light="#ffffff", omitsize=True)


def start_setup():
    db = get_db()
    db.execute("UPDATE two_factor SET pending_secret = ? WHERE id = 1", (new_secret(),))
    db.commit()


def cancel_setup():
    db = get_db()
    db.execute("UPDATE two_factor SET pending_secret = NULL WHERE id = 1")
    db.commit()


def finish_setup():
    db = get_db()
    db.execute("UPDATE two_factor SET secret = pending_secret, pending_secret = NULL WHERE id = 1")
    db.commit()


def switch_off():
    db = get_db()
    db.execute("UPDATE two_factor SET secret = NULL, pending_secret = NULL, failures = 0, locked_until = 0 WHERE id = 1")
    db.commit()


# Lost the phone? On the server:
#   docker exec -u someless someless-mail flask --app someless two-factor off
cli = AppGroup("two-factor", help="Two-factor authentication.")


@cli.command("off")
def off_command():
    """Switch the PIN off, so the password alone logs in again."""
    switch_off()
    click.echo("Two-factor authentication is off. Log in with your password.")
