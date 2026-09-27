"""Set it up on a device: the back of a mailbox's Configuration details, with how to add the
mailbox in Gmail on Android, on an iPhone (a configuration profile, mail_profile.py) and in
Outlook on Windows. The iPhone gets the profile from a QR code: a link that works for an hour."""
import plistlib
import re

from someless import mail_profile
from test_mailboxes import create, text
from test_engine_sync import authenticated_domain

PROFILE_KIND = "application/x-apple-aspen-config"


def mailbox(app, client, login):
    authenticated_domain(app)
    login()
    create(client)   # ceo@pineloop.online, the first mailbox
    return 1


def account(answer):
    """The mail account a profile sets up."""
    profile = plistlib.loads(answer.get_data())
    assert profile["PayloadType"] == "Configuration"
    (mail,) = profile["PayloadContent"]
    assert mail["PayloadType"] == "com.apple.mail.managed"
    return profile, mail


def test_the_profile_sets_up_the_mailbox(app, client, login):
    mailbox_id = mailbox(app, client, login)

    answer = client.get(f"/mailboxes/{mailbox_id}/profile")

    assert answer.status_code == 200 and answer.mimetype == PROFILE_KIND
    assert answer.headers["Content-Disposition"] == 'attachment; filename="ceo@pineloop.online.mobileconfig"'
    profile, mail = account(answer)
    assert mail["EmailAddress"] == "ceo@pineloop.online" and mail["EmailAccountType"] == "EmailTypeIMAP"
    assert (mail["IncomingMailServerHostName"], mail["IncomingMailServerPortNumber"],
            mail["IncomingMailServerUseSSL"]) == ("mail.pineloop.online", 993, True)
    assert (mail["OutgoingMailServerHostName"], mail["OutgoingMailServerPortNumber"],
            mail["OutgoingMailServerUseSSL"]) == ("mail.pineloop.online", 465, True)
    assert mail["IncomingMailServerUsername"] == mail["OutgoingMailServerUsername"] == "ceo@pineloop.online"
    assert mail["OutgoingPasswordSameAsIncomingPassword"] is True
    # no password in it (the iPhone asks), and no name (it asks for that too)
    assert not [key for key in mail if "Password" in key and key != "OutgoingPasswordSameAsIncomingPassword"]
    assert "EmailAccountName" not in mail
    assert profile["PayloadDisplayName"] == "ceo@pineloop.online"


def test_installing_it_again_replaces_it(app, client, login):
    mailbox_id = mailbox(app, client, login)

    first, _ = account(client.get(f"/mailboxes/{mailbox_id}/profile"))
    again, _ = account(client.get(f"/mailboxes/{mailbox_id}/profile"))

    assert first["PayloadIdentifier"] == again["PayloadIdentifier"] and first["PayloadUUID"] == again["PayloadUUID"]


def test_the_profile_needs_a_login(app, client, login):
    mailbox_id = mailbox(app, client, login)

    assert app.test_client().get(f"/mailboxes/{mailbox_id}/profile").status_code == 302
    assert app.test_client().get(f"/mailboxes/{mailbox_id}/profile-link").status_code == 302
    assert client.get("/mailboxes/99/profile").status_code == 404


def test_an_iphone_gets_it_from_a_qr_code_without_a_login(app, client, login):
    mailbox_id = mailbox(app, client, login)

    answer = client.get(f"/mailboxes/{mailbox_id}/profile-link").get_json()

    assert re.fullmatch(r"http://localhost/mailboxes/profile/[\w.-]+", answer["url"])
    assert answer["qr"].startswith("<svg") and "</svg>" in answer["qr"]
    iphone = app.test_client()
    profile = iphone.get(answer["url"].removeprefix("http://localhost"))
    assert profile.status_code == 200 and profile.mimetype == PROFILE_KIND
    assert account(profile)[1]["EmailAddress"] == "ceo@pineloop.online"


def test_the_qr_code_works_for_an_hour(app, client, login, monkeypatch):
    mailbox_id = mailbox(app, client, login)
    now = mail_profile._now()
    url = client.get(f"/mailboxes/{mailbox_id}/profile-link").get_json()["url"].removeprefix("http://localhost")

    monkeypatch.setattr(mail_profile, "_now", lambda: now + 59 * 60)
    assert app.test_client().get(url).status_code == 200
    monkeypatch.setattr(mail_profile, "_now", lambda: now + 61 * 60)
    expired = app.test_client().get(url)
    assert expired.status_code == 410 and "This link has expired" in text(expired)


def test_a_made_up_or_deleted_mailboxs_link_gives_nothing(app, client, login):
    mailbox_id = mailbox(app, client, login)
    url = client.get(f"/mailboxes/{mailbox_id}/profile-link").get_json()["url"].removeprefix("http://localhost")

    assert app.test_client().get("/mailboxes/profile/not-a-real-link").status_code == 404
    assert app.test_client().get(url[:-3] + "abc").status_code == 404   # changed: its signature no longer fits
    client.post(f"/mailboxes/{mailbox_id}/delete")
    assert app.test_client().get(url).status_code == 404


def test_the_configuration_details_turn_over_to_the_devices(app, client, login):
    mailbox_id = mailbox(app, client, login)

    page = text(client.get("/mailboxes"))

    assert f'data-config-profile="/mailboxes/{mailbox_id}/profile"' in page
    assert f'data-config-link="/mailboxes/{mailbox_id}/profile-link"' in page
    details = page[page.index('id="config-dialog"'):]
    details = details[:details.index("</dialog>")]
    assert "data-config-flip" in details and "lottie/phone.json" in details
    tabs = re.findall(r'<button[^>]*data-device-tab[^>]*>.*?<span>([^<]+)</span>', details, re.S)
    assert tabs == ["Android", "iPhone", "Windows PC"]
    assert "Gmail" in details and "Profile Downloaded" in details and "Outlook" in details
    assert "mail.pineloop.online" in details[details.index('id="device-panel-android"'):]
