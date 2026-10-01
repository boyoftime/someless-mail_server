"""The certificate, as soon as it can be had (engine/certificate.py): while the server name has none,
whether Let's Encrypt's check gets through (the proxy host) is looked at again and again; the moment
it does, the certificate is asked for at once, with no click. The pages say how it stands, live."""
import re

import pytest

from someless.engine import certificate, checks, supervisor
from someless.engine import sync as sync_module
from test_engine_sync import authenticated_domain, sync_now

CERTIFICATE = {"c1": {"subjectAlternativeNames": {"mail.pineloop.online": True}, "notValidAfter": "2099-01-01T00:00:00Z"}}


@pytest.fixture
def proxy(monkeypatch):
    """Whether the proxy host passes Let's Encrypt's check on to Someless Mail: none to start."""
    state = {"works": False}
    monkeypatch.setattr(checks, "relay_reached", lambda name: state["works"])
    return state


@pytest.fixture
def ready(app, engine):
    """An authenticated domain, its server name mail.pineloop.online set up in the engine."""
    authenticated_domain(app)
    sync_now(app)
    engine.calls.clear()
    return engine


def orders(engine):
    return [call for call in engine.calls if call[:2] == ("create", "Task")]


def watch(app):
    with app.app_context():
        return certificate.watch()


def test_while_the_proxy_host_is_missing_it_waits_and_asks_nothing(app, ready, proxy):
    found = watch(app)

    assert found["state"] == "waiting" and "proxy host" in found["detail"]
    assert orders(ready) == []


def test_the_moment_the_proxy_host_works_the_certificate_is_asked_for(app, ready, proxy, client, login):
    login()
    client.post("/smtp/checks")   # (a Check again a moment ago, while it didn't work: not 10 minutes since)
    assert len(orders(ready)) == 1
    watch(app)

    proxy["works"] = True
    found = watch(app)

    assert found["state"] == "getting" and "Let's Encrypt" in found["detail"]
    assert len(orders(ready)) == 2   # (asked at once all the same: now the check can pass)
    watch(app)
    assert len(orders(ready)) == 2   # (once: an order takes a minute or so)


def test_once_the_certificate_is_in_it_says_so_and_asks_nothing(app, ready, proxy):
    proxy["works"] = True
    ready.objects["Certificate"] = CERTIFICATE

    found = watch(app)

    assert found["state"] == "ok" and orders(ready) == []


def test_without_a_server_name_there_is_nothing_to_watch(app, engine, proxy):
    assert watch(app)["state"] == "none"


def test_the_container_looks_every_half_minute(app, ready, proxy, monkeypatch):
    looked = []
    monkeypatch.setattr(certificate, "watch", lambda: looked.append(True))

    supervisor.watch_certificate(app)

    assert looked and supervisor.CERTIFICATE_EVERY == 30


def test_the_pages_follow_it_live(app, ready, proxy, client, login):
    assert client.get("/smtp/certificate").headers["Location"] == "/login"
    login()

    assert client.get("/smtp/certificate").get_json()["state"] == "waiting"
    proxy["works"] = True
    assert client.get("/smtp/certificate").get_json()["state"] == "getting"
    for path in ("/smtp", "/settings/mail-server"):
        page = client.get(path).get_data(as_text=True)
        assert re.search(r'<li class="ready-item is-\w+"[^>]*data-certificate-watch="/smtp/certificate"', page), path
        assert 'src="/static/js/certificate-watch.js?v=' in page, path


def test_a_check_again_still_waits_ten_minutes_between_asks(app, ready, proxy, client, login):
    login()
    client.post("/smtp/checks")
    client.post("/smtp/checks")

    assert len(orders(ready)) == 1
    assert sync_module.ASK_AGAIN_AFTER == 600
