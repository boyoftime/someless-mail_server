import hashlib
import html
import re
import time

import pytest

from someless import smtp
from someless.db import get_db
from someless.logins import make_login


def text(response):
    return html.unescape(response.get_data(as_text=True))


def plain(page):
    return re.sub(r"<[^>]+>", "", page)


@pytest.fixture
def client(app):
    """The panel opened by the server's public address."""
    app.config["SERVER_NAME"] = "194.163.167.106:17080"
    return app.test_client()


def generate(client, name="Website", variant="standard", expiry="1y"):
    return client.post("/smtp", data={"name": name, "variant": variant, "expiry": expiry})


def shown_key(page):
    """The key in the dialog that shows it once."""
    dialog = page[page.index('id="key-dialog"'):]
    return re.search(r'data-copy="([A-Za-z0-9]+)"', dialog).group(1)


def keys_in_db(app):
    with app.app_context():
        return get_db().execute("SELECT * FROM smtp_keys ORDER BY id").fetchall()


def test_smtp_page_needs_login(client):
    assert client.get("/smtp").headers["Location"] == "/login"


def test_the_menu_has_smtp_and_api_keys(client, login):
    login()

    page = text(client.get("/smtp"))

    menu = page[page.index('<dialog class="side-menu"'):page.index("</dialog>")]
    assert re.search(r'<a [^>]*href="/smtp"[^>]*aria-current="page"', menu)
    assert 'href="/api-keys"' in menu and "Soon" in plain(menu[menu.index('href="/api-keys"'):])


def test_api_keys_are_coming_soon(client, login):
    login()

    page = text(client.get("/api-keys"))

    assert "<title>API keys | Someless Mail</title>" in page
    assert "Coming soon" in plain(page)
    menu = page[page.index('<dialog class="side-menu"'):page.index("</dialog>")]
    assert re.search(r'<a [^>]*href="/api-keys"[^>]*aria-current="page"', menu)


def test_the_smtp_settings_say_how_to_connect(client, login, app):
    login()

    page = plain(text(client.get("/smtp")))

    assert "194.163.167.106" in page and "587" in page
    assert "The login of the key you use" in page  # each key has its own
    assert "Ready to send" in page  # and whether it can, yet


def test_an_authenticated_domain_names_the_smtp_server(client, login, app):
    login()
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO domains (name, authenticated, added_at) VALUES ('example.com', 1, 0)")
        db.execute("INSERT INTO domain_keys (domain_id, code, dkim_selector, dkim_private, dkim_public, mail_host)"
                   " VALUES (1, 'c', 'someless', 'p', 'k', 'mx')")
        db.commit()

    assert 'data-copy="mx.example.com"' in text(client.get("/smtp"))


def test_a_new_key_is_shown_once_and_only_its_fingerprint_is_kept(client, login, app):
    login()

    page = text(generate(client))

    key = shown_key(page)
    assert len(key) == 64
    row = keys_in_db(app)[0]
    assert row["name"] == "Website" and row["variant"] == "standard"
    assert row["key_hash"] == hashlib.sha256(key.encode()).hexdigest()
    assert key not in [str(value) for value in row]
    # the form that made it starts afresh for the next key (page-swap.js fills in only forms with problems)
    assert re.search(r'<form method="post" action="/smtp" class="rules-form" data-swap-fresh>', page)
    later = text(client.get("/smtp"))
    assert key not in later  # never shown again
    assert "Website" in later and "…" + key[-4:] in plain(later)


def test_a_short_key_has_15_characters(client, login):
    login()

    assert len(shown_key(text(generate(client, variant="short")))) == 15


def test_keys_expire_when_chosen(client, login, app):
    login()

    generate(client, name="A week", expiry="7d")
    generate(client, name="Forever", expiry="never")

    week, forever = keys_in_db(app)
    assert abs(week["expires_at"] - (time.time() + 7 * 86400)) < 60
    assert forever["expires_at"] is None
    page = plain(text(client.get("/smtp")))
    assert "Never" in page


def test_an_expired_key_says_so_and_no_longer_works(client, login, app):
    login()
    key = shown_key(text(generate(client)))
    with app.app_context():
        assert smtp.key_works(key)
        get_db().execute("UPDATE smtp_keys SET expires_at = 1")
        get_db().commit()
        assert not smtp.key_works(key)
        assert not smtp.key_works("x" * 64)

    assert "Expired" in plain(text(client.get("/smtp")))


