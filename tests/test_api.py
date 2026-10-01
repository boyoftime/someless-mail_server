"""The API (api.py): an app manages the senders and mailboxes with an API key, in JSON, as the
panel would (the same checks, the same words)."""
import hashlib
import time

import pytest

from someless import mail_password
from someless.db import get_db
from test_engine_sync import a_mailbox, a_sender, authenticated_domain

KEY = "sm_" + "k" * 48
PASSWORD = "Mailbox-Pass-123!"


def a_key(app, key=KEY, expires_at=None):
    with app.app_context():
        get_db().execute("INSERT INTO api_keys (name, key_hash, hint, created_at, expires_at) VALUES ('App', ?, ?, ?, ?)",
                         (hashlib.sha256(key.encode()).hexdigest(), key[-4:], time.time(), expires_at))
        get_db().commit()


def rows(app, sql, *args):
    with app.app_context():
        return [dict(row) for row in get_db().execute(sql, args).fetchall()]


@pytest.fixture
def api(app, client):
    """Calls with the key, as an app would."""
    a_key(app)
    domain_id = authenticated_domain(app, "pineloop.online")
    authenticated_domain(app, "samakiafrica.com", authenticated=False)

    class Api:
        domain = domain_id

        def __getattr__(self, method):
            def call(path, json=None, key=KEY):
                headers = {"Authorization": f"Bearer {key}"} if key else {}
                return getattr(client, method)("/api/s1" + path, json=json, headers=headers)
            return call
    return Api()


# --- the key -------------------------------------------------------------------------------------

def test_without_a_key_nothing_answers(api):
    response = api.get("/domains", key=None)

    assert response.status_code == 401 and "API key" in response.json["error"]


def test_a_wrong_or_expired_key_is_turned_away(api, app):
    assert api.get("/domains", key="sm_" + "x" * 48).status_code == 401
    a_key(app, "sm_" + "e" * 48, expires_at=1)
    assert api.get("/domains", key="sm_" + "e" * 48).status_code == 401


def test_the_admins_login_is_no_key(api, login, client):
    login()   # (the panel's session cookie: never enough on its own, so no page can call the API for it)

    assert client.get("/api/s1/domains").status_code == 401


def test_a_key_is_marked_as_used(api, app):
    api.get("/domains")

    assert rows(app, "SELECT last_used_at FROM api_keys")[0]["last_used_at"] > time.time() - 60


def test_too_many_wrong_keys_make_the_caller_wait(api):
    for _ in range(10):
        assert api.get("/domains", key="sm_wrong").status_code == 401

    response = api.get("/domains")   # (even the right one, for a while)

    assert response.status_code == 429 and "Retry-After" in response.headers


def test_unknown_calls_answer_in_json(api):
    assert api.get("/nothing-here").status_code == 404 and "error" in api.get("/nothing-here").json
    assert api.put("/senders").status_code == 405 and "error" in api.put("/senders").json


def test_a_body_has_to_be_json(api, client):
    response = client.post("/api/s1/senders", data="name=x", headers={"Authorization": f"Bearer {KEY}"})

    assert response.status_code == 400 and "JSON" in response.json["error"]


# --- domains -------------------------------------------------------------------------------------

def test_every_domain_is_listed_saying_whether_it_is_authenticated(api):
    """(an app makes senders and mailboxes at the authenticated ones)"""
    assert api.get("/domains").json == {"domains": [{"name": "pineloop.online", "authenticated": True},
                                                    {"name": "samakiafrica.com", "authenticated": False}]}


# --- senders -------------------------------------------------------------------------------------

def test_a_sender_is_added(api, app):
    response = api.post("/senders", {"name": "PineLoop INC", "email": "no-reply@pineloop.online"})

    assert response.status_code == 201
    sender = response.json["sender"]
    assert {key: sender[key] for key in ("name", "email", "domain", "has_mailbox")} == {
        "name": "PineLoop INC", "email": "no-reply@pineloop.online", "domain": "pineloop.online", "has_mailbox": False}
    assert rows(app, "SELECT name, email FROM senders") == [{"name": "PineLoop INC", "email": "no-reply@pineloop.online"}]


