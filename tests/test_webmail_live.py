"""New mail as it comes (webmail/live.py): the engine's push read as it arrives, what counts as new
mail in the Inbox, and who may open the page's WebSocket. The engine is the made-up one."""
import io

import pytest

from someless import mail_password
from someless.webmail import create_webmail_app, live
from jmap_fake import FakeJmap
from test_engine_sync import a_mailbox, authenticated_domain

PASSWORD = "Mailbox-Pass-1!"


def test_the_engines_changes_are_read_as_they_come():
    stream = io.BytesIO(b"event: state\r\ndata: {\"@type\":\"StateChange\",\"changed\":{\"c\":{\"Email\":\"s1\",\"EmailDelivery\":\"s1\"}}}\r\n\r\n"
                        b": a comment\r\n\r\nevent: state\r\ndata: {\"changed\":{\"c\":{\"Mailbox\":\"s2\"}}}\r\n\r\n"
                        b"data: not json\r\n\r\n")

    assert list(live._changes(stream)) == [{"Email", "EmailDelivery"}, {"Mailbox"}]


@pytest.fixture
def jmap():
    return FakeJmap()


def test_new_mail_is_what_came_to_the_inbox_since_the_last_look(app, jmap):
    old = jmap.add(subject="Old", received="2026-09-28T10:00:00Z")
    inbox = jmap.role("inbox")
    since = live._latest(jmap, inbox)
    assert since == "2026-09-28T10:00:00Z"
    jmap.add(subject="Budget", sender=("Amina Hassan", "amina@example.com"), received="2026-09-28T11:00:00Z")
    jmap.add(subject="Read already", received="2026-09-28T11:30:00Z", unread=False)
    jmap.add(folder="junk", subject="Spam", received="2026-09-28T12:00:00Z")

    count, newest, latest = live._arrived(jmap, inbox, since)

    assert count == 2 and latest == "2026-09-28T11:30:00Z"
    assert [message["subject"] for message in newest] == ["Budget"]   # (the one read on a phone already: no ring)
    assert newest[0]["from"] == "Amina Hassan" and old not in [message["id"] for message in newest]
    assert live._arrived(jmap, inbox, latest)[1] == []   # nothing since


def test_the_page_says_where_to_listen_and_with_what_sound(app, jmap):
    domain_id = authenticated_domain(app)
    a_mailbox(app, "ceo@pineloop.online", domain_id, password_hash=mail_password.hash_password(PASSWORD))
    webmail = create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "WTF_CSRF_ENABLED": False,
                                  "JMAP": lambda email: jmap})
    client = webmail.test_client()
    client.post("/login", data={"email": "ceo@pineloop.online", "password": PASSWORD})

    page = client.get("/mail/inbox").get_data(as_text=True)

    assert 'data-live-url="/live"' in page and "sounds/new-mail.mp3" in page and "js/webmail-live.js" in page
    assert 'data-sound="1"' in page and 'data-notify="0"' in page   # the sound on, notifications off, to begin with


def test_only_the_webmails_own_pages_may_listen(app):
    webmail = create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"]})
    with webmail.test_request_context("/live", headers={"Origin": "https://evil.example"}):
        assert not live._same_site()
    with webmail.test_request_context("/live", base_url="http://localhost", headers={"Origin": "http://localhost"}):
        assert live._same_site()
