import html
import re

from someless import create_app


def text(response):
    return html.unescape(response.get_data(as_text=True))


def save_rules(client, min_length="8", letters=True, numbers=True, special=True):
    data = {"min_length": min_length}
    for name, forced in [("require_letters", letters), ("require_numbers", numbers), ("require_special", special)]:
        if forced:
            data[name] = "on"
    return client.post("/settings/password-rules", data=data)


def change_password(client, new, current="admin"):
    return client.post("/settings/password", data={
        "current_password": current,
        "new_password": new,
        "confirm_password": new,
    })


def settings_page(client):
    return text(client.get("/settings"))


def rules_dialog(page):
    start = page.index('id="password-rules-dialog"')
    return page[start:page.index("</dialog>", start)]


def rules_list(page):
    start = page.index("data-password-rules")
    return page[start:page.index("</ul>", start)]


def test_password_card_has_a_password_rules_button_and_dialog(client, login):
    login()
    page = settings_page(client)

    assert 'data-dialog-open="password-rules-dialog"' in page
    assert '<dialog class="rules-dialog" id="password-rules-dialog"' in page
    assert 'src="/static/js/password-rules-dialog.js?v=' in page


def test_rules_start_at_8_characters_with_everything_forced(client, login):
    login()
    dialog = rules_dialog(settings_page(client))

    assert re.search(r'<input type="range"[^>]*name="min_length" min="1" max="12" step="1" value="8"', dialog)
    assert dialog.count('class="length-dot') == 12  # the glowing line has a dot for 1 to 12
    for name in ["require_special", "require_numbers", "require_letters"]:
        assert re.search(rf'<input [^>]*name="{name}"[^>]*checked', dialog)


def test_saving_rules_is_confirmed_on_settings(client, login):
    login()

    response = save_rules(client, min_length="10")

    assert response.headers["Location"] == "/settings"
    assert "Password rules saved." in settings_page(client)


def test_the_list_follows_the_saved_rules(client, login):
    login()
    save_rules(client, min_length="10", letters=False, numbers=False, special=True)

    listed = rules_list(settings_page(client))

    assert "At least 10 characters" in listed
    assert 'data-min-length="10"' in listed
    assert 'data-rule="special"' in listed
    assert 'data-rule="letter"' not in listed and 'data-rule="number"' not in listed


def test_new_password_follows_the_saved_rules(client, login):
    login()
    save_rules(client, min_length="10", letters=True, numbers=False, special=False)

    too_short = change_password(client, "abcdefghi")  # 9 characters

    assert too_short.status_code == 400
    assert "at least 10 characters" in text(too_short)
    assert change_password(client, "abcdefghij").status_code == 302  # letters only is enough now


def test_rules_can_allow_a_short_simple_password(client, login):
    login()
    save_rules(client, min_length="4", letters=False, numbers=False, special=False)

    assert change_password(client, "1234").status_code == 302


def test_each_forced_kind_of_character_is_checked(client, login):
    login()  # everything is forced to start with

    for password, message in [
        ("12345678!", "needs a letter"),
        ("abcdefgh!", "needs a number"),
        ("abcd1234", "needs a special character"),
    ]:
        response = change_password(client, password)
        assert response.status_code == 400
        assert message in text(response)


def test_minimum_length_must_be_1_to_12(client, login):
    login()

    for bad in ["0", "13", "eight", ""]:
        response = save_rules(client, min_length=bad)
        assert response.status_code == 400
        assert "from 1 to 12" in text(response)


def test_password_rules_need_login(client):
    response = save_rules(client)

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_rules_survive_a_restart(tmp_path):
    config = {"TESTING": True, "DATA_DIR": str(tmp_path), "WTF_CSRF_ENABLED": False}
    first = create_app(config).test_client()
    first.post("/login", data={"username": "admin", "password": "admin"})
    save_rules(first, min_length="12", special=False)

    second = create_app(config).test_client()
    second.post("/login", data={"username": "admin", "password": "admin"})
    page = settings_page(second)

    assert "At least 12 characters" in rules_list(page)
    special = re.search(r'<input [^>]*name="require_special"[^>]*>', page).group(0)
    assert "checked" not in special
