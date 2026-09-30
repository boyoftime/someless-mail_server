"""More than one mailbox in the webmail (webmail/accounts.py): each mailbox keeps its own list of
the others it added, by signing in to each once; the account card lists them, and one tap switches.
Each tab keeps the account it shows in its address (/u/<id>/...), so switching in one tab never
mixes up another. The engine is the made-up one (jmap_fake.py)."""
import html
import re

import pytest

from someless import mail_password
from someless.db import get_db
from someless.webmail import accounts, create_webmail_app
from jmap_fake import FakeJmap
from test_engine_sync import a_mailbox, authenticated_domain

PASSWORD = "Mailbox-Pass-1!"
JSON = {"Accept": "application/json"}
PAGE = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}   # (a browser opening a page)


@pytest.fixture
def jmap():
    return FakeJmap()


@pytest.fixture
def webmail(app, jmap):
    return create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "WTF_CSRF_ENABLED": False,
                               "JMAP": lambda email: jmap})


@pytest.fixture
def boxes(app):
    """Three mailboxes at pineloop.online, all with the same password: {local part: id}."""
    domain_id = authenticated_domain(app)
    hashed = mail_password.hash_password(PASSWORD)
    return {local: a_mailbox(app, f"{local}@pineloop.online", domain_id, password_hash=hashed)
            for local in ("ceo", "info", "sales")}


def text(response):
    return html.unescape(response.get_data(as_text=True))


def sign_in(client, local="ceo"):
    return client.post("/login", data={"email": f"{local}@pineloop.online", "password": PASSWORD})


def add(client, local, password=PASSWORD, at=""):
    return client.post(f"{at}/login", data={"add": "1", "email": f"{local}@pineloop.online", "password": password})


def listed(page):
    """The accounts on the account card: [(address, active?)]."""
    return [(email, bool(active)) for email, active in
            re.findall(r'<a class="wm-switch-account[^"]*"[^>]*data-email="([^"]+)"[^>]*?( aria-current="true")?>', page)]


@pytest.fixture
def ceo(webmail, boxes):
    client = webmail.test_client()
    sign_in(client)
    return client


def test_another_account_is_added_by_signing_in_to_it(ceo, boxes):
    page = text(ceo.get("/login?add=1"))
    assert "Add another account" in page and 'name="add" value="1"' in page

    response = add(ceo, "info")

    assert response.status_code == 302 and response.headers["Location"] == f"/u/{boxes['info']}/"
    page = text(ceo.get(f"/u/{boxes['info']}/mail/inbox"))
    assert "info@pineloop.online" in page.split('class="wm-account-email"')[1][:200]   # (the card: info's)
    assert listed(page) == [("ceo@pineloop.online", False), ("info@pineloop.online", True)]


def test_each_tab_keeps_its_own_account(ceo, boxes):
    add(ceo, "info")

    as_ceo = text(ceo.get(f"/u/{boxes['ceo']}/mail/inbox"))
    as_info = text(ceo.get(f"/u/{boxes['info']}/mail/inbox"))

    assert dict(listed(as_ceo))["ceo@pineloop.online"] and dict(listed(as_info))["info@pineloop.online"]
    # its links, forms and calls all carry its account
    assert f'href="/u/{boxes["info"]}/settings' in as_info and f'action="/u/{boxes["info"]}/logout"' in as_info
    assert f'data-live-url="/u/{boxes["info"]}/live"' in as_info


def test_a_plain_address_opens_the_account_used_last(ceo, boxes):
    add(ceo, "info")
    ceo.get(f"/u/{boxes['ceo']}/mail/inbox", headers=PAGE)   # (a tab on ceo@, opened after)
    ceo.get(f"/u/{boxes['info']}/list/inbox", headers=JSON)   # (and info@'s tab, asking for more of its list)

    response = ceo.get("/mail/inbox")

    assert response.status_code == 302 and response.headers["Location"] == f"/u/{boxes['ceo']}/mail/inbox"


def test_with_one_account_addresses_stay_as_they_were(ceo):
    page = ceo.get("/mail/inbox")

    assert page.status_code == 200 and "Add another account" in text(page)
    assert listed(text(page)) == [("ceo@pineloop.online", True)]


def test_each_account_keeps_its_own_list(webmail, ceo, boxes):
    add(ceo, "info")
    add(ceo, "sales", at=f"/u/{boxes['info']}")   # (added while on info@: to the list of the one signed in)

    elsewhere = webmail.test_client()   # another browser: signed in to info@ itself
    sign_in(elsewhere, "info")
    alone = text(elsewhere.get("/mail/inbox"))
    ceo_again = webmail.test_client()   # and one signed in to ceo@: its list comes with it
    sign_in(ceo_again)
    all_three = text(ceo_again.get(f"/u/{boxes['ceo']}/mail/inbox"))

    assert listed(alone) == [("info@pineloop.online", True)]
    assert [email for email, _ in listed(all_three)] == ["ceo@pineloop.online", "info@pineloop.online", "sales@pineloop.online"]


