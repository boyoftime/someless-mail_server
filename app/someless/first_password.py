"""The admin's first password: made at random on a new install's first start (not admin/admin, which
anyone could try), printed once in the container's logs, and kept in the data folder, readable
only by the app, until it's changed in Settings. On the server:

    docker exec -u someless someless-mail flask --app someless initial-password   (shows it)
    docker exec -u someless someless-mail flask --app someless reset-password     (a new one, if forgotten)

SOMELESS_INITIAL_PASSWORD, when set, is the first password instead (the tests use it)."""
import os
import secrets
from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash

from .db import get_db

# easy to read aloud and type: no 0/O, 1/l/I
LETTERS = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SHOW = "docker exec -u someless someless-mail flask --app someless initial-password"


def make():
    """Three groups of six, like hE7kq2-Wm9xTa-4pRz8n: about 100 bits, with letters and digits."""
    while True:
        password = "-".join("".join(secrets.choice(LETTERS) for _ in range(6)) for _ in range(3))
        if any(c.isdigit() for c in password) and any(c.isalpha() for c in password):
            return password


def path(data_dir=None):
    return Path(data_dir or current_app.config["DATA_DIR"]) / "initial_password"


def first(data_dir):
    """The first password for a new install, kept for the commands above (unless it was given)."""
    given = os.environ.get("SOMELESS_INITIAL_PASSWORD")
    if given:
        return given
    password = make()
    kept = path(data_dir)
    kept.write_text(password + "\n")
    kept.chmod(0o600)
    print("\n  Someless Mail is ready. Log in with:\n"
          f"    Username: admin\n    Password: {password}\n"
          "  Change the password in Settings. Until then, this shows it again:\n"
          f"    {SHOW}\n", flush=True)
    return password


def forget():
    """Changed in Settings: nothing to show any more."""
    path().unlink(missing_ok=True)


@click.command("initial-password")
@with_appcontext
def show_command():
    """Show the admin's first password, until it's changed in Settings."""
    kept = path()
    if kept.exists():
        username = get_db().execute("SELECT username FROM admin WHERE id = 1").fetchone()["username"]
        click.echo(f"Username: {username}\nPassword: {kept.read_text().strip()}")
    else:
        click.echo("The first password was changed in Settings: log in with yours. Forgot it? "
                   "Make a new one with: flask --app someless reset-password")


@click.command("reset-password")
@with_appcontext
def reset_command():
    """Give the admin a new random password (a forgotten one), shown until it's changed."""
    password = make()
    db = get_db()
    db.execute("UPDATE admin SET password_hash = ?, default_password = 1 WHERE id = 1", (generate_password_hash(password),))
    db.commit()
    kept = path()
    kept.write_text(password + "\n")
    kept.chmod(0o600)
    username = db.execute("SELECT username FROM admin WHERE id = 1").fetchone()["username"]
    click.echo(f"Username: {username}\nPassword: {password}\nChange it in Settings once you're in.")
