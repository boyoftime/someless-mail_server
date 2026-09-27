"""The mail domains: the part of an email address after the @. The admin adds them here and
authenticates them with DNS records at their domain provider (domain_records.py)."""
import json
import re
import time

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from . import domain_checks, domain_records
from .auth import login_required
from .db import get_db
from .engine import sync as engine_sync

bp = Blueprint("domains", __name__, url_prefix="/domains")

# Labels of letters, digits and dashes (never first or last), dots between them, and a
# top level of letters (or an internationalised xn-- one).
_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
DOMAIN_PATTERN = re.compile(rf"(?=.{{1,253}}$)(?:{_LABEL}\.)+(?:[a-z]{{2,63}}|xn--[a-z0-9-]{{1,59}})")
NOT_A_DOMAIN = "Type a domain like example.com: the part of an email address after the @."
# How the check names what is still to add or fix
SHORT_NAMES = {"code": "Someless code", "a": "mail server address", "spf": "SPF", "dkim": "DKIM", "dmarc": "DMARC",
               "mx": "MX"}


def tidy(typed):
    """A domain name as people type it: without spaces, capitals, https:// or a path, or a
    dot at the end."""
    name = re.sub(r"^[a-z]+://", "", typed.strip().lower())
    return name.split("/", 1)[0].rstrip(".")


def _page(status=200, **context):
    # Every domain is on the page; the ones the search doesn't match are hidden, so typing
    # in the search box can filter the whole list on the spot (domains-page.js).
    query = request.args.get("q", "").strip()
    domains = [
        {"id": row["id"], "name": row["name"], "authenticated": row["authenticated"],
         "provider": row["provider"], "shown": query.lower() in row["name"]}
        for row in get_db().execute("SELECT * FROM domains ORDER BY name")
    ]
    return render_template("domains.html", domains=domains, query=query, **context), status


def _domain(domain_id):
    domain = get_db().execute("SELECT * FROM domains WHERE id = ?", (domain_id,)).fetchone()
    if domain is None:
        abort(404)
    return domain


def _note_provider(domain_id, name):
    """Who runs the domain's DNS, noted for the list and the Authenticate page."""
    provider = domain_records.dns_provider(name)
    db = get_db()
    db.execute("UPDATE domains SET provider = ? WHERE id = ?", (provider, domain_id))
    db.commit()
    return provider


