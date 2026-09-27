"""The admin's profile picture (avatar.py): uploaded in Settings, cropped to a square where the
admin placed it, made small and light with Pillow, and shown in the top right corner."""
import io
import re

from PIL import Image

MB = 1024 * 1024


def image(width=1000, height=600, kind="PNG", color=(20, 120, 220)):
    data = io.BytesIO()
    Image.new("RGB", (width, height), color).save(data, kind)
    data.seek(0)
    return data


def upload(client, data, x="200", y="0", size="600", name="me.png"):
    return client.post("/settings/avatar", data={"picture": (data, name), "x": x, "y": y, "size": size},
                       content_type="multipart/form-data", headers={"Accept": "application/json"})


def saved(app):
    import pathlib
    return pathlib.Path(app.config["DATA_DIR"]) / "avatar.webp"


def test_the_card_is_for_the_username_and_the_picture(client, login):
    login()

    page = client.get("/settings").get_data(as_text=True)

    assert "Update username and profile picture" in page
    assert 'accept="image/jpeg,image/png,image/webp,image/gif"' in page


def test_a_picture_is_cropped_made_small_and_shown(app, client, login):
    login()

    answer = upload(client, image())

    assert answer.status_code == 200 and answer.get_json()["url"].startswith("/settings/avatar?v=")
    with Image.open(saved(app)) as picture:
        assert picture.format == "WEBP" and picture.size == (512, 512)
    page = client.get("/settings").get_data(as_text=True)
    topbar = page[page.index('id="topbar-user"'):page.index("</span>\n  </span>", page.index('id="topbar-user"'))]
    assert re.search(r'<img class="topbar-avatar[^"]*" src="/settings/avatar\?v=', topbar)
    served = client.get("/settings/avatar")
    assert served.status_code == 200 and served.mimetype == "image/webp"


def test_the_square_is_where_the_admin_put_it(app, client, login):
    """Left half red, right half blue: a square cut from the right comes out blue."""
    login()
    picture = Image.new("RGB", (800, 400), (255, 0, 0))
    picture.paste((0, 0, 255), (400, 0, 800, 400))
    data = io.BytesIO()
    picture.save(data, "PNG")
    data.seek(0)

    upload(client, data, x="400", y="0", size="400")

    with Image.open(saved(app)) as done:
        red, green, blue = done.convert("RGB").getpixel((256, 256))
    assert blue > 200 and red < 60


def test_a_square_past_the_edges_is_kept_inside(app, client, login):
    login()

    assert upload(client, image(), x="900", y="-50", size="5000").status_code == 200

    with Image.open(saved(app)) as picture:
        assert picture.size == (512, 512)


def test_what_isnt_a_picture_is_refused(app, client, login):
    login()

    for data, name in ((io.BytesIO(b"not an image at all"), "notes.png"), (io.BytesIO(b"GIF89a" + b"\0" * 20), "broken.gif")):
        answer = upload(client, data, name=name)
        assert answer.status_code == 400 and "picture" in answer.get_json()["problem"], name
    assert not saved(app).exists()


def test_a_picture_over_5_mb_is_refused(app, client, login):
    login()
    big = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\0" * (5 * MB + 10))

    answer = upload(client, big)

    assert answer.status_code in (400, 413) and not saved(app).exists()


def test_the_picture_can_be_removed(app, client, login):
    login()
    upload(client, image())

    client.post("/settings/avatar/delete")

    assert not saved(app).exists()
    assert "<img class=\"topbar-avatar" not in client.get("/settings").get_data(as_text=True)


def test_the_picture_is_only_for_the_admin(app, client, login):
    login()
    upload(client, image())
    client.post("/logout")

    assert client.get("/settings/avatar").status_code in (302, 404)
    assert upload(client, image()).status_code in (302, 401)


def test_removing_answers_the_page_that_asked_in_the_background(app, client, login):
    login()
    upload(client, image())

    answer = client.post("/settings/avatar/delete", headers={"Accept": "application/json"})

    assert answer.status_code == 200 and answer.get_json() == {"removed": True}
    assert not saved(app).exists()


def test_the_picture_is_found_with_a_data_folder_given_by_a_relative_path(tmp_path, monkeypatch, login):
    """SOMELESS_DATA_DIR=./devdata, as in the README's development steps."""
    from someless import create_app
    monkeypatch.chdir(tmp_path)
    app = create_app({"TESTING": True, "DATA_DIR": "devdata", "WTF_CSRF_ENABLED": False})
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": "admin"})

    assert upload(client, image()).status_code == 200
    assert client.get("/settings/avatar").status_code == 200
