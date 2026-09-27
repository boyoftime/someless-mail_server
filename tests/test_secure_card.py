"""Settings > Account > Secure the panel and webmail: how to put both on HTTPS, with Nginx Proxy
Manager (the proxy hosts to add, filled in) or without it."""
import html
import re

from test_engine_sync import authenticated_domain


def text(response):
    return html.unescape(response.get_data(as_text=True))


def card(page):
    start = page.index('aria-labelledby="secure-title"')
    return page[start:page.index('id="password-rules-dialog"')]   # the last card: up to the dialogs after the cards


def test_the_card_gives_the_proxy_hosts_for_the_panel_and_the_webmail(app, client, login):
    authenticated_domain(app, "cloudnix.net")
    login()

    found = card(text(client.get("/settings")))

    assert "Secure the panel and webmail" in found
    for value in ("panel.cloudnix.net", "webmail.cloudnix.net", "someless-mail", "17080", "17090"):
        assert f'data-copy="{value}"' in found, value
    assert "Request a new SSL certificate" in found and "Force SSL" in found
    # and what to do after: the webmail's address, and closing the way in by IP
    assert "Webmail address" in found and '"17080:17080"' in found


def test_without_a_domain_the_tables_use_an_example(client, login):
    login()

    found = card(text(client.get("/settings")))

    assert 'data-copy="panel.example.com"' in found


def test_without_nginx_proxy_manager_there_is_another_way(app, client, login):
    authenticated_domain(app, "cloudnix.net")
    login()

    found = card(text(client.get("/settings")))

    assert "Without Nginx Proxy Manager" in found
    assert "reverse_proxy 127.0.0.1:17080" in found and "http://mail.cloudnix.net" in found   # Caddy
    assert "127.0.0.1:17080:17080" in found   # reachable only through it


def test_the_card_says_whether_this_page_came_over_https(client, login):
    login()

    plain = card(text(client.get("/settings")))
    secure = card(text(client.get("/settings", headers={"X-Forwarded-Proto": "https"})))

    assert "plain http://" in plain and "is-warning" in plain
    assert "came over HTTPS" in secure and "is-ok" in secure
