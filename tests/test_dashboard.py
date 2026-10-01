import html
import re

from test_engine_sync import a_mailbox, a_sender, authenticated_domain


def main_area(client, login):
    login()
    page = html.unescape(client.get("/dashboard").get_data(as_text=True))
    return page[page.index('<main class="app-main"'):page.index("</main>")]


def boards(main):
    """The hanging boards: [(link, count, name)]"""
    return re.findall(r'<a class="dash-board"[^>]*href="([^"]+)"[^>]*>.*?<span class="dash-board-count">(\d+)</span>\s*'
                      r'<span class="dash-board-label">([^<]+)</span>', main, re.S)


def test_the_dashboard_hangs_a_board_each_for_domains_mailboxes_and_senders(app, client, login):
    domain_id = authenticated_domain(app)
    authenticated_domain(app, "samakiafrica.com", authenticated=False)
    a_sender(app, domain_id, "ceo@pineloop.online")
    a_sender(app, domain_id, "info@pineloop.online")
    a_mailbox(app, "ceo@pineloop.online", domain_id)

    main = main_area(client, login)

    assert '<h1 class="page-title">Dashboard</h1>' in main and "Coming soon" not in main
    # (the mail server: one, going by an authenticated domain's mail name, mail.pineloop.online)
    assert boards(main) == [("/domains", "2", "Domains"), ("/mailboxes", "1", "Mailbox"), ("/senders", "2", "Senders"),
                            ("/settings/mail-server", "1", "Mail server")]
    # (swinging in the wind: PixiJS draws the ropes and the breeze; the boards stay links to read and click)
    assert "data-dash-hang" in main and "js/dashboard.js" in main
    assert re.search(r'data-pixi="/static/js/pixi\.min\.js\?v=[0-9a-f]+"', main)


def test_the_boards_hang_from_a_metal_beam(client, login):
    """(Kenney's platformer art, public domain: its metal platform, a beam across each row of boards)"""
    css = client.get("/static/css/style.css").get_data(as_text=True)
    assert re.search(r'\.dash-beam \{[^}]*url\("\.\./img/dash/beam-left\.png"\)', css)
    for piece in ("left", "mid", "right"):
        assert client.get(f"/static/img/dash/beam-{piece}.png").status_code == 200
    script = client.get("/static/js/dashboard.js").get_data(as_text=True)
    assert '"dash-beam"' in script


def test_a_helicopter_flies_over_the_boards_now_and_then(client, login):
    """The boards hang nearly still; every 30 seconds a helicopter flies across (dashboard.js), and its
    downwash swings each board as it passes. Not with less motion asked for (motion only)."""
    main = main_area(client, login)

    heli = re.search(r'<div class="dash-heli" aria-hidden="true" data-lottie="([^"]+)" data-lottie-motion-only></div>', main)
    assert heli and heli.group(1).startswith("/static/lottie/helicopter.json")
    assert client.get("/static/lottie/helicopter.json").status_code == 200
    assert main.index('class="dash-heli"') > main.index("data-dash-hang")   # (it flies inside the boards' space)


def test_the_boards_are_made_of_sand(client):
    """(Kenney's sand tiles: a cream sand top along each board, sandstone under it, dark words on it)"""
    css = client.get("/static/css/style.css").get_data(as_text=True)
    rule = re.search(r"\.dash-board \{[^}]*\}", css).group(0)
    assert 'url("../img/dash/sand-top.png")' in rule and 'url("../img/dash/sand-fill.png")' in rule
    for piece in ("top", "fill"):
        assert client.get(f"/static/img/dash/sand-{piece}.png").status_code == 200
    assert not re.search(r':root:not\(\[data-theme="dark"\]\) \.dash-board \{[^}]*background', css)   # (sand in both themes)


def test_the_ropes_are_tied_to_the_middle_of_the_beam(client):
    """Over the beam, not behind it: the beam, then the ropes (PixiJS's canvas), then the boards;
    still, the CSS ropes reach as high as the beam's middle."""
    css = client.get("/static/css/style.css").get_data(as_text=True)

    def z(selector):
        return int(re.search(re.escape(selector) + r' \{[^}]*z-index: (\d+)', css).group(1))

    assert z(".dash-beam") < z(".dash-sky") < z(".dash-boards")
    assert re.search(r'\.dash-board::after \{[^}]*height: calc\(var\(--rope\) \+ var\(--beam\) / 2', css)


def test_a_new_server_shows_its_boards_at_nought(client, login):
    """(no mail server yet either: it takes its name once a domain is authenticated)"""
    assert boards(main_area(client, login)) == [("/domains", "0", "Domains"), ("/mailboxes", "0", "Mailboxes"),
                                                ("/senders", "0", "Senders"), ("/settings/mail-server", "0", "Mail servers")]


def test_dashboard_still_warns_about_the_default_password(client, login):
    assert "You're still using the password Someless Mail started with" in main_area(client, login)
