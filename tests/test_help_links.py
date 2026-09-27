"""Need help? Links to share a domain's records with a developer or IT (help_links.py): a page of
its own, with or without a password, until it expires, is deleted, or authenticates the domain."""
import html
import re

import pytest

from someless.db import get_db
from test_domain_records import add_domain, all_right, client, dns  # noqa: F401 (fixtures: the panel by its public address, a made-up DNS)


def text(response):
    return html.unescape(response.get_data(as_text=True))


def create(client, domain_id, password_on=False, password="", expires="7d"):
    data = {"expires": expires}
    if password_on:
        data.update(password_on="on", password=password)
    return client.post(f"/domains/{domain_id}/help-links", data=data, headers={"Accept": "application/json"})


def token_of(answer):
    return answer.get_json()["url"].rsplit("/help/", 1)[1]


def links(app):
    with app.app_context():
        return get_db().execute("SELECT * FROM help_links ORDER BY id").fetchall()


@pytest.fixture
def domain_id(client, login):
    login()
    return add_domain(client)


def test_need_help_shows_while_the_domain_isnt_authenticated(app, client, domain_id, dns):
    page = text(client.get(f"/domains/{domain_id}"))
    assert 'data-dialog-open="help-dialog"' in page and 'id="help-dialog"' in page

    all_right(dns, app, domain_id)
    client.post(f"/domains/{domain_id}/check")
    assert 'id="help-dialog"' not in text(client.get(f"/domains/{domain_id}"))


def test_a_link_is_made_and_kept_only_as_a_fingerprint(app, client, domain_id):
    answer = create(client, domain_id, expires="1d")

    assert answer.status_code == 200
    url, token = answer.get_json()["url"], token_of(answer)
    assert url.startswith("http://194.163.167.106:17080/help/") and len(token) >= 30
    (row,) = links(app)
    assert token not in row["token_hash"] and row["password_hash"] is None
    assert 86000 < row["expires_at"] - row["created_at"] <= 86400
    assert url in answer.get_json()["html"]   # shown this once, in the dialog's list


def test_a_link_with_a_password_needs_one(app, client, domain_id):
    assert create(client, domain_id, password_on=True, password="").status_code == 400
    assert create(client, domain_id, password_on=True, password="abc").status_code == 400   # too short

    create(client, domain_id, password_on=True, password="letmein")

    (row,) = links(app)
    assert row["password_hash"] and "letmein" not in row["password_hash"]


def test_a_never_expiring_link(app, client, domain_id):
    create(client, domain_id, expires="never")
    assert links(app)[0]["expires_at"] is None
    assert create(client, domain_id, expires="forever-ish").status_code == 400


def test_the_page_shows_the_records_without_a_login(app, client, domain_id):
    token = token_of(create(client, domain_id))
    visitor = app.test_client()   # the developer: not logged in

    page = text(visitor.get(f"/help/{token}"))

    assert "Set up example.com" in page and "Someless Mail" in page
    for key in ("code", "a", "spf", "dkim", "dmarc", "mx"):
        assert f'id="record-{key}"' in page, key
    assert f'action="/help/{token}/check"' in page
    assert "side-menu" not in page   # nothing of the panel
    assert links(app)[0]["opens"] == 1 and links(app)[0]["opened_at"]


def test_the_dialog_follows_each_link(app, client, domain_id):
    token = token_of(create(client, domain_id))
    listing = client.get(f"/domains/{domain_id}/help-links").get_json()["html"]
    assert "Not opened yet" in listing

    app.test_client().get(f"/help/{token}")

    assert "Opened" in client.get(f"/domains/{domain_id}/help-links").get_json()["html"]


def test_a_password_link_asks_for_it_first(app, client, domain_id):
    token = token_of(create(client, domain_id, password_on=True, password="letmein"))
    visitor = app.test_client()

    page = text(visitor.get(f"/help/{token}"))
    assert 'name="password"' in page and 'id="record-spf"' not in page

    wrong = visitor.post(f"/help/{token}/unlock", data={"password": "nope"})
    assert wrong.status_code == 400
    assert visitor.post(f"/help/{token}/unlock", data={"password": "letmein"}).headers["Location"] == f"/help/{token}"
    assert 'id="record-spf"' in text(visitor.get(f"/help/{token}"))


def test_five_wrong_passwords_lock_the_link_for_a_while(app, client, domain_id):
    token = token_of(create(client, domain_id, password_on=True, password="letmein"))
    visitor = app.test_client()
    for _ in range(5):
        visitor.post(f"/help/{token}/unlock", data={"password": "nope"})

    locked = visitor.post(f"/help/{token}/unlock", data={"password": "letmein"})

    assert locked.status_code == 429 and "Too many tries" in text(locked)


