from flask import Blueprint, g, redirect, render_template, url_for

from .auth import login_required

bp = Blueprint("pages", __name__)


@bp.get("/")
def welcome():
    if g.admin is not None:
        return redirect(url_for("pages.dashboard"))
    return render_template("welcome.html")


@bp.get("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


@bp.get("/api-keys")
@login_required
def api_keys():
    return render_template("api-keys.html")


@bp.get("/healthz")
def healthz():
    return "ok"
