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


def plain(page):
    """The page's words, without the tags between them."""
    return re.sub(r"<[^>]+>", "", page)


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
    assert "doesn't receive mail anywhere yet" in plain(receive)


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

    page = text(client.get(f"/domains/{domain_id}"))
    assert 'class="dns-status is-different"' in record(page, "spf")
    assert "a:mail.example.com added" in summary(page)


def test_two_spf_records_are_flagged(client, login, app, dns):
    login()
    domain_id = add_domain(client)
    all_right(dns, app, domain_id)
    dns[("example.com", "TXT")].append("v=spf1 include:spf.privateemail.com ~all")

    client.post(f"/domains/{domain_id}/check")

    page = text(client.get(f"/domains/{domain_id}"))
    assert 'class="dns-status is-different"' in record(page, "spf")
    assert "only one SPF record" in summary(page)


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
    assert 'class="dns-status is-elsewhere"' in record(page, "mx")  # "Not moved yet": right until the mail moves
    assert "mx1.privateemail.com" in summary(page)


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


NAMECHEAP = ["dns1.registrar-servers.com", "dns2.registrar-servers.com"]


def test_adding_a_domain_finds_who_runs_its_dns(client, login, dns):
    dns[("example.com", "NS")] = NAMECHEAP
    login()

    add_domain(client)

    row = text(client.get("/domains"))
    assert "DNS at Namecheap" in row


@pytest.mark.parametrize("servers, provider", [
    (["amy.ns.cloudflare.com", "bob.ns.cloudflare.com"], "Cloudflare"),
    (["ns-1.awsdns-01.org"], "Amazon Route 53"),
    (["ns41.domaincontrol.com"], "GoDaddy"),
    (["ns1.some-dns.example"], "ns1.some-dns.example"),  # not one we know: its name server
])
def test_dns_providers_are_named(client, login, dns, servers, provider):
    dns[("example.com", "NS")] = servers
    login()

    add_domain(client)

    assert f"DNS at {provider}" in text(client.get("/domains"))


def test_a_subdomain_uses_the_dns_of_its_parent_domain(client, login, dns):
    dns[("cloudnix.net", "NS")] = NAMECHEAP  # mail.cloudnix.net has none of its own
    login()

    add_domain(client, "mail.cloudnix.net")

    assert "DNS at Namecheap" in text(client.get("/domains"))


def test_without_an_answer_no_provider_is_named(client, login):
    login()

    add_domain(client)

    assert "DNS at" not in text(client.get("/domains"))


def test_authenticate_page_says_where_to_add_the_records(client, login, dns):
    dns[("example.com", "NS")] = NAMECHEAP
    login()
    domain_id = add_domain(client)

    page = text(client.get(f"/domains/{domain_id}"))

    assert "Your domain's DNS is at Namecheap" in plain(page)


def test_the_check_notices_a_move_to_another_provider(client, login, dns):
    dns[("example.com", "NS")] = NAMECHEAP
    login()
    domain_id = add_domain(client)
    dns[("example.com", "NS")] = ["amy.ns.cloudflare.com"]

    client.post(f"/domains/{domain_id}/check")

    assert "DNS at Cloudflare" in text(client.get("/domains"))


def test_domains_added_before_get_their_provider_on_their_page(client, login, dns, app):
    login()
    domain_id = add_domain(client)  # no answer at the time
    dns[("example.com", "NS")] = NAMECHEAP

    page = text(client.get(f"/domains/{domain_id}"))

    assert "Your domain's DNS is at Namecheap" in plain(page)


def test_older_databases_get_the_provider_column(tmp_path):
    import sqlite3
    from someless import create_app
    with sqlite3.connect(tmp_path / "someless.db") as db:  # as the first Domains page left it
        db.execute("CREATE TABLE domains (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,"
                   " authenticated INTEGER NOT NULL DEFAULT 0, added_at REAL NOT NULL)")
        db.execute("INSERT INTO domains (name, added_at) VALUES ('example.com', 0)")

    create_app({"TESTING": True, "DATA_DIR": str(tmp_path)})

    with sqlite3.connect(tmp_path / "someless.db") as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(domains)")]
        kept = db.execute("SELECT name FROM domains").fetchall()
    assert "provider" in columns
    assert kept == [("example.com",)]