def _ago(when):
    if when is None:
        return None
    seconds = time.time() - when
    for size, unit in [(86400, "day"), (3600, "hour"), (60, "minute")]:
        if seconds >= size:
            count = int(seconds // size)
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    return "just now"


@bp.get("")
@login_required
def index():
    return _page()


@bp.post("")
@login_required
def add():
    typed = request.form.get("name", "")
    name = tidy(typed)
    if not DOMAIN_PATTERN.fullmatch(name):
        return _page(400, add_error=NOT_A_DOMAIN, add_value=typed.strip())
    db = get_db()
    if db.execute("SELECT 1 FROM domains WHERE name = ?", (name,)).fetchone():
        return _page(400, add_error=f"{name} is already added.", add_value=typed.strip())
    added = db.execute("INSERT INTO domains (name, added_at) VALUES (?, ?)", (name, time.time()))
    db.commit()
    domain_records.keys_for(added.lastrowid)  # its code and signing key, ready for its records
    _note_provider(added.lastrowid, name)
    flash(f"{name} was added.", "added")
    return redirect(url_for("domains.index"))


@bp.get("/<int:domain_id>")
@login_required
def authenticate(domain_id):
    """The DNS records to add at the domain provider, and how the last check of them went."""
    domain = _domain(domain_id)
    address = domain_records.server_address(request.host)
    domain_checks.remember_address(address)   # for the automatic checks, which have no page to ask
    keys = domain_records.keys_for(domain_id)
    # domains added before providers were noted (or when DNS didn't answer) find out now
    provider = domain["provider"] or _note_provider(domain_id, domain["name"])
    if domain_records.out_of_date(keys):  # see what the domain has for mail now
        host, found, results = domain_records.look(domain["name"], keys, address)
        # a domain checked before is checked again, so what the check says fits the records
        # the page shows now
        domain_records.save(domain_id, host, found, results if keys["checks"] else None)
        engine_sync.after_change()  # a re-check can authenticate the domain, or undo it
        keys = domain_records.keys_for(domain_id)
    authenticating, receiving = domain_records.records(domain["name"], keys, address)
    return render_template(
        "domain.html", domain=domain, provider=provider, records=authenticating, receiving=receiving,
        celebrate=session.pop("celebrate", None) == domain_id,   # a check just found it all right (below)
        receive_note=domain_records.receive_note(domain["name"], keys),
        receive_tip=domain_records.receive_tip(domain["name"], keys),
        help_links=None if domain["authenticated"] else _help_links(domain_id),
        summary=domain_records.summary(domain["name"], keys, address),
        checks=json.loads(keys["checks"]) if keys["checks"] else {}, checked_ago=_ago(keys["checked_at"]),
    )


def _help_links(domain_id):
    """The Need help? dialog's list, as it is now, and how many links it has (help_links.py
    imports this module)."""
    from . import help_links
    return {"html": help_links.list_html(domain_id), "count": help_links.count(domain_id)}


def check_now(domain, host):
    """Look the domain's records up in DNS now and keep what's found (the Authenticate page, and
    the pages its help links open): None when it's authenticated, else what's still to add or fix."""
    address = domain_records.server_address(host)
    domain_checks.remember_address(address)
    found_host, found, results = domain_records.look(domain["name"], domain_records.keys_for(domain["id"]), address)
    domain_records.save(domain["id"], found_host, found, results)
    engine_sync.after_change()
    _note_provider(domain["id"], domain["name"])  # it may have moved its DNS since
    if domain_records.authenticated(results):
        return None
    still = [SHORT_NAMES[key] for key in domain_records.AUTHENTICATING if results[key]["state"] != "found"]
    return (f"Still to add or fix: {', '.join(still)}. New records can take a while to show up, "
            "so check again later.")


@bp.post("/<int:domain_id>/check")
@login_required
def check(domain_id):
    """Look the records up in DNS ("Authenticate this email domain")."""
    domain = _domain(domain_id)
    still = check_now(domain, request.host)
    if still is None:
        flash(f"{domain['name']} is authenticated.", "authenticated")
        session["celebrate"] = domain_id   # every check that finds it all right: the page celebrates
    else:
        flash(still, "not-authenticated")
    return redirect(url_for("domains.authenticate", domain_id=domain_id))


@bp.post("/<int:domain_id>/delete")
@login_required
def delete(domain_id):
    db = get_db()
    domain = db.execute("SELECT name FROM domains WHERE id = ?", (domain_id,)).fetchone()
    if domain and db.execute("SELECT 1 FROM mailboxes WHERE domain_id = ? UNION SELECT 1 FROM mailbox_aliases"
                             " WHERE domain_id = ?", (domain_id, domain_id)).fetchone():
        # deleting it would stop its mail: the mailboxes (and the mail in them) go first, on purpose
        flash(f"{domain['name']} has mailboxes or aliases. Delete its mailboxes first (and aliases at it, "
              "on the Mailboxes page), then the domain.", "not-deleted")
    elif domain:
        db.execute("DELETE FROM domains WHERE id = ?", (domain_id,))
        db.execute("DELETE FROM domain_keys WHERE domain_id = ?", (domain_id,))
        db.execute("DELETE FROM senders WHERE domain_id = ?", (domain_id,))  # its addresses go with it
        db.execute("DELETE FROM help_links WHERE domain_id = ?", (domain_id,))  # and its help links
        db.commit()
        engine_sync.after_change()
        flash(f"{domain['name']} was deleted.", "deleted")
    return redirect(url_for("domains.index"))
