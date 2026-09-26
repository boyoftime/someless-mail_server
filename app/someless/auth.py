import functools

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import two_factor
from .db import get_db

bp = Blueprint("auth", __name__)

# Checked when the username doesn't exist, so a wrong username takes as long as a wrong password.
_DUMMY_HASH = generate_password_hash("someless-dummy-password")

# With two-factor authentication on, a right password is good for this long while the
# PIN from the authenticator app is awaited.
PIN_STEP_SECONDS = 5 * 60


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


def _wants_json():
    # login-submit.js sends the login forms in the background and asks for JSON, so the
    # page (and what was typed) stays put after a mistake.
    return request.accept_mimetypes.best == "application/json"


def _logged_in(admin):
    session.clear()
    session["admin_id"] = admin["id"]
    flash(f"Logged in as {admin['username']}.", "welcome")
    if _wants_json():
        return jsonify(redirect=url_for("pages.dashboard"))
    return redirect(url_for("pages.dashboard"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        admin = get_db().execute("SELECT * FROM admin WHERE username = ?", (username,)).fetchone()
        password_ok = check_password_hash(admin["password_hash"] if admin else _DUMMY_HASH, password)
        if admin and password_ok:
            if two_factor.secret() is None:
                return _logged_in(admin)
            # The password is right; the PIN from the authenticator app comes next. (The
            # session keeps its form token, so the PIN form on the same page still works.)
            session.pop("admin_id", None)
            session["pin_for"] = admin["id"]
            session["pin_since"] = two_factor.clock()
            if _wants_json():
                return jsonify(pin=True)
            return render_template("login.html", flipped=True, pin_step=True)
        error = "Wrong username or password."
        if _wants_json():
            return jsonify(error=error), 401
        return render_template("login.html", error=error, username=username, flipped=True), 401
    return render_template("login.html")


@bp.post("/login/pin")
def login_pin():
    admin_id = session.get("pin_for")
    if admin_id is None:
        return _pin_problem("Log in with your password first.", 401, restart=True)
    if two_factor.clock() - session.get("pin_since", 0) > PIN_STEP_SECONDS:
        return _pin_problem("That took too long. Log in with your password again.", 401, restart=True)

    admin = get_db().execute("SELECT * FROM admin WHERE id = ?", (admin_id,)).fetchone()
    secret = two_factor.secret()
    result = two_factor.check(request.form.get("pin", ""), secret) if secret else "ok"
    if result == "locked":
        return _pin_problem("Too many wrong PINs. Try again in 5 minutes.", 429, restart=True)
    if result == "wrong":
        return _pin_problem("Wrong PIN. Check your authenticator app and try again.", 401)
    return _logged_in(admin)


def _pin_problem(error, status, restart=False):
    """A PIN that didn't let the admin in. `restart`: back to the password first."""
    if restart:
        session.pop("pin_for", None)
        session.pop("pin_since", None)
    if _wants_json():
        return jsonify(error=error, restart=restart), status
    return render_template("login.html", error=error, flipped=True, pin_step=not restart), status


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
