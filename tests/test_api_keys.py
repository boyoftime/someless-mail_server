"""API keys (api_keys.py): the page that makes the keys the API takes (api.py), and its guide."""
import hashlib
import html
import re
import time

import pytest

from someless.db import get_db


def text(response):
    return html.unescape(response.get_data(as_text=True))


def plain(page):
    return re.sub(r"<[^>]+>", "", page)


@pytest.fixture
def client(app):
    """The panel opened by its public address."""
    app.config["SERVER_NAME"] = "panel.pineloop.online"
    return app.test_client()


def create(client, name="Website", expiry="1y"):
    return client.post("/api-keys", data={"name": name, "expiry": expiry})


def shown_key(page):
    """The key in the dialog that shows it once."""
    dialog = page[page.index('id="key-dialog"'):]
    return re.search(r'data-copy="(sm_[A-Za-z0-9]+)"', dialog).group(1)


def keys_in_db(app):
    with app.app_context():
        return get_db().execute("SELECT * FROM api_keys ORDER BY id").fetchall()


def menu_of(page):
    return page[page.index('<dialog class="side-menu"'):page.index("</dialog>")]


def test_the_page_needs_login(client):
    assert client.get("/api-keys").headers["Location"] == "/login"
    assert client.get("/api-keys/docs").headers["Location"] == "/login"


def test_api_keys_are_here_now(client, login):
    login()

    page = text(client.get("/api-keys"))

    assert "<title>API keys | Someless Mail</title>" in page
    assert "Coming soon" not in plain(page)
    menu = menu_of(page)
    assert re.search(r'<a [^>]*href="/api-keys"[^>]*aria-current="page"', menu)
    assert "Soon" not in plain(menu)
    assert "No API keys yet" in plain(page)


def test_a_new_key_is_shown_once_and_only_its_fingerprint_is_kept(client, login, app):
    login()

    page = text(create(client))

    key = shown_key(page)
    assert re.fullmatch(r"sm_[A-Za-z0-9]{48}", key)
    row = keys_in_db(app)[0]
    assert row["name"] == "Website" and row["hint"] == key[-4:]
    assert row["key_hash"] == hashlib.sha256(key.encode()).hexdigest()
    assert key not in [str(value) for value in row]
    later = text(client.get("/api-keys"))
    assert key not in later   # never shown again
    assert "Website" in later and "…" + key[-4:] in plain(later) and "Never used" in plain(later)


def test_keys_expire_when_chosen(client, login, app):
    login()

    create(client, name="A week", expiry="7d")
    create(client, name="Forever", expiry="never")

    week, forever = keys_in_db(app)
    assert abs(week["expires_at"] - (time.time() + 7 * 86400)) < 60
    assert forever["expires_at"] is None


@pytest.mark.parametrize("data, problem", [
    ({"name": "", "expiry": "1y"}, "Give the key a name"),
    ({"name": "x" * 61, "expiry": "1y"}, "60 characters or fewer"),
    ({"name": "Site", "expiry": "2y"}, "Choose when the key expires"),
])
def test_a_key_needs_a_name_and_an_expiry(client, login, app, data, problem):
    login()

    response = client.post("/api-keys", data=data)

    assert response.status_code == 400 and problem in text(response)
    assert re.search(r'<dialog [^>]*id="generate-dialog"[^>]*data-open', text(response))   # opens again, as typed
    assert keys_in_db(app) == []


def test_two_keys_cannot_share_a_name(client, login):
    login()
    create(client, name="Website")

    response = create(client, name="website")

    assert response.status_code == 400 and "already a key named" in text(response)


def test_a_key_can_be_deleted(client, login, app):
    login()
    create(client)

    client.post(f"/api-keys/{keys_in_db(app)[0]['id']}/delete")

    assert keys_in_db(app) == []
    assert "Website was deleted." in text(client.get("/api-keys"))


def test_the_page_turns_over_to_the_guide(client, login):
    login()

    page = text(client.get("/api-keys"))

    assert re.search(r'<a class="docs-button" href="/api-keys/docs"[^>]*data-page-flip', page)


