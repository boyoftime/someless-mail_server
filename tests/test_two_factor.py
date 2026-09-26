import base64
import html
import re

import pytest

from someless import two_factor
from someless.db import get_db

JSON = {"Accept": "application/json"}
KNOWN_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32 of the RFC 6238 test key


def text(response):
    return html.unescape(response.get_data(as_text=True))


@pytest.fixture
def clock(monkeypatch):
    """A fixed time for the authenticator PINs; call it to move on (30 s by default)."""
    now = [1_800_000_000.0]
    monkeypatch.setattr(two_factor, "clock", lambda: now[0])

    def advance(seconds=30):
        now[0] += seconds
    return advance


@pytest.fixture(autouse=True)
def known_secret(monkeypatch):
    monkeypatch.setattr(two_factor, "new_secret", lambda: KNOWN_SECRET)


def stored(app, column="secret"):
    with app.app_context():
        return get_db().execute(f"SELECT {column} FROM two_factor").fetchone()[0]


def pin_now():
    return two_factor.code_at(KNOWN_SECRET, two_factor.current_step())


def wrong_pin():
    step = two_factor.current_step()
    valid = {two_factor.code_at(KNOWN_SECRET, step + d) for d in (-1, 0, 1)}
    return next(f"{n:06d}" for n in range(1_000_000) if f"{n:06d}" not in valid)


def turn_on(client, clock):
    client.post("/settings/two-factor/setup")
    response = client.post("/settings/two-factor/enable", data={"pin": pin_now()})
    clock()  # each PIN works once: the next one comes 30 seconds later
    return response


def password_step(client):
    return client.post("/login", data={"username": "admin", "password": "admin"}, headers=JSON)


def settings_page(client):
    return text(client.get("/settings"))


def two_factor_card(page):
    start = page.index('aria-labelledby="two-factor-title"')
    return page[start:page.index("</section>", start)]


