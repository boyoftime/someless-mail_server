"""Writing mail in the webmail (webmail/compose.py), as PrivateEmail's composer: what a new
message, a reply, a forward or a draft starts with; files uploaded; drafts saved; mail sent
through the engine (JMAP EmailSubmission), and what's said when it can't be. The engine is the
made-up one (jmap_fake.py)."""
import base64
import io

import pytest

from someless import mail_password
from someless.db import get_db
from someless.webmail import compose, create_webmail_app
from jmap_fake import FakeJmap
from test_engine_sync import a_mailbox, a_sender, authenticated_domain

PASSWORD = "Mailbox-Pass-1!"


@pytest.fixture
def jmap():
    return FakeJmap()


@pytest.fixture
def mailbox(app):
    domain_id = authenticated_domain(app)
    a_sender(app, domain_id, "ceo@pineloop.online")
    return a_mailbox(app, "ceo@pineloop.online", domain_id, password_hash=mail_password.hash_password(PASSWORD),
                     aliases=("sales@pineloop.online",))


@pytest.fixture
def mail(app, jmap, mailbox):
    webmail = create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "WTF_CSRF_ENABLED": False,
                                  "JMAP": lambda email: jmap})
    client = webmail.test_client()
    client.post("/login", data={"email": "ceo@pineloop.online", "password": PASSWORD})
    client.get("/mail/inbox")   # (the Archive is made)
    return client


def start(mail, kind="new", email_id=None):
    return mail.get("/compose/start", query_string={"kind": kind, **({"id": email_id} if email_id else {})})


def message(**extra):
    return {"from": "ceo@pineloop.online", "to": [{"name": "Amina", "email": "amina@example.com"}], "cc": [], "bcc": [],
            "subject": "Hello", "html": "<p>Hi <b>Amina</b></p>", "attachments": [], **extra}


def in_folder(jmap, role):
    box = jmap.role(role)
    return [email for email in jmap.emails.values() if box in email["mailboxIds"]]


# --- what it starts with ---

def test_a_new_message_is_from_the_mailbox_or_its_aliases(mail):
    started = start(mail).get_json()

    assert started["from"] == "ceo@pineloop.online"
    assert [one["email"] for one in started["froms"]] == ["ceo@pineloop.online", "sales@pineloop.online"]
    assert started["froms"][0]["name"] == "S"   # the sender's name (test_engine_sync.a_sender)
    assert started["to"] == [] and started["subject"] == "" and started["limits"]["recipients"] == 50


def test_the_default_signature_goes_in_a_new_message(app, mail, mailbox):
    with app.app_context():
        get_db().execute("INSERT INTO webmail_signatures (mailbox_id, name, html, is_default, created_at) VALUES (?, 'Work', '<p>Amani, CEO</p>', 1, 0)",
                         (mailbox,))
        get_db().commit()

    started = start(mail).get_json()

    assert "Amani, CEO" in started["html"] and 'class="wm-signature"' in started["html"]
    assert started["signatures"][0]["name"] == "Work"


def test_a_reply_goes_to_the_sender_with_the_message_quoted(mail, jmap):
    email_id = jmap.add(subject="Partnership", sender=("Amina Hassan", "amina@example.com"), text="Shall we meet?",
                        received="2026-09-28T18:51:00Z")

    started = start(mail, "reply", email_id).get_json()

    assert started["to"] == [{"name": "Amina Hassan", "email": "amina@example.com"}] and started["cc"] == []
    assert started["subject"] == "Re: Partnership"
    assert "Replying to amina@example.com on September 28, 2026 at 6:51 PM" in started["html"]
    assert "From: amina@example.com" in started["html"] and "Shall we meet?" in started["html"]
    assert started["reply"]["kind"] == "reply" and started["reply"]["inReplyTo"] == [f"{email_id}@example.com"]


def test_re_isnt_doubled(mail, jmap):
    email_id = jmap.add(subject="RE: Partnership")

    assert start(mail, "reply", email_id).get_json()["subject"] == "RE: Partnership"


