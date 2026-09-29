"""The webmail (someless/webmail): its own little site on port 17090, where a mailbox logs in with
its own address and password, on a page that looks like the panel's login, then reads and sorts
its mail as in PrivateEmail. The mail comes from the mail engine over JMAP: here, a made-up
engine (jmap_fake.py). The Mailboxes page has its login link, to copy or share."""
import datetime
import html
import io
import json
import re
import zipfile

import pytest

from someless import mail_password
from someless.db import get_db
from someless.webmail import create_webmail_app, messages
from jmap_fake import FakeJmap
from test_engine_sync import a_mailbox, authenticated_domain

PASSWORD = "Mailbox-Pass-1!"
JSON = {"Accept": "application/json"}


@pytest.fixture
def jmap():
    """The mailbox's mail on the (made-up) engine."""
    return FakeJmap()


@pytest.fixture
def webmail(app, jmap):
    """The webmail beside the panel: the same data folder, so the same mailboxes."""
    return create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "WTF_CSRF_ENABLED": False,
                               "JMAP": lambda email: jmap})


@pytest.fixture
def mail(webmail):
    return webmail.test_client()


@pytest.fixture
def mailbox(app):
    domain_id = authenticated_domain(app)
    return a_mailbox(app, "ceo@pineloop.online", domain_id, password_hash=mail_password.hash_password(PASSWORD))


@pytest.fixture
def signed_in(mail, mailbox):
    sign_in(mail)
    return mail


def text(response):
    return html.unescape(response.get_data(as_text=True))


def sign_in(mail, email="ceo@pineloop.online", password=PASSWORD):
    return mail.post("/login", data={"email": email, "password": password})


def do(mail, action, ids=None, **extra):
    return mail.post("/do", json={"action": action, "ids": ids, **extra})


def folder_do(mail, key, action, **extra):
    return mail.post(f"/folders/{key}", json={"action": action, **extra})


def key_of(page, name):
    """A folder's key, by its name in the side column."""
    return re.search(rf'data-folder="([^"]+)"[^>]*data-name="{re.escape(name)}"', page).group(1)


def row_ids(page):
    """The messages in the list (or a piece of it), in order: their ids."""
    return re.findall(r'<li class="wm-message[^"]*"\s+style="--i: \d+" data-id="([^"]+)"', page)


def folder_names(page):
    return re.findall(r'<span class="wm-folder-name">([^<]+)</span>', page)


# --- logging in ---

def test_it_answers_its_health_check(mail):
    assert mail.get("/healthz").get_data(as_text=True) == "ok"


def test_it_asks_to_log_in_first(mail):
    assert mail.get("/").headers["Location"] == "/login"
    assert mail.get("/mail/inbox").headers["Location"] == "/login"
    page = text(mail.get("/login"))
    assert "Webmail" in page and 'name="email"' in page and 'name="password"' in page
    assert "side-menu" not in page   # its own site, not the panel


def test_its_scripts_are_told_to_log_in_again(mail, mailbox):
    for response in (mail.get("/list/inbox", headers=JSON), mail.post("/do", json={"action": "read", "ids": ["x"]})):
        assert response.status_code == 401 and response.get_json() == {"problem": "Log in again.", "login": "/login"}


def test_its_login_looks_like_the_panels(mail):
    page = text(mail.get("/login"))

    assert 'class="login-bg"' in page and "img/float/" in page   # the floating mail icons
    assert 'class="auth-card' in page and "Log in to your mailbox" in page
    assert re.search(r'<label[^>]*for="webmail-email"[^>]*>Email</label>', page)
    assert re.search(r'<button class="button button-block"[^>]*type="submit"', page)
    assert "js/webmail-zone.js" in page   # the reader's time zone, for the times in the mail


def test_its_login_link_can_fill_in_the_address(mail):
    page = text(mail.get("/login?email=%20CEO@PineLoop.online"))

    email = re.search(r'<input id="webmail-email"[^>]*>', page).group(0)
    assert 'value="ceo@pineloop.online"' in email and "autofocus" not in email
    assert "autofocus" in re.search(r'<input id="webmail-password"[^>]*>', page).group(0)   # straight to the password


def test_a_mailbox_logs_in_to_its_inbox(mail, mailbox):
    response = sign_in(mail, email=" CEO@PineLoop.online ")

    assert response.headers["Location"] == "/"
    assert mail.get("/").headers["Location"] == "/mail/inbox"
    page = text(mail.get("/mail/inbox"))
    assert "ceo@pineloop.online" in page and 'action="/logout"' in page
    assert "<title>Inbox | Someless Webmail</title>" in page


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

    assert mail.get("/mail/inbox").headers["Location"] == "/login"


def test_a_deleted_mailbox_is_logged_out(app, mail, mailbox):
    sign_in(mail)
    with app.app_context():
        get_db().execute("DELETE FROM mailboxes WHERE id = ?", (mailbox,))
        get_db().commit()

    assert mail.get("/mail/inbox").headers["Location"] == "/login"


def test_log_out(signed_in):
    assert signed_in.post("/logout").headers["Location"] == "/login"
    assert signed_in.get("/mail/inbox").headers["Location"] == "/login"


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


def test_its_scripts_send_the_token_too(app, jmap, mailbox):
    """The mail's scripts send the page's token in a header (webmail-core.js): without it, refused."""
    webmail = create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "JMAP": lambda email: jmap})
    client = webmail.test_client()
    login_page = text(client.get("/login"))
    token = re.search(r'name="csrf_token" [^>]*value="([^"]+)"', login_page).group(1)
    client.post("/login", data={"email": "ceo@pineloop.online", "password": PASSWORD, "csrf_token": token})
    page = text(client.get("/mail/inbox"))
    meta = re.search(r'<meta name="csrf-token" content="([^"]+)">', page).group(1)
    email_id = jmap.add()

    refused = client.post("/do", json={"action": "read", "ids": [email_id]})
    done = client.post("/do", json={"action": "read", "ids": [email_id]}, headers={"X-CSRFToken": meta})

    assert refused.status_code == 400 and "Reload it and try again" in refused.get_json()["problem"]
    assert done.status_code == 200 and "$seen" in jmap.emails[email_id]["keywords"]


