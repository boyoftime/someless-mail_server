import base64
import html
import re

import pytest
from cryptography.hazmat.primitives import serialization

from someless import domain_records
from someless.db import get_db

JSON = {"Accept": "application/json"}


def text(response):
    return html.unescape(response.get_data(as_text=True))


@pytest.fixture
def client(app):
    """The panel opened by the server's public address (what the A and SPF records use)."""
    app.config["SERVER_NAME"] = "194.163.167.106:17080"
    return app.test_client()


@pytest.fixture
def dns(monkeypatch):
    """A made-up DNS: {(name, type): [answers]}. Nothing is looked up for real."""
    answers = {}
    monkeypatch.setattr(domain_records, "lookup", lambda name, rdtype: answers.get((name, rdtype), []))
    return answers


def add_domain(client, name="example.com"):
    client.post("/domains", data={"name": name})
    page = text(client.get("/domains"))
    return re.search(rf'<a class="domain-action" href="/domains/(\d+)"[^>]*data-for="{re.escape(name)}"', page).group(1)


def keys(app, domain_id):
    with app.app_context():
        return get_db().execute("SELECT * FROM domain_keys WHERE domain_id = ?", (domain_id,)).fetchone()


def record(page, key):
    """One record's card on the authenticate page."""
    start = page.index(f'id="record-{key}"')
    return page[page.rindex("<article", 0, start):page.index("</article>", start)]


def all_right(dns, app, domain_id, name="example.com", ip="194.163.167.106"):
    row = keys(app, domain_id)
    dns[(name, "TXT")] = [f"someless-code:{row['code']}", "v=spf1 a:mail.example.com mx ~all"]
    dns[(f"mail.{name}", "A")] = [ip]
    dns[(f"someless._domainkey.{name}", "TXT")] = [f"v=DKIM1; k=rsa; p={row['dkim_public']}"]
    dns[(f"_dmarc.{name}", "TXT")] = ["v=DMARC1; p=none"]


def test_list_links_each_domain_to_its_authenticate_page(client, login):
    login()
    domain_id = add_domain(client)

    page = text(client.get("/domains"))

    assert re.search(rf'<a class="domain-action" href="/domains/{domain_id}"[^>]*>Authenticate</a>', page)


def test_authenticate_page_lists_the_records_to_add(client, login, app):
    login()
    domain_id = add_domain(client)
    row = keys(app, domain_id)

    page = text(client.get(f"/domains/{domain_id}"))

    assert "<title>Authenticate example.com | Someless Mail</title>" in page
    expected = {
        "code": ("TXT", "@", f"someless-code:{row['code']}"),
        "a": ("A", "mail", "194.163.167.106"),
        "spf": ("TXT", "@", "v=spf1 a:mail.example.com mx ~all"),
        "dkim": ("TXT", "someless._domainkey", f"v=DKIM1; k=rsa; p={row['dkim_public']}"),
        "dmarc": ("TXT", "_dmarc", "v=DMARC1; p=none"),
        "mx": ("MX", "@", "mail.example.com"),
    }
    for key, (rdtype, host, value) in expected.items():
        card = record(page, key)
        assert f'<span class="dns-box">{rdtype}</span>' in card, key
        assert f'data-copy="{host}"' in card, key
        assert f'data-copy="{value}"' in card, key
    # receiving mail here is kept apart, with a warning not to move it too early
    receive = page[page.index('class="dns-group dns-group-receive"'):]
    assert 'id="record-mx"' in receive and "Priority" in record(page, "mx")
    assert "keep your current MX records" in receive


def test_each_domain_gets_its_own_signing_key(client, login, app):
    login()
    first = keys(app, add_domain(client, "example.com"))
    second = keys(app, add_domain(client, "other.org"))

    assert first["dkim_public"] != second["dkim_public"]
    assert first["code"] != second["code"]
    # the private half (kept here, for signing mail) belongs to the public half in DNS
    private = serialization.load_pem_private_key(first["dkim_private"].encode(), password=None)
    public = private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    assert base64.b64encode(public).decode() == first["dkim_public"]


def test_the_records_stay_the_same(client, login):
    login()
    domain_id = add_domain(client)

    first = text(client.get(f"/domains/{domain_id}"))
    second = text(client.get(f"/domains/{domain_id}"))

    assert record(first, "dkim") == record(second, "dkim")
    assert record(first, "code") == record(second, "code")