def test_a_wrong_password_adds_nothing(ceo, boxes):
    response = add(ceo, "info", password="wrong")

    assert response.status_code == 400 and "Add another account" in text(response)
    assert listed(text(ceo.get("/mail/inbox"))) == [("ceo@pineloop.online", True)]


def test_adding_one_already_on_the_list_switches_to_it(ceo, boxes):
    add(ceo, "info")

    again = add(ceo, "info")
    own = add(ceo, "ceo")

    assert again.headers["Location"] == f"/u/{boxes['info']}/" and own.headers["Location"] == f"/u/{boxes['ceo']}/"
    assert len(listed(text(ceo.get(f"/u/{boxes['ceo']}/mail/inbox")))) == 2


def test_the_list_holds_five_at_most(app, webmail, ceo, boxes):
    domain_id = get_domain(app)
    hashed = mail_password.hash_password(PASSWORD)
    for local in ("a", "b"):
        a_mailbox(app, f"{local}@pineloop.online", domain_id, password_hash=hashed)
    for local in ("info", "sales", "a", "b"):
        assert add(ceo, local).status_code == 302
    a_mailbox(app, "c@pineloop.online", domain_id, password_hash=hashed)

    response = add(ceo, "c")

    assert response.status_code == 400 and f"up to {accounts.MOST} accounts" in text(response)


def get_domain(app):
    with app.app_context():
        return get_db().execute("SELECT id FROM domains").fetchone()["id"]


def test_an_account_whose_password_changed_drops_off(app, ceo, boxes):
    add(ceo, "info")
    with app.app_context():
        get_db().execute("UPDATE mailboxes SET password_version = password_version + 1 WHERE id = ?", (boxes["info"],))
        get_db().commit()

    page = ceo.get(f"/u/{boxes['info']}/mail/inbox")
    call = ceo.post(f"/u/{boxes['info']}/do", json={"action": "read", "ids": []}, headers=JSON)

    assert page.status_code == 302 and page.headers["Location"] == "/"
    assert call.status_code == 401 and call.get_json()["login"] == "/"
    assert listed(text(ceo.get(f"/u/{boxes['ceo']}/mail/inbox"))) == [("ceo@pineloop.online", True)]


def test_an_account_can_be_taken_off_the_list(ceo, boxes):
    add(ceo, "info")

    answer = ceo.post(f"/u/{boxes['ceo']}/accounts/{boxes['info']}/remove", headers=JSON).get_json()

    assert answer["message"] == "info@pineloop.online was taken off this list."
    assert listed(text(ceo.get(f"/u/{boxes['ceo']}/mail/inbox"))) == [("ceo@pineloop.online", True)]


def test_the_account_signed_in_with_stays_on_its_list(ceo, boxes):
    response = ceo.post(f"/accounts/{boxes['ceo']}/remove", headers=JSON)

    assert response.status_code == 400


def test_each_accounts_unread_mail_is_counted(ceo, boxes, jmap):
    add(ceo, "info")
    jmap.add(unread=True)

    counts = ceo.get(f"/u/{boxes['ceo']}/accounts/unread", headers=JSON).get_json()

    assert counts == {str(boxes["ceo"]): 1, str(boxes["info"]): 1}   # (the made-up engine is one mailbox for all)


def test_logging_out_ends_them_all(ceo, boxes):
    add(ceo, "info")

    ceo.post(f"/u/{boxes['info']}/logout")

    assert ceo.get(f"/u/{boxes['ceo']}/mail/inbox").headers["Location"].endswith("/login")
    assert ceo.get(f"/u/{boxes['info']}/mail/inbox").headers["Location"].endswith("/login")


def test_the_account_menus_links_are_plain_rows(webmail):
    """(Settings and Add another account: no link underline, rows like the others)"""
    css = webmail.test_client().get("/static/css/webmail-app.css").get_data(as_text=True)
    assert re.search(r"\.wm-account-row \{[^}]*text-decoration: none", css)
    assert re.search(r"\.wm-switch-account \{[^}]*text-decoration: none", css)


def test_the_scripts_find_the_tabs_account_in_its_address(webmail):
    core = webmail.test_client().get("/static/js/webmail-core.js").get_data(as_text=True)
    nav = webmail.test_client().get("/static/js/webmail-nav.js").get_data(as_text=True)
    assert "wm.root" in core and r"\/u\/\d+" in core
    assert r"(\/u\/\d+)?" in nav   # (a folder's address with the account before it is still the mail's)
