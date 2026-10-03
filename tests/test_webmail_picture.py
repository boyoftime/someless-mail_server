"""A mailbox's profile picture (avatar.py, webmail Settings > Profile): uploaded and placed as the
panel's admin picture is, shown in the webmail's corner and account menu, and handed to the
mailbox's apps through the API (GET /api/s1/mailboxes/{id}/picture, and in a password check's
answer), so a site that signs people in with their mailbox can show it too."""
import base64
import io
import re
from pathlib import Path

from PIL import Image

from someless import avatar
from someless.db import get_db
from test_api import KEY, PASSWORD, a_key, api  # noqa: F401 (the fixture)
from test_api_login import a_mailbox as api_mailbox
from test_webmail_settings import jmap, mail, mailbox, webmail  # noqa: F401 (the fixtures)


def image(width=900, height=600, kind="PNG", color=(20, 120, 220)):
    data = io.BytesIO()
    Image.new("RGB", (width, height), color).save(data, kind)
    data.seek(0)
    return data


def upload(client, data, x="150", y="0", size="600", name="me.png"):
    return client.post("/settings/picture", data={"picture": (data, name), "x": x, "y": y, "size": size},
                       content_type="multipart/form-data", headers={"Accept": "application/json"})


def kept(app, mailbox_id):
    return Path(app.config["DATA_DIR"]) / "avatars" / f"{mailbox_id}.webp"


# --- the webmail ---------------------------------------------------------------------------------

def test_the_profile_card_offers_a_picture(mail):
    page = mail.get("/settings").get_data(as_text=True)

    profile = page[page.index('aria-labelledby="card-profile"'):page.index('aria-labelledby="card-system"')]
    assert "data-avatar-choose" in profile and ">Upload picture</span>" in profile
    assert 'accept="image/jpeg,image/png,image/webp,image/gif"' in profile
    dialog = re.search(r'<dialog [^>]*id="avatar-dialog"[^>]*>.*?</dialog>', page, re.S).group(0)
    assert 'action="/settings/picture"' in dialog and "data-avatar-stage" in dialog and "data-avatar-zoom" in dialog
    assert "js/settings-avatar.js" in page   # (the panel's own: placed the same way)


def test_a_picture_is_placed_cut_and_kept(mail, app, mailbox):
    answer = upload(mail, image())

    assert answer.status_code == 200
    assert answer.get_json()["url"].startswith(f"/settings/picture/{mailbox}?v=")
    with Image.open(kept(app, mailbox)) as saved:
        assert saved.format == "WEBP" and saved.size == (avatar.SIDE, avatar.SIDE)


def test_it_shows_in_the_corner_the_account_menu_and_the_card(mail, mailbox):
    url = upload(mail, image()).get_json()["url"]

    page = mail.get("/mail/inbox").get_data(as_text=True)
    assert re.search(rf'<button type="button" class="wm-avatar has-picture"[^>]*>\s*<img alt="" src="{re.escape(url)}"', page)
    assert re.search(rf'<span class="wm-account-picture has-picture"[^>]*>\s*<img alt="" src="{re.escape(url)}"', page)
    settings = mail.get("/settings").get_data(as_text=True)
    assert re.search(rf'<span class="wm-profile-avatar has-picture"[^>]*>\s*<img alt="" src="{re.escape(url)}"', settings)
    assert ">Change picture</span>" in settings


def test_the_picture_is_served_to_its_own_mailbox_only(mail, app, mailbox, webmail):
    upload(mail, image())

    served = mail.get(f"/settings/picture/{mailbox}")
    assert served.status_code == 200 and served.mimetype == "image/webp"
    assert mail.get(f"/settings/picture/{mailbox + 99}").status_code == 404
    assert webmail.test_client().get(f"/settings/picture/{mailbox}").status_code in (302, 401)   # (nobody signed in)


def test_what_isnt_a_picture_is_refused(mail, app, mailbox):
    answer = upload(mail, io.BytesIO(b"not a picture at all"), name="note.png")

    assert answer.status_code == 400 and answer.get_json()["problem"] == avatar.NOT_A_PICTURE
    assert not kept(app, mailbox).exists()


