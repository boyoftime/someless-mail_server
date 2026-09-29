import re
from collections import namedtuple

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import avatar, domain_checks, engine, first_password, two_factor, webmail_lock, webmail_site
from .auth import login_required
from .db import get_db
from .domain_records import server_address
from .engine import checks, names
from .engine import sync as engine_sync

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


def _secure():
    """What the Secure the panel and webmail card fills its tables in with: the mail server
    name's domain (example.com before there is one), this server's address, and whether this
    very page came over HTTPS."""
    name = names.server_name()
    domain = name.split(".", 1)[1] if name else "example.com"
    return {"domain": domain, "mail_name": name or f"mail.{domain}", "address": server_address(request.host),
            "https": request.scheme == "https"}


def _settings_page(status=200, **context):
    rules = password_rules()
    return render_template(
        "settings.html", rules=rules, checks=password_checks(rules), tf=two_factor.state(), secure=_secure(), **context
    ), status


def _current_password_ok():
    return check_password_hash(g.admin["password_hash"], request.form.get("current_password", ""))


@bp.get("")
@login_required
def index():
    return _settings_page()


# The profile picture (avatar.py): uploaded from the username card, placed in a dialog
# (settings-avatar.js), and shown in the top right corner

@bp.get("/avatar")
@login_required
def avatar_image():
    picture = avatar.path()
    if not picture.exists():
        abort(404)
    # its address changes with it (?v=), so browsers may keep it
    return send_file(picture, mimetype="image/webp", max_age=31536000 if request.args.get("v") else 0)


@bp.post("/avatar")
@login_required
def upload_avatar():
    wants_json = request.accept_mimetypes.best == "application/json"
    upload = request.files.get("picture")
    data = upload.read(avatar.LARGEST + 1) if upload else b""
    problem = avatar.save(data, request.form.get("x"), request.form.get("y"), request.form.get("size")) if data \
        else "Choose a picture first."
    if problem:
        if wants_json:
            return {"problem": problem}, 400
        return _settings_page(400, avatar_error=problem)
    if wants_json:
        return {"url": avatar.url()}
    flash("Profile picture saved.", "success")
    return redirect(url_for("settings.index"))


@bp.post("/avatar/delete")
@login_required
def delete_avatar():
    avatar.remove()
    if request.accept_mimetypes.best == "application/json":   # settings-avatar.js: the page stays put
        return {"removed": True}
    flash("Profile picture removed.", "success")
    return redirect(url_for("settings.index"))


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
    first_password.forget()   # the first one isn't kept, nor shown, any more
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


# Mail server name: the one name the mail server goes by (engine/names.py). Apps connect to it,
# and its certificate and reverse DNS carry it; it's one of the authenticated domains' mail names.

@bp.get("/mail-server")
@login_required
def mail_server():
    return render_template("settings-mail-server.html", server_names=names.server_names(), server_name=names.server_name(),
                           needs=checks.name_checks(server_address(request.host)))


@bp.post("/mail-server")
@login_required
def save_mail_server():
    chosen = request.form.get("server_name", "")
    if chosen in names.server_names():
        changed = chosen != names.server_name()
        engine.remember(server_name=chosen)   # kept even when it's the first one: it stays, whatever domains come later
        if changed:
            engine_sync.after_change()   # the engine greets with it, and asks Let's Encrypt for its certificate
            flash(f"Your mail server is {chosen} now.", "success")
    return redirect(url_for("settings.mail_server"))


@bp.post("/mail-server/check")
@login_required
def check_mail_server():
    """Check again: nothing cached, and Let's Encrypt asked again (at most every 10 minutes)."""
    checks.forget()
    engine_sync.ask_for_certificate()
    return redirect(url_for("settings.mail_server"))


# Miscellaneous: the settings that fit nowhere else. Automatic domain checks, and the webmail's
# sign-in lock.