ZOHO_MX = ["mx.zoho.com", "mx2.zoho.com", "mx3.zoho.com"]
ZOHO_SPF = "v=spf1 include:zohomail.com ~all"


def authenticate_page(client, login, name="example.com"):
    login()
    return text(client.get(f"/domains/{add_domain(client, name)}"))


def summary(page):
    """The summary at the end of the page: what other mail services left on the domain, and
    what to do about it (as words)."""
    start = page.index('id="other-services"')
    return plain(page[start:page.index("</section>", start)])


def test_a_domain_nothing_else_uses_is_ready_to_set_up(client, login):
    page = authenticate_page(client, login)

    assert 'class="dns-ready"' in page
    assert "Your domain is ready to set up" in plain(page)
    assert 'id="other-services"' not in page


def test_a_domain_other_services_use_gets_its_summary_at_the_end(client, login, dns):
    dns[("example.com", "MX")] = ZOHO_MX

    page = authenticate_page(client, login)

    assert 'class="dns-ready"' not in page  # nothing at the top
    assert page.index('class="dns-group dns-group-receive"') < page.index('id="other-services"') < page.index('class="dns-actions"')


def test_an_existing_spf_record_is_extended_not_doubled(client, login, dns):
    dns[("example.com", "TXT")] = [ZOHO_SPF]
    dns[("example.com", "MX")] = ZOHO_MX

    page = authenticate_page(client, login)

    card = plain(record(page, "spf"))
    assert "v=spf1 include:zohomail.com a:mail.example.com ~all" in card
    assert "Replace your current SPF record with this one." in card
    assert "Now:" not in card  # the card just says what to add
    told = summary(page)
    assert "Replace your SPF record with the one above" in told and "a:mail.example.com added" in told
    assert "Don't add it as a second record" in told
    assert f"Now: {ZOHO_SPF}" in told


def test_several_spf_records_become_one(client, login, dns):
    dns[("example.com", "TXT")] = [ZOHO_SPF, "v=spf1 include:spf.brevo.com -all"]

    page = authenticate_page(client, login)

    assert "v=spf1 include:zohomail.com include:spf.brevo.com a:mail.example.com ~all" in plain(record(page, "spf"))
    assert "Replace your 2 SPF records with this one." in plain(record(page, "spf"))
    assert "Delete them all and add the one above" in summary(page)


def test_a_strict_spf_record_stays_strict(client, login, dns):
    dns[("example.com", "TXT")] = ["v=spf1 include:_spf.google.com -all"]

    card = plain(record(authenticate_page(client, login), "spf"))

    assert "v=spf1 include:_spf.google.com a:mail.example.com -all" in card


def test_an_spf_record_that_already_includes_this_server_is_kept(client, login, dns):
    dns[("example.com", "TXT")] = ["v=spf1 include:zohomail.com a:mail.example.com ~all"]

    card = plain(record(authenticate_page(client, login), "spf"))

    assert "Already there: keep it." in card


def test_an_existing_dmarc_record_is_kept(client, login, dns):
    dns[("_dmarc.example.com", "TXT")] = ["v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com"]

    page = authenticate_page(client, login)

    card = plain(record(page, "dmarc"))
    assert "Already there: keep it." in card
    assert "v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com" in card
    assert 'class="dns-ready"' in page  # a DMARC record alone is no other service


def test_the_mx_advice_says_where_mail_goes_now(client, login, dns):
    dns[("example.com", "MX")] = ZOHO_MX

    page = authenticate_page(client, login)

    told = summary(page)
    assert "Mail for example.com goes to Zoho Mail now" in told and "mx.zoho.com" in told
    assert "don't keep both" in told
    start = page.index('class="dns-group dns-group-receive"')
    assert "Zoho" not in page[start:page.index("</section>", start)]  # the receive part just says when to add it


def test_a_mail_name_in_use_moves_this_server_to_a_free_one(client, login, dns):
    dns[("mail.example.com", "A")] = ["203.0.113.9"]  # something else lives there

    page = authenticate_page(client, login)

    assert 'data-copy="mx"' in record(page, "a")
    assert 'data-copy="v=spf1 a:mx.example.com mx ~all"' in record(page, "spf")
    assert 'data-copy="mx.example.com"' in record(page, "mx")
    assert "mail.example.com is already in use" in summary(page)


