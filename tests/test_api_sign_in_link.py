"""Opening the webmail signed in from an app (POST /api/s1/mailboxes/{id}/sign-in-link): the app's
server asks for a one-time link and sends the person's browser to it. The link works once, within a
minute, for that mailbox alone, and is kept only as a fingerprint (the panel's own tickets,
webmail_site.py). It never shows, changes or checks a password, and every link made and used is
logged."""
import hashlib
import time

import pytest

from someless import webmail_site
from someless.db import get_db
from test_api import PASSWORD, a_key, api, rows  # noqa: F401 (the fixture)
from test_api_login import EMAIL, a_mailbox, webmail_client  # noqa: F401 (the fixture)

GONE = "This sign-in link has expired. Sign in with your password."


def make_link(api, mailbox_id):
    return api.post(f"/mailboxes/{mailbox_id}/sign-in-link")


def token_of(url):
    return url.rsplit("/sso/", 1)[1]


def test_a_link_opens_the_webmail_signed_in(api, app, webmail_client):
    mailbox_id = a_mailbox(app, api)

    answer = make_link(api, mailbox_id)

    assert answer.status_code == 200
    body = answer.json
    assert body["url"].startswith("http://localhost:17090/sso/")   # the webmail, beside the panel
    assert body["expires_in"] == 60
    assert 55 <= time.mktime(time.strptime(body["expires_at"], "%Y-%m-%dT%H:%M:%S+00:00")) - time.mktime(time.gmtime()) <= 61
    assert answer.headers["Cache-Control"] == "no-store"
    opened = webmail_client.get(f"/sso/{token_of(body['url'])}")
    assert opened.status_code == 302 and "/sso/" not in opened.headers["Location"]   # (the token leaves the address bar)
    home = webmail_client.get(opened.headers["Location"])   # (as a login with the password: home, then the inbox)
    assert home.headers["Location"] == "/mail/inbox"
    assert webmail_client.get("/mail/inbox").status_code == 200


def test_the_link_is_at_the_webmails_own_address(api, app):
    mailbox_id = a_mailbox(app, api)
    with app.app_context():
        webmail_site.save("https://webmail.pineloop.online")

    assert make_link(api, mailbox_id).json["url"].startswith("https://webmail.pineloop.online/sso/")


def test_the_token_is_long_random_and_kept_only_as_a_fingerprint(api, app):
    mailbox_id = a_mailbox(app, api)

    first, second = (token_of(make_link(api, mailbox_id).json["url"]) for _ in range(2))

    assert first != second and len(first) >= 43   # (32 random bytes)
    kept = [row["token_hash"] for row in rows(app, "SELECT token_hash FROM webmail_tickets")]
    assert hashlib.sha256(first.encode()).hexdigest() in kept and first not in kept


def test_a_link_works_once(api, app, webmail_client):
    token = token_of(make_link(api, a_mailbox(app, api)).json["url"])
    webmail_client.get(f"/sso/{token}")
    webmail_client.post("/logout")

    again = webmail_client.get(f"/sso/{token}")

    assert again.status_code == 400 and GONE in again.get_data(as_text=True)
    assert EMAIL not in again.get_data(as_text=True)   # (no hint of whose it was)
    assert webmail_client.get("/mail/inbox").headers["Location"] == "/login"


def test_a_link_lasts_a_minute(api, app, webmail_client, monkeypatch):
    token = token_of(make_link(api, a_mailbox(app, api)).json["url"])
    later = time.time() + 61
    monkeypatch.setattr(webmail_site.time, "time", lambda: later)

    answer = webmail_client.get(f"/sso/{token}")

    assert answer.status_code == 400 and GONE in answer.get_data(as_text=True)
    assert EMAIL not in answer.get_data(as_text=True)


def test_a_made_up_link_says_the_same(webmail_client):
    answer = webmail_client.get("/sso/made-up-token")

    assert answer.status_code == 400 and GONE in answer.get_data(as_text=True)


def test_a_link_is_for_its_mailbox_alone(api, app, webmail_client):
    other = a_mailbox(app, api, email="amina@pineloop.online", name="Amina Hassan")
    a_mailbox(app, api)
    webmail_client.get(f"/sso/{token_of(make_link(api, other).json['url'])}")

    with webmail_client.session_transaction() as session:
        assert session["mailbox_id"] == other


