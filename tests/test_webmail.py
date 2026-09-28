"""The webmail (webmail.py): its own little site on port 17090, where a mailbox logs in with
its own address and password, on a page that looks like the panel's login. For now it says the
inbox is coming soon. The Mailboxes page has its login link, to copy or share."""
import html
import re

import pytest

from someless import mail_password, webmail_sample
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
    assert "side-menu" not in page   # its own site, not the panel


def test_its_login_looks_like_the_panels(mail):
    page = text(mail.get("/login"))

    assert 'class="login-bg"' in page and "img/float/" in page   # the floating mail icons
    assert 'class="auth-card' in page and "Log in to your mailbox" in page
    assert re.search(r'<label[^>]*for="webmail-email"[^>]*>Email</label>', page)
    assert re.search(r'<button class="button button-block"[^>]*type="submit"', page)


def test_its_login_link_can_fill_in_the_address(mail):
    page = text(mail.get("/login?email=%20CEO@PineLoop.online"))

    email = re.search(r'<input id="webmail-email"[^>]*>', page).group(0)
    assert 'value="ceo@pineloop.online"' in email and "autofocus" not in email
    assert "autofocus" in re.search(r'<input id="webmail-password"[^>]*>', page).group(0)   # straight to the password


def test_a_mailbox_logs_in_and_the_inbox_is_coming_soon(mail, mailbox):
    response = sign_in(mail, email=" CEO@PineLoop.online ")

    assert response.headers["Location"] == "/"
    page = text(mail.get("/"))
    soon = page[page.index('class="webmail-soon"'):]
    assert "Your inbox is coming soon" in soon and "ceo@pineloop.online" in page
    assert "mail.pineloop.online" in soon   # until then, any mail app, at this server
    assert "config-row" not in page   # no settings table: just the message, in the middle
    assert 'action="/logout"' in page


@pytest.fixture
def preview(app):
    """The webmail with its inbox design switched on (SOMELESS_WEBMAIL_PREVIEW=1): made-up mail,
    until it reads the real mail from the mail engine."""
    return create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "WTF_CSRF_ENABLED": False,
                               "INBOX_PREVIEW": True}).test_client()


def test_the_inbox_design_shows_only_in_the_preview(mail, preview, mailbox):
    sign_in(mail)
    assert "Your inbox is coming soon" in text(mail.get("/"))   # a real server: not yet

    sign_in(preview)
    page = text(preview.get("/"))

    assert "Your inbox is coming soon" not in page
    assert re.search(r'class="wm-compose"[^>]*>\s*Compose\s*<', page)
    names = re.findall(r'<span class="wm-folder-name">([^<]+)</span>', page)
    assert names == ["Inbox", "Drafts", "Sent", "Archive", "Spam", "Trash"]
    assert 'placeholder="Search mail"' in page and "No mail selected" in page
    assert len(re.findall(r'<li class="wm-message', page)) >= 5   # the made-up mail
    assert "1 GB" in page   # the mailbox's own storage


def test_the_account_card_has_the_mailbox_and_log_out(preview, mailbox):
    sign_in(preview)

    page = text(preview.get("/"))

    card = page[page.index('id="wm-account"'):]
    card = card[:card.index("</section>")]
    assert "ceo@pineloop.online" in card and 'data-copy="ceo@pineloop.online"' in card
    assert 'action="/logout"' in card and "data-theme-switch" in card


def test_the_inbox_comes_in_smoothly_each_time_it_opens(preview, mailbox):
    sign_in(preview)

    first = text(preview.get("/"))
    again = text(preview.get("/"))   # a refresh

    for page in (first, again):
        assert re.search(r'<body class="[^"]*\bis-arriving\b', page)
    assert re.search(r'<li class="wm-message[^"]*" style="--i: 1"', first)   # one after another


def row_ids(html):
    """The messages in a piece of the list, in order: their ids."""
    return re.findall(r'<li class="wm-message[^"]*" style="--i: \d+" data-id="([^"]+)"', html)


def test_the_inbox_opens_with_its_newest_50_messages(preview, mailbox):
    sign_in(preview)

    page = text(preview.get("/"))

    assert row_ids(page) == [str(number) for number in range(1, 51)]
    assert 'data-wm-more data-url="/messages?after=50"' in page   # where the next ones come from


def test_scrolling_down_brings_50_more_each_time_until_the_last(preview, mailbox):
    assert 100 < len(webmail_sample.MESSAGES) <= 150   # (the made-up mail: enough for three pieces)
    sign_in(preview)

    second = preview.get("/messages?after=50").get_json()
    third = preview.get(second["next"]).get_json()

    assert row_ids(second["html"]) == [str(number) for number in range(51, 101)]
    assert second["next"] == "/messages?after=100"
    assert row_ids(third["html"]) == [str(number) for number in range(101, len(webmail_sample.MESSAGES) + 1)]
    assert third["next"] is None   # the end: nothing more to ask for
    assert re.search(r'<li class="wm-message[^"]*\bis-more\b[^"]*" style="--i: 0"', second["html"])   # they come in too


def test_more_mail_needs_a_login(preview, mailbox):
    assert preview.get("/messages?after=50").headers["Location"] == "/login"