def test_a_sign_in_page_left_open_too_long_asks_again_nicely(app):
    """Its form's token runs out after an hour: the page says to sign in again, on its own look."""
    webmail = create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"]})

    response = webmail.test_client().post("/login", data={"email": "ceo@pineloop.online", "password": "x"})

    assert response.status_code == 400
    page = text(response)
    assert "Log in to your mailbox" in page and 'data-board="error"' in page and "Log in again" in page


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


# --- opening a mailbox's webmail from the Mailboxes page: signed in, no password asked ---

def open_webmail(client, mailbox_id):
    return client.post(f"/mailboxes/{mailbox_id}/webmail")


def ticket_of(response):
    location = response.headers["Location"]
    return location, location.split("ticket=", 1)[1]


def test_a_mailbox_card_opens_its_webmail_in_a_new_tab(app, client, login, mailbox):
    login()

    page = text(client.get("/mailboxes"))

    form = re.search(rf'<form [^>]*action="/mailboxes/{mailbox}/webmail"[^>]*>', page).group(0)
    assert 'target="_blank"' in form and "data-full-load" in form


def test_the_panel_sends_the_admin_to_the_webmail_with_a_one_time_ticket(app, client, login, mailbox):
    login()

    location, ticket = ticket_of(open_webmail(client, mailbox))

    assert location.startswith("http://localhost:17090/enter?ticket=")   # the webmail, beside the panel
    with app.app_context():
        stored = get_db().execute("SELECT * FROM webmail_tickets").fetchall()
    assert len(stored) == 1 and ticket not in stored[0]["token_hash"]   # kept only as a fingerprint


def test_the_ticket_signs_the_webmail_in_once(app, client, login, mail, mailbox):
    login()
    _, ticket = ticket_of(open_webmail(client, mailbox))

    response = mail.get(f"/enter?ticket={ticket}")

    assert response.headers["Location"] == "/"   # the ticket leaves the address bar at once
    assert "ceo@pineloop.online" in text(mail.get("/mail/inbox"))
    other = mail.application.test_client()
    again = other.get(f"/enter?ticket={ticket}")
    assert again.status_code == 400 and "Open the webmail from the Mailboxes page again" in text(again)


def test_a_ticket_lasts_a_minute(app, client, login, mail, mailbox, monkeypatch):
    import someless.webmail as webmail_module
    login()
    _, ticket = ticket_of(open_webmail(client, mailbox))
    later = webmail_module.time.time() + 61
    monkeypatch.setattr(webmail_module.time, "time", lambda: later)

    assert mail.get(f"/enter?ticket={ticket}").status_code == 400
    assert mail.get("/enter?ticket=made-up").status_code == 400


def test_the_mailboxes_page_shares_the_webmail_login_link(client, login, mailbox):
    login()

    page = text(client.get("/mailboxes"))

    assert 'data-dialog-open="webmail-link-dialog"' in page
    dialog = page[page.index('id="webmail-link-dialog"'):]
    dialog = dialog[:dialog.index("</dialog>")]
    assert 'data-copy="http://localhost:17090/login"' in dialog   # the webmail, beside the panel
    options = re.findall(r'<option value="([^"]*)"', dialog)
    assert options == ["http://localhost:17090/login", "http://localhost:17090/login?email=ceo@pineloop.online"]
    assert "data-webmail-share" in dialog


def test_the_link_uses_the_webmail_address_from_settings(client, login, mailbox):
    login()
    client.post("/settings/miscellaneous/webmail-address", data={"address": "https://webmail.pineloop.online"})

    page = text(client.get("/mailboxes"))

    assert 'data-copy="https://webmail.pineloop.online/login"' in page


def test_only_the_admin_gets_a_ticket(client, mailbox):
    assert client.post(f"/mailboxes/{mailbox}/webmail").headers["Location"] == "/login"


def test_the_webmail_address_is_set_in_settings(app, client, login, mailbox):
    login()
    page = text(client.get("/settings/miscellaneous"))
    assert "Webmail address" in page and "http://localhost:17090" in page   # until one is set

    response = client.post("/settings/miscellaneous/webmail-address", data={"address": " https://webmail.pineloop.online/ "})

    assert response.headers["Location"] == "/settings/miscellaneous"
    location, _ = ticket_of(open_webmail(client, mailbox))
    assert location.startswith("https://webmail.pineloop.online/enter?ticket=")
    for wrong in ("webmail", "ftp://x.com", "https://", "javascript:alert(1)"):
        assert client.post("/settings/miscellaneous/webmail-address", data={"address": wrong}).status_code == 400, wrong
    client.post("/settings/miscellaneous/webmail-address", data={"address": ""})   # empty: back to beside the panel
    assert ticket_of(open_webmail(client, mailbox))[0].startswith("http://localhost:17090/")


# --- the page ---

def test_the_mail_page_is_laid_out_as_privateemail(signed_in, jmap):
    page = text(signed_in.get("/mail/inbox"))

    assert re.search(r'class="wm-compose"[^>]*>\s*Compose\s*<', page)
    assert 'placeholder="Search mail"' in page and "No mail selected" in page
    assert 'aria-label="Sort and filter"' in page and "Filter and sort emails" in page
    for label in ("Unread", "Favorites", "High Priority", "Newest first", "Oldest first", "Largest first", "Smallest first", "Reset"):
        assert f"<span>{label}</span>" in page or f">{label}<" in page, label
    assert "150 MB" in page and "1 GB" in page   # how full it is, from the engine
    assert '<meta name="csrf-token"' in page


def test_the_account_card_has_the_mailbox_and_log_out(signed_in):
    page = text(signed_in.get("/mail/inbox"))

    card = page[page.index('id="wm-account"'):]
    card = card[:card.index("</section>")]
    assert "ceo@pineloop.online" in card and 'data-copy="ceo@pineloop.online"' in card
    assert 'action="/logout"' in card and "data-theme-switch" in card


