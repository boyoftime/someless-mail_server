"""Open webmail and the Webmail link when the panel is behind Cloudflare's proxy and the webmail has
no address of its own yet (webmail_site.beside): the proxy doesn't carry port 17090, so they go to
the server's own IP address instead, and the Mailboxes page says to give the webmail an address."""
import re

import pytest

from someless import domain_records
from test_webmail import mailbox, open_webmail, text, ticket_of  # noqa: F401 (the fixture)

HERE = "194.163.167.106"
CLOUDFLARE = "104.21.9.46"
NOTE = "Your panel is behind Cloudflare's proxy"


@pytest.fixture
def panel_at(app, monkeypatch):
    """The panel opened by a name that points to the address given."""
    def _panel_at(name, address, own=HERE):
        app.config["SERVER_NAME"] = name
        monkeypatch.setattr(domain_records.socket, "getaddrinfo",
                            lambda host, port, family: [(family, 1, 6, "", (address, 0))])
        if own:
            monkeypatch.setattr(domain_records, "_cloudflare_whoami", lambda: own)
    return _panel_at


def test_behind_cloudflare_open_webmail_goes_to_the_servers_own_address(client, login, mailbox, panel_at):
    panel_at("panel.someless.top", CLOUDFLARE)
    login()

    location, _ = ticket_of(open_webmail(client, mailbox))

    assert location.startswith(f"http://{HERE}:17090/enter?ticket=")


def test_behind_cloudflare_the_webmail_link_and_a_note_say_so(client, login, mailbox, panel_at):
    panel_at("panel.someless.top", CLOUDFLARE)
    login()

    page = text(client.get("/mailboxes"))

    assert f'data-copy="http://{HERE}:17090/login"' in page
    note = re.search(rf'<p class="smtp-note">.*?{NOTE}.*?</p>', page, re.S).group(0)
    assert "port (17090)" in note and 'href="/settings/miscellaneous"' in note
    assert "https://webmail.example.com" in note


def test_with_an_address_of_its_own_there_is_nothing_to_say(client, login, mailbox, panel_at):
    panel_at("panel.someless.top", CLOUDFLARE)
    login()
    client.post("/settings/miscellaneous/webmail-address", data={"address": "https://webmail.someless.top"})

    page = text(client.get("/mailboxes"))

    assert NOTE not in page
    assert ticket_of(open_webmail(client, mailbox))[0].startswith("https://webmail.someless.top/enter?ticket=")


def test_a_panel_straight_on_the_server_opens_it_beside_as_before(client, login, mailbox, panel_at):
    panel_at("panel.mvuviafrica.com", HERE)
    login()

    assert NOTE not in text(client.get("/mailboxes"))
    assert ticket_of(open_webmail(client, mailbox))[0].startswith("http://panel.mvuviafrica.com:17090/enter?ticket=")


def test_when_dns_cant_tell_the_servers_address_the_note_still_helps(client, login, mailbox, panel_at):
    panel_at("panel.someless.top", CLOUDFLARE, own=None)   # (conftest: DNS answers nothing in the tests)
    login()

    assert NOTE in text(client.get("/mailboxes"))
    assert ticket_of(open_webmail(client, mailbox))[0].startswith("http://panel.someless.top:17090/")


def test_settings_says_where_it_opens_for_now(client, login, panel_at):
    panel_at("panel.someless.top", CLOUDFLARE)
    login()

    assert f"http://{HERE}:17090" in text(client.get("/settings/miscellaneous"))


def test_the_readme_says_what_happens_behind_the_proxy():
    from pathlib import Path
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    https = readme[readme.index("**On HTTPS, at `webmail.example.com`:**"):readme.index("**Calendar and contacts apps**")]

    assert "**Web interface behind Cloudflare's proxy**" in https and "http://your-server-ip:17090" in https