def test_the_guide_explains_every_call_with_this_panels_address(client, login, app):
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO domains (name, authenticated, added_at) VALUES ('pineloop.online', 1, 0)")
        db.commit()
    login()

    page = text(client.get("/api-keys/docs"))

    assert "<title>The Someless Mail API | Someless Mail</title>" in page
    words = plain(page)
    assert "https://panel.pineloop.online/api/s1" in words or "http://panel.pineloop.online/api/s1" in words
    assert "Authorization: Bearer" in words
    for call in ("GET /domains", "POST /domains", "GET /domains/{name}", "POST /domains/{name}/authenticate",
                 "DELETE /domains/{name}", "GET /senders", "POST /senders", "GET /senders/{id}", "PATCH /senders/{id}",
                 "DELETE /senders/{id}", "GET /mailboxes", "POST /mailboxes", "GET /mailboxes/{id}",
                 "PATCH /mailboxes/{id}", "POST /mailboxes/password", "DELETE /mailboxes/{id}",
                 "POST /mailboxes/{id}/aliases", "DELETE /mailboxes/{id}/aliases/{alias}"):
        assert call in words, call
    for field in ("storage", "send_limit_mb", "disable_delete", "aliases", "password", "disabled", "refuse_mail"):
        assert field in words, field
    assert "@pineloop.online" in words   # the examples use one of the admin's authenticated domains
    assert re.search(r'<a class="back-link" href="/api-keys" data-page-flip="back"', page)
    assert re.search(r'<a [^>]*href="/api-keys"[^>]*aria-current="page"', menu_of(page))


def test_each_call_shows_its_request_and_its_response_side_by_side(client, login):
    """As in Postman: the call on the left; on the right its request, in four languages (the one
    picked is picked for every call: api-docs.js), and its response, each with a copy button."""
    login()

    page = text(client.get("/api-keys/docs"))

    calls = re.findall(r'<article class="api-call" id="(call-[a-z-]+)">(.*?)</article>', page, re.S)
    assert len(calls) == 20
    for call_id, call in calls:
        assert '<div class="api-call-doc">' in call and '<div class="api-call-code">' in call, call_id
        tabs = re.findall(r'<button [^>]*role="tab"[^>]*>(.*?)</button>', call, re.S)
        assert [plain(tab).strip() for tab in tabs] == ["cURL", "JavaScript", "Python", "PHP"], call_id
        requests = re.findall(r'<pre class="code-block"[^>]*><code>(.*?)</code></pre>', call, re.S)
        assert len(requests) == 4, call_id
        for request in requests:
            assert "SOMELESS_API_KEY" in plain(request), call_id   # the key from the environment, never the code
        response = call[call.index('class="api-console is-response"'):]
        assert re.search(r'<span class="api-status is-ok">20[01] (OK|Created)</span>', response), call_id
        assert len(re.findall(r'<button [^>]*class="[^"]*api-copy[^"]*"[^>]*data-copy="', call)) == 2, call_id
    post_mailboxes = dict(calls)["call-post-mailboxes"]
    assert "201 Created" in post_mailboxes and '"send_limit_mb"' in plain(post_mailboxes)
    assert "requests.post(" in plain(post_mailboxes) and "CURLOPT_POSTFIELDS" in plain(post_mailboxes)
    assert 'src="/static/js/api-docs.js?v=' in page


CALLS = ("GET /domains", "POST /domains", "GET /domains/{name}", "POST /domains/{name}/authenticate", "DELETE /domains/{name}",
         "GET /senders", "POST /senders", "GET /senders/{id}", "PATCH /senders/{id}", "DELETE /senders/{id}",
         "GET /mailboxes", "POST /mailboxes", "GET /mailboxes/{id}", "PATCH /mailboxes/{id}", "POST /mailboxes/password",
         "DELETE /mailboxes/{id}", "POST /mailboxes/{id}/aliases", "DELETE /mailboxes/{id}/aliases/{alias}")


def test_the_whole_guide_is_also_plain_text_for_an_ai_with_no_login(client, app):
    with app.app_context():
        get_db().execute("INSERT INTO domains (name, authenticated, added_at) VALUES ('pineloop.online', 1, 0)")
        get_db().commit()

    response = client.get("/api/s1/docs.md")   # (no login, no key: an AI assistant opens it)

    assert response.status_code == 200 and response.mimetype == "text/markdown"
    guide = response.get_data(as_text=True)
    assert guide.startswith("# The Someless Mail API")
    assert "http://panel.pineloop.online/api/s1" in guide and "Authorization: Bearer" in guide
    for call in CALLS:
        assert f"## {call}" in guide, call
    for field in ("`storage`", "`send_limit_mb`", "`disable_delete`", "`aliases`", "`password`", "`disabled`", "`refuse_mail`",
                  "SOMELESS_API_KEY",
                  '"send_limit_mb": 50', "201 Created", "429"):
        assert field in guide, field
    # open to anyone: the admin's own domains stay out of it (an app finds them with GET /domains)
    assert "pineloop.online" not in guide.replace("panel.pineloop.online", "") and "@example.com" in guide


