import html as html_lib

from someless import create_app


def text(response):
    return html_lib.unescape(response.get_data(as_text=True))


def test_login_page_shows_username_and_password_fields(client):
    html = client.get("/login").get_data(as_text=True)

    assert 'name="username"' in html
    assert 'name="password"' in html


def test_default_admin_can_log_in(client, login):
    response = login("admin", "admin")

    assert response.status_code == 302
    assert response.headers["Location"] == "/dashboard"


def test_wrong_password_is_rejected(client, login):
    response = login("admin", "not-the-password")

    assert response.status_code == 401
    assert "Wrong username or password." in response.get_data(as_text=True)


def test_unknown_username_is_rejected(client, login):
    response = login("root", "admin")

    assert response.status_code == 401


def test_dashboard_requires_login(client):
    response = client.get("/dashboard")

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_dashboard_shows_signed_in_admin(client, login):
    login()

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "admin" in response.get_data(as_text=True)


def test_logout_ends_the_session(client, login):
    login()

    client.post("/logout")

    assert client.get("/dashboard").status_code == 302


def test_welcome_sends_signed_in_admin_to_dashboard(client, login):
    login()

    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == "/dashboard"


def test_session_survives_app_restart(tmp_path):
    config = {"TESTING": True, "DATA_DIR": str(tmp_path), "WTF_CSRF_ENABLED": False}
    first = create_app(config).test_client()
    first.post("/login", data={"username": "admin", "password": "admin"})
    cookie = first.get_cookie("session")

    second = create_app(config).test_client()
    second.set_cookie("session", cookie.value)

    assert second.get("/dashboard").status_code == 200


def test_forms_are_protected_against_cross_site_posts(tmp_path):
    app = create_app({"TESTING": True, "DATA_DIR": str(tmp_path)})

    response = app.test_client().post("/login", data={"username": "admin", "password": "admin"})

    assert response.status_code == 400


def test_login_page_shows_the_someless_logo(client):
    html = client.get("/login").get_data(as_text=True)
    logo = client.get("/static/img/logo.webp")

    assert 'src="/static/img/logo.webp?v=' in html
    assert 'alt="Someless Mail"' in html
    assert logo.status_code == 200


def test_password_can_be_shown_with_the_eye_button(client):
    html = client.get("/login").get_data(as_text=True)

    assert 'id="password"' in html
    assert 'data-password-toggle aria-controls="password"' in html
    assert 'src="/static/js/password-toggle.js?v=' in html


def test_login_background_is_drawn_with_pixi_and_hidden_from_screen_readers(client):
    html = client.get("/login").get_data(as_text=True)

    assert '<div class="login-bg" aria-hidden="true"' in html
    assert 'src="/static/js/pixi.min.js?v=' in html
    assert 'src="/static/js/login-background.js?v=' in html
    assert client.get("/static/js/pixi.min.js").status_code == 200


def test_login_page_opens_on_the_welcome_side(client):
    html = client.get("/login").get_data(as_text=True)

    assert '<div class="flip-card">' in html
    assert 'data-lottie="/static/lottie/contact-mail.json?v=' in html
    assert 'src="/static/js/lottie_light.min.js?v=' in html
    assert "layers" in client.get("/static/lottie/contact-mail.json").get_json()
    assert "Welcome to Someless Mail" in html
    assert "data-flip-to-login>Continue</button>" in html
    assert 'src="/static/js/login-card.js?v=' in html


def test_failed_login_shows_the_form_side_straight_away(client, login):
    response = login("admin", "wrong-password")

    assert '<div class="flip-card is-flipped">' in response.get_data(as_text=True)


def test_login_button_shows_a_spinner_while_logging_in(client):
    html = client.get("/login").get_data(as_text=True)

    assert 'data-busy-label="Logging in…"' in html
    assert '<span class="button-spinner" aria-hidden="true"></span>' in html
    assert 'src="/static/js/busy-button.js?v=' in html


def test_login_from_script_reports_a_wrong_password_as_json(client):
    response = client.post("/login", data={"username": "admin", "password": "typo"},
                           headers={"Accept": "application/json"})

    assert response.status_code == 401
    assert response.get_json() == {"error": "Wrong username or password."}


def test_login_from_script_says_where_to_go_next(client):
    response = client.post("/login", data={"username": "admin", "password": "admin"},
                           headers={"Accept": "application/json"})

    assert response.status_code == 200
    assert response.get_json() == {"redirect": "/dashboard"}
    assert client.get("/dashboard").status_code == 200


def test_failed_login_never_sends_the_password_back(client, login):
    response = login("admin", "my-secret-typo")

    assert "my-secret-typo" not in response.get_data(as_text=True)


def test_login_form_is_sent_by_script_so_fields_keep_their_text(client):
    html = client.get("/login").get_data(as_text=True)

    assert "data-login-form" in html
    assert "data-login-error" in html
    assert 'src="/static/js/login-submit.js?v=' in html


FLOATING_ICONS = ["gmail-m", "gmail-envelope", "mail-app", "inbox", "paper-plane", "yahoo"]


def test_login_background_floats_the_mail_icons(client):
    html = client.get("/login").get_data(as_text=True)

    for name in FLOATING_ICONS:
        url = f"/static/img/float/{name}.webp"
        assert url in html
        assert client.get(url).status_code == 200


def test_every_page_can_show_notice_boards(client, login):
    pages = [client.get("/").get_data(as_text=True), client.get("/login").get_data(as_text=True)]
    login()
    pages.append(client.get("/dashboard").get_data(as_text=True))

    for html in pages:
        assert 'src="/static/js/board.js?v=' in html


def test_login_welcomes_the_admin_with_a_green_board(client, login):
    login()

    html = text(client.get("/dashboard"))

    assert 'data-board="success"' in html
    assert 'data-board-title="Welcome back"' in html
    assert "Logged in as admin." in html
