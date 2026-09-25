import html
import re

import pytest
from flask import g

from someless import create_app


def text(response):
    return html.unescape(response.get_data(as_text=True))


def main_area(page):
    return page[page.index('<main class="app-main" id="app-main">'):page.index("</main>")]


@pytest.fixture
def csrf_client(tmp_path):
    # Form security tokens checked, as on a real server
    return create_app({"TESTING": True, "DATA_DIR": str(tmp_path)}).test_client()


def test_unknown_address_shows_our_not_found_page(client):
    response = client.get("/settings/fgh")

    page = text(response)
    assert response.status_code == 404
    assert "Page not found" in page
    assert 'data-lottie="/static/lottie/not-found.json?v=' in page
    assert 'href="/login"' in page  # signed out: the way back is the login page
    assert "The requested URL was not found on the server" not in page  # Flask's own page


def test_unknown_address_when_signed_in_shows_in_the_main_area(client, login):
    login()
    response = client.get("/settings/fgh")

    page = text(response)
    assert response.status_code == 404
    assert 'id="side-menu"' in page
    # inside the main area, so moving between pages can swap it in like any other page
    assert "Page not found" in main_area(page)
    assert 'href="/dashboard"' in main_area(page)


def test_opening_logout_from_the_address_bar_explains_itself(client):
    response = client.get("/logout")

    page = text(response)
    assert response.status_code == 405
    assert "can't be opened directly" in page
    assert "lottie/not-found.json" in page
    assert "POST" in response.headers["Allow"]


def test_server_errors_show_our_error_page(app):
    app.config["PROPAGATE_EXCEPTIONS"] = False  # answer like the real server, not the debugger

    @app.get("/broken")
    def broken():
        raise RuntimeError("boom")

    response = app.test_client().get("/broken")

    page = text(response)
    assert response.status_code == 500
    assert "Something went wrong" in page
    assert 'data-lottie="/static/lottie/error.json?v=' in page
    assert "The server encountered an internal error" not in page  # Flask's own page


def test_server_errors_when_signed_in_show_in_the_main_area(app, client, login):
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.get("/broken")
    def broken():
        raise RuntimeError("boom")

    login()
    page = text(client.get("/broken"))

    assert "Something went wrong" in main_area(page)
    assert "lottie/error.json" in main_area(page)


def test_error_page_still_shows_when_the_signed_in_layout_breaks(app, client, login):
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.get("/broken")
    def broken():
        g.admin = {}  # the layout can't show the admin's name from this
        raise RuntimeError("boom")

    login()
    response = client.get("/broken")

    page = text(response)
    assert response.status_code == 500
    assert "Something went wrong" in page
    assert 'id="side-menu"' not in page  # the page on its own instead


def test_expired_form_shows_our_expired_page(csrf_client):
    response = csrf_client.post("/logout")  # no security token, like a form left open too long

    page = text(response)
    assert response.status_code == 400
    assert "This page has expired" in page
    assert "lottie/error.json" in page


def test_expired_form_when_signed_in_shows_in_the_main_area(csrf_client):
    login_page = csrf_client.get("/login").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', login_page).group(1)
    csrf_client.post("/login", data={"csrf_token": token, "username": "admin", "password": "admin"})

    response = csrf_client.post("/settings/username", data={"username": "boss", "current_password": "admin"})

    page = text(response)
    assert response.status_code == 400
    assert "This page has expired" in main_area(page)


def test_expired_login_form_answers_the_login_script_in_json(csrf_client):
    response = csrf_client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 400
    assert "expired" in response.get_json()["error"]


def test_error_pages_follow_the_theme(client):
    client.set_cookie("theme", "light")

    assert 'data-theme="light"' in client.get("/nope").get_data(as_text=True)


@pytest.mark.parametrize("name", ["not-found", "error"])
def test_error_animations_are_served(client, name):
    assert client.get(f"/static/lottie/{name}.json").get_json()["layers"]