def test_the_guide_page_offers_the_link_and_the_text_for_an_ai(client, login):
    """In a pop-up, opened by the AI animation at the top right of the guide's title"""
    login()

    page = text(client.get("/api-keys/docs"))

    header = page[page.index('<header class="page-header page-header-row">'):]
    header = header[:header.index("</header>")]
    button = re.search(r'<button type="button" class="docs-button api-ai-button" data-dialog-open="ai-dialog"[^>]*>', header).group(0)
    assert 'aria-haspopup="dialog"' in button and "aria-label=" in button
    assert 'data-lottie="/static/lottie/ai-loading.json?v=' in header
    assert re.search(r'<dialog class="api-ai-dialog" id="ai-dialog" aria-labelledby="api-ai-title">', page)
    assert page.index('id="ai-dialog"') < page.index('class="api-ai"')   # (the card is in the pop-up, not on the page)
    card = page[page.index('class="api-ai"'):]
    assert re.search(r'<span class="api-ai-badge" aria-hidden="true">\s*<span class="api-ai-badge-anim" data-lottie="/static/lottie/ai\.json\?v=', card)
    card = card[:card.index("</section>")]
    assert 'data-copy="http://panel.pineloop.online/api/s1/docs.md"' in card
    raw = client.get("/api-keys/docs").get_data(as_text=True)   # (the text's own quotes stay escaped in it)
    whole = html.unescape(re.search(r'<button [^>]*class="[^"]*api-ai-copy[^"]*"[^>]*data-copy="([^"]*)"', raw).group(1))
    assert whole.startswith("# The Someless Mail API") and "## POST /mailboxes" in whole
    assert re.search(r'<a [^>]*href="/api/s1/docs.md"[^>]*target="_blank"', card)


def test_a_long_line_of_code_scrolls_in_its_console_never_out_of_its_card(client):
    """(the longest, Python's headers line, is wider than the console on a 1920 screen at 125%)"""
    css = client.get("/static/css/style.css").get_data(as_text=True)

    assert re.search(r"\.api-call-code \{[^}]*grid-template-columns: minmax\(0, 1fr\)", css)
    assert re.search(r"\.api-console \{[^}]*min-width: 0", css)


def test_the_guide_stands_on_a_grass_island(client, login):
    """From its title down, the guide sits on one big rounded block of Kenney's grass: grass along
    its top, earth through it, a jagged rocky edge under it (public domain art)."""
    login()

    page = text(client.get("/api-keys/docs"))

    land = page[page.index('<div class="api-land">'):]
    assert page.index('class="back-link"') < page.index('<div class="api-land">')   # (the way back stays above it)
    assert re.match(r'<div class="api-land">\s*<div class="api-land-art" aria-hidden="true"></div>\s*'
                    r'<header class="page-header page-header-row">\s*<div>\s*<h1 class="page-title">The Someless Mail API</h1>', land)
    css = client.get("/static/css/style.css").get_data(as_text=True)
    rule = " ".join(re.findall(r"\.api-land-art(?:::before|::after)? \{[^}]*\}", css))
    for piece in ("top", "fill", "bottom"):
        assert f'url("../img/api/grass-{piece}.png")' in rule, piece
        assert client.get(f"/static/img/api/grass-{piece}.png").status_code == 200, piece
    wires = client.get("/static/js/api-wires.js").get_data(as_text=True)   # (the ropes still find every card: from the title down)
    assert ".api-land > .page-header" in wires and ".api-land > .smtp-card" in wires and ".api-ai," not in wires


def test_glowing_ropes_tie_the_guides_cards_together(client, login):
    """Down the right of the cards, five glowing ropes waving, with a branch into each card (api-wires.js)"""
    login()

    page = text(client.get("/api-keys/docs"))

    assert re.search(r'<div class="api-docs" data-api-wires>', page)
    assert re.search(r'<canvas class="api-wires" aria-hidden="true"></canvas>', page)
    assert 'src="/static/js/api-wires.js?v=' in page


def test_the_guide_starts_with_an_index_of_the_calls(client, login):
    login()

    page = text(client.get("/api-keys/docs"))

    index = page[page.index('<nav class="api-index"'):]
    index = index[:index.index("</nav>")]
    links = re.findall(r'<a [^>]*href="#(call-[a-z-]+)"[^>]*>', index)
    assert len(links) == 20 and len(set(links)) == 20
    for link in links:
        assert f'id="{link}"' in page
    # as in Postman's sidebar: each group with its icon and how many calls; each call named in words, its path under it
    words = re.sub(r"\s+", " ", plain(index))
    for group, count in (("Domains", "5 calls"), ("Senders", "5 calls"), ("Mailboxes", "10 calls")):
        assert f"{group} {count}" in words, group
    for name, path in (("Make a mailbox", "/mailboxes"), ("Reset a password", "/mailboxes/password"),
                       ("Check a mailbox's password", "/mailboxes/login"), ("Get a profile picture", "/mailboxes/{id}/picture"),
                       ("Delete an alias", "/mailboxes/{id}/aliases/{alias}")):
        assert f"{name} {path}" in words, name
