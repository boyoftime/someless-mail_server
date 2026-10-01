"""The API's domains (api.py): an app adds a domain, gets the DNS records to add at its domain
provider, has them checked (authenticate), and deletes it, as the Domains page does."""
import pytest

from someless.db import get_db
from test_api import KEY, a_key
from test_domain_records import all_right, dns  # noqa: F401 (dns: the made-up DNS, a fixture)
from test_engine_sync import a_mailbox, a_sender

RECORDS = ["code", "a", "spf", "dkim", "dmarc", "mx"]


@pytest.fixture
def api(app):
    """Calls with the key, on the panel opened by the server's public address (what the A and SPF
    records use)."""
    app.config["SERVER_NAME"] = "194.163.167.106:17080"
    client = app.test_client()
    a_key(app)

    def call(method, path, json=None):
        return getattr(client, method)("/api/s1" + path, json=json, headers={"Authorization": f"Bearer {KEY}"})
    return call


def domain_id(app, name="example.com"):
    with app.app_context():
        return get_db().execute("SELECT id FROM domains WHERE name = ?", (name,)).fetchone()["id"]


def test_a_domain_is_added_with_the_records_to_add_for_it(api, app, dns):
    response = api("post", "/domains", {"name": "  https://Example.com/  "})

    assert response.status_code == 201
    domain = response.json["domain"]
    assert (domain["name"], domain["authenticated"]) == ("example.com", False)
    records = {record["key"]: record for record in domain["records"]}
    assert list(records) == RECORDS
    with app.app_context():
        code = get_db().execute("SELECT code FROM domain_keys").fetchone()["code"]
    assert records["code"] == {**records["code"], "type": "TXT", "host": "@", "value": f"someless-code:{code}"}
    assert (records["a"]["type"], records["a"]["host"], records["a"]["value"]) == ("A", "mail", "194.163.167.106")
    assert (records["mx"]["value"], records["mx"]["priority"]) == ("mail.example.com", 10)
    assert {record["state"] for record in domain["records"]} == {"not checked"}


def test_called_by_a_private_address_the_a_record_says_to_use_the_public_one(app, dns):
    app.config["SERVER_NAME"] = "127.0.0.1:17080"
    a_key(app)

    response = app.test_client().post("/api/s1/domains", json={"name": "example.com"}, headers={"Authorization": f"Bearer {KEY}"})

    a_record = next(record for record in response.json["domain"]["records"] if record["key"] == "a")
    assert a_record["value"] is None and "public IP address" in a_record["note"]


@pytest.mark.parametrize("name, problem", [("not a domain", "Type a domain like example.com"),
                                           ("example.com", "example.com is already added.")])
def test_a_domain_is_checked_as_in_the_panel(api, app, name, problem):
    api("post", "/domains", {"name": "example.com"})

    response = api("post", "/domains", {"name": name})

    assert response.status_code == 400 and problem in response.json["error"]


def test_authenticating_checks_dns_and_says_what_is_still_to_add(api, app, dns):
    api("post", "/domains", {"name": "example.com"})

    first = api("post", "/domains/example.com/authenticate")

    assert first.status_code == 200 and first.json["domain"]["authenticated"] is False
    assert "Still to add or fix" in first.json["message"]
    assert {record["state"] for record in first.json["domain"]["records"]} == {"missing"}

    all_right(dns, app, domain_id(app))
    second = api("post", "/domains/example.com/authenticate")

    assert second.json["domain"]["authenticated"] is True and second.json["message"] == "example.com is authenticated."
    assert {record["state"] for record in second.json["domain"]["records"]} == {"found"}
    assert api("get", "/domains").json["domains"] == [{"name": "example.com", "authenticated": True}]


def test_a_domain_is_read_by_its_name(api, app, dns):
    api("post", "/domains", {"name": "example.com"})

    assert api("get", "/domains/EXAMPLE.com").json["domain"]["name"] == "example.com"
    missing = api("get", "/domains/nowhere.com")
    assert missing.status_code == 404 and "nowhere.com" in missing.json["error"]


def test_a_domain_is_deleted_unless_it_has_mailboxes(api, app, dns):
    api("post", "/domains", {"name": "example.com"})
    api("post", "/domains", {"name": "pineloop.online"})
    a_sender(app, domain_id(app), "hello@example.com")
    a_mailbox(app, "ceo@pineloop.online", domain_id(app, "pineloop.online"))

    deleted = api("delete", "/domains/example.com")
    kept = api("delete", "/domains/pineloop.online")

    assert deleted.json == {"deleted": True}
    with app.app_context():
        assert get_db().execute("SELECT * FROM senders").fetchall() == []   # (its senders go with it)
    assert kept.status_code == 400 and "Delete its mailboxes first" in kept.json["error"]
    assert [domain["name"] for domain in api("get", "/domains").json["domains"]] == ["pineloop.online"]
