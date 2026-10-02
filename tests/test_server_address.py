"""This server's public IP address (domain_records.server_address): what the panel's name points
to, unless that's Cloudflare's proxy (an orange-cloud record), where it's the server's own address
as DNS tells it. Every A record, check and zone file goes by it."""
import dns.exception
import pytest

from someless import domain_checks, domain_records
from test_engine_sync import authenticated_domain

HERE = "194.163.167.106"
CLOUDFLARE = "104.21.9.46"   # what a proxied panel.someless.top points to


@pytest.fixture
def points_to(monkeypatch):
    """What the panel's name points to, as the server's DNS says."""
    def _points_to(address):
        monkeypatch.setattr(domain_records.socket, "getaddrinfo",
                            lambda name, port, family: [(family, 1, 6, "", (address, 0))])
    return _points_to


@pytest.fixture
def clock(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(domain_records.time, "time", lambda: now[0])
    return now


def test_a_name_behind_cloudflare_gives_the_servers_own_address(monkeypatch, points_to):
    points_to(CLOUDFLARE)
    monkeypatch.setattr(domain_records, "_cloudflare_whoami", lambda: HERE)

    assert domain_records.server_address("panel.someless.top") == HERE


def test_a_name_pointing_straight_here_is_taken_as_it_is(monkeypatch, points_to):
    points_to(HERE)
    def never():
        raise AssertionError("DNS asked who's asking, for no reason")
    monkeypatch.setattr(domain_records, "_cloudflare_whoami", never)

    assert domain_records.server_address("panel.mvuviafrica.com") == HERE
    assert domain_records.server_address("194.163.167.106:17080") == HERE


def test_opendns_is_asked_when_cloudflare_cant_tell(monkeypatch):
    def timed_out():
        raise dns.exception.Timeout()
    monkeypatch.setattr(domain_records, "_cloudflare_whoami", timed_out)
    monkeypatch.setattr(domain_records, "_opendns_myip", lambda: HERE)

    assert domain_records.ask_own_address() == HERE


@pytest.mark.parametrize("told", [CLOUDFLARE, "10.0.0.5", "not an address"])
def test_an_answer_that_isnt_a_public_address_of_its_own_is_left_out(monkeypatch, told):
    monkeypatch.setattr(domain_records, "_cloudflare_whoami", lambda: told)

    assert domain_records.ask_own_address() is None


def test_no_address_rather_than_cloudflares(points_to):
    points_to(CLOUDFLARE)   # (and DNS can't tell the server its own: see conftest)

    assert domain_records.server_address("panel.someless.top") is None


def test_the_own_address_is_asked_once_an_hour(monkeypatch, points_to, clock):
    points_to(CLOUDFLARE)
    asked = []
    monkeypatch.setattr(domain_records, "_cloudflare_whoami", lambda: asked.append(1) or HERE)

    domain_records.server_address("panel.someless.top")
    clock[0] += 3500
    domain_records.server_address("panel.someless.top")
    assert len(asked) == 1
    clock[0] += 200
    assert domain_records.server_address("panel.someless.top") == HERE
    assert len(asked) == 2


def test_after_no_answer_it_asks_again_in_five_minutes(monkeypatch, points_to, clock):
    points_to(CLOUDFLARE)
    assert domain_records.server_address("panel.someless.top") is None

    monkeypatch.setattr(domain_records, "_cloudflare_whoami", lambda: HERE)
    clock[0] += 200
    assert domain_records.server_address("panel.someless.top") is None
    clock[0] += 150
    assert domain_records.server_address("panel.someless.top") == HERE


def test_a_panel_opened_through_cloudflare_gives_the_right_a_record(app, client, login, monkeypatch, points_to):
    """The zone file to import, and the address the automatic checks compare with."""
    app.config["SERVER_NAME"] = "panel.someless.top"
    points_to(CLOUDFLARE)
    monkeypatch.setattr(domain_records, "_cloudflare_whoami", lambda: HERE)
    domain_id = authenticated_domain(app)
    login()

    zone = client.get(f"/domains/{domain_id}/zone").get_data(as_text=True)
    client.get(f"/domains/{domain_id}")   # (its page: where the address is kept for the checks)

    assert f"IN\tA\t{HERE} ; cf_tags=cf-proxied:false" in zone and CLOUDFLARE not in zone
    with app.app_context():
        assert domain_checks.settings()["server_address"] == HERE