@pytest.mark.parametrize("data, problem", [
    ({"name": "", "variant": "standard", "expiry": "1y"}, "Give the key a name"),
    ({"name": "Site", "variant": "long", "expiry": "1y"}, "Choose Standard or Short"),
    ({"name": "Site", "variant": "standard", "expiry": "2y"}, "Choose when the key expires"),
])
def test_a_key_needs_a_name_a_variant_and_an_expiry(client, login, app, data, problem):
    login()

    response = client.post("/smtp", data=data)

    assert response.status_code == 400
    page = text(response)
    assert problem in page
    assert re.search(r'<dialog [^>]*id="generate-dialog"[^>]*data-open', page)  # opens again, as typed
    assert keys_in_db(app) == []


def test_two_keys_cannot_share_a_name(client, login):
    login()
    generate(client, name="Website")

    response = generate(client, name="website")

    assert response.status_code == 400 and "already a key named" in text(response)


def test_a_key_can_be_deleted(client, login, app):
    login()
    generate(client)
    key_id = keys_in_db(app)[0]["id"]

    client.post(f"/smtp/{key_id}/delete")

    assert keys_in_db(app) == []
    assert "Website was deleted." in text(client.get("/smtp"))


def test_the_expiry_is_chosen_from_a_list(client, login):
    login()

    page = text(client.get("/smtp"))

    select = re.search(r'<select [^>]*name="expiry"[^>]*data-dropdown[^>]*>(.*?)</select>', page, re.S).group(1)
    options = re.findall(r'<option value="([^"]+)"([^>]*)>([^<]+)</option>', select)
    assert [value for value, _, _ in options] == ["7d", "14d", "1m", "3m", "6m", "1y", "never"]
    assert [value for value, attributes, _ in options if "selected" in attributes] == ["1y"]
    assert re.fullmatch(r"1 year \(\w{3} \d{1,2}, \d{4}\)", options[5][2])
    assert options[6][2] == "No expiration"
    # the dates count from the admin's own clock, in their time zone (local-time.js)
    assert 'data-label="7 days" data-days="7"' in options[0][1]
    assert 'data-label="1 year" data-months="12"' in options[5][1]
    assert "data-days" not in options[6][1] and "data-months" not in options[6][1]


def test_key_dates_are_shown_in_the_admins_own_time(client, login, app):
    login()
    generate(client, expiry="7d")
    created, expires = keys_in_db(app)[0]["created_at"], keys_in_db(app)[0]["expires_at"]

    page = text(client.get("/smtp"))

    from datetime import datetime, timezone
    for moment in (created, expires):
        iso = datetime.fromtimestamp(moment, timezone.utc).isoformat(timespec="seconds")
        assert re.search(rf'<time datetime="{re.escape(iso)}" data-local-date>\w{{3}} \d{{1,2}}, \d{{4}}</time>', page), iso
    assert 'src="/static/js/local-time.js?v=' in page


LANGUAGES = ["Python", "Node.js", "PHP", "Java", "C#", "Go"]


def guide(client):
    return text(client.get("/smtp/docs"))


def test_the_smtp_page_turns_over_to_the_guide(client, login):
    login()

    page = text(client.get("/smtp"))

    button = re.search(r'<a class="docs-button" href="/smtp/docs"[^>]*>', page).group(0)
    assert "data-page-flip" in button and "data-tip=" in button and "aria-label=" in button
    assert 'data-lottie="/static/lottie/programming.json' in page
    assert 'src="/static/js/page-flip.js?v=' in page


def test_the_guide_needs_login(client):
    assert client.get("/smtp/docs").headers["Location"] == "/login"


def test_the_guide_shows_six_languages_with_these_settings(client, login, app):
    login()

    page = guide(client)

    assert "<title>Send mail from your code | Someless Mail</title>" in page
    tabs = re.findall(r'<button [^>]*role="tab"[^>]*>(.*?)</button>', page, re.S)
    assert [plain(tab).strip() for tab in tabs] == LANGUAGES
    icons = [re.search(r'<span class="lang-badge"[^>]*><img src="/static/img/lang/(\w+)\.svg', tab) for tab in tabs]
    assert [icon.group(1) for icon in icons] == ["python", "nodejs", "php", "java", "csharp", "go"]  # each in its round badge
    samples = re.findall(r'<pre class="code-block"[^>]*><code>(.*?)</code></pre>', page, re.S)
    assert len(samples) == 6
    for language, sample in zip(LANGUAGES, samples):
        code = plain(sample)
        assert "194.163.167.106" in code and "587" in code and "SOMELESS_SMTP_LOGIN" in code, language
        assert "SOMELESS_SMTP_KEY" in code, language  # the key comes from the environment, never the code
    assert re.search(r'<a class="back-link" href="/smtp" data-page-flip="back"', page)
    menu = page[page.index('<dialog class="side-menu"'):page.index("</dialog>")]
    assert re.search(r'<a [^>]*href="/smtp"[^>]*aria-current="page"', menu)


