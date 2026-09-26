import pytest

from someless import create_app, domain_records


@pytest.fixture(autouse=True)
def no_real_dns(monkeypatch):
    """Tests never ask the real DNS: nothing is found, unless a test's `dns` fixture says so."""
    monkeypatch.setattr(domain_records, "lookup", lambda name, rdtype: [])
    # a domain's own name servers don't answer either, so the (made-up) usual DNS is asked
    monkeypatch.setattr(domain_records, "lookup_at", lambda servers, name, rdtype: None)
    # nor the mail engine's checklist: port 25 is open, no reverse DNS, the server name points nowhere
    from someless.engine import checks
    checks.forget()
    monkeypatch.setattr(checks, "port25_open", lambda: True)
    monkeypatch.setattr(checks, "reverse_name", lambda ip: None)
    monkeypatch.setattr(checks, "addresses_of", lambda name: [])


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "DATA_DIR": str(tmp_path),
        "WTF_CSRF_ENABLED": False,
    })


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login(client):
    def _login(username="admin", password="admin"):
        return client.post("/login", data={"username": username, "password": password})
    return _login


@pytest.fixture
def engine(app):
    """A made-up mail engine beside the panel (tests that need one)."""
    from engine_fake import FakeEngine
    fake = FakeEngine()
    fake.objects["Domain"] = {"d0": {"name": "someless.internal"}}
    fake.objects["Account"] = {"a0": {"name": "admin", "domainId": "d0"}}
    fake.objects["SystemSettings"] = {"singleton": {"defaultHostname": "someless.internal"}}
    app.config.update(ENGINE_ENABLED=True, ENGINE_CLIENT=lambda: fake)
    return fake
