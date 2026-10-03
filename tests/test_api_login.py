"""Checking a mailbox's password from an app (POST /api/s1/mailboxes/login): a site that lets people
sign in with their mailbox's address and password, and greets them by name. The webmail's own
rules: wrong passwords count towards its sign-in lock (Settings > Miscellaneous), the same answer
whether the address or the password is wrong, and a disabled mailbox said so only to the right
password."""
import time

import pytest

from someless import api_guide, mail_password
from someless.db import get_db
from someless.webmail import create_webmail_app
from jmap_fake import FakeJmap
from test_api import KEY, PASSWORD, a_key, api  # noqa: F401 (the fixture)

EMAIL = "lewis@pineloop.online"


@pytest.fixture
def webmail_client(app):
    return create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "WTF_CSRF_ENABLED": False,
                               "JMAP": lambda email: FakeJmap()}).test_client()


def a_mailbox(app, api, email=EMAIL, name="Lewis Mutalemwa", disabled=False):
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO senders (name, email, domain_id, created_at, disabled) VALUES (?, ?, ?, 0, ?)",
                   (name, email, api.domain, int(disabled)))
        mailbox_id = db.execute("INSERT INTO mailboxes (email, domain_id, quota_bytes, password_hash, created_at, disabled)"
                                " VALUES (?, ?, ?, ?, 0, ?)",
                                (email, api.domain, 1024 ** 3, mail_password.hash_password(PASSWORD), int(disabled))).lastrowid
        db.commit()
        return mailbox_id


def check(api, email=EMAIL, password=PASSWORD):
    return api.post("/mailboxes/login", json={"email": email, "password": password})


def test_the_right_password_says_who_it_is(api, app):
    mailbox_id = a_mailbox(app, api)

    answer = check(api)

    assert answer.status_code == 200
    body = answer.json
    assert body["valid"] is True and body["email"] == EMAIL and body["name"] == "Lewis Mutalemwa"
    assert body["mailbox"]["id"] == mailbox_id and body["mailbox"]["email"] == EMAIL


def test_the_address_is_taken_as_people_type_it(api, app):
    a_mailbox(app, api)

    assert check(api, email="  Lewis@PineLoop.online ").json["valid"] is True


def test_the_name_they_chose_in_the_webmail_comes_first(api, app):
    mailbox_id = a_mailbox(app, api)
    with app.app_context():
        from someless.webmail import views
        views.set_display_name(mailbox_id, "Lewis M.")

    assert check(api).json["name"] == "Lewis M."


def test_a_wrong_password_and_no_such_mailbox_answer_alike(api, app):
    a_mailbox(app, api)

    wrong = check(api, password="Not-It-123!")
    nobody = check(api, email="nobody@pineloop.online")

    assert wrong.status_code == nobody.status_code == 200
    assert wrong.json == nobody.json == {"valid": False, "reason": "wrong"}


def test_a_disabled_mailbox_is_said_so_only_to_the_right_password(api, app):
    a_mailbox(app, api, disabled=True)

    assert check(api).json == {"valid": False, "reason": "disabled"}
    assert check(api, password="Not-It-123!").json == {"valid": False, "reason": "wrong"}


def test_wrong_passwords_lock_the_address_as_the_webmail_does(api, app):
    a_mailbox(app, api)
    for _ in range(5):   # the lock's start: 5 wrong in a row, 5 minutes
        check(api, password="Not-It-123!")

    locked = check(api)   # the right one, now: still locked

    assert locked.status_code == 429
    assert locked.json["valid"] is False and locked.json["reason"] == "locked"
    assert 0 < locked.json["retry_after"] <= 300 and locked.headers["Retry-After"] == str(locked.json["retry_after"])
    with app.app_context():   # the same lock as the webmail's login
        row = get_db().execute("SELECT locked_until FROM webmail_tries WHERE email = ?", (EMAIL,)).fetchone()
    assert row["locked_until"] > time.time()


def test_the_webmails_wrong_passwords_count_too(api, app, webmail_client):
    a_mailbox(app, api)
    for _ in range(5):
        webmail_client.post("/login", data={"email": EMAIL, "password": "Not-It-123!"})

    assert check(api).status_code == 429


def test_the_right_password_forgets_the_wrong_ones_before_it(api, app):
    a_mailbox(app, api)
    for _ in range(4):
        check(api, password="Not-It-123!")

    assert check(api).json["valid"] is True
    for _ in range(4):
        check(api, password="Not-It-123!")
    assert check(api).json["valid"] is True   # (the count started again)


def test_with_the_lock_off_nobody_waits(api, app):
    a_mailbox(app, api)
    with app.app_context():
        from someless import webmail_lock
        webmail_lock.switch(False)
    for _ in range(8):
        check(api, password="Not-It-123!")

    assert check(api).json["valid"] is True


def test_it_takes_an_address_and_a_password_only(api, app):
    a_mailbox(app, api)

    assert api.post("/mailboxes/login", json={"email": EMAIL}).status_code == 400
    assert "isn't a field here" in api.post("/mailboxes/login", json={"email": EMAIL, "password": PASSWORD, "x": 1}).json["error"]


def test_it_needs_the_key(api, app):
    a_mailbox(app, api)

    assert api.post("/mailboxes/login", json={"email": EMAIL, "password": PASSWORD}, key=None).status_code == 401


def test_the_guide_shows_it_with_the_mailboxes(api, client):
    mailboxes = next(group for group in api_guide.calls("https://panel.example.com/api/s1", "example.com")
                     if group["title"] == "Mailboxes")
    call = next(call for call in mailboxes["calls"] if call["path"] == "/mailboxes/login")
    assert call["method"] == "POST" and call["name"] == "Check a mailbox's password"
    docs = client.get("/api/s1/docs.md").get_data(as_text=True)
    assert "/mailboxes/login" in docs and '"reason": "locked"' in docs and "never from a browser" in docs
