import re


def visible_text(response):
    html = response.get_data(as_text=True)
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def test_welcome_page_greets_visitor(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Welcome to Someless Mail Server" in visible_text(response)


def test_welcome_page_leads_to_login(client):
    html = client.get("/").get_data(as_text=True)

    assert 'href="/login"' in html


def test_google_sans_is_served_from_our_own_server(client):
    html = client.get("/").get_data(as_text=True)
    css = client.get("/static/css/style.css").get_data(as_text=True)
    font = client.get("/static/fonts/GoogleSans-latin.woff2")

    assert 'href="/static/css/style.css"' in html
    assert "fonts.googleapis.com" not in html
    assert "GoogleSans-latin.woff2" in css
    assert font.status_code == 200


def test_healthz_reports_ok(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "ok"
