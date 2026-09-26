"""The mail engine: Stalwart, running beside the panel in the same container. The panel
sets it up (setup.py), keeps it in line with what the admin set here (sync.py), checks it's
ready to send (checks.py) and follows the mail it sends (deliveries.py).
Design: docs/superpowers/specs/2026-09-26-mail-engine-sending-design.md"""
import secrets

from flask import current_app

from ..db import get_db
from .client import EngineClient, EngineError, EngineUnavailable  # noqa: F401 (the package's API)

INTERNAL_DOMAIN = "someless.internal"  # Stalwart's own default domain; the key accounts live in it
PANEL_ACCOUNT = "someless-panel"       # the panel's own sending account (test emails)
SENDERS_GROUP = "someless-senders"     # holds the Senders' addresses; every sending account is in it
API_URL = "http://127.0.0.1:17880"


def enabled():
    """Whether a mail engine runs beside this panel (in the container; not on a dev machine)."""
    return bool(current_app.config.get("ENGINE_ENABLED"))


def state():
    return get_db().execute("SELECT * FROM engine WHERE id = 1").fetchone()


def remember(**values):
    db = get_db()
    db.execute("UPDATE engine SET " + ", ".join(f"{name} = ?" for name in values) + " WHERE id = 1",
               tuple(values.values()))
    db.commit()


def secret(name):
    """A secret kept in the engine table, made the first time it's needed."""
    value = state()[name]
    if not value:
        value = secrets.token_urlsafe(32)
        remember(**{name: value})
    return value


def client():
    """The management client. The test suite puts a fake in ENGINE_CLIENT."""
    factory = current_app.config.get("ENGINE_CLIENT")
    if factory:
        return factory()
    row = state()
    return EngineClient(current_app.config.get("ENGINE_URL", API_URL), basic=(row["admin_login"], row["admin_password"]))
