"""Settings > Mail server name: the one name the mail server goes by (engine/names.py)."""
import html
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from someless import engine as engine_module
from someless.engine import checks, supervisor
from test_engine_sync import authenticated_domain


def text(response):
    return html.unescape(response.get_data(as_text=True))


def plain(page):
    return re.sub(r"<[^>]+>", "", page)


def tabs_of(page):
    tabs = page[page.index('<nav class="page-tabs"'):]
    return tabs[:tabs.index("</nav>")]


def test_settings_has_a_mail_server_name_tab(client, login):
    login()

    tabs = tabs_of(text(client.get("/settings")))

    assert '<a class="page-tab" href="/settings" aria-current="page">' in tabs
    assert '<a class="page-tab" href="/settings/mail-server">' in tabs and "Mail server name" in tabs


def test_the_tab_opens_its_own_page(client, login):
    login()

    tabs = tabs_of(text(client.get("/settings/mail-server")))

    assert '<a class="page-tab" href="/settings/mail-server" aria-current="page">' in tabs
    assert '<a class="page-tab" href="/settings">' in tabs   # Account, not the current one here


def test_the_page_needs_login(client):
    assert client.get("/settings/mail-server").headers["Location"] == "/login"


def test_only_authenticated_domains_are_offered(app, client, login):
    authenticated_domain(app, "pineloop.online")
    authenticated_domain(app, "cloudnix.net", authenticated=False)
    login()

    page = text(client.get("/settings/mail-server"))

    assert re.findall(r'name="server_name" value="([^"]+)"', page) == ["mail.pineloop.online"]


def test_without_an_authenticated_domain_it_says_what_to_do_first(client, login):
    login()

    page = text(client.get("/settings/mail-server"))

    assert "Authenticate a domain first" in plain(page)
    assert 'href="/domains"' in page


def test_choosing_a_name_saves_it_and_updates_the_engine(app, client, login, engine):
    authenticated_domain(app, "cloudnix.net")
    authenticated_domain(app, "pineloop.online")
    login()

    response = client.post("/settings/mail-server", data={"server_name": "mail.pineloop.online"})

    assert response.status_code == 302
    with app.app_context():
        assert engine_module.state()["server_name"] == "mail.pineloop.online"
    assert engine.objects["SystemSettings"]["singleton"]["defaultHostname"] == "mail.pineloop.online"
    assert re.search(r'value="mail\.pineloop\.online" checked', text(client.get("/settings/mail-server")))


def test_an_unknown_name_is_ignored(app, client, login, engine):
    authenticated_domain(app, "pineloop.online")
    login()

    client.post("/settings/mail-server", data={"server_name": "mail.elsewhere.com"})

    with app.app_context():
        assert engine_module.state()["server_name"] is None


def test_the_card_lists_what_the_name_needs(app, client, login, engine, monkeypatch):
    authenticated_domain(app)
    monkeypatch.setattr(checks, "addresses_of", lambda name: ["194.163.167.106"])
    monkeypatch.setattr(checks, "relay_reached", lambda name: True)
    app.config["SERVER_NAME"] = "194.163.167.106:17080"   # the panel opened by the server's public address
    login()

    page = plain(text(client.get("/settings/mail-server")))

    for title in ("Points to this server", "Proxy host", "Reverse DNS", "Certificate"):
        assert title in page, title
    assert "mail.pineloop.online" in page and "17081" in page


def test_the_smtp_page_links_here_instead_of_its_own_picker(app, client, login, engine):
    authenticated_domain(app, "cloudnix.net")
    authenticated_domain(app, "pineloop.online")
    login()

    page = text(client.get("/smtp"))

    assert 'name="server_name"' not in page
    assert 'href="/settings/mail-server"' in page
    assert client.post("/smtp/server-name", data={"server_name": "mail.pineloop.online"}).status_code == 404


def _serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_the_proxy_host_counts_when_it_reaches_the_relay():
    relay = _serve(supervisor._Relay)
    try:
        assert checks.relay_answers(f"http://127.0.0.1:{relay.server_port}/.well-known/acme-challenge/someless-check")
    finally:
        relay.shutdown()


def test_the_proxy_host_doesnt_count_when_something_else_answers():
    class Other(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"<html>404 Not Found nginx</html>")

        def log_message(self, *args):
            pass

    other = _serve(Other)
    try:
        assert not checks.relay_answers(f"http://127.0.0.1:{other.server_port}/.well-known/acme-challenge/someless-check")
        assert not checks.relay_answers("http://127.0.0.1:9/.well-known/acme-challenge/someless-check")   # nothing there
    finally:
        other.shutdown()


def test_a_missing_proxy_host_lists_its_settings(app, client, login, engine):
    """Field by field, as Nginx Proxy Manager asks for them, the scheme included."""
    authenticated_domain(app)
    login()

    page = text(client.get("/settings/mail-server"))

    fields = page[page.index('proxy-fields"'):]
    fields = fields[:fields.index("</dl>")]
    for label, value in (("Domain names", "mail.pineloop.online"), ("Scheme", "http"),
                         ("Forward hostname", "someless-mail"), ("Forward port", "17081")):
        assert re.search(rf"<dt>{label}</dt>\s*<dd>.*?{re.escape(value)}", fields, re.S), label
    assert 'data-copy="someless-mail"' in fields and 'data-copy="17081"' in fields
    assert "SSL" in plain(fields) and "Force SSL" in plain(fields)
