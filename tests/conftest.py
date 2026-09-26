import pytest

from someless import create_app, domain_records


@pytest.fixture(autouse=True)
def no_real_dns(monkeypatch):
    """Tests never ask the real DNS: nothing is found, unless a test's `dns` fixture says so."""
    monkeypatch.setattr(domain_records, "lookup", lambda name, rdtype: [])
    # a domain's own name servers don't answer either, so the (made-up) usual DNS is asked
    monkeypatch.setattr(domain_records, "lookup_at", lambda servers, name, rdtype: None)


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
