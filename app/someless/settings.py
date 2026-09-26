import re
from collections import namedtuple

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import two_factor
from .auth import login_required
from .db import get_db

bp = Blueprint("settings", __name__, url_prefix="/settings")

USERNAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{3,32}")
# The dots on the line in the "Password rules" dialog
MIN_LENGTHS = range(1, 13)
FORCED_KINDS = ("require_letters", "require_numbers", "require_special")

# One thing a new password must contain under the saved rules. The settings page lists
# them (label) and password-rules.js ticks them off as you type (key); the server says
# `message` when a new password lacks it.
Check = namedtuple("Check", "key label test message")


def password_rules():
    """The saved rules (Settings > Password rules): minimum length and which kinds of
    character a new password must have."""
    return get_db().execute("SELECT * FROM password_rules WHERE id = 1").fetchone()


def password_checks(rules):
    n = rules["min_length"]
    characters = "character" if n == 1 else "characters"
    checks = [Check("length", f"At least {n} {characters}", lambda p: len(p) >= n,
                    f"New password must be at least {n} {characters}.")]
    if rules["require_letters"]:
        checks.append(Check("letter", "At least one letter", lambda p: re.search(r"[A-Za-z]", p),
                            "New password needs a letter."))
    if rules["require_numbers"]:
        checks.append(Check("number", "At least one number", lambda p: re.search(r"[0-9]", p),
                            "New password needs a number."))
    if rules["require_special"]:
        checks.append(Check("special", "At least one special character (e.g. ! @ # $ % ^ & *)",
                            lambda p: re.search(r"[^A-Za-z0-9]", p),
                            "New password needs a special character, like ! @ # $ or %."))
    return checks


def _settings_page(status=200, **context):
    rules = password_rules()
    return render_template(
        "settings.html", rules=rules, checks=password_checks(rules), tf=two_factor.state(), **context
    ), status


def _current_password_ok():
    return check_password_hash(g.admin["password_hash"], request.form.get("current_password", ""))


@bp.get("")
@login_required
def index():
    return _settings_page()


@bp.post("/username")
@login_required
def change_username():
    username = request.form.get("username", "").strip()
    if not USERNAME_PATTERN.fullmatch(username):
        error = "Use 3 to 32 characters: letters, numbers, dots, dashes or underscores."
        return _settings_page(400, username_error=error, username_value=username)

    db = get_db()
    db.execute("UPDATE admin SET username = ? WHERE id = ?", (username, g.admin["id"]))
    db.commit()
    flash("Username changed.", "success")
    return redirect(url_for("settings.index"))


@bp.post("/password")
@login_required
def change_password():
    new_password = request.form.get("new_password", "")
    error = None
    broken = [check.message for check in password_checks(password_rules()) if not check.test(new_password)]
    if not _current_password_ok():
        error = "Current password is wrong."
    elif broken:
        error = broken[0]
    elif new_password != request.form.get("confirm_password", ""):
        error = "New passwords don't match."
    if error:
        return _settings_page(400, password_error=error)

    db = get_db()
    db.execute(
        "UPDATE admin SET password_hash = ?, default_password = 0 WHERE id = ?",
        (generate_password_hash(new_password), g.admin["id"]),
    )
    db.commit()
    flash("Password changed.", "success")
    return redirect(url_for("settings.index"))


# Two-factor authentication: the password is always asked; "Use PIN" adds the PIN from an
# authenticator app (two_factor.py).
_PIN_ERRORS = {
    "wrong": "That PIN didn't match. Check the app and try again.",
    "locked": "Too many wrong PINs. Try again in 5 minutes.",
}


def _pin_error(result, **context):
    return _settings_page(429 if result == "locked" else 400, two_factor_error=_PIN_ERRORS[result], **context)


@bp.post("/two-factor/setup")
@login_required
def two_factor_setup():
    """"Use PIN" switched on: a new secret to scan, which counts once a PIN confirms it."""
    if two_factor.secret() is None:
        two_factor.start_setup()
    return redirect(url_for("settings.index"))


@bp.post("/two-factor/cancel")
@login_required
def two_factor_cancel():
    two_factor.cancel_setup()
    return redirect(url_for("settings.index"))


@bp.post("/two-factor/enable")
@login_required
def two_factor_enable():
    pending = two_factor.pending_secret()
    if pending is None:
        return redirect(url_for("settings.index"))
    result = two_factor.check(request.form.get("pin", ""), pending)
    if result != "ok":
        return _pin_error(result)
    two_factor.finish_setup()
    flash("Two-factor authentication is on.", "success")
    return redirect(url_for("settings.index"))


@bp.post("/two-factor/disable")
@login_required
def two_factor_disable():
    secret = two_factor.secret()
    if secret is None:
        return redirect(url_for("settings.index"))
    result = two_factor.check(request.form.get("pin", ""), secret)
    if result != "ok":
        return _pin_error(result, turning_off=True)
    two_factor.switch_off()
    flash("Two-factor authentication is off.", "success")
    return redirect(url_for("settings.index"))


@bp.post("/password-rules")
@login_required
def change_password_rules():
    min_length = request.form.get("min_length", "")
    if not min_length.isdigit() or int(min_length) not in MIN_LENGTHS:
        return _settings_page(400, rules_error="Pick a minimum length from 1 to 12.")

    db = get_db()
    db.execute(
        "UPDATE password_rules SET min_length = ?, require_letters = ?, require_numbers = ?,"
        " require_special = ? WHERE id = 1",
        (int(min_length), *(kind in request.form for kind in FORCED_KINDS)),
    )
    db.commit()
    flash("Password rules saved.", "success")
    return redirect(url_for("settings.index"))
