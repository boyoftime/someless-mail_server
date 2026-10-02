"""Domains, Senders and Mailboxes: how many there are, in a chip beside the page's title (all of
them, even while a search shows only some)."""
import html
import re

import pytest

from test_engine_sync import a_mailbox, a_sender, authenticated_domain


def title_row(client, path):
    page = html.unescape(client.get(path).get_data(as_text=True))
    return re.search(r'<div class="page-title-row">(.*?)</div>', page, re.S).group(1)


def counted(row):
    """The chip's number, and the words a screen reader hears with it."""
    chip = re.search(r'<span class="page-count"[^>]*>(\d+)<span class="visually-hidden"> ([^<]+)</span></span>', row)
    return int(chip.group(1)), chip.group(2)


@pytest.fixture
def server(app):
    domain_id = authenticated_domain(app)
    authenticated_domain(app, "samakiafrica.com", authenticated=False)
    a_sender(app, domain_id, "ceo@pineloop.online")
    a_sender(app, domain_id, "info@pineloop.online")
    a_sender(app, domain_id, "sales@pineloop.online")
    a_mailbox(app, "ceo@pineloop.online", domain_id)
    return domain_id


@pytest.mark.parametrize("path, title, count, words", [
    ("/domains", "Domains", 2, "domains"),
    ("/senders", "Senders", 3, "senders"),
    ("/mailboxes", "Mailboxes", 1, "mailbox"),
])
def test_each_page_counts_what_it_holds_beside_its_title(server, client, login, path, title, count, words):
    login()

    row = title_row(client, path)

    assert f'<h1 class="page-title">{title}</h1>' in row
    assert counted(row) == (count, words)


@pytest.mark.parametrize("path", ["/domains?q=pine", "/senders?q=ceo", "/mailboxes?q=nobody"])
def test_a_search_still_counts_them_all(server, client, login, path):
    login()

    assert counted(title_row(client, path))[0] == {"/domains": 2, "/senders": 3, "/mailboxes": 1}[path.split("?")[0]]


@pytest.mark.parametrize("path, words", [("/domains", "domains"), ("/senders", "senders"), ("/mailboxes", "mailboxes")])
def test_a_new_server_counts_nought(client, login, path, words):
    login()

    assert counted(title_row(client, path)) == (0, words)