def test_the_page_comes_in_smoothly(signed_in, jmap):
    for number in range(3):
        jmap.add(subject=f"Mail {number}")

    page = text(signed_in.get("/mail/inbox"))

    assert re.search(r'<body class="[^"]*\bis-arriving\b', page)
    assert re.search(r'<li class="wm-message[^"]*"\s+style="--i: 1"', page)   # one after another
    assert "js/webmail-first.js" in page   # (another folder comes in quietly)


def shell(page):
    return re.search(r'<div class="wm-shell"[^>]*>', page).group(0)


def test_the_columns_have_dividers_to_drag(signed_in):
    page = text(signed_in.get("/mail/inbox"))

    for name in ("side", "list"):
        handle = re.search(rf'<span class="wm-resize[^"]*"[^>]*data-wm-resize="{name}"[^>]*>', page).group(0)
        assert 'role="separator"' in handle and 'aria-orientation="vertical"' in handle, name
    assert "style=" not in shell(page)   # the widths it starts with (webmail-app.css)


def test_the_columns_keep_the_widths_they_were_dragged_to(signed_in):
    signed_in.set_cookie("wm_columns", "200,400")

    page = text(signed_in.get("/mail/inbox"))

    assert 'style="--wm-side-width: 200px; --wm-list-width: 400px"' in shell(page)


@pytest.mark.parametrize("columns", ["abc", "200", "200,400,500", "20,400", "200,-5", "200,99999", "2e2,400", ""])
def test_widths_that_cant_be_are_left_out(signed_in, columns):
    signed_in.set_cookie("wm_columns", columns)

    assert "style=" not in shell(text(signed_in.get("/mail/inbox")))


def test_the_mail_out_of_reach_is_said_so(signed_in, jmap):
    jmap.down = True

    page = signed_in.get("/mail/inbox")
    answer = signed_in.get("/list/inbox", headers=JSON)

    assert page.status_code == 503 and "Your mail can't be reached right now" in text(page)
    assert "Try again" in text(page) and 'action="/logout"' in text(page)
    assert answer.status_code == 503 and answer.get_json() == {"problem": "Your mail can't be reached right now. Try again in a moment."}


# --- the folders ---

def test_the_folders_are_privateemails(signed_in, jmap):
    page = text(signed_in.get("/mail/inbox"))

    assert folder_names(page) == ["Inbox", "Drafts", "Sent", "Archive", "Spam", "Trash"]   # (the engine's Junk Mail, Deleted Items...)
    assert any(box["role"] == "archive" for box in jmap.mailboxes.values())   # the Archive was made
    assert re.search(r'<div class="wm-folder is-current"[^>]*data-folder="inbox"', page)


def test_a_folder_that_isnt_there_is_not_found(signed_in):
    assert signed_in.get("/mail/f-nope").status_code == 404


def test_the_mailboxs_own_folders_follow_with_theirs_inside(signed_in, jmap):
    inbox = jmap.role("inbox")
    clients = jmap.add_mailbox("Clients", parent=inbox)
    jmap.add_mailbox("Acme", parent=clients)
    jmap.add_mailbox("Receipts")

    page = text(signed_in.get("/mail/inbox"))

    assert folder_names(page) == ["Inbox", "Clients", "Acme", "Drafts", "Sent", "Archive", "Spam", "Trash", "Receipts"]
    acme = re.search(r'<div class="wm-folder[^"]*" style="--depth: (\d)"[^>]*data-name="Acme"', page)
    assert acme.group(1) == "2"
    assert 'data-name="Clients" data-depth="1"' in page and "wm-folder-opener" in page   # its folders fold away


def test_counts_are_unread_but_drafts_counts_all(signed_in, jmap):
    jmap.add(unread=True)
    jmap.add(unread=True)
    jmap.add(unread=False)
    jmap.add(folder="drafts", subject="Draft one")

    page = text(signed_in.get("/mail/inbox"))

    counts = dict(re.findall(r'data-folder="([^"]+)".*?<span class="wm-count"[^>]*>(\d*)</span>', page, re.S))
    assert counts["inbox"] == "2" and counts["drafts"] == "1"
    assert "<title>(2) Inbox | Someless Webmail</title>" in page   # the Inbox's unread, in the tab


def test_each_folders_menu_offers_what_privateemail_does(signed_in, jmap):
    inbox = jmap.role("inbox")
    jmap.add_mailbox("Clients", parent=inbox)
    page = text(signed_in.get("/mail/inbox"))

    def menu(name):
        return re.search(rf'data-name="{name}"[^>]*data-menu="([^"]*)"', page).group(1).split()

    assert menu("Inbox") == ["subfolder", "archive_all", "read_all", "unread_all", "delete_all"]
    assert menu("Drafts") == ["delete_all"]
    assert menu("Sent") == ["read_all", "unread_all", "delete_all"]   # nothing goes in Sent, Drafts or Spam
    assert menu("Spam") == ["read_all", "unread_all", "delete_all"]
    assert menu("Archive") == ["subfolder", "inbox_all", "read_all", "unread_all", "delete_all"]
    assert menu("Trash") == ["subfolder", "read_all", "unread_all", "empty"]
    assert menu("Clients") == ["subfolder", "rename", "archive_all", "to_archive", "read_all", "unread_all", "delete_all", "delete"]


def create(mail, name, parent=None):
    return mail.post("/folders", json={"name": name, "parent": parent})


def test_a_folder_is_made_inside_another(signed_in, jmap):
    answer = create(signed_in, "  Clients  ", "inbox").get_json()

    made = next(box for box in jmap.mailboxes.values() if box["name"] == "Clients")
    assert made["parentId"] == jmap.role("inbox")
    assert answer["key"].startswith("f-") and 'data-name="Clients"' in answer["html"]


@pytest.mark.parametrize("name,problem", [
    ("", "Folder name is required"),
    ("x" * 61, "Folder name max length is 60 symbols"),
    ("a/b", "Not allowed characters were used for the folder name"),
    ("Spam ☢", "Not allowed characters were used for the folder name"),
    ("..", "Not allowed characters were used for the folder name"),
])
def test_a_folder_name_that_cant_be_is_refused(signed_in, jmap, name, problem):
    response = create(signed_in, name, "inbox")

    assert response.status_code == 400 and response.get_json()["problem"] == problem