@pytest.mark.parametrize("body, problem", [
    ({"email": "no-reply@pineloop.online"}, "Give the sender a name"),
    ({"name": "Samaki", "email": "hi@samakiafrica.com"}, "samakiafrica.com isn't authenticated yet"),
    ({"name": "Nobody", "email": "hi@elsewhere.com"}, "elsewhere.com isn't one of your domains"),
    ({"name": "Bad", "email": "not an address"}, "Type the part of the address before the @"),
])
def test_a_sender_is_checked_as_in_the_panel(api, app, body, problem):
    response = api.post("/senders", body)

    assert response.status_code == 400 and problem in response.json["error"]
    assert rows(app, "SELECT * FROM senders") == []


def test_senders_are_listed_read_changed_and_deleted(api, app):
    sender_id = api.post("/senders", {"name": "PineLoop", "email": "hello@pineloop.online"}).json["sender"]["id"]

    assert [sender["email"] for sender in api.get("/senders").json["senders"]] == ["hello@pineloop.online"]
    assert api.get(f"/senders/{sender_id}").json["sender"]["name"] == "PineLoop"
    changed = api.patch(f"/senders/{sender_id}", {"name": "PineLoop INC"})
    assert changed.status_code == 200 and changed.json["sender"]["name"] == "PineLoop INC"
    assert changed.json["sender"]["email"] == "hello@pineloop.online"   # (what isn't sent stays as it is)
    assert api.delete(f"/senders/{sender_id}").json == {"deleted": True}
    assert rows(app, "SELECT * FROM senders") == []
    assert api.get(f"/senders/{sender_id}").status_code == 404


def test_a_sender_with_a_mailbox_keeps_its_address_and_stays(api, app):
    a_sender(app, api.domain, "ceo@pineloop.online")
    a_mailbox(app, "ceo@pineloop.online", api.domain)
    sender_id = rows(app, "SELECT id FROM senders")[0]["id"]

    moved = api.patch(f"/senders/{sender_id}", {"email": "boss@pineloop.online"})
    deleted = api.delete(f"/senders/{sender_id}")

    assert moved.status_code == 400 and "has a mailbox" in moved.json["error"]
    assert deleted.status_code == 400 and "Delete its mailbox first" in deleted.json["error"]
    assert rows(app, "SELECT email FROM senders") == [{"email": "ceo@pineloop.online"}]


# --- mailboxes -----------------------------------------------------------------------------------

def test_a_mailbox_is_made_with_every_option_and_its_sender_in_one_call(api, app):
    response = api.post("/mailboxes", {
        "email": "sales@pineloop.online", "name": "Sales Team", "password": PASSWORD, "storage": "15 GB",
        "send_limit_mb": 25, "disable_delete": {"webmail": True, "apps": False},
        "aliases": ["orders@pineloop.online", "shop@pineloop.online"]})

    assert response.status_code == 201
    mailbox = response.json["mailbox"]
    assert {key: mailbox[key] for key in ("email", "name", "domain", "storage", "storage_bytes", "send_limit_mb",
                                          "disable_delete", "aliases")} == {
        "email": "sales@pineloop.online", "name": "Sales Team", "domain": "pineloop.online", "storage": "15 GB",
        "storage_bytes": 15 * 1024 ** 3, "send_limit_mb": 25, "disable_delete": {"webmail": True, "apps": False},
        "aliases": ["orders@pineloop.online", "shop@pineloop.online"]}
    assert "password" not in str(mailbox).lower()
    assert rows(app, "SELECT name, email FROM senders") == [{"name": "Sales Team", "email": "sales@pineloop.online"}]
    stored = rows(app, "SELECT * FROM mailboxes")[0]
    assert mail_password.password_ok(stored["password_hash"], PASSWORD)
    assert (stored["no_delete_webmail"], stored["no_delete_apps"]) == (1, 0)


