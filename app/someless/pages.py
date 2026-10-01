from flask import Blueprint, g, redirect, render_template, request, session, url_for

from . import engine, server_stats
from .auth import login_required
from .db import get_db
from .engine import names

bp = Blueprint("pages", __name__)

# While the mail engine is set up on the very first start: the steps the page shows, each
# done once the setup is past the step it's named with (engine/setup.py)
PREPARING_STEPS = [("new", "Setting up the mail engine"), ("bootstrapped", "Getting it ready to send"),
                   ("provisioned", "Almost there")]
DONATE = "https://nowpayments.io/donation/someless"   # Credits: where to support Someless Mail


def preparing_page():
    """The first start's "Preparing your Someless Mail server" in place of the welcome or login
    page, while the mail engine is set up; None when there's nothing to wait for (or the admin
    chose not to wait)."""
    if not engine.preparing() or session.get("skip_preparing"):
        return None
    reached = engine.SETUP_STEPS.index(engine.state()["setup_step"])
    steps = [{"text": text, "state": "done" if index < reached else "active" if index == reached else "waiting"}
             for index, (_, text) in enumerate(PREPARING_STEPS)]
    return render_template("preparing.html", steps=steps, next_page=request.path)


@bp.get("/")
def welcome():
    if g.admin is not None:
        return redirect(url_for("pages.dashboard"))
    return preparing_page() or render_template("welcome.html")


@bp.get("/preparing/progress")
def preparing_progress():
    """How far the first start's setup got (preparing.js asks every 2 seconds)."""
    step = engine.state()["setup_step"] if engine.enabled() else "ready"
    return {"step": step, "ready": step == "ready"}


@bp.get("/preparing/skip")
def preparing_skip():
    """Continue without waiting (offered when setting up takes long): back to where the admin was."""
    session["skip_preparing"] = True
    next_page = request.args.get("next", "")
    own = next_page.startswith("/") and not next_page.startswith("//") and "\\" not in next_page
    return redirect(next_page if own else url_for("pages.welcome"))


@bp.get("/dashboard")
@login_required
def dashboard():
    """The mail server at a glance: boards hanging from ropes, swaying in the wind (dashboard.js),
    one each for the domains, the mailboxes, the senders and the mail server (one, once it has a
    name: an authenticated domain's mail name); and under them, the server itself (server_stats.py):
    its RAM, its disk, Someless Mail's share of the RAM, and whether it's healthy."""
    db = get_db()
    counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("domains", "mailboxes", "senders")}
    counts["server"] = 1 if names.server_name() else 0
    hung = [("domains", "domains.index", "Domain", "Domains", "globe"), ("mailboxes", "mailboxes.index", "Mailbox", "Mailboxes", "inbox"),
            ("senders", "senders.index", "Sender", "Senders", "sender"),
            ("server", "settings.mail_server", "Mail server", "Mail servers", "server")]
    boards = [{"key": key, "url": url_for(endpoint), "count": counts[key], "name": one if counts[key] == 1 else many, "icon": icon}
              for key, endpoint, one, many, icon in hung]
    return render_template("dashboard.html", boards=boards, server=server_stats.cards())


@bp.get("/dashboard/stats")
@login_required
def dashboard_stats():
    """The server boards' figures again: the open Dashboard asks every so often (dashboard.js)."""
    return server_stats.cards()


@bp.get("/credits")
@login_required
def credits():
    """Who made Someless Mail, why it's worth running, the thanks, and where to donate."""
    return render_template("credits.html", donate=DONATE)


@bp.get("/healthz")
def healthz():
    return "ok"