def test_a_name_taken_there_already_is_refused(signed_in, jmap):
    create(signed_in, "Clients", "inbox")

    again = create(signed_in, "clients", "inbox")
    elsewhere = create(signed_in, "Clients", "archive")
    top = create(signed_in, "Inbox")

    assert again.status_code == 400 and again.get_json()["problem"] == 'A folder named "clients" already exists'
    assert elsewhere.status_code == 200
    assert top.status_code == 400   # the mailbox's own folders' names


def test_folders_go_four_deep_at_most(signed_in, jmap):
    parent = "inbox"
    for name in ("One", "Two", "Three"):
        parent = create(signed_in, name, parent).get_json()["key"]

    too_deep = create(signed_in, "Four", parent)

    assert too_deep.status_code == 400
    assert too_deep.get_json()["problem"] == "Ooops, you cannot create more than 4 levels of subfolders"


@pytest.mark.parametrize("parent", ["drafts", "sent", "spam"])
def test_no_folders_go_in_drafts_sent_or_spam(signed_in, parent):
    assert create(signed_in, "Inside", parent).status_code == 400


def test_a_folder_is_renamed(signed_in, jmap):
    key = create(signed_in, "Clients", "inbox").get_json()["key"]

    answer = folder_do(signed_in, key, "rename", name="Customers").get_json()

    assert answer["message"] == 'Folder "Clients" has been renamed to "Customers"'
    assert 'data-name="Customers"' in answer["html"]


def test_the_mailboxs_own_folders_cant_be_renamed_or_deleted(signed_in):
    assert folder_do(signed_in, "inbox", "rename", name="Other").status_code == 400
    assert folder_do(signed_in, "sent", "delete").status_code == 400
    assert folder_do(signed_in, "trash", "delete_all").status_code == 400   # the Trash is emptied instead


def test_a_folder_moves_to_the_archive_and_back(signed_in, jmap):
    key = create(signed_in, "Clients", "inbox").get_json()["key"]
    jmap.add(folder=key[2:], subject="In clients")

    to_archive = folder_do(signed_in, key, "to_archive").get_json()
    back = folder_do(signed_in, key, "to_inbox").get_json()

    assert to_archive["message"] == 'Moved folder "Clients" and 1 message(s) to "Archive" folder'
    assert back["message"] == 'Moved folder "Clients" and 1 message(s) to "Inbox" folder'
    assert jmap.mailboxes[key[2:]]["parentId"] == jmap.role("inbox")


def test_a_folder_dragged_onto_another_goes_inside_it(signed_in, jmap):
    clients = create(signed_in, "Clients", "inbox").get_json()["key"]
    acme = create(signed_in, "Acme", "inbox").get_json()["key"]

    moved = folder_do(signed_in, acme, "move", to=clients)
    into_itself = folder_do(signed_in, clients, "move", to=clients)

    assert moved.status_code == 200 and jmap.mailboxes[acme[2:]]["parentId"] == clients[2:]
    assert into_itself.status_code == 400 and into_itself.get_json()["problem"] == "A folder can't go inside itself."


def test_a_deleted_folder_goes_to_the_trash_then_for_good(signed_in, jmap):
    key = create(signed_in, "Clients", "inbox").get_json()["key"]
    jmap.add(folder=key[2:])

    first = folder_do(signed_in, key, "delete").get_json()
    second = folder_do(signed_in, key, "delete").get_json()

    assert first["message"] == 'Moved folder "Clients" and 1 message(s) to "Trash" folder'
    assert second["message"] == 'The "Clients" was permanently deleted'
    assert key[2:] not in jmap.mailboxes and not jmap.emails


def test_the_folder_being_looked_at_deleted_for_good_goes_back_to_the_inbox(signed_in, jmap):
    key = create(signed_in, "Clients", "inbox").get_json()["key"]

    to_trash = folder_do(signed_in, key, "delete", current=key).get_json()
    for_good = folder_do(signed_in, key, "delete", current=key).get_json()

    assert to_trash["gone"] is False   # (in the Trash, it's still there to look at)
    assert for_good["gone"] is True


def test_delete_all_messages_moves_them_to_the_trash(signed_in, jmap):
    first, second = jmap.add(), jmap.add()

    answer = folder_do(signed_in, "inbox", "delete_all").get_json()

    assert answer["message"] == 'Moved 2 message(s) to "Trash" folder'
    trash = jmap.role("trash")
    assert all(jmap.emails[email_id]["mailboxIds"] == {trash: True} for email_id in (first, second))


def test_an_empty_folder_says_so(signed_in):
    answer = folder_do(signed_in, "inbox", "delete_all").get_json()

    assert answer["warning"] is True and answer["message"] == 'Folder "Inbox" contains no messages'


def test_emptying_the_trash_deletes_it_all_for_good(signed_in, jmap):
    jmap.add(folder="trash")
    old = create(signed_in, "Old", "trash").get_json()["key"]
    jmap.add(folder=old[2:])

    answer = folder_do(signed_in, "trash", "empty").get_json()

    assert answer["message"] == "Trash has been cleared"
    assert not jmap.emails and old[2:] not in jmap.mailboxes


def test_all_of_a_folder_is_marked_read_or_moved(signed_in, jmap):
    ids = [jmap.add(), jmap.add()]

    folder_do(signed_in, "inbox", "read_all")
    assert all("$seen" in jmap.emails[email_id]["keywords"] for email_id in ids)
    folder_do(signed_in, "inbox", "unread_all")
    assert all("$seen" not in jmap.emails[email_id]["keywords"] for email_id in ids)
    answer = folder_do(signed_in, "inbox", "archive_all").get_json()
    assert answer["message"] == 'All emails moved to "Archive"'


