from someless import create_app


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