def test_pins_follow_the_authenticator_app_standard():
    # RFC 6238 test values (SHA-1, 6 digits), as every authenticator app computes them
    secret = base64.b32encode(b"12345678901234567890").decode()
    for seconds, expected in [(59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")]:
        assert two_factor.code_at(secret, seconds // 30) == expected


def test_two_factor_card_sits_below_the_password_card(client, login):
    login()
    page = settings_page(client)

    password_card = page.index('aria-labelledby="password-title"')
    divider = page.index('class="glow-divider"', password_card)
    assert password_card < divider < page.index('aria-labelledby="two-factor-title"')


def test_password_is_always_asked_and_its_switch_is_locked(client, login):
    login()
    card = two_factor_card(settings_page(client))

    assert re.search(r'role="switch" aria-checked="true" aria-disabled="true" aria-label="Use password', card)
    assert re.search(r'role="switch" aria-checked="false" aria-label="Use PIN"', card)


def test_switching_the_pin_on_shows_a_qr_code_to_scan(client, login):
    login()
    client.post("/settings/two-factor/setup")
    card = two_factor_card(settings_page(client))

    assert re.search(r'<div class="factor-qr"[^>]*><svg', card)
    assert "GEZD GNBV GY3T QOJQ GEZD GNBV GY3T QOJQ" in card  # the key, to type in by hand
    # grey until a PIN confirms it, green only once it's really on
    assert re.search(r'class="switch is-on is-pending"[^>]*aria-label="Use PIN"', card)
    # ...with a button that copies it (without the spaces)
    assert 'data-copy="GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"' in card
    # once the page comes in, it glides down to this part
    assert re.search(r'<div class="factor-setup" data-swap-reveal', card)


def test_copy_buttons_work_on_every_signed_in_page(client, login):
    login()
    page = settings_page(client)
    main = page[page.index('<main class="app-main"'):page.index("</main>")]

    assert 'src="/static/js/copy-button.js?v=' in page
    assert "copy-button.js" not in main  # loaded once with the layout, not with every swapped page


def test_the_pin_turns_on_only_with_a_pin_from_the_app(client, login, app, clock):
    login()
    client.post("/settings/two-factor/setup")

    wrong = client.post("/settings/two-factor/enable", data={"pin": wrong_pin()})
    assert wrong.status_code == 400
    assert "didn't match" in text(wrong)
    assert stored(app) is None

    right = client.post("/settings/two-factor/enable", data={"pin": pin_now()})
    assert right.headers["Location"] == "/settings"
    assert stored(app) == KNOWN_SECRET
    card = two_factor_card(settings_page(client))
    assert re.search(r'role="switch" aria-checked="true"[^>]*aria-label="Use PIN"', card)
    assert "is-pending" not in card


def test_setup_can_be_cancelled(client, login, app):
    login()
    client.post("/settings/two-factor/setup")

    client.post("/settings/two-factor/cancel")

    assert stored(app, "pending_secret") is None
    assert "factor-qr" not in two_factor_card(settings_page(client))


def test_login_asks_for_the_pin_after_the_password(client, login, clock):
    login()
    turn_on(client, clock)
    client.post("/logout")

    assert password_step(client).get_json() == {"pin": True}
    assert client.get("/dashboard").headers["Location"] == "/login"  # not in yet

    response = client.post("/login/pin", data={"pin": pin_now()}, headers=JSON)
    assert response.get_json() == {"redirect": "/dashboard"}
    assert client.get("/dashboard").status_code == 200


def test_without_javascript_the_login_page_shows_the_pin_form(client, login, clock):
    login()
    turn_on(client, clock)
    client.post("/logout")

    response = client.post("/login", data={"username": "admin", "password": "admin"})

    page = text(response)
    assert response.status_code == 200
    assert re.search(r"<form [^>]*data-pin-form(?![^>]*hidden)", page)
    assert re.search(r"<form [^>]*data-login-form[^>]*hidden", page)


def test_the_pin_step_needs_the_right_password_first(client, login, clock):
    login()
    turn_on(client, clock)
    client.post("/logout")
    client.post("/login", data={"username": "admin", "password": "wrong"}, headers=JSON)

    response = client.post("/login/pin", data={"pin": pin_now()}, headers=JSON)

    assert response.status_code == 401
    assert response.get_json()["restart"] is True
    assert client.get("/dashboard").status_code == 302


def test_a_wrong_pin_is_refused(client, login, clock):
    login()
    turn_on(client, clock)
    client.post("/logout")
    password_step(client)

    response = client.post("/login/pin", data={"pin": wrong_pin()}, headers=JSON)

    assert response.status_code == 401
    assert "Wrong PIN" in response.get_json()["error"]


def test_a_pin_works_only_once(client, login, clock):
    login()
    turn_on(client, clock)
    client.post("/logout")
    used = pin_now()
    password_step(client)
    client.post("/login/pin", data={"pin": used}, headers=JSON)
    client.post("/logout")

    password_step(client)
    response = client.post("/login/pin", data={"pin": used}, headers=JSON)

    assert response.status_code == 401


def test_five_wrong_pins_lock_the_pin_for_five_minutes(client, login, clock):
    login()
    turn_on(client, clock)
    client.post("/logout")
    password_step(client)
    for _ in range(5):
        client.post("/login/pin", data={"pin": wrong_pin()}, headers=JSON)

    password_step(client)
    locked = client.post("/login/pin", data={"pin": pin_now()}, headers=JSON)
    assert locked.status_code == 429
    assert "Too many wrong PINs" in locked.get_json()["error"]

    clock(5 * 60 + 1)
    password_step(client)
    assert client.post("/login/pin", data={"pin": pin_now()}, headers=JSON).status_code == 200


def test_the_pin_step_runs_out_after_five_minutes(client, login, clock):
    login()
    turn_on(client, clock)
    client.post("/logout")
    password_step(client)

    clock(5 * 60 + 1)
    response = client.post("/login/pin", data={"pin": pin_now()}, headers=JSON)

    assert response.status_code == 401
    assert response.get_json()["restart"] is True


def test_switching_the_pin_off_needs_a_pin(client, login, app, clock):
    login()
    turn_on(client, clock)

    wrong = client.post("/settings/two-factor/disable", data={"pin": wrong_pin()})
    assert wrong.status_code == 400
    assert stored(app) == KNOWN_SECRET

    client.post("/settings/two-factor/disable", data={"pin": pin_now()})
    assert stored(app) is None
    client.post("/logout")
    assert login().headers["Location"] == "/dashboard"  # the password alone again


def test_two_factor_settings_need_login(client):
    response = client.post("/settings/two-factor/setup")

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_lost_phone_command_switches_the_pin_off(client, login, app, clock):
    login()
    turn_on(client, clock)

    result = app.test_cli_runner().invoke(args=["two-factor", "off"])

    assert result.exit_code == 0
    assert "off" in result.output
    assert stored(app) is None
