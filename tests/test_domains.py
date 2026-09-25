import html
import re


def domains_page(client, login):
    login()
    return html.unescape(client.get("/domains").get_data(as_text=True))


def test_domains_requires_login(client):
    response = client.get("/domains")

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_domains_page_says_there_are_no_domains_yet(client, login):
    page = domains_page(client, login)

    assert "<title>Domains | Someless Mail</title>" in page
    assert '<h1 class="page-title">Domains</h1>' in page
    assert "No domains yet" in page


def test_menu_lights_up_domains_on_its_page(client, login):
    page = domains_page(client, login)
    menu = page[page.index('<dialog class="side-menu"'):page.index("</dialog>")]

    current = re.findall(r'<a [^>]*aria-current="page"[^>]*>', menu)
    assert len(current) == 1
    assert 'href="/domains"' in current[0]
