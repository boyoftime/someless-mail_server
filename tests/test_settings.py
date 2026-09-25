import html
import re

from someless import create_app

DEFAULT_WARNING = "You're still using the default password"


def text(response):
    return html.unescape(response.get_data(as_text=True))


def change_password(client, current="admin", new="new-secret-1", confirm=None):
    return client.post("/settings/password", data={
        "current_password": current,
        "new_password": new,
        "confirm_password": new if confirm is None else confirm,
    })


def change_username(client, new="postmaster", current_password="admin"):
    return client.post("/settings/username", data={
        "username": new,
        "current_password": current_password,
    })


def test_settings_requires_login(client):
    response = client.get("/settings")

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_settings_page_shows_current_username(client, login):
    login()

    page = client.get("/settings").get_data(as_text=True)

    assert 'value="admin"' in page


def test_admin_can_change_password(client, login):
    login()

    response = change_password(client, new="new-secret-1")
    client.post("/logout")

    assert response.headers["Location"] == "/settings"
    assert login("admin", "admin").status_code == 401
    assert login("admin", "new-secret-1").status_code == 302


def test_password_change_is_confirmed_to_the_admin(client, login):
    login()

    response = change_password(client)
    page = text(client.get(response.headers["Location"]))

    assert "Password changed." in page


def test_password_change_needs_the_current_password(client, login):
    login()

    response = change_password(client, current="wrong")
    client.post("/logout")

    assert response.status_code == 400
    assert "Current password is wrong." in text(response)
    assert login("admin", "admin").status_code == 302


def test_new_password_must_be_at_least_8_characters(client, login):
    login()

    response = change_password(client, new="short")

    assert response.status_code == 400
    assert "at least 8 characters" in text(response)


def test_new_password_must_match_confirmation(client, login):
    login()

    response = change_password(client, new="new-secret-1", confirm="new-secret-2")

    assert response.status_code == 400
    assert "New passwords don't match." in text(response)


def test_admin_can_change_username(client, login):
    login()

    response = change_username(client, new="postmaster")
    client.post("/logout")

    assert response.headers["Location"] == "/settings"
    assert login("admin", "admin").status_code == 401
    assert login("postmaster", "admin").status_code == 302


def test_username_change_needs_the_current_password(client, login):
    login()

    response = change_username(client, new="postmaster", current_password="wrong")

    assert response.status_code == 400
    assert "Current password is wrong." in text(response)


def test_username_must_use_allowed_characters(client, login):
    login()

    response = change_username(client, new="bad name!")

    assert response.status_code == 400
    assert "3 to 32 characters" in text(response)


def test_dashboard_warns_while_default_password_is_in_use(client, login):
    login()

    assert DEFAULT_WARNING in text(client.get("/dashboard"))


def test_dashboard_warning_disappears_after_password_change(client, login):
    login()

    change_password(client)

    assert DEFAULT_WARNING not in text(client.get("/dashboard"))


def test_new_credentials_survive_app_restart(tmp_path):
    config = {"TESTING": True, "DATA_DIR": str(tmp_path), "WTF_CSRF_ENABLED": False}
    first = create_app(config).test_client()
    first.post("/login", data={"username": "admin", "password": "admin"})
    change_username(first, new="postmaster")
    change_password(first, new="new-secret-1")

    second = create_app(config).test_client()
    response = second.post("/login", data={"username": "postmaster", "password": "new-secret-1"})

    assert response.status_code == 302


def test_saved_settings_are_announced_on_a_green_board(client, login):
    login()

    response = change_password(client)
    page = text(client.get(response.headers["Location"]))

    assert 'data-board="success"' in page
    assert 'data-board-title="Saved"' in page


def settings_page(client, login):
    login()
    return client.get("/settings").get_data(as_text=True)


def test_settings_opens_on_the_account_tab(client, login):
    html = settings_page(client, login)
    tabs = html[html.index('<nav class="page-tabs"'):]
    tabs = tabs[:tabs.index("</nav>")]

    assert '<a class="page-tab" href="/settings" aria-current="page">' in tabs
    assert "Account" in tabs


def test_settings_has_a_username_card_and_a_password_card(client, login):
    html = settings_page(client, login)

    assert "Update username" in html and "Change password" in html
    assert 'value="admin" readonly' in html  # the current username is shown, not editable
    assert html.count("data-password-toggle") >= 3  # every password field has the eye


def test_password_rules_are_listed_for_a_live_check(client, login):
    html = settings_page(client, login)

    for rule in ["length", "mix", "special"]:
        assert f'data-rule="{rule}"' in html
    assert 'src="/static/js/password-rules.js?v=' in html


def test_new_password_needs_letters_and_numbers(client, login):
    login()

    for weak in ["abcdefgh!", "12345678!"]:
        response = change_password(client, new=weak)
        assert response.status_code == 400
        assert "letters and numbers" in text(response)


def test_new_password_needs_a_special_character(client, login):
    login()

    response = change_password(client, new="abcd1234")

    assert response.status_code == 400
    assert "special character" in text(response)


def test_settings_errors_come_down_on_the_red_board(client, login):
    login()

    response = change_password(client, current="wrong")

    assert 'data-board="error"' in response.get_data(as_text=True)


def test_password_card_sits_below_the_username_card_with_a_glowing_divider(client, login):
    html = settings_page(client, login)

    username_card = html.index('aria-labelledby="username-title"')
    divider = html.index('class="glow-divider"')
    password_card = html.index('aria-labelledby="password-title"')
    assert username_card < divider < password_card


def card_tags(html):
    return re.findall(r'<section class="settings-card[^"]*"', html)


def test_settings_cards_start_closed(client, login):
    html = settings_page(client, login)
    toggles = re.findall(r'<button [^>]*data-card-toggle[^>]*>', html)

    assert len(toggles) == 2
    assert all('aria-expanded="false"' in toggle for toggle in toggles)
    assert not any("is-open" in tag for tag in card_tags(html))
    assert 'src="/static/js/collapsible-cards.js?v=' in html


def test_a_card_with_an_error_opens_by_itself(client, login):
    login()

    html = change_password(client, current="wrong").get_data(as_text=True)
    username_card, password_card = card_tags(html)

    assert "is-open" in password_card and "is-open" not in username_card
    assert re.search(r'data-card-toggle aria-controls="password-body" aria-expanded="true"', html)