def test_a_reply_to_all_leaves_the_mailbox_out(mail, jmap):
    email_id = jmap.add(sender=("Amina", "amina@example.com"),
                        to=(("Ceo", "ceo@pineloop.online"), ("Musa", "musa@example.com")),
                        cc=(("Grace", "grace@example.com"), ("Sales", "sales@pineloop.online")))

    started = start(mail, "all", email_id).get_json()

    assert [person["email"] for person in started["to"]] == ["amina@example.com", "musa@example.com"]
    assert [person["email"] for person in started["cc"]] == ["grace@example.com"]


def test_a_reply_uses_reply_to_and_the_address_it_came_to(mail, jmap):
    email_id = jmap.add(sender=("Shop", "noreply@shop.example"), reply_to=(("Help", "help@shop.example"),),
                        to=(("Sales", "sales@pineloop.online"),))

    started = start(mail, "reply", email_id).get_json()

    assert started["to"] == [{"name": "Help", "email": "help@shop.example"}]
    assert started["from"] == "sales@pineloop.online"


def test_a_reply_to_the_mailboxs_own_mail_goes_to_whom_it_went(mail, jmap):
    email_id = jmap.add(folder="sent", sender=("Ceo", "ceo@pineloop.online"), to=(("Musa", "musa@example.com"),))

    assert start(mail, "reply", email_id).get_json()["to"] == [{"name": "Musa", "email": "musa@example.com"}]


def test_a_forward_brings_the_files(mail, jmap):
    email_id = jmap.add(subject="Budget", sender=("Amina", "amina@example.com"),
                        attachments=[("budget.pdf", "application/pdf", b"%PDF-1")])

    started = start(mail, "forward", email_id).get_json()

    assert started["subject"] == "Fwd: Budget" and started["to"] == []
    assert "Forwarding email from amina@example.com at" in started["html"]
    assert [part["name"] for part in started["attachments"]] == ["budget.pdf"]


def test_a_quote_shows_no_scripts_or_styles(mail, jmap):
    email_id = jmap.add(html='<style>body{display:none}</style><p onclick="x()">Hi</p><script>alert(1)</script>', text="")

    quoted = start(mail, "reply", email_id).get_json()["html"]

    assert "Hi" in quoted
    for gone in ("<script", "<style", "onclick", "display:none"):
        assert gone not in quoted, gone


def test_a_reply_to_a_message_that_went_says_so(mail):
    response = start(mail, "reply", "gone")

    assert response.status_code == 404
    assert response.get_json()["problem"] == "Message not sent. Original email no longer exists."


# --- files ---

def test_a_file_is_uploaded_to_the_engine(mail, jmap):
    answer = mail.post("/compose/upload", data={"file": (io.BytesIO(b"hello"), "notes.txt", "text/plain")}).get_json()

    assert answer["name"] == "notes.txt" and answer["size"] == 5 and answer["type"] == "text/plain"
    assert jmap.blobs[answer["blobId"]] == (b"hello", "text/plain")


def test_a_picture_is_made_smaller_without_losing_anything(mail, jmap):
    from PIL import Image
    picture = Image.new("RGB", (160, 90))
    for x in range(160):
        picture.putpixel((x, x % 90), (x, 255 - x, 90))
    loose = io.BytesIO()
    picture.save(loose, "PNG", compress_level=0)

    answer = mail.post("/compose/upload", data={"file": (io.BytesIO(loose.getvalue()), "chart.png", "image/png")}).get_json()

    stored = jmap.blobs[answer["blobId"]][0]
    assert answer["size"] == len(stored) < len(loose.getvalue()) == answer["original"]
    with Image.open(io.BytesIO(stored)) as kept:
        assert kept.tobytes() == picture.tobytes()


def sending_limit(app, megabytes):
    """The mailbox's limit, as the panel's Mailboxes page sets it."""
    with app.app_context():
        get_db().execute("UPDATE mailboxes SET send_limit_mb = ? WHERE email = 'ceo@pineloop.online'", (megabytes,))
        get_db().commit()


def test_the_limits_are_the_mailboxs_own(app, mail):
    started = start(mail).get_json()
    assert started["limits"]["file"] == started["limits"]["all"] == 50 * 1024 ** 2   # (a new mailbox's)

    sending_limit(app, 80)

    started = start(mail).get_json()
    assert started["limits"]["file"] == started["limits"]["all"] == 80 * 1024 ** 2