def test_checking_from_the_link_authenticates_and_closes_it(app, client, domain_id, dns):
    token = token_of(create(client, domain_id))
    visitor = app.test_client()
    all_right(dns, app, domain_id)

    response = visitor.post(f"/help/{token}/check")

    assert response.headers["Location"] == f"/help/{token}"
    page = text(visitor.get(f"/help/{token}"))
    assert "example.com is authenticated" in page and "data-celebrate" in page
    assert 'id="record-spf"' not in page   # closed: nothing left to do
    with app.app_context():
        assert get_db().execute("SELECT authenticated FROM domains WHERE id = ?", (domain_id,)).fetchone()[0] == 1
    assert links(app)[0]["authenticated_at"]
    assert "data-celebrate" not in text(visitor.get(f"/help/{token}"))   # once, right after
    assert "Authenticated" in client.get(f"/domains/{domain_id}/help-links").get_json()["html"]


def test_a_check_that_finds_something_missing_says_what(app, client, domain_id):
    token = token_of(create(client, domain_id))
    visitor = app.test_client()

    visitor.post(f"/help/{token}/check")

    page = text(visitor.get(f"/help/{token}"))
    assert 'data-board="error"' in page and "Still to add or fix" in page
    assert 'class="dns-status is-missing"' in page


def test_checks_from_a_link_wait_half_a_minute(app, client, domain_id, monkeypatch):
    from someless import domain_records
    token = token_of(create(client, domain_id))
    visitor = app.test_client()
    visitor.post(f"/help/{token}/check")
    looks = []
    monkeypatch.setattr(domain_records, "look", lambda *args: looks.append(args))

    visitor.post(f"/help/{token}/check")

    assert looks == [] and "a moment ago" in text(visitor.get(f"/help/{token}"))


def test_an_expired_or_deleted_link_says_to_ask_again(app, client, domain_id, monkeypatch):
    import time
    expiring = token_of(create(client, domain_id, expires="1h"))
    deleted = token_of(create(client, domain_id))
    later = time.time() + 3601
    monkeypatch.setattr(time, "time", lambda: later)
    link_id = links(app)[1]["id"]

    answer = client.post(f"/domains/{domain_id}/help-links/{link_id}/delete", headers={"Accept": "application/json"})

    assert answer.status_code == 200 and len(links(app)) == 1
    visitor = app.test_client()
    for token in (expiring, deleted, "made-up"):
        page = visitor.get(f"/help/{token}")
        assert page.status_code in (404, 410) and "Ask for a new link" in text(page), token
    assert "Expired" in client.get(f"/domains/{domain_id}/help-links").get_json()["html"]


def test_links_are_the_admins_to_make_and_delete(app, client, domain_id):
    other = add_domain(client, "other.org")
    create(client, domain_id)
    link_id = links(app)[0]["id"]

    client.post(f"/domains/{other}/help-links/{link_id}/delete")   # not that domain's link
    assert len(links(app)) == 1

    anonymous = app.test_client()
    assert anonymous.post(f"/domains/{domain_id}/help-links", data={"expires": "7d"}).headers["Location"] == "/login"
    assert anonymous.get(f"/domains/{domain_id}/help-links").headers["Location"] == "/login"


def test_a_deleted_domain_takes_its_links(app, client, domain_id):
    create(client, domain_id)

    client.post(f"/domains/{domain_id}/delete")

    assert links(app) == []


def test_the_page_says_how_to_add_records_at_the_provider(app, client, domain_id):
    with app.app_context():
        get_db().execute("UPDATE domains SET provider = 'Namecheap' WHERE id = ?", (domain_id,))
        get_db().commit()
    token = token_of(create(client, domain_id))

    page = text(app.test_client().get(f"/help/{token}"))

    assert "Advanced DNS" in page   # Namecheap's own words
    assert re.search(r"<ol[^>]*class=\"help-steps\"", page)


def test_every_link_shows_its_address_masked(app, client, domain_id):
    first = token_of(create(client, domain_id))
    answer = create(client, domain_id)
    second = token_of(answer)

    listing = client.get(f"/domains/{domain_id}/help-links").get_json()["html"]

    for token in (first, second):
        masked = f"http://194.163.167.106:17080/help/{token[:4]}**********{token[-4:]}"
        assert masked in listing, token
        assert token not in listing
    assert links(app)[0]["shown"].endswith(f"{first[:4]}**********{first[-4:]}")
    assert answer.get_json()["count"] == 2


def test_the_dialog_has_a_tab_for_new_links_and_one_for_the_links(app, client, domain_id):
    create(client, domain_id)

    page = text(client.get(f"/domains/{domain_id}"))

    dialog = page[page.index('id="help-dialog"'):page.index("</dialog>", page.index('id="help-dialog"'))]
    tabs = re.findall(r'<button[^>]*role="tab"[^>]*>(.*?)</button>', dialog, re.S)
    assert [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", tab)).strip() for tab in tabs] == ["New link", "Links 1"]
    assert 'id="help-panel-new"' in dialog and re.search(r'id="help-panel-links"[^>]*hidden', dialog)
