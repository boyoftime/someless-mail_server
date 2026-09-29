"""Calendar and contacts apps through the webmail's address (webmail/dav.py): they sign in with the
mailbox's address and password, checked here (and locked after too many wrong ones), and their
requests go on to the engine's /dav/ as the mailbox. The engine is a made-up one that notes what
it was sent."""
import base64

import pytest

from someless import mail_password, webmail_lock
from someless.db import get_db
from someless.webmail import create_webmail_app, dav
from test_engine_sync import a_mailbox, a_sender, authenticated_domain

PASSWORD = "Mailbox-Pass-1!"
MULTISTATUS = b'<?xml version="1.0"?><D:multistatus xmlns:D="DAV:"><D:response><D:href>/dav/cal/ceo%40pineloop.online/</D:href></D:response></D:multistatus>'


class Engine:
    def __init__(self):
        self.sent = []
        self.answer = (207, {"Content-Type": "application/xml; charset=utf-8", "DAV": "1, 2, calendar-access"}, MULTISTATUS)

    def __call__(self, method, path, headers, body):
        self.sent.append({"method": method, "path": path, "headers": dict(headers), "body": body})
        return self.answer


@pytest.fixture
def engine():
    dav.forget_trust()
    return Engine()


@pytest.fixture
def mailbox(app):
    domain_id = authenticated_domain(app)
    a_sender(app, domain_id, "ceo@pineloop.online")
    return a_mailbox(app, "ceo@pineloop.online", domain_id, password_hash=mail_password.hash_password(PASSWORD))


@pytest.fixture
def webmail(app, engine, mailbox):
    return create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "DAV_FORWARD": engine, "DAV_SECRET": "service-secret"})


@pytest.fixture
def client(webmail):
    return webmail.test_client()


def basic(email="ceo@pineloop.online", password=PASSWORD):
    return {"Authorization": "Basic " + base64.b64encode(f"{email}:{password}".encode()).decode()}


def test_an_app_is_asked_to_sign_in(client, engine):
    response = client.open("/dav/cal/ceo@pineloop.online/", method="PROPFIND")

    assert response.status_code == 401 and response.headers["WWW-Authenticate"].startswith('Basic realm="Someless Mail"')
    assert engine.sent == []


def test_a_signed_in_request_goes_on_to_the_engine_as_the_mailbox(client, engine):
    response = client.open("/dav/cal/ceo@pineloop.online/", method="PROPFIND", data=b"<propfind/>",
                           headers={**basic("CEO@pineloop.online"), "Depth": "1", "Content-Type": "application/xml"})

    assert response.status_code == 207 and response.data == MULTISTATUS
    assert response.headers["DAV"] == "1, 2, calendar-access" and response.headers["Cache-Control"] == "no-store"
    sent = engine.sent[0]
    assert (sent["method"], sent["path"], sent["body"]) == ("PROPFIND", "/dav/cal/ceo@pineloop.online/", b"<propfind/>")
    assert sent["headers"]["Depth"] == "1" and sent["headers"]["Content-Type"] == "application/xml"
    login = base64.b64decode(sent["headers"]["Authorization"][6:]).decode()
    assert login == "ceo@pineloop.online%someless-webmail@someless.internal:service-secret"   # (never the mailbox's password)


def test_the_well_known_addresses_lead_to_the_engines_own(client, engine):
    engine.answer = (307, {"Location": "/dav/cal"}, b"")

    response = client.get("/.well-known/caldav", headers=basic())

    assert response.status_code == 307 and response.headers["Location"] == "/dav/cal"
    assert engine.sent[0]["path"] == "/.well-known/caldav"


def test_a_name_with_spaces_goes_on_as_it_came(client, engine):
    client.put("/dav/cal/ceo@pineloop.online/default/team%20lunch.ics", data=b"BEGIN:VCALENDAR", headers=basic())

    assert engine.sent[0]["path"] == "/dav/cal/ceo@pineloop.online/default/team%20lunch.ics"


