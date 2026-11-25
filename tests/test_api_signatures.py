"""A mailbox's signatures from an app (/api/s1/mailboxes/{id}/signatures): the ones its owner sees in
the webmail (Settings > Signatures) and picks from as they write, under the webmail's own rules: at
most 20, a name up to 50 characters, cleaned as the webmail cleans them, pictures kept inside them,
and the first one the default."""
import base64

from someless.db import get_db
from someless.webmail import views as webmail_views
from test_api import a_key, api, rows  # noqa: F401 (the fixture)
from test_api_login import a_mailbox

LOGO = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n-mali-bahari-logo").decode()
SIGNATURE = (f'<p><b>Lazarus Augustinus</b></p><p><b>Head of Strategic Finance and Investments</b></p>'
             f'<p><img src="{LOGO}" width="600" alt="Mali Bahari Limited"></p>')


def add(api, mailbox_id, **fields):
    return api.post(f"/mailboxes/{mailbox_id}/signatures", json={"name": "Work", "html": SIGNATURE, **fields})


def test_a_signature_is_added_as_the_webmail_shows_it(api, app):
    mailbox_id = a_mailbox(app, api)

    answer = add(api, mailbox_id)

    assert answer.status_code == 201
    signature = answer.json["signature"]
    assert signature["name"] == "Work" and signature["default"] is True   # (the first one)
    assert "Lazarus Augustinus" in signature["html"] and LOGO in signature["html"]   # (its logo kept inside it)
    with app.app_context():
        assert [(one["id"], one["name"], bool(one["is_default"])) for one in webmail_views.signatures(mailbox_id)] == [
            (signature["id"], "Work", True)]


def test_its_html_is_cleaned_as_the_webmails(api, app):
    mailbox_id = a_mailbox(app, api)

    html = add(api, mailbox_id, html='<p onclick="steal()">Hi<script>alert(1)</script></p>'
                                     '<img src="javascript:alert(1)">').json["signature"]["html"]

    assert "Hi" in html and "onclick" not in html and "<script" not in html and "javascript:" not in html


def test_a_new_default_takes_over(api, app):
    mailbox_id = a_mailbox(app, api)
    first = add(api, mailbox_id).json["signature"]

    second = add(api, mailbox_id, name="Short", html="<p>Lazarus</p>", default=True).json["signature"]

    listed = api.get(f"/mailboxes/{mailbox_id}/signatures").json["signatures"]
    assert [(one["id"], one["default"]) for one in listed] == [(second["id"], True), (first["id"], False)]


def test_a_signature_is_changed_and_deleted(api, app):
    mailbox_id = a_mailbox(app, api)
    made = add(api, mailbox_id).json["signature"]
    other = add(api, mailbox_id, name="Short", html="<p>Lazarus</p>").json["signature"]

    changed = api.patch(f"/mailboxes/{mailbox_id}/signatures/{other['id']}", json={"default": True})

    assert changed.status_code == 200
    assert changed.json["signature"] == {**other, "default": True}   # (only what was sent changes)
    renamed = api.patch(f"/mailboxes/{mailbox_id}/signatures/{made['id']}", json={"name": "Full", "html": "<p>New</p>"})
    assert renamed.json["signature"]["name"] == "Full" and renamed.json["signature"]["html"] == "<p>New</p>"
    assert api.delete(f"/mailboxes/{mailbox_id}/signatures/{made['id']}").json == {"deleted": True}
    assert [one["id"] for one in api.get(f"/mailboxes/{mailbox_id}/signatures").json["signatures"]] == [other["id"]]


def test_what_isnt_right_is_refused_in_the_webmails_words(api, app):
    mailbox_id = a_mailbox(app, api)

    assert add(api, mailbox_id, name="x" * 51).json["error"] == "Signature name max length is 50 symbols"
    assert add(api, mailbox_id, name="   ").status_code == 400
    assert add(api, mailbox_id, html="<p> </p>").json["error"] == "html is empty: give what the signature says."
    assert add(api, mailbox_id, html="<p>" + "x" * 2_000_001 + "</p>").json["error"] == (
        "This signature is too large. Use smaller pictures, or fewer of them.")
    assert add(api, mailbox_id, default="yes").json["error"] == "Give default as true or false."
    assert add(api, mailbox_id, colour="red").status_code == 400
    assert api.post(f"/mailboxes/{mailbox_id}/signatures", json={"name": "Work"}).json["error"] == "html is missing."
    assert rows(app, "SELECT * FROM webmail_signatures") == []


def test_a_mailbox_has_twenty_at_most(api, app):
    mailbox_id = a_mailbox(app, api)
    for number in range(20):
        assert add(api, mailbox_id, name=f"Signature {number}").status_code == 201

    answer = add(api, mailbox_id)

    assert answer.status_code == 400 and answer.json["error"] == "A mailbox can have 20 signatures at most."


def test_no_such_mailbox_or_signature(api, app):
    mailbox_id = a_mailbox(app, api)
    other = a_mailbox(app, api, email="amina@pineloop.online", name="Amina Hassan")
    theirs = add(api, other).json["signature"]

    assert add(api, 999).status_code == 404
    assert api.get("/mailboxes/999/signatures").status_code == 404
    missing = api.patch(f"/mailboxes/{mailbox_id}/signatures/{theirs['id']}", json={"name": "Mine now"})
    assert missing.status_code == 404 and missing.json["error"] == f"This mailbox has no signature with the id {theirs['id']}."
    assert api.delete(f"/mailboxes/{mailbox_id}/signatures/{theirs['id']}").status_code == 404
    assert api.get(f"/mailboxes/{other}/signatures").json["signatures"][0]["name"] == "Work"   # (untouched)


def test_they_go_with_their_mailbox(api, app):
    mailbox_id = a_mailbox(app, api)
    add(api, mailbox_id)

    api.delete(f"/mailboxes/{mailbox_id}")

    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM webmail_signatures").fetchone()[0] == 0


def test_it_needs_the_key(api, app):
    assert api.get(f"/mailboxes/{a_mailbox(app, api)}/signatures", key=None).status_code == 401


def test_the_guide_has_them(client, login):
    login()
    page = client.get("/api-keys/docs").get_data(as_text=True)
    text = client.get("/api/s1/docs.md").get_data(as_text=True)

    for guide in (page, text):
        for call in ("GET /mailboxes/{id}/signatures", "POST /mailboxes/{id}/signatures",
                     "PATCH /mailboxes/{id}/signatures/{signature_id}", "DELETE /mailboxes/{id}/signatures/{signature_id}"):
            method, path = call.split(" ")
            assert path in guide, call
        assert "data:image/png;base64," in guide
