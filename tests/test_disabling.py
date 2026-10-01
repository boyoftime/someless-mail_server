"""Disabling (disabling.py): a sender and its mailbox (the same address), together, both ways. A
disabled sender can't be sent as; a disabled mailbox can't be signed in to (mail apps, the webmail,
calendar and contacts apps), and, with Refuse new mail, takes none (it bounces). Enabled again,
both work as before. In the panel and through the API."""
import base64
import html
import re

import pytest

from someless import mail_password
from someless.db import get_db
from someless.engine import sync
from someless.webmail import create_webmail_app
from jmap_fake import FakeJmap
from test_engine_sync import a_mailbox, a_sender, allowed, authenticated_domain, sync_now

PASSWORD = "Mailbox-Pass-1!"


def text(response):
    return html.unescape(response.get_data(as_text=True))


def state(app, email="ceo@pineloop.online"):
    """(sender disabled, mailbox disabled, mailbox refuses mail)"""
    with app.app_context():
        db = get_db()
        sender = db.execute("SELECT disabled FROM senders WHERE lower(email) = ?", (email,)).fetchone()
        mailbox = db.execute("SELECT disabled, refuse_mail FROM mailboxes WHERE email = ?", (email,)).fetchone()
    return (sender and sender["disabled"], mailbox and mailbox["disabled"], mailbox and mailbox["refuse_mail"])


@pytest.fixture
def address(app):
    """ceo@pineloop.online: a sender with its mailbox; and no-reply@, a sender alone"""
    domain_id = authenticated_domain(app)
    a_sender(app, domain_id, "ceo@pineloop.online")
    a_sender(app, domain_id, "no-reply@pineloop.online")
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", domain_id, password_hash=mail_password.hash_password(PASSWORD))
    with app.app_context():
        ids = {row["email"]: row["id"] for row in get_db().execute("SELECT id, email FROM senders")}

    class Address:
        mailbox = mailbox_id
        sender = ids["ceo@pineloop.online"]
        alone = ids["no-reply@pineloop.online"]
    return Address()


# --- in the panel ----------------------------------------------------------------------------------

def test_disabling_a_sender_disables_its_mailbox_too_and_enabling_brings_both_back(app, client, login, address):
    login()

    client.post(f"/senders/{address.sender}/disable", data={})

    assert state(app) == (1, 1, 0)   # (new mail still comes, by default)
    assert "is disabled, and so is its mailbox" in text(client.get("/senders"))
    client.post(f"/senders/{address.sender}/enable")
    assert state(app) == (0, 0, 0)


def test_disabling_a_mailbox_disables_its_sender_too_and_it_can_refuse_new_mail(app, client, login, address):
    login()

    client.post(f"/mailboxes/{address.mailbox}/disable", data={"refuse": "on"})

    assert state(app) == (1, 1, 1)
    client.post(f"/mailboxes/{address.mailbox}/enable")
    assert state(app) == (0, 0, 0)   # (and refusing goes with it)


def test_the_pages_say_so_and_offer_to_enable(app, client, login, address):
    login()
    client.post(f"/mailboxes/{address.mailbox}/disable", data={"refuse": "on"})

    senders, mailboxes = text(client.get("/senders")), text(client.get("/mailboxes"))

    ceo = senders[senders.index(f'data-sender-id="{address.sender}"'):]
    ceo = ceo[:ceo.index("</article>")]
    assert "Disabled" in ceo and f'action="/senders/{address.sender}/enable"' in ceo
    assert "Send test email" not in ceo   # (nothing can be sent as it)
    box = mailboxes[mailboxes.index(f'data-mailbox-id="{address.mailbox}"'):]
    box = box[:box.index("</article>")]
    assert "Disabled" in box and "refuses new mail" in box and f'action="/mailboxes/{address.mailbox}/enable"' in box
    assert "/webmail" not in box   # (no opening its webmail)
    assert re.search(r'<dialog [^>]*id="disable-dialog"', mailboxes) and re.search(r'<dialog [^>]*id="disable-dialog"', senders)


def test_a_disabled_sender_sends_no_test_and_gets_no_new_mailbox(app, client, login, address):
    login()
    client.post(f"/senders/{address.alone}/disable")

    test = client.post(f"/senders/{address.alone}/test", json={"to": "friend@example.org"})
    made = client.post("/mailboxes", data={"email": "no-reply@pineloop.online", "storage": "1", "unit": "GB",
                                           "password": PASSWORD, "confirm": PASSWORD})

    assert test.status_code == 400 and "disabled" in test.get_json()["problem"]
    assert made.status_code == 400 and "is disabled" in text(made)
    assert 'value="no-reply@pineloop.online"' not in text(client.get("/mailboxes"))   # (not offered for a mailbox)


# --- in the mail engine ------------------------------------------------------------------------------