def test_nothing_outside_dav_is_reached(client, engine):
    response = client.get("/dav/../jmap/session", headers=basic())

    assert response.status_code == 400 and engine.sent == []


def test_a_query_string_goes_along(client, engine):
    client.get("/dav/card/ceo@pineloop.online/contacts/?export", headers=basic())

    assert engine.sent[0]["path"] == "/dav/card/ceo@pineloop.online/contacts/?export"


def test_a_copy_or_move_is_told_the_engines_own_address(client, engine):
    client.open("/dav/cal/ceo@pineloop.online/default/a.ics", method="MOVE",
                headers={**basic(), "Destination": "http://localhost/dav/cal/ceo@pineloop.online/work/a.ics", "Overwrite": "F"})

    assert engine.sent[0]["headers"]["Destination"] == "http://127.0.0.1:17880/dav/cal/ceo@pineloop.online/work/a.ics"
    assert engine.sent[0]["headers"]["Overwrite"] == "F"


def test_a_wrong_password_is_refused_and_counted(client, engine, webmail):
    response = client.open("/dav/", method="PROPFIND", headers=basic(password="wrong"))

    assert response.status_code == 401 and engine.sent == []
    with webmail.app_context():
        assert get_db().execute("SELECT failures FROM webmail_tries WHERE email = 'ceo@pineloop.online'").fetchone()[0] == 1


def test_too_many_wrong_passwords_lock_the_address(client, engine, webmail):
    with webmail.app_context():
        tries = webmail_lock.settings()[0]
    for _ in range(tries):
        client.open("/dav/", method="PROPFIND", headers=basic(password="wrong"))

    response = client.open("/dav/", method="PROPFIND", headers=basic())

    assert response.status_code == 429 and b"Too many tries with a wrong password" in response.data
    assert engine.sent == []


def test_an_address_that_isnt_a_mailbox(client, engine):
    assert client.open("/dav/", method="PROPFIND", headers=basic("nobody@pineloop.online")).status_code == 401


def test_a_right_password_is_trusted_for_a_while(client, engine, monkeypatch):
    checked = []
    real = mail_password.password_ok
    monkeypatch.setattr(mail_password, "password_ok", lambda stored, password: checked.append(1) or real(stored, password))

    for _ in range(3):
        assert client.open("/dav/", method="PROPFIND", headers=basic()).status_code == 207

    assert len(checked) == 1


def test_a_new_password_ends_the_trust(client, engine, webmail, mailbox):
    client.open("/dav/", method="PROPFIND", headers=basic())
    with webmail.app_context():
        get_db().execute("UPDATE mailboxes SET password_hash = ?, password_version = password_version + 1 WHERE id = ?",
                         (mail_password.hash_password("Another-Pass-2!"), mailbox))
        get_db().commit()

    assert client.open("/dav/", method="PROPFIND", headers=basic()).status_code == 401
    assert client.open("/dav/", method="PROPFIND", headers=basic(password="Another-Pass-2!")).status_code == 207


def test_apps_need_no_page_token(app, engine, mailbox):
    guarded = create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "DAV_FORWARD": engine,
                                  "DAV_SECRET": "service-secret", "WTF_CSRF_ENABLED": True})

    response = guarded.test_client().put("/dav/card/ceo@pineloop.online/default/x.vcf", data=b"BEGIN:VCARD", headers=basic())

    assert response.status_code == 207 and engine.sent[0]["method"] == "PUT"


def test_the_engine_not_answering(client, webmail, monkeypatch):
    webmail.config.pop("DAV_FORWARD")
    webmail.config["ENGINE_URL"] = "http://127.0.0.1:9"   # (nothing there)

    response = client.open("/dav/", method="PROPFIND", headers=basic())

    assert response.status_code == 503 and response.headers["Retry-After"] == "30"