def test_a_file_over_the_mailboxs_limit_is_refused(app, mail):
    sending_limit(app, 1)

    response = mail.post("/compose/upload", data={"file": (io.BytesIO(b"x" * (1024 ** 2 + 1)), "notes.bin")})

    assert response.status_code == 413 and response.get_json()["problem"] == "Maximum allowed file size 1 MB"


def test_files_over_the_mailboxs_limit_are_not_sent(app, mail):
    sending_limit(app, 1)
    files = [{"blobId": f"b{number}", "name": f"part{number}.bin", "type": "application/octet-stream", "size": 600 * 1024}
             for number in (1, 2)]

    response = mail.post("/compose/send", json=message(attachments=files))

    assert response.get_json()["problem"] == "All files should not exceed 1 MB"


def test_only_pictures_go_in_what_it_says(mail):
    response = mail.post("/compose/upload", data={"file": (io.BytesIO(b"MZ"), "tool.exe", "application/x-msdownload"),
                                                  "picture": "1"})

    assert response.status_code == 400 and response.get_json()["problem"] == "File type is not supported"


# --- drafts ---

def test_a_draft_is_saved_and_saved_again(mail, jmap):
    first = mail.post("/compose/save", json=message()).get_json()
    second = mail.post("/compose/save", json=message(subject="Hello again", draft=first["draft"])).get_json()

    assert first["message"] == "Your message has been successfully saved to drafts"
    assert second["message"] == "Your drafts message has been successfully updated"
    drafts = in_folder(jmap, "drafts")
    assert [email["subject"] for email in drafts] == ["Hello again"]   # (the one before is gone)
    assert drafts[0]["keywords"] == {"$draft": True, "$seen": True}
    assert second["counts"]["drafts"] == 1


def test_a_quiet_save_says_nothing(mail):
    assert mail.post("/compose/save", json=message(quiet=True)).get_json()["message"] is None


def test_a_draft_opens_as_it_was_left(mail, jmap):
    email_id = jmap.add(subject="Half written")
    reply = start(mail, "reply", email_id).get_json()["reply"]
    saved = mail.post("/compose/save", json=message(subject="Re: Half written", reply=reply,
                                                    cc=[{"email": "grace@example.com"}], important=True)).get_json()

    started = start(mail, "draft", saved["draft"]).get_json()

    assert started["draft"] == saved["draft"] and started["subject"] == "Re: Half written"
    assert started["cc"] == [{"name": None, "email": "grace@example.com"}] and started["important"] is True
    assert started["reply"]["kind"] == "reply" and started["reply"]["id"] == email_id
    assert "Hi <b>Amina</b>" in started["html"]


def test_a_draft_discarded_is_gone(mail, jmap):
    draft = mail.post("/compose/save", json=message()).get_json()["draft"]
    other = jmap.add()

    mail.post("/compose/discard", json={"draft": draft})
    mail.post("/compose/discard", json={"draft": other})   # not a draft: left alone

    assert draft not in jmap.emails and other in jmap.emails


# --- sending ---

def test_a_message_is_sent_and_lands_in_sent(mail, jmap):
    answer = mail.post("/compose/send", json=message()).get_json()

    assert answer["message"] == "Message has been successfully sent"
    [sent] = jmap.submissions
    assert sent["identity"]["email"] == "ceo@pineloop.online"
    email = sent["email"]
    assert email["to"] == [{"name": "Amina", "email": "amina@example.com"}] and email["subject"] == "Hello"
    assert email["from"] == [{"name": "S", "email": "ceo@pineloop.online"}]   # the mailbox's name, not the engine's
    assert email["_html"].endswith("<p>Hi <b>Amina</b></p></body></html>")
    assert email["_text"].strip() == "Hi Amina"
    [landed] = in_folder(jmap, "sent")
    assert "$draft" not in landed["keywords"] and not in_folder(jmap, "drafts")