def test_folded_folders_stay_folded(signed_in, jmap):
    key = create(signed_in, "Clients", "inbox").get_json()["key"]
    create(signed_in, "Acme", key)

    folder_do(signed_in, key, "collapse")
    page = text(signed_in.get("/mail/inbox"))

    item = re.search(r'<div class="wm-folder-item[^"]*">\s*<div class="wm-folder[^"]*"[^>]*data-name="Clients"', page).group(0)
    assert "is-collapsed" in item
    folder_do(signed_in, key, "expand")
    assert "is-collapsed" not in text(signed_in.get("/mail/inbox"))


def test_folders_go_by_name_when_asked(signed_in, jmap):
    jmap.add_mailbox("Zebra")
    jmap.add_mailbox("Apple")
    assert folder_names(text(signed_in.get("/mail/inbox")))[-2:] == ["Zebra", "Apple"]   # as they were made

    answer = signed_in.post("/folders/order", json={"by_name": True}).get_json()

    assert answer["by_name"] is True
    assert folder_names(text(signed_in.get("/mail/inbox")))[-2:] == ["Apple", "Zebra"]


def test_a_deleted_mailbox_forgets_how_it_liked_its_mail(app, client, login, signed_in, mailbox):
    signed_in.post("/view/inbox", json={"sort": "oldest", "filters": []})
    login()

    client.post(f"/mailboxes/{mailbox}/delete")

    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM webmail_views").fetchone()[0] == 0


# --- the list ---

def test_the_list_opens_with_the_newest_50(signed_in, jmap):
    ids = [jmap.add(subject=f"Mail {number}", received=f"2026-09-{1 + number // 10:02d}T{number % 10:02d}:00:00Z")
           for number in range(120)]
    newest = list(reversed(ids))

    page = text(signed_in.get("/mail/inbox"))
    second = signed_in.get(re.search(r'data-wm-more data-url="([^"]+)"', page).group(1)).get_json()
    third = signed_in.get(second["next"]).get_json()

    assert row_ids(page) == newest[:50]
    assert row_ids(second["html"]) == newest[50:100] and "is-more" in second["html"]
    assert row_ids(third["html"]) == newest[100:] and third["next"] is None
    assert second["total"] == 120


def test_a_made_up_place_in_the_list_is_refused(signed_in, jmap):
    jmap.add()

    assert signed_in.get("/list/inbox?after=nope").status_code == 400


def test_an_empty_folder_says_no_messages_found(signed_in):
    page = text(signed_in.get("/mail/inbox"))

    assert re.search(r'<div class="wm-list-empty" data-wm-list-empty>', page) and "No messages found" in page


def test_a_row_shows_what_privateemail_shows(signed_in, jmap):
    jmap.add(subject="Budget", sender=("Amina Hassan", "amina@example.com"), text="Numbers for Q4", unread=True,
             flagged=True, important=True, forwarded=True, attachments=[("budget.pdf", "application/pdf", b"%PDF-1.4")])

    page = text(signed_in.get("/mail/inbox"))
    row = page[page.index('<li class="wm-message'):]
    row = row[:row.index("</li>")]

    assert "is-unread" in row and "is-flagged" in row
    assert '<span class="wm-from">Amina Hassan</span>' in row and "Budget" in row and "Numbers for Q4" in row
    for mark in ("High Priority", "Forwarded", "Has attachments", "Favorite"):
        assert f'title="{mark}"' in row, mark
    assert 'href="/mail/inbox/' in row and 'draggable="true"' in row


def test_sent_mail_shows_who_its_to(signed_in, jmap):
    jmap.add(folder="sent", to=(("Musa", "musa@example.com"),))

    page = text(signed_in.get("/mail/sent"))

    assert '<span class="wm-from">Musa</span>' in page


def test_times_are_the_readers_own(signed_in, jmap):
    jmap.add(received="2026-09-28T18:51:00Z")
    signed_in.set_cookie("wm_tz", "Africa/Nairobi")

    page = text(signed_in.get("/mail/inbox"))

    assert re.search(r'<time class="wm-time" title="September 28(, 2026)?, 9:51 PM">', page)


def test_the_time_zone_cookie_is_read_as_the_browser_writes_it(signed_in, jmap):
    """webmail-zone.js writes it encoded (Africa%2FNairobi), as cookies are."""
    jmap.add(received="2026-09-28T18:51:00Z")
    signed_in.set_cookie("wm_tz", "Africa%2FNairobi")

    page = text(signed_in.get("/mail/inbox"))

    assert re.search(r'<time class="wm-time" title="September 28(, 2026)?, 9:51 PM">', page)


def test_times_in_the_list_are_as_privateemail_writes_them(tmp_path):
    now = datetime.datetime(2026, 9, 28, 20, 0, tzinfo=datetime.timezone.utc)
    with create_webmail_app({"TESTING": True, "DATA_DIR": str(tmp_path)}).test_request_context():
        assert messages.list_time("2026-09-28T18:51:00Z", now) == "06:51 PM"
        assert messages.list_time("2026-09-23T08:00:00Z", now) == "Sep 23"
        assert messages.list_time("2025-09-23T08:00:00Z", now) == "Sep 23, 2025"
        assert messages.full_time("2026-09-18T17:34:00Z", now) == "September 18, 5:34 PM"
        assert messages.full_time("2025-09-18T17:34:00Z", now) == "September 18, 2025, 5:34 PM"


def test_sort_and_filter_are_each_folders_own(signed_in, jmap):
    old = jmap.add(subject="Old", received="2026-01-01T00:00:00Z", unread=False, size=10)
    new = jmap.add(subject="New", received="2026-09-01T00:00:00Z", size=5000)
    starred = jmap.add(subject="Starred", received="2026-05-01T00:00:00Z", unread=False, flagged=True, size=300)

    oldest = signed_in.post("/view/inbox", json={"sort": "oldest", "filters": []}).get_json()
    assert row_ids(oldest["html"]) == [old, starred, new]
    assert row_ids(text(signed_in.get("/mail/inbox"))) == [old, starred, new]   # kept for next time
    assert row_ids(text(signed_in.get("/mail/archive"))) == []   # (another folder has its own)

    unread = signed_in.post("/view/inbox", json={"sort": "newest", "filters": ["unread"]}).get_json()
    favorites = signed_in.post("/view/inbox", json={"sort": "largest", "filters": ["favorites"]}).get_json()
    assert row_ids(unread["html"]) == [new] and row_ids(favorites["html"]) == [starred]
    page = text(signed_in.get("/mail/inbox"))
    assert re.search(r'aria-checked="true" data-wm-filter="favorites"', page)
    assert re.search(r'aria-checked="true" data-wm-sort-by="largest"', page)
    assert re.search(r'data-wm-sort-badge>1<', page)