def test_more_mail_is_only_in_the_preview(mail, mailbox):
    sign_in(mail)

    assert mail.get("/messages?after=50").status_code == 404


def test_a_made_up_place_in_the_list_is_refused(preview, mailbox):
    sign_in(preview)

    assert preview.get("/messages?after=nope").status_code == 400


JSON = {"Accept": "application/json"}


def unread_count(page):
    """The Inbox's count of unread mail, in the folders."""
    return int(re.search(r'data-wm-unread>(\d+)<', page).group(1))


def test_the_mail_links_to_each_message(preview, mailbox):
    sign_in(preview)

    page = text(preview.get("/"))

    assert '<a class="wm-message-link" href="/message/1"' in page
    assert re.search(r'<div class="wm-empty" data-wm-empty>', page)   # nothing open yet


def test_a_message_opens_on_a_page_of_its_own(preview, mailbox):
    sign_in(preview)

    page = text(preview.get("/message/2"))

    reader = page[page.index("data-wm-reader"):]
    assert '<h2 class="wm-read-subject">Re: Partnership proposal</h2>' in reader
    assert "amina.hassan@example.com" in reader and "To: <ceo@pineloop.online>" in reader
    assert re.search(r'<li class="wm-message[^"]*\bis-open\b[^"]*" style="--i: 1" data-id="2"', page)
    assert "<title>Re: Partnership proposal | Someless Webmail</title>" in page


def test_a_message_opens_in_the_reading_pane_without_a_new_page(preview, mailbox):
    sign_in(preview)

    answer = preview.get("/message/2", headers=JSON).get_json()

    assert answer["subject"] == "Re: Partnership proposal"
    assert '<h2 class="wm-read-subject">' in answer["html"] and "<html" not in answer["html"]   # just the pane


def test_opening_a_message_marks_it_read(preview, mailbox):
    sign_in(preview)
    unread = unread_count(text(preview.get("/")))

    answer = preview.get("/message/2", headers=JSON).get_json()
    page = text(preview.get("/"))

    assert answer["unread"] == unread_count(page) == unread - 1
    assert re.search(r'<li class="wm-message" style="--i: 1" data-id="2"', page)   # no longer in bold


def test_the_message_itself_is_kept_apart_from_the_webmail(preview, mailbox):
    sign_in(preview)

    raw = preview.get("/message/2").get_data(as_text=True)

    frame = html.unescape(re.search(r'<iframe [^>]*data-wm-body[^>]*>', raw).group(0))
    assert 'sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"' in frame   # no scripts
    assert "default-src 'none'" in frame   # nothing loads from other sites
    assert "Before the meeting, could you confirm the following:" in frame


def test_a_messages_attachments_are_listed(preview, mailbox):
    sign_in(preview)

    page = text(preview.get("/message/2"))

    assert "3 attachments" in page
    for name, size in (("Partnership-notes", "35.4 KB"), ("Budget-2027", "48.2 KB"), ("logo", "12.6 KB")):
        assert name in page and size in page, name


def test_a_message_that_isnt_there_is_not_found(preview, mailbox):
    sign_in(preview)

    assert preview.get("/message/999").status_code == 404


def test_a_message_needs_a_login(preview, mailbox):
    assert preview.get("/message/2").headers["Location"] == "/login"


def test_messages_open_only_in_the_preview(mail, mailbox):
    sign_in(mail)

    assert mail.get("/message/2").status_code == 404


def shell(page):
    return re.search(r'<div class="wm-shell"[^>]*>', page).group(0)


def test_the_columns_have_dividers_to_drag(preview, mailbox):
    sign_in(preview)

    page = text(preview.get("/"))

    for name in ("side", "list"):
        handle = re.search(rf'<span class="wm-resize[^"]*"[^>]*data-wm-resize="{name}"[^>]*>', page).group(0)
        assert 'role="separator"' in handle and 'aria-orientation="vertical"' in handle, name
    assert "style=" not in shell(page)   # the widths it starts with (webmail-app.css)


def test_the_columns_keep_the_widths_they_were_dragged_to(preview, mailbox):
    sign_in(preview)
    preview.set_cookie("wm_columns", "200,400")

    page = text(preview.get("/"))

    assert 'style="--wm-side-width: 200px; --wm-list-width: 400px"' in shell(page)


@pytest.mark.parametrize("columns", ["abc", "200", "200,400,500", "20,400", "200,-5", "200,99999", "2e2,400", ""])
def test_widths_that_cant_be_are_left_out(preview, mailbox, columns):
    sign_in(preview)
    preview.set_cookie("wm_columns", columns)

    assert "style=" not in shell(text(preview.get("/")))


def test_the_preview_is_switched_on_where_the_webmail_runs(app, monkeypatch):
    monkeypatch.setenv("SOMELESS_WEBMAIL_PREVIEW", "1")
    assert create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"]}).config["INBOX_PREVIEW"]
    monkeypatch.delenv("SOMELESS_WEBMAIL_PREVIEW")
    assert not create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"]}).config["INBOX_PREVIEW"]


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


# Opening a mailbox's webmail from the Mailboxes page: signed in, no password asked

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
    assert "Your inbox is coming soon" in text(mail.get("/")) and "ceo@pineloop.online" in text(mail.get("/"))
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