def _misc_page(status=200, problem=None, typed=None, lock_problem=None, lock_typed=None, address_problem=None,
               address_typed=None):
    row = domain_checks.settings()
    every = row["every_minutes"]
    tries, minutes = webmail_lock.settings()
    # a custom time shows in the biggest unit it's whole in: 2 days, 36 hours, 45 minutes
    custom_unit = "days" if every % 1440 == 0 else "hours" if every % 60 == 0 else "minutes"
    return render_template(
        "settings-misc.html", checks=row, presets=[(value, domain_checks.describe(value)) for value in domain_checks.PRESETS],
        every=every, every_text=domain_checks.describe(every), custom=every not in domain_checks.PRESETS,
        custom_unit=custom_unit, custom_amount=every // {"days": 1440, "hours": 60, "minutes": 1}[custom_unit],
        problem=problem, typed=typed or {},
        last_run=row["last_run"] and _moment(row["last_run"]), longest_days=domain_checks.LONGEST // 1440,
        lock={"tries": tries, "wait": minutes // 60 if minutes % 60 == 0 else minutes, "on": webmail_lock.is_on(),
              "unit": "hours" if minutes % 60 == 0 else "minutes", "text": webmail_lock.describe(minutes),
              "locked": [{"email": email, "until": _moment(until)} for email, until in webmail_lock.locked_now()]},
        lock_problem=lock_problem, lock_typed=lock_typed or {}, most_tries=webmail_lock.MOST_TRIES,
        webmail_saved=webmail_site.saved(), webmail_beside=webmail_site.beside(request.host),
        address_problem=address_problem, address_typed=address_typed,
    ), status


UNIT_MINUTES = {"minutes": 1, "hours": 60, "days": 1440}


def _chosen_minutes(form):
    """How often, as chosen: (minutes, None, typed), or (None, problem, typed)."""
    every = form.get("every", "")
    if every == "custom":
        amount, unit = form.get("amount", "").strip(), form.get("unit", "hours")
        minutes = int(amount) * UNIT_MINUTES[unit] if amount.isdigit() and unit in UNIT_MINUTES else 0
        if not 1 <= minutes <= domain_checks.LONGEST:
            return None, (f"Choose a time between 1 minute and {domain_checks.LONGEST // 1440} days, "
                          "in whole minutes, hours or days."), {"amount": amount, "unit": unit}
        return minutes, None, {}
    if every.isdigit() and int(every) in domain_checks.PRESETS:
        return int(every), None, {}
    return None, "Choose how often to check.", {}


def _moment(when):
    import datetime
    return datetime.datetime.fromtimestamp(when, datetime.timezone.utc).isoformat(timespec="seconds")


@bp.get("/miscellaneous")
@login_required
def misc():
    return _misc_page()


@bp.post("/miscellaneous/domain-checks")
@login_required
def save_domain_checks():
    enabled = request.form.get("enabled") == "on"
    minutes, problem, typed = _chosen_minutes(request.form)
    if problem and not enabled:   # switched off: how often doesn't matter, the last one is kept
        minutes, problem = domain_checks.settings()["every_minutes"], None
    if problem:
        return _misc_page(400, typed={**typed, "enabled": enabled}, problem=problem)
    domain_checks.save(enabled, minutes)
    flash(f"Automatic domain checks are on: every {domain_checks.describe(minutes)}." if enabled
          else "Automatic domain checks are off.", "success")
    return redirect(url_for("settings.misc"))


@bp.post("/miscellaneous/webmail-lock")
@login_required
def save_webmail_lock():
    if not request.form.get("on"):   # switched off: what's typed stays as it was, for later
        webmail_lock.switch(False)
        flash("Webmail sign-in lock is off: wrong passwords never make an address wait.", "success")
        return redirect(url_for("settings.misc"))
    tries, minutes, problem = webmail_lock.chosen(request.form)
    if problem:
        return _misc_page(400, lock_problem=problem, lock_typed={
            "tries": request.form.get("tries", ""), "wait": request.form.get("wait", ""), "unit": request.form.get("wait_unit", ""),
            "on": True})
    webmail_lock.save(tries, minutes)
    webmail_lock.switch(True)
    flash(f"Webmail sign-in lock saved: after {tries} wrong password{'s' if tries != 1 else ''} in a row, "
          f"a wait of {webmail_lock.describe(minutes)}.", "success")
    return redirect(url_for("settings.misc"))


@bp.post("/miscellaneous/webmail-lock/unlock")
@login_required
def unlock_webmail_address():
    """An address locked now, let in at once (its wrong passwords forgotten)."""
    email = request.form.get("email", "").strip().lower()[:254]
    if webmail_lock.unlock(email):
        flash(f"{email} can sign in to the webmail again.", "success")
    return redirect(url_for("settings.misc"))


@bp.post("/miscellaneous/webmail-address")
@login_required
def save_webmail_address():
    typed = request.form.get("address", "")
    value, problem = webmail_site.tidy(typed)
    if problem:
        return _misc_page(400, address_problem=problem, address_typed=typed)
    webmail_site.save(value)
    flash(f"The webmail opens at {value}." if value else
          f"The webmail opens beside the panel: {webmail_site.beside(request.host)}.", "success")
    return redirect(url_for("settings.misc"))