def test_high_priority_shows_only_what_was_sent_as_important(signed_in, jmap):
    jmap.add(subject="Normal")
    urgent = jmap.add(subject="Urgent", important=True)

    answer = signed_in.post("/view/inbox", json={"sort": "newest", "filters": ["important"]}).get_json()

    assert row_ids(answer["html"]) == [urgent]


def test_made_up_sorts_and_filters_are_left_out(signed_in, jmap):
    jmap.add()

    answer = signed_in.post("/view/inbox", json={"sort": "sideways", "filters": ["nope", "unread"]}).get_json()

    assert answer["sort"] == "newest" and answer["filters"] == ["unread"]


def test_refreshing_brings_the_counts_too(signed_in, jmap):
    jmap.add()

    answer = signed_in.get("/list/inbox", headers=JSON).get_json()

    assert answer["counts"]["inbox"] == 1 and answer["unread"] == 1 and len(row_ids(answer["html"])) == 1


# --- reading ---

def test_a_message_opens_on_a_page_of_its_own(signed_in, jmap):
    email_id = jmap.add(subject="Re: Partnership proposal", sender=("Amina Hassan", "amina.hassan@example.com"),
                        cc=(("Musa", "musa@example.com"),))

    page = text(signed_in.get(f"/mail/inbox/{email_id}"))

    reader = page[page.index("data-wm-reader"):]
    assert '<h2 class="wm-read-subject">Re: Partnership proposal</h2>' in reader
    assert "amina.hassan@example.com" in reader and "<ceo@pineloop.online>" in reader and "Cc:" in reader
    assert re.search(rf'<li class="wm-message[^"]*\bis-open\b[^"]*"\s+style="--i: 0" data-id="{email_id}"', page)
    assert "<title>Re: Partnership proposal | Someless Webmail</title>" in page


def test_a_message_opens_in_the_reading_pane_without_a_new_page(signed_in, jmap):
    email_id = jmap.add(subject="Hello there")

    answer = signed_in.get(f"/mail/inbox/{email_id}", headers=JSON).get_json()

    assert answer["subject"] == "Hello there"
    assert '<h2 class="wm-read-subject">' in answer["html"] and "<html" not in answer["html"]   # just the pane


def test_opening_a_message_marks_it_read(signed_in, jmap):
    email_id = jmap.add()
    jmap.add()

    answer = signed_in.get(f"/mail/inbox/{email_id}", headers=JSON).get_json()

    assert "$seen" in jmap.emails[email_id]["keywords"]
    assert answer["unread"] == 1 and answer["counts"]["inbox"] == 1


def test_a_draft_opens_without_being_marked_read(signed_in, jmap):
    email_id = jmap.add(folder="drafts", subject="Half written")

    page = text(signed_in.get(f"/mail/drafts/{email_id}"))

    assert "$seen" not in jmap.emails[email_id]["keywords"]
    tools = page[page.index('class="wm-read-tools"'):]
    tools = tools[:tools.index("</div>")]
    assert re.findall(r'data-act="([^"]+)"', tools) == ["edit-draft", "delete", "print", "source", "download"]


def test_the_reading_panes_buttons_are_privateemails(signed_in, jmap):
    email_id = jmap.add()
    spam_id = jmap.add(folder="junk")
    archived = jmap.add(folder="inbox")
    signed_in.get("/mail/inbox")   # (the Archive is made)
    do(signed_in, "archive", [archived])

    def tools(folder, email):
        page = text(signed_in.get(f"/mail/{folder}/{email}"))
        bar = page[page.index('class="wm-read-tools"'):]
        return re.findall(r'data-act="([^"]+)"', bar[:bar.index("</div>")])

    assert tools("inbox", email_id) == ["reply", "reply-all", "forward", "unread", "flag", "archive", "delete", "spam",
                                        "print", "download", "source"]
    assert tools("spam", spam_id)[5:8] == ["archive", "delete", "notspam"]
    assert tools("archive", archived)[5:7] == ["inbox", "delete"]


def test_a_message_that_isnt_there_is_not_found(signed_in):
    assert signed_in.get("/mail/inbox/nope").status_code == 404
    assert signed_in.get("/mail/inbox/nope", headers=JSON).get_json() == {"problem": "This message isn't there any more."}


def test_what_a_message_says_is_kept_apart_from_the_webmail(signed_in, jmap):
    email_id = jmap.add(html='<p onclick="steal()">Before the meeting</p><script>alert(1)</script>'
                             '<a href="javascript:alert(2)">bad</a><iframe src="https://evil.example"></iframe>', text="")

    raw = signed_in.get(f"/mail/inbox/{email_id}").get_data(as_text=True)

    frame = html.unescape(re.search(r'<iframe [^>]*data-wm-body[^>]*>', raw).group(0))
    assert 'sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"' in frame   # no scripts
    assert "default-src 'none'" in frame and "Before the meeting" in frame
    for gone in ("<script", "onclick", "javascript:", "evil.example"):
        assert gone not in frame, gone


def test_links_lose_their_tracking(signed_in, jmap):
    email_id = jmap.add(html='<a href="https://shop.example/sale?id=7&utm_source=mail&fbclid=abc">Sale</a>'
                             '<a href="https://shop.example/about">About</a>', text="")

    raw = signed_in.get(f"/mail/inbox/{email_id}").get_data(as_text=True)
    page = html.unescape(raw)

    assert "https://shop.example/sale?id=7" in page and "utm_source" not in html.unescape(re.search(
        r'<iframe [^>]*data-wm-body[^>]*>', raw).group(0))
    assert 'aria-label="Links cleaned from tracking: 1"' in page and 'data-tip="1 tracking link was cleaned"' in page
    assert "Original" in page and "Cleaned" in page and "utm_source=mail, fbclid=abc" in page   # "See details"


