import sqlite3
from pathlib import Path

from flask import current_app, g
from werkzeug.security import generate_password_hash

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    default_password INTEGER NOT NULL DEFAULT 1
);
-- What a new password must contain (Settings > Password rules)
CREATE TABLE IF NOT EXISTS password_rules (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    min_length INTEGER NOT NULL DEFAULT 8,
    require_letters INTEGER NOT NULL DEFAULT 1,
    require_numbers INTEGER NOT NULL DEFAULT 1,
    require_special INTEGER NOT NULL DEFAULT 1
);
INSERT OR IGNORE INTO password_rules (id) VALUES (1);
-- Two-factor authentication (Settings > Two-factor authentication, two_factor.py)
CREATE TABLE IF NOT EXISTS two_factor (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    secret TEXT,                            -- shared with the authenticator app; set = on
    pending_secret TEXT,                    -- shown as a QR code until a PIN confirms it
    last_step INTEGER NOT NULL DEFAULT 0,   -- the newest PIN used: none works twice
    failures INTEGER NOT NULL DEFAULT 0,    -- wrong PINs in a row
    locked_until REAL NOT NULL DEFAULT 0    -- after too many, no PIN is taken until then
);
INSERT OR IGNORE INTO two_factor (id) VALUES (1);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(Path(current_app.config["DATA_DIR"]) / "someless.db")
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        if db.execute("SELECT 1 FROM admin").fetchone() is None:
            db.execute(
                "INSERT INTO admin (id, username, password_hash) VALUES (1, ?, ?)",
                (DEFAULT_USERNAME, generate_password_hash(DEFAULT_PASSWORD)),
            )
            db.commit()
