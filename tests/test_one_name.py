"""A mailbox's name is its sender's: one name, changed from either side. The webmail's Settings >
Profile changes the sender's name in the panel, and the panel's Senders > Edit changes what the
webmail shows (and its mail goes out with)."""
from someless import db as db_module
from someless.db import get_db
from someless.webmail import views
from test_webmail_settings import jmap, mail, mailbox, post, webmail  # noqa: F401 (the fixtures)


def sender_name(app):
    with app.app_context():
        return get_db().execute("SELECT name FROM senders WHERE email = 'ceo@pineloop.online'").fetchone()["name"]


def test_a_name_changed_in_the_webmail_is_the_senders_in_the_panel(mail, app, client, login):
    answer = post(mail, "/settings/profile", display_name="Amani  Juma")

    assert answer.get_json()["display_name"] == "Amani Juma"
    assert sender_name(app) == "Amani Juma"
    login()
    assert "Amani Juma" in client.get("/senders").get_data(as_text=True)


def test_a_name_changed_in_the_panel_shows_in_the_webmail(mail, app, mailbox):
    with app.app_context():
        get_db().execute("UPDATE senders SET name = 'Chief Executive' WHERE email = 'ceo@pineloop.online'")
        get_db().commit()

    page = mail.get("/settings").get_data(as_text=True)

    assert 'value="Chief Executive"' in page and "Chief Executive" in mail.get("/mail/inbox").get_data(as_text=True)


def test_the_webmail_takes_no_longer_name_than_a_sender_can_have(mail, app):
    answer = post(mail, "/settings/profile", display_name="A" * 71)

    assert answer.status_code == 400 and "70 characters" in answer.get_json()["problem"]
    assert sender_name(app) == "S"


def test_names_chosen_in_the_webmail_before_become_the_senders(app, mailbox):
    with app.app_context():
        database = get_db()
        database.execute("INSERT INTO webmail_settings (mailbox_id, display_name) VALUES (?, 'Amani Juma')", (mailbox,))
        database.commit()
        db_module.one_name(database)

        assert views.display_name(mailbox) == "Amani Juma"
        assert database.execute("SELECT display_name FROM webmail_settings WHERE mailbox_id = ?", (mailbox,)).fetchone()[0] is None
    assert sender_name(app) == "Amani Juma"