def test_a_message_without_trackers_says_so(signed_in, jmap):
    email_id = jmap.add(text="Plain words, https://example.com/page")

    page = text(signed_in.get(f"/mail/inbox/{email_id}"))

    assert 'data-tip="No trackers found"' in page and "data-wm-trackers" not in page


def test_pictures_sent_with_a_message_come_from_the_webmail(signed_in, jmap):
    email_id = jmap.add(html='<p>Logo:</p><img src="cid:logo123">', text="",
                        attachments=[("logo.png", "image/png", b"\x89PNG", "logo123"), ("notes.txt", "text/plain", b"hi")])

    page = text(signed_in.get(f"/mail/inbox/{email_id}"))

    blob = f"/blob/{email_id}/b{email_id}-0?inline=1"
    assert f'src="{blob}"' in page
    assert "1 attachment" in page and "notes" in page   # the picture in what it says isn't listed with them


def test_a_messages_attachments_are_listed(signed_in, jmap):
    email_id = jmap.add(attachments=[("Partnership-notes.pdf", "application/pdf", b"%PDF" + b"x" * 36_000),
                                     ("Budget-2027.xlsx", "application/vnd.ms-excel", b"x" * 49_300),
                                     ("logo.png", "image/png", b"\x89PNG" + b"x" * 12_900)])

    page = text(signed_in.get(f"/mail/inbox/{email_id}"))

    assert "3 attachments" in page and "Save all" in page
    for name, size, kind in (("Partnership-notes", "35.16 KB", "pdf"), ("Budget-2027", "48.14 KB", "other"),
                             ("logo", "12.6 KB", "image")):
        assert name in page and size in page, name
        assert re.search(rf'data-kind="{kind}"', page), kind


def test_a_file_downloads_or_shows(signed_in, jmap):
    email_id = jmap.add(attachments=[("photo.png", "image/png", b"\x89PNG-data"), ("doc.pdf", "application/pdf", b"%PDF-1"),
                                     ("tool.exe", "application/x-msdownload", b"MZ")])

    download = signed_in.get(f"/blob/{email_id}/b{email_id}-0")
    picture = signed_in.get(f"/blob/{email_id}/b{email_id}-0?inline=1")
    pdf = signed_in.get(f"/blob/{email_id}/b{email_id}-1?inline=1")
    program = signed_in.get(f"/blob/{email_id}/b{email_id}-2?inline=1")

    assert download.headers["Content-Disposition"].startswith("attachment;") and download.data == b"\x89PNG-data"
    assert download.mimetype == "application/octet-stream"
    assert picture.headers["Content-Disposition"].startswith("inline;") and picture.mimetype == "image/png"
    assert "sandbox" in picture.headers["Content-Security-Policy"]
    assert pdf.mimetype == "application/pdf" and "Content-Security-Policy" not in pdf.headers   # the browser's own viewer
    assert program.headers["Content-Disposition"].startswith("attachment;")   # never shown on the page
    assert picture.headers["X-Content-Type-Options"] == "nosniff"


def test_a_file_that_isnt_the_messages_is_not_found(signed_in, jmap):
    email_id = jmap.add(attachments=[("a.txt", "text/plain", b"a")])
    other = jmap.add(attachments=[("b.txt", "text/plain", b"b")])

    assert signed_in.get(f"/blob/{email_id}/b{other}-0").status_code == 404


def test_save_all_zips_the_files(signed_in, jmap):
    email_id = jmap.add(subject="Q4 files", attachments=[("a.txt", "text/plain", b"one"), ("a.txt", "text/plain", b"two")])

    response = signed_in.get(f"/zip/{email_id}")

    assert response.headers["Content-Disposition"].startswith("attachment;") and "Q4 files.zip" in response.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert sorted(archive.namelist()) == ["a (2).txt", "a.txt"]


def test_view_source_and_download(signed_in, jmap):
    email_id = jmap.add(subject="Hello: world?")

    shown = signed_in.get(f"/source/{email_id}")
    saved = signed_in.get(f"/source/{email_id}?download=1")

    assert shown.mimetype == "text/plain" and "Subject: Hello: world?" in shown.get_data(as_text=True)
    assert saved.mimetype == "message/rfc822" and "Hello world.eml" in saved.headers["Content-Disposition"]


def test_print_shows_the_message_on_its_own(signed_in, jmap):
    email_id = jmap.add(subject="Invoice", html="<p>Total: 20</p>", text="")

    response = signed_in.get(f"/print/{email_id}")

    page = text(response)
    assert "<h1>Invoice</h1>" in page and "Total: 20" in page and "js/webmail-print.js" in page
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]


# --- what's done to messages ---

def test_messages_are_marked_read_unread_and_favorite(signed_in, jmap):
    email_id = jmap.add()

    do(signed_in, "read", [email_id])
    assert "$seen" in jmap.emails[email_id]["keywords"]
    do(signed_in, "unread", [email_id])
    assert "$seen" not in jmap.emails[email_id]["keywords"]
    answer = do(signed_in, "flag", [email_id]).get_json()
    assert "$flagged" in jmap.emails[email_id]["keywords"] and answer["left"] is False and answer["message"] is None
    do(signed_in, "unflag", [email_id])
    assert "$flagged" not in jmap.emails[email_id]["keywords"]


def test_messages_move_to_a_folder(signed_in, jmap):
    ids = [jmap.add(), jmap.add()]
    key = create(signed_in, "Clients", "inbox").get_json()["key"]

    answer = do(signed_in, "move", ids, to=key).get_json()

    assert answer["message"] == 'Emails moved to "Inbox / Clients"' and answer["left"] is True
    assert all(jmap.emails[email_id]["mailboxIds"] == {key[2:]: True} for email_id in ids)
    assert answer["counts"][key] == 2


def test_a_message_already_there_isnt_moved(signed_in, jmap):
    email_id = jmap.add()

    answer = do(signed_in, "move", [email_id], to="inbox").get_json()

    assert answer["warning"] is True and answer["message"] == 'Message is already in "Inbox" folder'