def test_nested_includes_count_toward_the_spf_lookup_limit(client, login, dns):
    others = " ".join(f"include:spf{n}.example.net" for n in range(6))
    dns[("example.com", "TXT")] = [f"v=spf1 include:_spf.google.com {others} ~all"]
    dns[("_spf.google.com", "TXT")] = ["v=spf1 include:_netblocks.google.com include:_netblocks2.google.com"
                                       " include:_netblocks3.google.com ~all"]  # 10 lookups in all

    page = authenticate_page(client, login)

    # a:mail.example.com would be an 11th, so this server goes in by its address
    assert f"v=spf1 include:_spf.google.com {others} ip4:194.163.167.106 ~all" in plain(record(page, "spf"))
    assert "already takes 10" in summary(page)


def test_an_spf_record_past_the_lookup_limit_is_flagged(client, login, dns):
    includes = " ".join(f"include:spf{n}.example.net" for n in range(11))
    dns[("example.com", "TXT")] = [f"v=spf1 {includes} ~all"]

    assert "more than the 10 DNS lookups SPF allows" in summary(authenticate_page(client, login))


def test_a_wildcard_record_leaves_names_free(client, login, monkeypatch):
    # *.example.com points every name at a web server, except mail.example.com, which has a
    # record of its own (another mail server)
    def lookup(name, rdtype):
        if rdtype != "A" or not name.endswith(".example.com"):
            return []
        return ["198.51.100.7"] if name == "mail.example.com" else ["203.0.113.9"]
    monkeypatch.setattr(domain_records, "lookup", lookup)

    page = authenticate_page(client, login)

    assert 'data-copy="mx"' in record(page, "a")  # the wildcard alone doesn't make mx taken


def test_a_mail_name_that_points_here_already_is_kept(client, login, dns):
    dns[("mail.example.com", "A")] = ["194.163.167.106"]

    assert 'data-copy="mail"' in record(authenticate_page(client, login), "a")


def test_a_second_address_on_the_mail_name_is_flagged(client, login, app, dns):
    login()
    domain_id = add_domain(client)
    all_right(dns, app, domain_id)
    dns[("mail.example.com", "A")] = ["194.163.167.106", "203.0.113.9"]

    client.post(f"/domains/{domain_id}/check")

    card = record(text(client.get(f"/domains/{domain_id}")), "a")
    assert 'class="dns-status is-different"' in card
    assert "also to 203.0.113.9" in card


def test_the_mail_name_stays_once_chosen(client, login, app, dns):
    login()
    domain_id = add_domain(client)
    client.get(f"/domains/{domain_id}")  # mail.example.com is free: this server takes it
    all_right(dns, app, domain_id, ip="203.0.113.9")  # then points somewhere else by mistake

    client.post(f"/domains/{domain_id}/check")

    page = text(client.get(f"/domains/{domain_id}"))
    assert 'data-copy="mail"' in record(page, "a")
    assert "not to this server (194.163.167.106)" in record(page, "a")


def test_the_page_sums_up_the_mail_services_it_found(client, login, dns):
    dns[("example.com", "TXT")] = ["v=spf1 include:zohomail.com include:spf.brevo.com ~all"]
    dns[("example.com", "MX")] = ZOHO_MX

    told = summary(authenticate_page(client, login))

    assert "example.com already uses Zoho Mail and Brevo" in told
    assert "Replace your SPF record with the one above" in told
    assert "Mail for example.com goes to Zoho Mail now" in told


def test_services_that_only_send_are_found_by_their_code(client, login, dns):
    dns[("example.com", "TXT")] = ["brevo-code:0123456789abcdef"]

    assert "example.com already uses Brevo" in summary(authenticate_page(client, login))


def test_an_authenticated_domain_says_so_at_the_top(client, login, app, dns):
    login()
    domain_id = add_domain(client)
    all_right(dns, app, domain_id)  # its own records are no other service's
    client.post(f"/domains/{domain_id}/check")

    page = text(client.get(f"/domains/{domain_id}"))

    assert "Your domain is authenticated" in plain(page[page.index('class="dns-ready"'):])