def test_a_mailbox_for_a_sender_already_there_needs_only_its_address(api, app):
    a_sender(app, api.domain, "ceo@pineloop.online")

    response = api.post("/mailboxes", {"email": "ceo@pineloop.online", "password": PASSWORD, "storage": "500 MB"})

    assert response.status_code == 201
    mailbox = response.json["mailbox"]
    assert mailbox["storage"] == "500 MB" and mailbox["send_limit_mb"] == 50   # (the panel's start)
    assert mailbox["disable_delete"] == {"webmail": False, "apps": False} and mailbox["aliases"] == []


@pytest.mark.parametrize("change, problem", [
    ({"email": "nobody@pineloop.online", "name": None}, "isn't a sender yet"),
    ({"email": "x@samakiafrica.com", "name": "X"}, "samakiafrica.com isn't authenticated yet"),
    ({"password": "short"}, "The password"),
    ({"storage": "lots"}, "storage"),
    ({"storage": None}, "storage"),
    ({"send_limit_mb": 500}, "1 to 100 MB"),
    ({"disable_delete": {"webmail": "yes"}}, "true or false"),
    ({"aliases": ["info@samakiafrica.com"]}, "samakiafrica.com isn't one of your authenticated domains"),
    ({"aliases": ["sales@pineloop.online"]}, "sales@pineloop.online"),
    ({"aliases": "info@pineloop.online"}, "a list"),
])
def test_a_mailbox_is_checked_as_in_the_panel_and_nothing_half_made(api, app, change, problem):
    body = {"email": "sales@pineloop.online", "name": "Sales", "password": PASSWORD, "storage": "1 GB", **change}

    response = api.post("/mailboxes", body)

    assert response.status_code == 400 and problem in response.json["error"]
    for table in ("senders", "mailboxes", "mailbox_aliases"):
        assert rows(app, f"SELECT * FROM {table}") == [], table


def test_mailboxes_are_listed_and_read(api, app):
    api.post("/mailboxes", {"email": "sales@pineloop.online", "name": "Sales", "password": PASSWORD, "storage": "2 GB",
                            "aliases": ["orders@pineloop.online"]})
    mailbox_id = rows(app, "SELECT id FROM mailboxes")[0]["id"]

    listed = api.get("/mailboxes").json["mailboxes"]
    one = api.get(f"/mailboxes/{mailbox_id}").json["mailbox"]

    assert [box["email"] for box in listed] == ["sales@pineloop.online"]
    assert one["aliases"] == ["orders@pineloop.online"] and one["storage"] == "2 GB" and one["name"] == "Sales"
    assert api.get("/mailboxes/999").status_code == 404


def test_a_mailbox_is_changed(api, app):
    a_sender(app, api.domain, "ceo@pineloop.online")
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", api.domain)

    response = api.patch(f"/mailboxes/{mailbox_id}", {"password": PASSWORD, "storage": "20 GB", "send_limit_mb": 10,
                                                      "disable_delete": {"apps": True}})

    assert response.status_code == 200
    mailbox = response.json["mailbox"]
    assert mailbox["storage"] == "20 GB" and mailbox["send_limit_mb"] == 10
    assert mailbox["disable_delete"] == {"webmail": False, "apps": True}   # (what isn't sent stays as it is)
    stored = rows(app, "SELECT * FROM mailboxes")[0]
    assert mail_password.password_ok(stored["password_hash"], PASSWORD) and stored["password_version"] == 2