def test_nothing_moves_to_drafts_or_sent(signed_in, jmap):
    email_id = jmap.add()

    assert do(signed_in, "move", [email_id], to="drafts").status_code == 400


def test_archive_and_back_to_the_inbox(signed_in, jmap):
    email_id = jmap.add()

    archived = do(signed_in, "archive", [email_id]).get_json()
    back = do(signed_in, "inbox", [email_id]).get_json()

    assert archived["message"] == 'Email moved to "Archive"' and back["message"] == 'Email moved to "Inbox"'


def test_spam_and_not_spam_teach_the_engine(signed_in, jmap):
    email_id = jmap.add()

    spam = do(signed_in, "spam", [email_id]).get_json()
    assert spam["message"] == "Email moved to spam"
    assert jmap.emails[email_id]["mailboxIds"] == {jmap.role("junk"): True} and "$junk" in jmap.emails[email_id]["keywords"]
    not_spam = do(signed_in, "notspam", [email_id]).get_json()
    assert not_spam["message"] == 'Email moved to "Inbox" and marked as not spam'
    assert "$notjunk" in jmap.emails[email_id]["keywords"] and "$junk" not in jmap.emails[email_id]["keywords"]


def test_deleting_moves_to_the_trash_then_deletes_for_good(signed_in, jmap):
    email_id = jmap.add()

    first = do(signed_in, "delete", [email_id]).get_json()
    assert first["message"] == 'Email moved to "Trash"' and jmap.emails[email_id]["mailboxIds"] == {jmap.role("trash"): True}
    second = do(signed_in, "delete", [email_id]).get_json()
    assert second["message"] == "Selected messages have been deleted" and email_id not in jmap.emails


def test_select_all_reaches_the_whole_folder_as_filtered(signed_in, jmap):
    unread = [jmap.add() for _ in range(3)]
    read = jmap.add(unread=False)
    signed_in.post("/view/inbox", json={"sort": "newest", "filters": ["unread"]})

    answer = do(signed_in, "archive", all={"folder": "inbox"}).get_json()

    archive = next(key for key, box in jmap.mailboxes.items() if box["role"] == "archive")
    assert all(jmap.emails[email_id]["mailboxIds"] == {archive: True} for email_id in unread)
    assert jmap.emails[read]["mailboxIds"] == {jmap.role("inbox"): True}   # not in the list: left
    assert answer["message"] == 'Emails moved to "Archive"'


def test_an_action_needs_messages_and_a_known_action(signed_in):
    assert do(signed_in, "read", []).get_json() == {"problem": "No messages selected"}
    assert do(signed_in, "explode", ["x"]).status_code == 400


# --- search ---

def test_the_search_panel_shows_the_first_results_in_bold(signed_in, jmap):
    jmap.add(subject="Invoice for September", sender=("Billing", "billing@example.com"), text="Your invoice is attached")
    jmap.add(subject="Lunch?", text="Tomorrow at noon")

    answer = signed_in.get("/search?q=invoice", headers=JSON).get_json()

    assert answer["total"] == 1
    assert "<b>Invoice</b> for September" in answer["html"] and "All 1 result" in answer["html"]
    assert '<span class="wm-search-folder">Inbox</span>' in answer["html"]   # all the mail: its folder shown


def test_the_search_panel_says_when_nothing_is_found(signed_in, jmap):
    answer = signed_in.get("/search?q=nothing-like-it", headers=JSON).get_json()

    assert answer["total"] == 0 and "No results for “nothing-like-it”" in html.unescape(answer["html"])
    assert "Try checking the spelling or using different keywords" in answer["html"]


def test_search_lists_all_results_with_their_folders(signed_in, jmap):
    in_inbox = jmap.add(subject="Report A")
    in_sent = jmap.add(folder="sent", subject="Report B")

    page = text(signed_in.get("/search?q=report"))
    in_folder = text(signed_in.get("/search?q=report&in=sent"))

    assert set(row_ids(page)) == {in_inbox, in_sent} and "2 results" in page
    assert '<span class="wm-located">Sent</span>' in page
    assert row_ids(in_folder) == [in_sent] and "1 result" in in_folder
    assert f'href="/mail/search/{in_sent}?q=report&amp;in=sent"' in signed_in.get("/search?q=report&in=sent").get_data(as_text=True)


def test_an_empty_search_goes_back_to_the_folder(signed_in):
    assert signed_in.get("/search?q=%20&in=sent").headers["Location"] == "/mail/sent"


# --- who each message is from, in a circle (webmail-message.html; the photo: webmail-list.js) ---

def avatar_of(page):
    return page.split('class="wm-face"')[1].split("</span>")[0]


def test_each_message_in_the_list_has_its_senders_initials_in_a_circle(signed_in, jmap):
    jmap.add(sender=("Amina Hassan", "Amina@Example.com"))

    avatar = avatar_of(signed_in.get("/mail/inbox").get_data(as_text=True))

    assert 'data-email="amina@example.com"' in avatar and avatar.rstrip().endswith(">AH")
    assert "--hue:" in avatar


def test_sent_mail_shows_whom_it_went_to_in_its_circle(signed_in, jmap):
    jmap.add(folder="sent", to=(("Musa Otieno", "musa@example.com"),))

    avatar = avatar_of(signed_in.get("/mail/sent").get_data(as_text=True))

    assert 'data-email="musa@example.com"' in avatar and avatar.rstrip().endswith(">MO")


def test_the_same_person_always_has_the_same_colour(signed_in, jmap):
    jmap.add(sender=("Amina", "amina@example.com"))
    jmap.add(sender=("Amina Hassan", "AMINA@example.com"))
    jmap.add(sender=("Musa", "musa@example.com"))

    page = signed_in.get("/mail/inbox").get_data(as_text=True)
    hues = {}
    for part in page.split('class="wm-face"')[1:]:
        email = part.split('data-email="')[1].split('"')[0]
        hues.setdefault(email, set()).add(part.split("--hue:")[1].split(";")[0].strip())

    assert len(hues["amina@example.com"]) == 1