def test_no_such_mailbox(api):
    answer = make_link(api, 999)

    assert answer.status_code == 404 and answer.json["error"]


def test_a_disabled_mailbox_gets_no_link(api, app):
    answer = make_link(api, a_mailbox(app, api, disabled=True))

    assert answer.status_code == 409
    assert answer.json == {"error": "This mailbox is disabled: nobody can sign in to it."}
    assert rows(app, "SELECT * FROM webmail_tickets") == []


def test_a_mailbox_disabled_after_its_link_was_made_isnt_opened(api, app, webmail_client):
    mailbox_id = a_mailbox(app, api)
    token = token_of(make_link(api, mailbox_id).json["url"])
    api.patch(f"/mailboxes/{mailbox_id}", json={"disabled": True})

    answer = webmail_client.get(f"/sso/{token}")

    assert answer.status_code == 403
    assert webmail_client.get("/mail/inbox").headers["Location"] == "/login"


def test_it_needs_the_key(api, app):
    assert api.post(f"/mailboxes/{a_mailbox(app, api)}/sign-in-link", key=None).status_code == 401


def test_it_leaves_the_password_and_the_sign_in_lock_alone(api, app, webmail_client):
    mailbox_id = a_mailbox(app, api)
    before = rows(app, "SELECT password_hash, password_version FROM mailboxes WHERE id = ?", mailbox_id)
    webmail_client.get(f"/sso/{token_of(make_link(api, mailbox_id).json['url'])}")

    assert rows(app, "SELECT password_hash, password_version FROM mailboxes WHERE id = ?", mailbox_id) == before
    assert rows(app, "SELECT * FROM webmail_tries") == []
    assert api.post("/mailboxes/login", json={"email": EMAIL, "password": PASSWORD}).json["valid"] is True


def test_every_link_made_and_used_is_logged(api, app, webmail_client):
    mailbox_id = a_mailbox(app, api)
    token = token_of(make_link(api, mailbox_id).json["url"])
    webmail_client.get(f"/sso/{token}", environ_base={"REMOTE_ADDR": "198.51.100.7"})

    logged = rows(app, "SELECT event, mailbox_id, email, api_key_id, api_key_name, address, at FROM sign_in_links ORDER BY id")
    key_id = rows(app, "SELECT id FROM api_keys")[0]["id"]
    assert [(row["event"], row["mailbox_id"], row["email"], row["api_key_id"], row["api_key_name"]) for row in logged] == [
        ("made", mailbox_id, EMAIL, key_id, "App"), ("used", mailbox_id, EMAIL, key_id, "App")]
    assert logged[0]["address"] == "127.0.0.1" and logged[1]["address"] == "198.51.100.7"
    assert all(abs(row["at"] - time.time()) < 60 for row in logged)
    assert not any(token in str(value) for row in logged for value in row.values())   # (never the token)


def test_the_panels_own_tickets_still_work(app, client, login, webmail_client):
    with app.app_context():
        db = get_db()
        domain_id = db.execute("INSERT INTO domains (name, authenticated, added_at) VALUES ('pineloop.online', 1, 0)").lastrowid
        mailbox_id = db.execute("INSERT INTO mailboxes (email, domain_id, quota_bytes, password_hash, created_at)"
                                " VALUES ('ceo@pineloop.online', ?, 1, 'x', 0)", (domain_id,)).lastrowid
        db.commit()
        token = webmail_site.new_ticket(mailbox_id)

    assert webmail_client.get(f"/enter?ticket={token}").status_code == 302
    assert rows(app, "SELECT * FROM sign_in_links") == []   # (the panel's own aren't the API's)


@pytest.mark.parametrize("where", ["page", "text"])
def test_the_guide_has_it(client, login, where):
    if where == "page":
        login()
        guide = client.get("/api-keys/docs").get_data(as_text=True)
    else:
        guide = client.get("/api/s1/docs.md").get_data(as_text=True)

    assert "/mailboxes/{id}/sign-in-link" in guide
    assert "/sso/" in guide and "expires_in" in guide
    assert "This mailbox is disabled: nobody can sign in to it." in guide
