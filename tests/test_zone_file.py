"""Download zone file: a domain's records in one file (BIND format), for DNS providers that
import them, like Cloudflare. On the Authenticate page, and on the page a Need help? link opens."""
import re

import pytest

from test_domain_records import ZOHO_MX, ZOHO_SPF, add_domain, all_right, client, dns, keys, text  # noqa: F401 (fixtures)
from test_help_links import create, token_of


def lines(zone):
    """The records in the file (the lines that aren't comments), as their fields."""
    return [line.split("\t") for line in zone.splitlines() if line and not line.startswith(";")]


def strings(value):
    """A TXT record's quoted strings."""
    return re.findall(r'"((?:[^"\\]|\\.)*)"', value)


@pytest.fixture
def domain_id(client, login, dns):
    login()
    return add_domain(client)


def download(client, domain_id):
    return client.get(f"/domains/{domain_id}/zone")


def test_the_file_has_all_six_records(app, client, domain_id):
    answer = download(client, domain_id)

    assert answer.status_code == 200 and answer.mimetype == "text/plain"
    assert answer.headers["Content-Disposition"] == 'attachment; filename="example.com-zone.txt"'
    records = {}
    for name, ttl, klass, rdtype, value in lines(answer.get_data(as_text=True)):
        assert (ttl, klass) == ("3600", "IN")
        records.setdefault((name, rdtype), []).append(value)
    assert records[("example.com.", "TXT")] == [f'"someless-code:{keys(app, domain_id)["code"]}"',
                                               '"v=spf1 a:mail.example.com mx ~all"']
    assert records[("mail.example.com.", "A")][0].startswith("194.163.167.106 ")
    assert len(records[("someless._domainkey.example.com.", "TXT")]) == 1
    assert records[("_dmarc.example.com.", "TXT")] == ['"v=DMARC1; p=none"']
    assert records[("example.com.", "MX")] == ["10 mail.example.com."]
    assert len(records) == 5   # six records: two of them TXT at the domain itself


def test_the_dkim_key_is_split_into_strings_dns_can_hold(app, client, domain_id):
    zone = download(client, domain_id).get_data(as_text=True)

    (dkim,) = [value for name, *_, value in lines(zone) if name == "someless._domainkey.example.com."]
    parts = strings(dkim)
    assert len(parts) > 1 and all(len(part) <= 255 for part in parts)
    assert "".join(parts) == f"v=DKIM1; k=rsa; p={keys(app, domain_id)['dkim_public']}"


def test_cloudflare_keeps_the_mail_server_out_of_its_proxy(client, domain_id):
    zone = download(client, domain_id).get_data(as_text=True)

    (a_line,) = [line for line in zone.splitlines() if line.startswith("mail.example.com.\t")]
    assert a_line.endswith("; cf_tags=cf-proxied:false")


def test_the_file_says_how_to_import_it(client, domain_id):
    zone = download(client, domain_id).get_data(as_text=True)

    assert zone.startswith("; ")
    assert "Import and Export" in zone and "Proxy imported DNS records" in zone


def test_a_record_the_domain_has_to_change_is_left_to_do_by_hand(client, domain_id, dns):
    dns[("example.com", "TXT")] = [ZOHO_SPF]   # its own SPF record: this one replaces it
    dns[("example.com", "MX")] = ZOHO_MX
    client.post(f"/domains/{domain_id}/check")

    zone = download(client, domain_id).get_data(as_text=True)

    assert not [value for name, *_, value in lines(zone) if "spf1" in value]   # never a second SPF record
    assert "; example.com.\t3600\tIN\tTXT\t\"v=spf1 include:zohomail.com a:mail.example.com ~all\"" in zone
    assert "only one SPF record" in zone
    assert "mx.zoho.com" in zone   # its old MX records, to delete once this one's in


def test_a_record_already_there_is_left_out(client, domain_id, dns):
    dns[("_dmarc.example.com", "TXT")] = ["v=DMARC1; p=quarantine"]
    client.post(f"/domains/{domain_id}/check")

    zone = download(client, domain_id).get_data(as_text=True)

    assert not [name for name, *_ in lines(zone) if name == "_dmarc.example.com."]
    assert "; _dmarc.example.com.\t3600\tIN\tTXT\t\"v=DMARC1; p=quarantine\"" in zone


def test_without_a_public_address_the_a_record_is_left_to_fill_in(app, client, login, dns):
    app.config["SERVER_NAME"] = None  # opened as http://localhost
    login()
    domain_id = add_domain(client)

    zone = download(client, domain_id).get_data(as_text=True)

    assert not [name for name, *_ in lines(zone) if name == "mail.example.com."]
    assert "your server's public IP address" in zone


def test_the_file_needs_a_login(app, client, domain_id):
    assert app.test_client().get(f"/domains/{domain_id}/zone").status_code == 302
    assert client.get("/domains/999/zone").status_code == 404


def test_the_authenticate_page_offers_it(app, client, domain_id, dns):
    page = text(client.get(f"/domains/{domain_id}"))
    assert f'href="/domains/{domain_id}/zone" download' in page

    all_right(dns, app, domain_id)
    client.post(f"/domains/{domain_id}/check")
    assert f'/domains/{domain_id}/zone"' not in text(client.get(f"/domains/{domain_id}"))   # nothing left to add


# The page a Need help? link opens

def test_a_help_link_offers_it_too(app, client, domain_id):
    token = token_of(create(client, domain_id))
    visitor = app.test_client()

    assert f'href="/help/{token}/zone" download' in text(visitor.get(f"/help/{token}"))
    answer = visitor.get(f"/help/{token}/zone")
    assert answer.status_code == 200
    assert answer.headers["Content-Disposition"] == 'attachment; filename="example.com-zone.txt"'
    assert f"someless-code:{keys(app, domain_id)['code']}" in answer.get_data(as_text=True)


def test_a_password_link_gives_it_only_once_opened(app, client, domain_id):
    token = token_of(create(client, domain_id, password_on=True, password="letmein"))
    visitor = app.test_client()

    refused = visitor.get(f"/help/{token}/zone")
    assert refused.status_code == 302 and "someless-code" not in refused.get_data(as_text=True)

    visitor.post(f"/help/{token}/unlock", data={"password": "letmein"})
    assert visitor.get(f"/help/{token}/zone").status_code == 200


def test_a_deleted_link_gives_nothing(app, client, domain_id):
    token = token_of(create(client, domain_id))

    assert app.test_client().get("/help/not-a-real-link/zone").status_code == 404
    client.post(f"/domains/{domain_id}/help-links/1/delete")
    assert app.test_client().get(f"/help/{token}/zone").status_code == 404