def test_without_a_public_address_the_a_record_says_what_to_use(app, client, login):
    app.config["SERVER_NAME"] = None  # opened as http://localhost
    login()
    domain_id = add_domain(client)

    page = text(client.get(f"/domains/{domain_id}"))

    assert "your server's public IP address" in record(page, "a")


def test_a_domain_with_all_records_right_is_authenticated(client, login, app, dns):
    login()
    domain_id = add_domain(client)
    all_right(dns, app, domain_id)

    response = client.post(f"/domains/{domain_id}/check")

    assert response.headers["Location"] == f"/domains/{domain_id}"
    page = text(client.get(f"/domains/{domain_id}"))
    for key in ["code", "a", "spf", "dkim", "dmarc"]:
        assert 'class="dns-status is-found"' in record(page, key), key
    assert "example.com is authenticated." in page
    listing = text(client.get("/domains"))
    assert "Authenticated" in listing and "Not authenticated" not in listing
    assert re.search(rf'<a class="domain-action" href="/domains/{domain_id}"[^>]*>View configuration</a>', listing)


def test_the_check_says_what_is_missing(client, login, app, dns):
    login()
    domain_id = add_domain(client)
    dns[("example.com", "TXT")] = [f"someless-code:{keys(app, domain_id)['code']}"]

    client.post(f"/domains/{domain_id}/check")

    page = text(client.get(f"/domains/{domain_id}"))
    assert 'class="dns-status is-found"' in record(page, "code")
    for key in ["a", "spf", "dkim", "dmarc"]:
        assert 'class="dns-status is-missing"' in record(page, key), key
    assert 'data-board="error"' in page and "Not authenticated yet" in page
    assert "Not authenticated" in text(client.get("/domains"))


def test_an_spf_record_without_this_server_is_flagged(client, login, app, dns):
    login()
    domain_id = add_domain(client)
    all_right(dns, app, domain_id)
    dns[("example.com", "TXT")] = [f"someless-code:{keys(app, domain_id)['code']}", "v=spf1 include:spf.privateemail.com ~all"]

    client.post(f"/domains/{domain_id}/check")

    card = record(text(client.get(f"/domains/{domain_id}")), "spf")
    assert 'class="dns-status is-different"' in card
    assert "add a:mail.example.com to it" in card


def test_two_spf_records_are_flagged(client, login, app, dns):
    login()
    domain_id = add_domain(client)
    all_right(dns, app, domain_id)
    dns[("example.com", "TXT")].append("v=spf1 include:spf.privateemail.com ~all")

    client.post(f"/domains/{domain_id}/check")

    card = record(text(client.get(f"/domains/{domain_id}")), "spf")
    assert 'class="dns-status is-different"' in card
    assert "only one SPF record" in card


def test_a_dkim_record_with_another_key_is_flagged(client, login, app, dns):
    login()
    domain_id = add_domain(client)
    all_right(dns, app, domain_id)
    dns[("someless._domainkey.example.com", "TXT")] = ["v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAother"]

    client.post(f"/domains/{domain_id}/check")

    assert 'class="dns-status is-different"' in record(text(client.get(f"/domains/{domain_id}")), "dkim")


def test_mx_is_checked_but_not_needed_to_authenticate(client, login, app, dns):
    login()
    domain_id = add_domain(client)
    all_right(dns, app, domain_id)
    dns[("example.com", "MX")] = ["mx1.privateemail.com"]

    client.post(f"/domains/{domain_id}/check")

    page = text(client.get(f"/domains/{domain_id}"))
    assert "example.com is authenticated." in page
    card = record(page, "mx")
    assert 'class="dns-status is-different"' in card
    assert "mx1.privateemail.com" in card


def test_dns_that_does_not_answer_counts_as_not_found(client, login, app, monkeypatch):
    def broken(name, rdtype):
        raise OSError("no DNS")
    monkeypatch.setattr(domain_records, "lookup", broken)
    login()
    domain_id = add_domain(client)

    response = client.post(f"/domains/{domain_id}/check")

    assert response.status_code == 302
    assert 'class="dns-status is-missing"' in record(text(client.get(f"/domains/{domain_id}")), "dkim")


def test_deleting_a_domain_deletes_its_keys(client, login, app):
    login()
    domain_id = add_domain(client)

    client.post(f"/domains/{domain_id}/delete")

    assert keys(app, domain_id) is None
    assert client.get(f"/domains/{domain_id}").status_code == 404


def test_the_authenticate_page_needs_login(client):
    assert client.get("/domains/1").headers["Location"] == "/login"