def test_the_engine_keeps_a_disabled_mailbox_from_signing_in_and_maybe_from_receiving(app, engine, address):
    sync_now(app)
    assert engine.named("Account", "ceo")["permissions"] == {"@type": "Inherit"}
    assert "ceo@pineloop.online" in allowed(engine)

    with app.app_context():
        from someless import disabling
        disabling.set_disabled("ceo@pineloop.online", True)
    sync_now(app)
    assert engine.named("Account", "ceo")["permissions"] == {"@type": "Merge", "disabledPermissions": {"authenticate": True}}
    assert "ceo@pineloop.online" not in allowed(engine)   # nothing sends as it

    with app.app_context():
        disabling.set_disabled("ceo@pineloop.online", True, refuse_mail=True)
        get_db().execute("UPDATE mailboxes SET no_delete_apps = 1")
        get_db().commit()
    sync_now(app)
    assert engine.named("Account", "ceo")["permissions"]["disabledPermissions"] == {
        "authenticate": True, "emailReceive": True, "imapExpunge": True, "imapDelete": True, "pop3Dele": True}

    with app.app_context():
        disabling.set_disabled("ceo@pineloop.online", False)
        get_db().execute("UPDATE mailboxes SET no_delete_apps = 0")
        get_db().commit()
    sync_now(app)
    assert engine.named("Account", "ceo")["permissions"] == {"@type": "Inherit"}
    assert "ceo@pineloop.online" in allowed(engine)


# --- in the webmail --------------------------------------------------------------------------------

@pytest.fixture
def mail(app):
    return create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "WTF_CSRF_ENABLED": False,
                               "JMAP": lambda email: FakeJmap()}).test_client()


def disable(app, email="ceo@pineloop.online"):
    with app.app_context():
        from someless import disabling
        disabling.set_disabled(email, True)


def test_a_disabled_mailbox_cant_sign_in_to_the_webmail(app, mail, address):
    disable(app)

    right = mail.post("/login", data={"email": "ceo@pineloop.online", "password": PASSWORD})
    wrong = mail.post("/login", data={"email": "ceo@pineloop.online", "password": "wrong"})

    assert right.status_code == 403 and "This mailbox is disabled" in text(right)
    assert "disabled" not in text(wrong)   # (only the right password learns it)


def test_a_mailbox_disabled_while_signed_in_is_signed_out(app, mail, address):
    mail.post("/login", data={"email": "ceo@pineloop.online", "password": PASSWORD})
    assert not mail.get("/").headers["Location"].endswith("/login")   # (signed in: on to the mail)

    disable(app)

    assert mail.get("/").headers["Location"].endswith("/login")
    assert "This mailbox is disabled" in text(mail.get("/login"))


def test_calendar_and_contacts_apps_cant_sign_in_either(app, mail, address):
    disable(app)
    credentials = base64.b64encode(f"ceo@pineloop.online:{PASSWORD}".encode()).decode()

    response = mail.open("/dav/", method="PROPFIND", headers={"Authorization": f"Basic {credentials}", "Depth": "0"})

    assert response.status_code == 403 and "disabled" in text(response)


# --- through the API ---------------------------------------------------------------------------------

@pytest.fixture
def api(app, client, address):
    from test_api import KEY, a_key
    a_key(app)

    def call(method, path, json=None):
        return getattr(client, method)("/api/s1" + path, json=json, headers={"Authorization": f"Bearer {KEY}"})
    return call


def test_the_api_disables_and_enables_both_ways(app, api, address):
    sender = api("patch", f"/senders/{address.sender}", {"disabled": True})
    assert sender.status_code == 200 and sender.json["sender"]["disabled"] is True
    assert state(app) == (1, 1, 0)
    mailbox = api("get", f"/mailboxes/{address.mailbox}").json["mailbox"]
    assert mailbox["disabled"] is True and mailbox["refuse_mail"] is False

    refusing = api("patch", f"/mailboxes/{address.mailbox}", {"refuse_mail": True})
    assert refusing.status_code == 200 and state(app) == (1, 1, 1)

    enabled = api("patch", f"/mailboxes/{address.mailbox}", {"disabled": False})
    assert enabled.json["mailbox"]["disabled"] is False and state(app) == (0, 0, 0)


@pytest.mark.parametrize("path, body, problem", [
    ("/mailboxes/{mailbox}", {"refuse_mail": True}, "only while it's disabled"),
    ("/mailboxes/{mailbox}", {"disabled": "yes"}, "true or false"),
    ("/senders/{sender}", {"disabled": 1}, "true or false"),
])
def test_the_api_checks_what_it_is_sent(app, api, address, path, body, problem):
    response = api("patch", path.format(mailbox=address.mailbox, sender=address.sender), body)

    assert response.status_code == 400 and problem in response.json["error"]
    assert state(app) == (0, 0, 0)


def test_the_api_makes_no_mailbox_for_a_disabled_sender(app, api, address):
    api("patch", f"/senders/{address.alone}", {"disabled": True})

    response = api("post", "/mailboxes", {"email": "no-reply@pineloop.online", "name": "No reply", "password": PASSWORD,
                                          "storage": "1 GB"})

    assert response.status_code == 400 and "is disabled" in response.json["error"]
