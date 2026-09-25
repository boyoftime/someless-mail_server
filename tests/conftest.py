import pytest

from someless import create_app


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
