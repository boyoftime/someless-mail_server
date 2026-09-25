import re


def visible_text(response):
    html = response.get_data(as_text=True)
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def test_welcome_page_greets_visitor(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Welcome to Someless Mail Server" in visible_text(response)


def test_welcome_page_moves_on_to_login_after_6_seconds(client):
    html = client.get("/").get_data(as_text=True)

    # splash.js times the move; the refresh is the fallback for browsers without JavaScript
    assert 'data-next="/login"' in html
    assert '<noscript><meta http-equiv="refresh" content="6; url=/login">' in html


def test_loading_animation_is_served_from_our_own_server(client):
    html = client.get("/").get_data(as_text=True)
    player = client.get("/static/js/lottie_light.min.js")
    animation = client.get("/static/lottie/loading.json")

    assert 'src="/static/js/lottie_light.min.js?v=' in html
    assert 'data-src="/static/lottie/loading.json?v=' in html
    assert player.status_code == 200
    assert "layers" in animation.get_json()


def test_google_sans_is_served_from_our_own_server(client):
    html = client.get("/").get_data(as_text=True)
    css = client.get("/static/css/style.css").get_data(as_text=True)
    font = client.get("/static/fonts/GoogleSans-latin.woff2")

    assert 'href="/static/css/style.css?v=' in html
    assert "fonts.googleapis.com" not in html
    assert "GoogleSans-latin.woff2" in css
    assert font.status_code == 200


def test_healthz_reports_ok(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "ok"


def test_every_page_has_the_top_loading_bar(client, login):
    pages = [client.get("/").get_data(as_text=True), client.get("/login").get_data(as_text=True)]
    login()
    pages.append(client.get("/dashboard").get_data(as_text=True))

    for html in pages:
        assert 'class="loading-bar-fill"' in html
        assert 'src="/static/js/loading-bar.js?v=' in html


def test_browser_tab_shows_the_someless_icon(client):
    html = client.get("/login").get_data(as_text=True)

    assert '<link rel="icon" href="/static/img/favicon.png?v=' in html
    assert client.get("/static/img/favicon.png").status_code == 200


STATIC_URL = re.compile(r'(?:src|href|data-src|data-lottie|data-icons)="([^"]*/static/[^"]*)"')


def static_urls(html):
    urls = set()
    for value in STATIC_URL.findall(html):
        urls.update(u for u in value.split() if u.startswith("/static/"))
    return urls


def test_static_links_carry_a_content_version(client):
    html = client.get("/").get_data(as_text=True)

    assert re.search(r'href="/static/css/style\.css\?v=[0-9a-f]{10}"', html)


def test_browsers_keep_static_files_for_a_year(client):
    response = client.get("/static/css/style.css")

    assert "max-age=31536000" in response.headers["Cache-Control"]


def test_splash_preloads_everything_the_login_page_needs(client):
    splash = client.get("/").get_data(as_text=True)
    login_page = client.get("/login").get_data(as_text=True)
    preload = re.search(r'data-preload="([^"]*)"', splash).group(1).split()

    missing = static_urls(login_page) - static_urls(splash) - set(preload)
    assert not missing, f"login page files the splash doesn't preload: {sorted(missing)}"


def test_static_files_are_the_same_for_every_visitor(client):
    client.get("/login")  # puts a form token in the session cookie

    response = client.get("/static/js/pixi.min.js")

    # "Vary: Cookie" would make browsers download files again once a cookie is set
    assert "Cookie" not in response.headers.get("Vary", "")


def test_font_preload_uses_the_same_address_as_the_stylesheet(client):
    html = client.get("/").get_data(as_text=True)
    css = client.get("/static/css/style.css").get_data(as_text=True)

    assert '<link rel="preload" href="/static/fonts/GoogleSans-latin.woff2" as="font"' in html
    assert 'url("../fonts/GoogleSans-latin.woff2")' in css
