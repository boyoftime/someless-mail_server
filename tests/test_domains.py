import html
import re

from someless import create_app


def text(response):
    return html.unescape(response.get_data(as_text=True))


def domains_page(client, query=""):
    return text(client.get("/domains" + query))


def add(client, name):
    return client.post("/domains", data={"name": name})


def rows(page):
    """The domains the table shows (rows the search hides are left out)."""
    return re.findall(r'<tr class="domain-row" data-domain="([^"]+)"(?! hidden)', page)


def test_domains_requires_login(client):
    response = client.get("/domains")

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_domains_page_says_there_are_no_domains_yet(client, login):
    login()
    page = domains_page(client)

    assert "<title>Domains | Someless Mail</title>" in page
    assert '<h1 class="page-title">Domains</h1>' in page
    assert "No domains yet" in page


def test_menu_lights_up_domains_on_its_page(client, login):
    login()
    page = domains_page(client)
    menu = page[page.index('<dialog class="side-menu"'):page.index("</dialog>")]

    current = re.findall(r'<a [^>]*aria-current="page"[^>]*>', menu)
    assert len(current) == 1
    assert 'href="/domains"' in current[0]


def test_add_domain_button_opens_a_dialog(client, login):
    login()
    page = domains_page(client)

    header = page[page.index('<header class="page-header'):page.index("</header>", page.index('<header class="page-header'))]
    assert 'data-dialog-open="add-domain-dialog"' in header
    assert page.count('data-dialog-open="add-domain-dialog"') == 1  # just the one, on the right
    assert '<dialog class="rules-dialog domain-dialog" id="add-domain-dialog"' in page
    assert re.search(r'<input [^>]*name="name"[^>]*required', page)


def test_admin_can_add_a_domain(client, login):
    login()

    response = add(client, "example.com")

    assert response.headers["Location"] == "/domains"
    page = domains_page(client)
    assert rows(page) == ["example.com"]
    assert "Not authenticated" in page
    assert "example.com was added." in page  # on a green board


def test_domain_names_are_tidied_up(client, login):
    login()

    add(client, "  HTTPS://Example.COM/  ")
    add(client, "mail.other.org.")

    assert rows(domains_page(client)) == ["example.com", "mail.other.org"]


def test_something_that_is_not_a_domain_is_refused(client, login):
    login()

    for bad in ["not a domain", "example", "-bad-.com", "a..b.com", "exa_mple.com", ""]:
        response = add(client, bad)
        assert response.status_code == 400, bad
        assert "like example.com" in text(response)
    assert rows(domains_page(client)) == []


def test_a_domain_can_be_added_only_once(client, login):
    login()
    add(client, "example.com")

    response = add(client, "Example.com")

    assert response.status_code == 400
    assert "example.com is already added." in text(response)
    assert rows(domains_page(client)) == ["example.com"]


def test_add_domain_dialog_reopens_with_the_error(client, login):
    login()
    add(client, "example.com")

    page = text(add(client, "example.com"))

    assert re.search(r'<dialog [^>]*id="add-domain-dialog"[^>]*data-open', page)
    assert 'value="example.com"' in page  # what was typed stays


def test_admin_can_delete_a_domain(client, login):
    login()
    add(client, "example.com")
    add(client, "other.org")
    domain_id = re.search(r'action="/domains/(\d+)/delete"[^>]*>\s*<input[^>]*>\s*<button[^>]*data-domain-name="example.com"', domains_page(client)).group(1)

    response = client.post(f"/domains/{domain_id}/delete")

    assert response.headers["Location"] == "/domains"
    page = domains_page(client)
    assert rows(page) == ["other.org"]
    assert "example.com was deleted." in page


def test_search_finds_domains_by_name(client, login):
    login()
    for name in ["example.com", "other.org", "shop.example.net"]:
        add(client, name)

    assert rows(domains_page(client, "?q=EXAMPLE")) == ["example.com", "shop.example.net"]
    assert 'value="EXAMPLE"' in domains_page(client, "?q=EXAMPLE")  # the search box keeps it


def test_domains_are_kept_across_restarts(tmp_path):
    config = {"TESTING": True, "DATA_DIR": str(tmp_path), "WTF_CSRF_ENABLED": False}
    first = create_app(config).test_client()
    first.post("/login", data={"username": "admin", "password": "admin"})
    add(first, "example.com")

    second = create_app(config).test_client()
    second.post("/login", data={"username": "admin", "password": "admin"})

    assert rows(domains_page(second)) == ["example.com"]


def test_the_status_help_shows_in_a_styled_tip(client, login):
    login()
    add(client, "example.com")

    page = domains_page(client)

    dot = re.search(r'<span class="help-dot"[^>]*>', page).group(0)
    assert 'data-tip="Add its DNS records at your domain provider' in dot
    assert "title=" not in dot  # not the browser's own plain tooltip
    main = page[page.index('<main class="app-main"'):page.index("</main>")]
    assert 'src="/static/js/tooltip.js?v=' in page and "tooltip.js" not in main  # once, with the layout