def test_sending_from_an_alias_makes_its_identity(mail, jmap):
    mail.post("/compose/send", json=message(**{"from": "sales@pineloop.online"}))

    assert jmap.submissions[0]["identity"]["email"] == "sales@pineloop.online"


def test_a_reply_marks_what_it_answers(mail, jmap):
    email_id = jmap.add()
    forwarded = jmap.add()
    reply = start(mail, "reply", email_id).get_json()["reply"]
    forward = start(mail, "forward", forwarded).get_json()["reply"]

    mail.post("/compose/send", json=message(reply=reply))
    mail.post("/compose/send", json=message(reply=forward))

    assert "$answered" in jmap.emails[email_id]["keywords"] and "$forwarded" in jmap.emails[forwarded]["keywords"]
    assert jmap.submissions[0]["email"]["inReplyTo"] == [f"{email_id}@example.com"]
    assert "header:X-Someless-Draft-Of:asText" not in jmap.submissions[0]["email"]["_created"]   # (the draft's own note)


def test_sending_a_draft_takes_it_out_of_drafts(mail, jmap):
    draft = mail.post("/compose/save", json=message()).get_json()["draft"]

    mail.post("/compose/send", json=message(draft=draft))

    assert draft not in jmap.emails and not in_folder(jmap, "drafts") and len(in_folder(jmap, "sent")) == 1


def test_important_mail_goes_as_high_priority(mail, jmap):
    mail.post("/compose/send", json=message(important=True))

    assert jmap.submissions[0]["email"]["_created"]["header:X-Priority:asText"] == "1 (Highest)"


@pytest.mark.parametrize("change,problem", [
    ({"to": []}, "Enter at least one email address in the 'To:' or 'Cc:' fields"),
    ({"to": [{"email": "not-an-address"}]}, "Invalid email address: not-an-address"),
    ({"to": [{"email": f"p{number}@example.com"} for number in range(51)]},
     "Recipient limit exceeded. The maximum number allowed per email is 50"),
    ({"subject": "x" * 256}, "Subject max length is 255 symbols"),
    ({"from": "someone@else.example"}, "You can't send from that address."),
])
def test_what_cant_be_sent_is_refused(mail, jmap, change, problem):
    response = mail.post("/compose/send", json=message(**change))

    assert response.status_code == 400 and response.get_json()["problem"] == problem
    assert not jmap.submissions


def test_mail_the_engine_wont_send_stays_in_drafts(mail, jmap):
    jmap.refuse_send = "invalidRecipients"

    response = mail.post("/compose/send", json=message())

    answer = response.get_json()
    assert response.status_code == 422 and answer["saved"] is True
    assert answer["title"] == "Delivery failed due to invalid recipient address."
    assert answer["problem"] == "Email was saved to Draft, please check and try again."
    assert [email["id"] for email in in_folder(jmap, "drafts")] == [answer["draft"]]


def test_a_full_mailbox_says_so(mail, jmap):
    jmap.refuse_create = "overQuota"

    response = mail.post("/compose/send", json=message())

    assert response.status_code == 507 and response.get_json()["title"] == "Your storage is full"


def test_pictures_in_what_it_says_go_with_it(mail, jmap):
    picture = mail.post("/compose/upload", data={"file": (io.BytesIO(b"\x89PNG"), "logo.png", "image/png"), "picture": "1"}).get_json()
    unused = mail.post("/compose/upload", data={"file": (io.BytesIO(b"\x89PNG2"), "old.png", "image/png"), "picture": "1"}).get_json()
    written = f'<p>Logo:</p><img src="/compose/blob/{picture["blobId"]}?type=image/png" alt="logo">'

    mail.post("/compose/send", json=message(html=written, attachments=[
        {**picture, "cid": "logo1@someless", "inline": True}, {**unused, "cid": "old@someless", "inline": True}]))

    email = jmap.submissions[0]["email"]
    assert 'src="cid:logo1@someless"' in email["_html"]
    assert [(part["name"], part["disposition"], part["cid"]) for part in email["attachments"]] == [("logo.png", "inline", "logo1@someless")]


PIXEL = base64.b64encode(b"\x89PNG\r\n\x1a\n-a-signature-picture").decode()