def test_the_guide_copies_the_code_as_it_is(client, login):
    login()

    raw = client.get("/smtp/docs").get_data(as_text=True)

    assert "&lt;?php" in raw and "<?php" not in raw  # shown as text, never run as markup
    php = html.unescape(re.findall(r'data-copy="([^"]*)"', raw)[[i for i, value in enumerate(re.findall(r'data-copy="([^"]*)"', raw)) if "PHPMailer" in value][0]])
    assert php.startswith("<?php\n") and "$mail->send();" in php


def test_the_guide_sends_from_an_authenticated_domain(client, login, app):
    login()
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO domains (name, authenticated, added_at) VALUES ('example.com', 1, 0)")
        db.execute("INSERT INTO domain_keys (domain_id, code, dkim_selector, dkim_private, dkim_public)"
                   " VALUES (1, 'c', 'someless', 'p', 'k')")
        db.commit()

    assert "hello@example.com" in plain(guide(client))


def test_logins_are_made_from_the_key_name():
    assert re.fullmatch(r"website-[0-9a-f]{4}", make_login("Website", set()))
    assert re.fullmatch(r"my-shop-2026-[0-9a-f]{4}", make_login("My Shop 2026!", set()))
    assert re.fullmatch(r"unicode-[0-9a-f]{4}", make_login("Ünïcödé ✨", set()))
    assert re.fullmatch(r"key-[0-9a-f]{4}", make_login("✨✨", set()))
    assert len(make_login("a" * 50, set())) == 25


def test_a_new_key_comes_with_its_own_login(client, login, app):
    login()

    page = text(generate(client))

    row = keys_in_db(app)[0]
    assert re.fullmatch(r"website-[0-9a-f]{4}", row["login"])
    dialog = page[page.index('id="key-dialog"'):]
    assert f'data-copy="{row["login"]}"' in dialog     # copied with its own button
    assert row["login"] in plain(text(client.get("/smtp")))  # and listed with the key


def test_keys_from_before_get_a_login(tmp_path):
    import sqlite3
    from someless import create_app
    with sqlite3.connect(tmp_path / "someless.db") as db:
        db.execute("CREATE TABLE smtp_keys (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, key_hash TEXT NOT NULL,"
                   " hint TEXT NOT NULL, variant TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL)")
        db.execute("INSERT INTO smtp_keys (name, key_hash, hint, variant, created_at) VALUES ('Old app', 'h', 'xxxx', 'standard', 0)")

    create_app({"TESTING": True, "DATA_DIR": str(tmp_path)})

    with sqlite3.connect(tmp_path / "someless.db") as db:
        (login,) = db.execute("SELECT login FROM smtp_keys").fetchone()
    assert re.fullmatch(r"old-app-[0-9a-f]{4}", login)


def test_smtp_page_without_engine(client, login):
    login()
    page = plain(text(client.get("/smtp")))
    assert "Ready to send" in page and "mail engine isn't running here" in page


def test_the_server_name_is_chosen_from_the_authenticated_domains(client, login, app, engine):
    from test_engine_sync import authenticated_domain
    from someless import engine as engine_module
    authenticated_domain(app, "cloudnix.net")
    authenticated_domain(app, "pineloop.online")
    login()

    page = text(client.get("/smtp"))
    assert '<option value="mail.pineloop.online"' in page  # two domains: a choice
    client.post("/smtp/server-name", data={"server_name": "mail.pineloop.online"})
    client.post("/smtp/server-name", data={"server_name": "mail.elsewhere.com"})  # not one of them: ignored

    with app.app_context():
        assert engine_module.state()["server_name"] == "mail.pineloop.online"
    assert engine.objects["SystemSettings"]["singleton"]["defaultHostname"] == "mail.pineloop.online"
    assert "mail.pineloop.online" in plain(text(client.get("/smtp")))  # the SMTP server apps use


def test_check_again_looks_again(client, login, monkeypatch):
    from someless.engine import checks
    login()
    client.get("/smtp")
    monkeypatch.setattr(checks, "port25_open", lambda: False)

    client.post("/smtp/checks")

    assert "blocks outgoing port 25" in plain(text(client.get("/smtp")))
