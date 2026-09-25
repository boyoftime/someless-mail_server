from flask import Blueprint, render_template

from .auth import login_required

bp = Blueprint("domains", __name__, url_prefix="/domains")


@bp.get("")
@login_required
def index():
    return render_template("domains.html")