def test_a_picture_is_removed(mail, app, mailbox):
    upload(mail, image())

    answer = mail.post("/settings/picture/delete", headers={"Accept": "application/json"})

    assert answer.status_code == 200 and not kept(app, mailbox).exists()
    page = mail.get("/mail/inbox").get_data(as_text=True)
    assert 'class="wm-avatar has-picture"' not in page


def test_a_deleted_mailbox_takes_its_picture_with_it(mail, app, mailbox):
    upload(mail, image())

    with app.app_context():
        from someless import mailboxes
        mailboxes.remove(mailbox)

    assert not kept(app, mailbox).exists()


# --- the API -------------------------------------------------------------------------------------

def with_picture(app, mailbox_id):
    with app.app_context():
        assert avatar.save(image().getvalue(), 150, 0, 600, avatar.mailbox_path(mailbox_id)) is None


def test_the_api_hands_the_picture_over(api, app):
    mailbox_id = api_mailbox(app, api)
    with_picture(app, mailbox_id)

    served = api.get(f"/mailboxes/{mailbox_id}/picture")

    assert served.status_code == 200 and served.mimetype == "image/webp"
    with Image.open(io.BytesIO(served.data)) as got:
        assert got.size == (avatar.SIDE, avatar.SIDE)
    assert api.get(f"/mailboxes/{mailbox_id}/picture", key=None).status_code == 401


def test_without_a_picture_the_api_says_so(api, app):
    mailbox_id = api_mailbox(app, api)

    answer = api.get(f"/mailboxes/{mailbox_id}/picture")

    assert answer.status_code == 404 and answer.json["error"] == "This mailbox has no profile picture."
    assert api.get(f"/mailboxes/{mailbox_id}").json["mailbox"]["picture_url"] is None


def test_a_mailbox_says_where_its_picture_is(api, app):
    mailbox_id = api_mailbox(app, api)
    with_picture(app, mailbox_id)

    assert api.get(f"/mailboxes/{mailbox_id}").json["mailbox"]["picture_url"] == \
        f"http://localhost/api/s1/mailboxes/{mailbox_id}/picture"


def test_a_password_check_brings_the_picture_to_show_at_once(api, app):
    mailbox_id = api_mailbox(app, api)
    assert api.post("/mailboxes/login", json={"email": "lewis@pineloop.online", "password": PASSWORD}).json["picture"] is None
    with_picture(app, mailbox_id)

    picture = api.post("/mailboxes/login", json={"email": "lewis@pineloop.online", "password": PASSWORD}).json["picture"]

    assert picture.startswith("data:image/webp;base64,")
    with Image.open(io.BytesIO(base64.b64decode(picture.split(",", 1)[1]))) as got:
        assert got.format == "WEBP"


def test_the_guide_shows_the_picture_call(client):
    from someless import api_guide
    mailboxes = next(group for group in api_guide.calls("https://panel.example.com/api/s1", "example.com")
                     if group["title"] == "Mailboxes")
    call = next(call for call in mailboxes["calls"] if call["path"] == "/mailboxes/{id}/picture")
    assert call["method"] == "GET" and call["name"] == "Get a profile picture"
    examples = {request["key"]: request["code"] for request in call["requests"]}   # (saved as a file: it's no JSON)
    assert "-o picture.webp" in examples["curl"] and "arrayBuffer()" in examples["javascript"]
    assert "response.content" in examples["python"] and "file_put_contents" in examples["php"]
    docs = client.get("/api/s1/docs.md").get_data(as_text=True)
    assert "/mailboxes/{id}/picture" in docs and '"picture": "data:image/webp;base64,' in docs


def test_the_readme_tells_of_the_picture_and_the_password_check():
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    api = readme[readme.index("## The API"):readme.index("## Troubleshooting")]
    webmail = readme[readme.index("What they find there:"):readme.index("**On HTTPS, at `webmail.example.com`:**")]

    assert "`POST /mailboxes/login`" in api and "`GET /mailboxes/{id}/picture`" in api
    assert "profile picture" in webmail
