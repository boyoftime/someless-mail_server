import functools

from flask import Blueprint, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

bp = Blueprint("auth", __name__)

# Checked when the username doesn't exist, so a wrong username takes as long as a wrong password.
_DUMMY_HASH = generate_password_hash("someless-dummy-password")


@bp.before_app_request
def load_admin():
    admin_id = session.get("admin_id")
    g.admin = None
    if admin_id is not None:
        g.admin = get_db().execute("SELECT * FROM admin WHERE id = ?", (admin_id,)).fetchone()


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.admin is None:
            return redirect(url_for("auth.login"))
        return view(**kwargs)
    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        admin = get_db().execute("SELECT * FROM admin WHERE username = ?", (username,)).fetchone()
        password_ok = check_password_hash(admin["password_hash"] if admin else _DUMMY_HASH, password)
        if admin and password_ok:
            session.clear()
            session["admin_id"] = admin["id"]
            return redirect(url_for("pages.dashboard"))
        return render_template("login.html", error="Wrong username or password.", username=username), 401
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
