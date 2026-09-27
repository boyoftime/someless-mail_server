"""A new install's first password (first_password.py): made at random on the first start, printed
in the container's logs, shown again by a command on the server until it's changed in Settings."""
import os
import pathlib

import pytest

from someless import create_app


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.delenv("SOMELESS_INITIAL_PASSWORD")
    return {"TESTING": True, "DATA_DIR": str(tmp_path), "WTF_CSRF_ENABLED": False}


def kept(config):
    return pathlib.Path(config["DATA_DIR"]) / "initial_password"


def log_in(app, password):
    return app.test_client().post("/login", data={"username": "admin", "password": password})


def test_a_new_install_makes_its_own_password_and_says_it(fresh, capsys):
    app = create_app(fresh)

    password = kept(fresh).read_text().strip()
    assert len(password) >= 16 and password != "admin"
    assert "/login" in log_in(app, "admin").headers.get("Location", "/login")   # admin/admin: no more
    assert log_in(app, password).headers["Location"] == "/dashboard"
    printed = capsys.readouterr().out
    assert password in printed and "admin" in printed and "flask --app someless initial-password" in printed
    if os.name != "nt":
        assert oct(kept(fresh).stat().st_mode & 0o777) == "0o600"


def test_the_next_start_keeps_it_and_says_nothing(fresh, capsys):
    create_app(fresh)
    password = kept(fresh).read_text().strip()
    capsys.readouterr()

    create_app(fresh)

    assert kept(fresh).read_text().strip() == password and password not in capsys.readouterr().out


def test_a_command_shows_it_until_it_is_changed(fresh):
    app = create_app(fresh)
    password = kept(fresh).read_text().strip()

    assert password in app.test_cli_runner().invoke(args=["initial-password"]).output

    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": password})
    client.post("/settings/password", data={"current_password": password, "new_password": "My-Own-Pass-123!",
                                            "confirm_password": "My-Own-Pass-123!"})

    assert not kept(fresh).exists()
    said = app.test_cli_runner().invoke(args=["initial-password"]).output
    assert password not in said and "changed" in said


def test_a_forgotten_password_is_reset_from_the_server(fresh):
    app = create_app(fresh)

    said = app.test_cli_runner().invoke(args=["reset-password"]).output

    password = kept(fresh).read_text().strip()
    assert password in said
    assert log_in(app, password).headers["Location"] == "/dashboard"
