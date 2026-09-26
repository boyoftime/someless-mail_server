import html
import json
import re

import pytest

from someless.db import get_db


def text(response):
    return html.unescape(response.get_data(as_text=True))


def plain(page):
    return re.sub(r"<[^>]+>", "", page)


def a_domain(app, name="pineloop.online", authenticated=True):
    """A domain as the Domains page leaves it: added, and (maybe) authenticated."""
    with app.app_context():
        db = get_db()
        domain_id = db.execute("INSERT INTO domains (name, authenticated, added_at) VALUES (?, ?, 0)",
                               (name, 1 if authenticated else 0)).lastrowid
        checks = {key: {"state": "found" if authenticated else "missing", "detail": ""}
                  for key in ["code", "a", "spf", "dkim", "dmarc"]}
        db.execute("INSERT INTO domain_keys (domain_id, code, dkim_selector, dkim_private, dkim_public, checks)"
                   " VALUES (?, 'c', 'someless', 'p', 'k', ?)", (domain_id, json.dumps(checks)))
        db.commit()
        return domain_id


def add(client, name="PineLoop INC", email="no-reply@pineloop.online"):
    return client.post("/senders", data={"name": name, "email": email})


def senders_in_db(app):
    with app.app_context():
        return get_db().execute("SELECT * FROM senders ORDER BY id").fetchall()


def test_senders_need_login(client):
    assert client.get("/senders").headers["Location"] == "/login"
    assert client.get("/senders/new").headers["Location"] == "/login"


def test_the_menu_has_senders(client, login):
    login()

    for path in ["/senders", "/senders/new"]:
        page = text(client.get(path))
        menu = page[page.index('<dialog class="side-menu"'):page.index("</dialog>")]
        assert re.search(r'<a [^>]*href="/senders"[^>]*aria-current="page"', menu), path


def test_no_senders_yet(client, login):
    login()

    page = text(client.get("/senders"))

    assert "<title>Senders | Someless Mail</title>" in page
    assert "No senders yet" in plain(page)
    assert re.search(r'<a class="button add-button" href="/senders/new"', page)  # Add sender, on the right


def test_without_an_authenticated_domain_there_is_no_form(client, login, app):
    a_domain(app, "cloudnix.net", authenticated=False)
    login()

    page = text(client.get("/senders/new"))

    assert "Authenticate a domain first" in plain(page)
    assert 'href="/domains"' in page[page.index('class="page-header'):]
    assert 'name="email"' not in page


def test_the_add_sender_page_shows_how_it_looks(client, login, app):
    a_domain(app)
    login()

    page = text(client.get("/senders/new"))

    assert "<title>Add sender | Someless Mail</title>" in page
    assert 'name="name"' in page and 'name="email"' in page
    assert "data-preview-name" in page and "data-preview-email" in page  # the phone, filled in as you type
    assert "pineloop.online" in plain(page)  # where addresses can be


def test_a_sender_at_an_authenticated_domain_is_added(client, login, app):
    domain_id = a_domain(app)
    login()

    response = add(client)

    assert response.headers["Location"] == "/senders"
    sender = senders_in_db(app)[0]
    assert (sender["name"], sender["email"], sender["domain_id"]) == ("PineLoop INC", "no-reply@pineloop.online", domain_id)
    page = text(client.get("/senders"))
    assert "PineLoop INC <no-reply@pineloop.online> was added." in page
    row = plain(page[page.index('class="sender-row'):])
    assert "PineLoop INC" in row and "no-reply@pineloop.online" in row and "Ready" in row
    assert "DKIM" in row and "DMARC" in row


def test_a_sender_at_a_domain_not_authenticated_yet_is_turned_away(client, login, app):
    a_domain(app)
    a_domain(app, "cloudnix.net", authenticated=False)
    login()

    response = add(client, email="hello@cloudnix.net")

    assert response.status_code == 400
    page = text(response)
    assert "cloudnix.net isn't authenticated yet" in page and "come back" in page
    assert 'value="hello@cloudnix.net"' in page  # kept as typed
    assert senders_in_db(app) == []


@pytest.mark.parametrize("name, email, problem", [
    ("Shop", "hello@elsewhere.com", "elsewhere.com isn't one of your domains"),
    ("Shop", "not an address", "Type an email address"),
    ("", "hello@pineloop.online", "Give the sender a name"),
])
def test_a_sender_needs_a_name_and_an_address_at_one_of_the_domains(client, login, app, name, email, problem):
    a_domain(app)
    login()

    response = add(client, name=name, email=email)

    assert response.status_code == 400 and problem in text(response)
    assert senders_in_db(app) == []


def test_an_address_is_added_once(client, login, app):
    a_domain(app)
    login()
    add(client)

    response = add(client, name="Again", email="No-Reply@PineLoop.Online")

    assert response.status_code == 400 and "already a sender" in text(response)


def test_the_domain_part_is_written_the_way_the_domain_is(client, login, app):
    a_domain(app)
    login()

    add(client, email="Hello@PineLoop.Online")

    assert senders_in_db(app)[0]["email"] == "Hello@pineloop.online"


def test_a_sender_can_be_changed(client, login, app):
    a_domain(app)
    login()
    add(client)
    sender_id = senders_in_db(app)[0]["id"]

    assert 'value="PineLoop INC"' in text(client.get(f"/senders/{sender_id}/edit"))
    response = client.post(f"/senders/{sender_id}", data={"name": "PineLoop", "email": "news@pineloop.online"})

    assert response.headers["Location"] == "/senders"
    sender = senders_in_db(app)[0]
    assert (sender["name"], sender["email"]) == ("PineLoop", "news@pineloop.online")


def test_a_sender_can_be_deleted(client, login, app):
    a_domain(app)
    login()
    add(client)

    client.post(f"/senders/{senders_in_db(app)[0]['id']}/delete")

    assert senders_in_db(app) == []
    assert "PineLoop INC <no-reply@pineloop.online> was deleted." in text(client.get("/senders"))


def test_deleting_a_domain_deletes_its_senders(client, login, app):
    domain_id = a_domain(app)
    login()
    add(client)

    client.post(f"/domains/{domain_id}/delete")

    assert senders_in_db(app) == []


def test_a_sender_whose_domain_is_no_longer_authenticated_says_so(client, login, app):
    domain_id = a_domain(app)
    login()
    add(client)
    with app.app_context():
        get_db().execute("UPDATE domains SET authenticated = 0 WHERE id = ?", (domain_id,))
        get_db().commit()

    row = plain(text(client.get("/senders")))

    assert "Domain not authenticated" in row
