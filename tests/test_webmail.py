"""The webmail (webmail.py): its own little site on port 17090, where a mailbox logs in with
its own address and password. For now it says the inbox is coming soon, and how to read the
mail in a mail app."""
import html
import re

import pytest

from someless import mail_password
from someless.db import get_db
from someless.webmail import create_webmail_app
from test_engine_sync import a_mailbox, authenticated_domain

PASSWORD = "Mailbox-Pass-1!"


@pytest.fixture
def webmail(app):
    """The webmail beside the panel: the same data folder, so the same mailboxes."""
    return create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "WTF_CSRF_ENABLED": False})


@pytest.fixture
def mail(webmail):
    return webmail.test_client()


@pytest.fixture
def mailbox(app):
    domain_id = authenticated_domain(app)
    return a_mailbox(app, "ceo@pineloop.online", domain_id, password_hash=mail_password.hash_password(PASSWORD))


def text(response):
    return html.unescape(response.get_data(as_text=True))


def sign_in(mail, email="ceo@pineloop.online", password=PASSWORD):
    return mail.post("/login", data={"email": email, "password": password})


def test_it_answers_its_health_check(mail):
    assert mail.get("/healthz").get_data(as_text=True) == "ok"


def test_it_asks_to_log_in_first(mail):
    assert mail.get("/").headers["Location"] == "/login"
    page = text(mail.get("/login"))
    assert "Webmail" in page and 'name="email"' in page and 'name="password"' in page
    assert "side-menu" not in page   # its own look, not the panel's


def test_a_mailbox_logs_in_and_the_inbox_is_coming_soon(mail, mailbox):
    response = sign_in(mail, email=" CEO@PineLoop.online ")

    assert response.headers["Location"] == "/"
    page = text(mail.get("/"))
    assert "Your inbox is coming soon" in page and "ceo@pineloop.online" in page
    for value in ("mail.pineloop.online", "993", "465", "587", "995"):
        assert f'data-copy="{value}"' in page, value
    assert 'action="/logout"' in page


@pytest.mark.parametrize("email,password", [("ceo@pineloop.online", "wrong"), ("nobody@pineloop.online", PASSWORD), ("", "")])
def test_a_wrong_address_or_password_says_the_same(mail, mailbox, email, password):
    response = sign_in(mail, email, password)

    assert response.status_code == 400
    assert 'data-board="error"' in text(response) and "The email or password is wrong." in text(response)
    assert mail.get("/").headers["Location"] == "/login"


def test_five_wrong_passwords_lock_the_address_for_five_minutes(mail, mailbox, monkeypatch):
    import someless.webmail as webmail_module
    now = [1_000_000.0]
    monkeypatch.setattr(webmail_module.time, "time", lambda: now[0])
    for _ in range(5):
        sign_in(mail, password="wrong")

    locked = sign_in(mail)   # even the right password
    assert locked.status_code == 429 and "Too many tries" in text(locked)

    now[0] += 5 * 60 + 1
    assert sign_in(mail).headers["Location"] == "/"


def test_a_login_that_works_starts_the_count_again(mail, mailbox):
    for _ in range(4):
        sign_in(mail, password="wrong")
    sign_in(mail)
    mail.post("/logout")
    for _ in range(4):
        sign_in(mail, password="wrong")

    assert sign_in(mail).headers["Location"] == "/"


def test_a_new_password_logs_the_mailbox_out(app, mail, mailbox):
    sign_in(mail)
    with app.app_context():
        get_db().execute("UPDATE mailboxes SET password_version = password_version + 1 WHERE id = ?", (mailbox,))
        get_db().commit()

    assert mail.get("/").headers["Location"] == "/login"


def test_a_deleted_mailbox_is_logged_out(app, mail, mailbox):
    sign_in(mail)
    with app.app_context():
        get_db().execute("DELETE FROM mailboxes WHERE id = ?", (mailbox,))
        get_db().commit()

    assert mail.get("/").headers["Location"] == "/login"


def test_log_out(mail, mailbox):
    sign_in(mail)

    assert mail.post("/logout").headers["Location"] == "/login"
    assert mail.get("/").headers["Location"] == "/login"


def test_its_cookie_is_its_own(app, webmail, client, login, mailbox):
    """The panel and the webmail can share a host (the same cookies, whatever the port): the
    admin's login isn't a mailbox's, and the other way round."""
    login()
    panel_cookie = client.get_cookie("session")
    assert panel_cookie is not None
    mail = webmail.test_client()
    mail.set_cookie("session", panel_cookie.value)

    assert mail.get("/").headers["Location"] == "/login"
    assert webmail.config["SESSION_COOKIE_NAME"] != app.config.get("SESSION_COOKIE_NAME", "session")
    assert webmail.secret_key != app.secret_key


def test_its_forms_need_their_token(app):
    webmail = create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"]})

    assert webmail.test_client().post("/login", data={"email": "a@b.c", "password": "x"}).status_code == 400
    assert re.search(r'name="csrf_token" [^>]*value="[^"]+"', text(webmail.test_client().get("/login")))


def test_a_sign_in_page_left_open_too_long_asks_again_nicely(app):
    """Its form's token runs out after an hour: the page says to sign in again, on its own look."""
    webmail = create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"]})

    response = webmail.test_client().post("/login", data={"email": "ceo@pineloop.online", "password": "x"})

    assert response.status_code == 400
    page = text(response)
    assert "Sign in to your mailbox" in page and 'data-board="error"' in page and "Sign in again" in page


def save_lock(client, tries="5", wait="5", unit="minutes"):
    return client.post("/settings/miscellaneous/webmail-lock", data={"tries": tries, "wait": wait, "wait_unit": unit})


def test_the_lock_is_set_in_settings(client, login):
    login()

    page = text(client.get("/settings/miscellaneous"))
    assert "Webmail sign-in lock" in page
    assert re.search(r'name="tries"[^>]*value="5"', page) and re.search(r'name="wait"[^>]*value="5"', page)

    assert save_lock(client, tries="3", wait="2", unit="hours").headers["Location"] == "/settings/miscellaneous"
    page = text(client.get("/settings/miscellaneous"))
    assert "3 wrong passwords in a row" in page and "2 hours" in page


@pytest.mark.parametrize("tries,wait,unit", [("0", "5", "minutes"), ("21", "5", "minutes"), ("x", "5", "minutes"),
                                             ("5", "0", "minutes"), ("5", "25", "hours"), ("5", "5", "days")])
def test_a_lock_that_cant_be_is_refused(client, login, tries, wait, unit):
    login()

    response = save_lock(client, tries, wait, unit)

    assert response.status_code == 400 and 'data-board="error"' in text(response)


def test_the_webmail_locks_as_set(client, login, mail, mailbox, monkeypatch):
    import someless.webmail as webmail_module
    login()
    save_lock(client, tries="3", wait="10", unit="minutes")
    now = [1_000_000.0]
    monkeypatch.setattr(webmail_module.time, "time", lambda: now[0])
    for _ in range(3):
        sign_in(mail, password="wrong")

    locked = sign_in(mail)
    assert locked.status_code == 429 and "Wait 10 minutes" in text(locked)
    now[0] += 9 * 60
    assert sign_in(mail).status_code == 429
    now[0] += 60 + 1
    assert sign_in(mail).headers["Location"] == "/"
