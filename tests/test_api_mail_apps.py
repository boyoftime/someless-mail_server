"""What a mail app (Outlook, Thunderbird, a phone's Mail app) needs to add a mailbox, from an app
(GET /api/s1/mailboxes/{id}/mail-app-settings): the same servers, ports and security the webmail's
Settings > Connect third-party apps shows. Never the password: it's only kept as a hash."""
from someless import webmail_site
from someless.engine import names
from test_api import a_key, api  # noqa: F401 (the fixture)
from test_api_login import EMAIL, a_mailbox


def test_it_says_what_a_mail_app_asks_for(api, app):
    mailbox_id = a_mailbox(app, api)

    answer = api.get(f"/mailboxes/{mailbox_id}/mail-app-settings")

    assert answer.status_code == 200
    assert answer.json == {
        "email": EMAIL, "username": EMAIL,
        "imap": {"server": "mail.pineloop.online", "port": 993, "security": "SSL/TLS"},
        "pop3": {"server": "mail.pineloop.online", "port": 995, "security": "SSL/TLS"},
        "smtp": {"server": "mail.pineloop.online", "port": 465, "security": "SSL/TLS", "starttls_port": 587},
        "calendar_server": f"http://localhost:17090/dav/cal/{EMAIL}/",
        "contacts_server": f"http://localhost:17090/dav/card/{EMAIL}/",
    }
    assert "password" not in answer.get_data(as_text=True)


def test_the_servers_are_the_mail_servers_and_the_webmails_own_names(api, app, monkeypatch):
    mailbox_id = a_mailbox(app, api)
    monkeypatch.setattr(names, "server_name", lambda: "mail.mvuviafrica.com")
    with app.app_context():
        webmail_site.save("https://webmail.pineloop.online")

    answer = api.get(f"/mailboxes/{mailbox_id}/mail-app-settings").json

    assert {answer[kind]["server"] for kind in ("imap", "pop3", "smtp")} == {"mail.mvuviafrica.com"}
    assert answer["calendar_server"] == f"https://webmail.pineloop.online/dav/cal/{EMAIL}/"


def test_no_such_mailbox(api):
    answer = api.get("/mailboxes/999/mail-app-settings")

    assert answer.status_code == 404 and answer.json["error"]


def test_it_needs_the_key(api, app):
    assert api.get(f"/mailboxes/{a_mailbox(app, api)}/mail-app-settings", key=None).status_code == 401


def test_the_guide_has_it(client, login):
    login()

    for guide in (client.get("/api-keys/docs").get_data(as_text=True), client.get("/api/s1/docs.md").get_data(as_text=True)):
        assert "/mailboxes/{id}/mail-app-settings" in guide and "starttls_port" in guide