def to_delete(page):
    """The summary's list of records to delete, as words."""
    start = page.index('id="clean-up"')
    return plain(page[start:page.index("</section>", start)])


def test_the_old_services_records_go_when_the_mail_moves(client, login, dns):
    dns[("example.com", "MX")] = ZOHO_MX
    dns[("example.com", "TXT")] = [ZOHO_SPF, "zoho-verification=zb12345678.zmverify.zoho.com"]
    dns[("zmail._domainkey.example.com", "TXT")] = ["v=DKIM1; k=rsa; p=MIGfMA0GCSqZOHO"]

    listed = to_delete(authenticate_page(client, login))

    assert "Delete when your mail moves here" in listed
    for left in ZOHO_MX + ["zoho-verification=zb12345678.zmverify.zoho.com", "zmail._domainkey", "include:zohomail.com"]:
        assert left in listed, left
    assert "so it reads: v=spf1 a:mail.example.com ~all" in listed  # the SPF record without Zoho
    assert "Delete now" not in listed  # nothing is in the way today


def test_mail_app_names_that_lead_to_the_old_service_go_too(client, login, dns):
    dns[("example.com", "MX")] = ["example-com.mail.protection.outlook.com"]
    dns[("autodiscover.example.com", "CNAME")] = ["autodiscover.outlook.com."]

    listed = to_delete(authenticate_page(client, login))

    assert "Microsoft 365" in listed and "autodiscover" in listed


def test_records_in_the_way_are_to_delete_now(client, login, dns):
    dns[("example.com", "TXT")] = [ZOHO_SPF, "v=spf1 include:spf.brevo.com -all"]
    dns[("_dmarc.example.com", "TXT")] = ["v=DMARC1; p=none", "v=DMARC1; p=reject"]
    dns[("mail.example.com", "A")] = ["194.163.167.106", "203.0.113.9"]
    dns[("mail.example.com", "AAAA")] = ["2001:db8::9"]

    listed = to_delete(authenticate_page(client, login))

    now = listed[listed.index("Delete now"):]
    for record in [ZOHO_SPF, "v=spf1 include:spf.brevo.com -all", "v=DMARC1; p=reject", "203.0.113.9", "2001:db8::9"]:
        assert record in now, record
    assert "v=DMARC1; p=none" not in now  # the one to keep


def test_services_that_send_are_kept(client, login, dns):
    dns[("example.com", "MX")] = ZOHO_MX
    dns[("example.com", "TXT")] = ["v=spf1 include:zohomail.com include:spf.brevo.com ~all", "brevo-code:0123456789abcdef"]

    listed = to_delete(authenticate_page(client, login))

    assert "Keep Brevo's records" in listed
    assert "brevo-code" not in listed
    assert "so it reads: v=spf1 include:spf.brevo.com a:mail.example.com ~all" in listed  # Brevo stays in SPF


def test_leftovers_of_a_service_no_longer_used_are_listed(client, login, dns):
    dns[("example.com", "TXT")] = ["zoho-verification=zb12345678.zmverify.zoho.com"]

    listed = to_delete(authenticate_page(client, login))

    assert "If you no longer use Zoho Mail" in listed
    assert "zoho-verification=zb12345678.zmverify.zoho.com" in listed


def test_with_nothing_to_delete_there_is_no_list(client, login, dns):
    dns[("_dmarc.example.com", "TXT")] = ["v=DMARC1; p=none"]  # kept: nothing to delete

    assert 'id="clean-up"' not in authenticate_page(client, login)


def test_a_check_from_before_the_update_is_done_again(client, login, app, dns):
    import json
    login()
    domain_id = add_domain(client)
    with app.app_context():  # as the previous version checked it: its own words, no look yet
        db = get_db()
        db.execute("UPDATE domain_keys SET checks = ?, checked_at = 0, found = NULL WHERE domain_id = ?", (json.dumps({
            "code": {"state": "missing", "detail": ""},
            "mx": {"state": "different", "detail": "Mail for example.com still goes to mx.zoho.com."}}), domain_id))
        db.commit()
    dns[("example.com", "MX")] = ZOHO_MX

    card = record(text(client.get(f"/domains/{domain_id}")), "mx")

    assert 'class="dns-status is-elsewhere"' in card
    assert "still goes to" not in card