def test_a_change_is_checked_and_all_or_nothing(api, app):
    a_sender(app, api.domain, "ceo@pineloop.online")
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", api.domain)

    response = api.patch(f"/mailboxes/{mailbox_id}", {"storage": "20 GB", "send_limit_mb": 0})

    assert response.status_code == 400 and "1 to 100 MB" in response.json["error"]
    assert rows(app, "SELECT quota_bytes FROM mailboxes")[0]["quota_bytes"] == 1024 ** 3


def test_a_forgotten_password_is_reset_by_the_mailboxs_address(api, app):
    """(an app helping someone who forgot theirs: the address, and the new password twice)"""
    a_sender(app, api.domain, "ceo@pineloop.online")
    a_mailbox(app, "ceo@pineloop.online", api.domain)

    response = api.post("/mailboxes/password", {"email": "CEO@pineloop.online", "password": PASSWORD,
                                                "confirm_password": PASSWORD})

    assert response.status_code == 200 and response.json["mailbox"]["email"] == "ceo@pineloop.online"
    stored = rows(app, "SELECT * FROM mailboxes")[0]
    # a new version: the webmail and the mail apps signed in with the old one ask for the new one
    assert mail_password.password_ok(stored["password_hash"], PASSWORD) and stored["password_version"] == 2


@pytest.mark.parametrize("body, status, problem", [
    ({"email": "ceo@pineloop.online", "password": PASSWORD, "confirm_password": PASSWORD + "x"}, 400, "don't match"),
    ({"email": "ceo@pineloop.online", "password": "short", "confirm_password": "short"}, 400, "The password"),
    ({"email": "ceo@pineloop.online", "password": PASSWORD}, 400, "confirm_password is missing"),
    ({"email": "nobody@pineloop.online", "password": PASSWORD, "confirm_password": PASSWORD}, 404, "no mailbox at nobody@pineloop.online"),
])
def test_a_reset_is_checked_and_changes_nothing_when_refused(api, app, body, status, problem):
    a_sender(app, api.domain, "ceo@pineloop.online")
    a_mailbox(app, "ceo@pineloop.online", api.domain)

    response = api.post("/mailboxes/password", body)

    assert response.status_code == status and problem in response.json["error"]
    assert rows(app, "SELECT password_version FROM mailboxes")[0]["password_version"] == 1


def test_aliases_are_added_and_deleted(api, app):
    a_sender(app, api.domain, "ceo@pineloop.online")
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", api.domain)

    added = api.post(f"/mailboxes/{mailbox_id}/aliases", {"email": "boss@pineloop.online"})
    again = api.post(f"/mailboxes/{mailbox_id}/aliases", {"email": "boss@pineloop.online"})

    assert added.status_code == 201 and added.json["mailbox"]["aliases"] == ["boss@pineloop.online"]
    assert again.status_code == 400 and "already an alias" in again.json["error"]
    deleted = api.delete(f"/mailboxes/{mailbox_id}/aliases/boss@pineloop.online")
    assert deleted.status_code == 200 and deleted.json["mailbox"]["aliases"] == []
    assert api.delete(f"/mailboxes/{mailbox_id}/aliases/boss@pineloop.online").status_code == 404


def test_a_mailbox_is_deleted_with_its_aliases_and_its_sender_stays(api, app):
    a_sender(app, api.domain, "ceo@pineloop.online")
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", api.domain, aliases=["boss@pineloop.online"])

    response = api.delete(f"/mailboxes/{mailbox_id}")

    assert response.status_code == 200 and response.json == {"deleted": True}
    assert rows(app, "SELECT * FROM mailboxes") == [] and rows(app, "SELECT * FROM mailbox_aliases") == []
    assert rows(app, "SELECT email FROM senders") == [{"email": "ceo@pineloop.online"}]


def test_changes_reach_the_mail_engine(api, app, monkeypatch):
    from someless.engine import sync
    synced = []
    monkeypatch.setattr(sync, "after_change", lambda: synced.append(True))

    api.post("/senders", {"name": "PineLoop", "email": "hello@pineloop.online"})

    assert synced
