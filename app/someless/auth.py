import functools

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

bp = Blueprint("auth", __name__)

# Checked when the username doesn't exist, so a wrong username takes as long as a wrong password.
_DUMMY_HASH = generate_password_hash("someless-dummy-password")


@bp.before_app_request
def load_admin():
    g.admin = None
    # Static files are the same for everyone. Reading the session here would add
    # "Vary: Cookie" to them, and browsers would then re-download cached files.
    if request.endpoint == "static":
        return
    admin_id = session.get("admin_id")
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
        # login-submit.js sends the form in the background and asks for JSON, so the page
        # (and what was typed) stays put after a wrong password.
        wants_json = request.accept_mimetypes.best == "application/json"
        if admin and password_ok:
            session.clear()
            session["admin_id"] = admin["id"]
            flash(f"Logged in as {admin['username']}.", "welcome")
            if wants_json:
                return jsonify(redirect=url_for("pages.dashboard"))
            return redirect(url_for("pages.dashboard"))
        error = "Wrong username or password."
        if wants_json:
            return jsonify(error=error), 401
        return render_template("login.html", error=error, username=username, flipped=True), 401
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