def at_namecheap(dns):
    """example.com's DNS is at Namecheap, whose name server is at 156.154.132.200."""
    dns[("example.com", "NS")] = ["dns1.registrar-servers.com"]
    dns[("dns1.registrar-servers.com", "A")] = ["156.154.132.200"]


def test_the_domains_own_name_servers_are_asked_not_a_cache(client, login, dns, monkeypatch):
    at_namecheap(dns)
    dns[("example.com", "MX")] = ZOHO_MX  # a cache still has the Zoho records just deleted at Namecheap
    asked = []

    def namecheap(servers, name, rdtype):
        asked.append(servers)
        return []  # nothing there any more
    monkeypatch.setattr(domain_records, "lookup_at", namecheap)

    page = authenticate_page(client, login)

    assert "Zoho" not in page
    assert asked and all(servers == ["156.154.132.200"] for servers in asked)


def test_the_usual_dns_is_asked_when_the_name_servers_do_not_answer(client, login, dns):
    at_namecheap(dns)  # its name server doesn't answer (conftest)
    dns[("example.com", "MX")] = ZOHO_MX

    assert "example.com already uses Zoho Mail" in plain(authenticate_page(client, login))


def looked_long_ago(app, domain_id):
    import json
    with app.app_context():
        db = get_db()
        found = json.loads(db.execute("SELECT found FROM domain_keys WHERE domain_id = ?", (domain_id,)).fetchone()[0])
        db.execute("UPDATE domain_keys SET found = ? WHERE domain_id = ?", (json.dumps({**found, "at": 0}), domain_id))
        db.commit()


def test_the_page_looks_again_once_its_last_look_is_old(client, login, app, dns):
    login()
    domain_id = add_domain(client)
    client.get(f"/domains/{domain_id}")  # nothing set up yet
    dns[("example.com", "MX")] = ZOHO_MX  # then the admin connects Zoho Mail
    looked_long_ago(app, domain_id)

    page = text(client.get(f"/domains/{domain_id}"))

    assert "example.com already uses Zoho Mail" in plain(page)


def test_a_recent_look_is_not_done_again(client, login, dns):
    login()
    domain_id = add_domain(client)
    client.get(f"/domains/{domain_id}")
    asked = []
    dns_lookup = domain_records.lookup
    domain_records.lookup = lambda name, rdtype: asked.append(name) or dns_lookup(name, rdtype)
    try:
        client.get(f"/domains/{domain_id}")  # as right after the check's own look
    finally:
        domain_records.lookup = dns_lookup

    assert not [name for name in asked if name.endswith("example.com") and name != "example.com"]


def test_the_check_accepts_the_extended_spf_record(client, login, app, dns):
    dns[("example.com", "TXT")] = [ZOHO_SPF]
    login()
    domain_id = add_domain(client)
    all_right(dns, app, domain_id)
    dns[("example.com", "TXT")] = [f"someless-code:{keys(app, domain_id)['code']}", "v=spf1 include:zohomail.com a:mail.example.com ~all"]

    client.post(f"/domains/{domain_id}/check")

    assert 'class="dns-status is-found"' in record(text(client.get(f"/domains/{domain_id}")), "spf")


def test_older_databases_get_the_domain_keys_columns(tmp_path):
    import sqlite3
    from someless import create_app
    with sqlite3.connect(tmp_path / "someless.db") as db:  # as the first Authenticate page left it
        db.execute("CREATE TABLE domain_keys (domain_id INTEGER PRIMARY KEY, code TEXT NOT NULL, dkim_selector TEXT NOT NULL,"
                   " dkim_private TEXT NOT NULL, dkim_public TEXT NOT NULL, checks TEXT, checked_at REAL)")

    create_app({"TESTING": True, "DATA_DIR": str(tmp_path)})

    with sqlite3.connect(tmp_path / "someless.db") as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(domain_keys)")]
    assert "found" in columns and "mail_host" in columns


def test_the_authenticate_page_needs_login(client):
    assert client.get("/domains/1").headers["Location"] == "/login"
