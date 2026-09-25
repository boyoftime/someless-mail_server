import re

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .auth import login_required
from .db import get_db

bp = Blueprint("settings", __name__, url_prefix="/settings")

USERNAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{3,32}")
MIN_PASSWORD_LENGTH = 8


def _current_password_ok():
    return check_password_hash(g.admin["password_hash"], request.form.get("current_password", ""))


@bp.get("")
@login_required
def index():
    return render_template("settings.html")


@bp.post("/username")
@login_required
def change_username():
    username = request.form.get("username", "").strip()
    error = None
    if not USERNAME_PATTERN.fullmatch(username):
        error = "Use 3 to 32 characters: letters, numbers, dots, dashes or underscores."
    elif not _current_password_ok():
        error = "Current password is wrong."
    if error:
        return render_template("settings.html", username_error=error, username_value=username), 400

    db = get_db()
    db.execute("UPDATE admin SET username = ? WHERE id = ?", (username, g.admin["id"]))
    db.commit()
    flash("Username changed.")
    return redirect(url_for("settings.index"))


@bp.post("/password")
@login_required
def change_password():
    new_password = request.form.get("new_password", "")
    error = None
    if not _current_password_ok():
        error = "Current password is wrong."
    elif len(new_password) < MIN_PASSWORD_LENGTH:
        error = f"New password must be at least {MIN_PASSWORD_LENGTH} characters."
    elif new_password != request.form.get("confirm_password", ""):
        error = "New passwords don't match."
    if error:
        return render_template("settings.html", password_error=error), 400

    db = get_db()
    db.execute(
        "UPDATE admin SET password_hash = ?, default_password = 0 WHERE id = ?",
        (generate_password_hash(new_password), g.admin["id"]),
    )
    db.commit()
    flash("Password changed.")
    return redirect(url_for("settings.index"))