def test_a_signatures_picture_goes_as_a_part_of_its_own(mail, jmap):
    """Pictures in a signature are kept in it (data:), which Gmail and Outlook don't show: they
    go as parts of the message (cid:), each once."""
    written = (f'<p>Hi</p><div class="wm-signature"><img src="data:image/png;base64,{PIXEL}" width="200" alt="">'
               f'<img src="data:image/png;base64,{PIXEL}" alt=""></div>')

    mail.post("/compose/send", json=message(html=written))

    email = jmap.submissions[0]["email"]
    assert "data:image" not in email["_html"]
    parts = email["attachments"]
    assert [(part["disposition"], part["type"]) for part in parts] == [("inline", "image/png")]
    assert email["_html"].count(f'src="cid:{parts[0]["cid"]}"') == 2
    assert jmap.blobs[parts[0]["blobId"]][0] == base64.b64decode(PIXEL)


def test_a_signatures_picture_is_kept_with_a_draft_too(mail, jmap):
    mail.post("/compose/save", json=message(html=f'<p>Hi</p><img src="data:image/jpeg;base64,{PIXEL}">'))

    draft = next(email for email in jmap.emails.values() if "$draft" in email["keywords"])
    assert "data:image" not in draft["_html"] and draft["attachments"][0]["type"] == "image/jpeg"


# --- what it says, safe to send ---

def test_what_it_says_is_cleaned_before_it_goes():
    written = ('<p onmouseover="x()">Hi</p><script>alert(1)</script><a href="javascript:alert(2)">bad</a>'
               '<img src="/compose/blob/b1?type=image/png"><iframe src="https://evil.example"></iframe>')

    clean = compose.clean_outgoing(written, [{"blobId": "b1", "cid": "c1@someless"}])

    assert "<p>Hi</p>" in clean and 'src="cid:c1@someless"' in clean
    for gone in ("onmouseover", "<script", "javascript:", "<iframe", "evil.example"):
        assert gone not in clean, gone


def test_plain_text_goes_with_it():
    text = compose.to_text('<p>Hello</p><ul><li>One</li><li>Two</li></ul><p>See <a href="https://example.com">this</a></p>')

    assert text == "Hello\n\n- One\n- Two\n\nSee this (https://example.com)\n"


# --- who to write to ---

def test_addresses_are_suggested_as_they_are_typed(mail, jmap):
    jmap.add(sender=("Amina Hassan", "amina@example.com"))
    jmap.add(folder="sent", to=(("Musa Otieno", "musa@kilimo.example"),))

    by_name = mail.get("/compose/suggest?q=mus").get_json()["people"]
    by_address = mail.get("/compose/suggest?q=amina@").get_json()["people"]

    assert by_name == [{"name": "Musa Otieno", "email": "musa@kilimo.example"}]
    assert by_address == [{"name": "Amina Hassan", "email": "amina@example.com"}]
    assert mail.get("/compose/suggest?q=ceo").get_json()["people"] == []   # (not the mailbox itself)


# --- the composer's tools, on the page (webmail-composer.html, webmail-tables.js) ---

def test_the_formatting_bar_can_strike_words_through(mail):
    page = mail.get("/mail/inbox").get_data(as_text=True)
    strike = page.split('data-format="strikeThrough"')[1].split(">")[0]
    assert 'aria-label="Strikethrough"' in strike


def test_a_composer_can_take_the_whole_screen_beside_maximize(mail):
    page = mail.get("/mail/inbox").get_data(as_text=True)
    maximize = page.split('data-cm="fullscreen"')[1].split(">")[0]
    screen = page.split('data-cm="screen"')[1].split(">")[0]
    assert 'aria-label="Maximize"' in maximize and 'data-tip-on="Restore"' in maximize
    assert 'aria-label="Full screen"' in screen and 'data-tip-on="Exit full screen"' in screen


def test_the_mail_page_brings_the_tools_for_tables_before_the_composer(mail):
    page = mail.get("/mail/inbox").get_data(as_text=True)
    assert "js/webmail-tables.js" in page
    assert page.index("js/webmail-tables.js") < page.index("js/webmail-compose.js")
