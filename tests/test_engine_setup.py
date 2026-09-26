from pathlib import Path

from someless import engine as engine_module
from someless.engine import setup


class FakeProcess:
    """Stands in for Stalwart: records how it's started; the fake API answers meanwhile."""
    def __init__(self, config_exists=True):
        self.starts = []
        self.data_dir = "/data/stalwart"
        # Stalwart's config.json: this file stands in for one that's there
        self.config = Path(__file__) if config_exists else Path(__file__).with_name("no-such-config.json")

    def start(self, mode, recovery_password=None):
        self.starts.append((mode, bool(recovery_password)))

    def stop(self, timeout=15):
        self.starts.append(("stop", None))

    def wait_until_up(self, timeout=60):
        pass

    def running(self):
        return True


def test_first_setup_bootstraps_provisions_and_starts_normally(app, engine, monkeypatch):
    monkeypatch.setattr(setup, "admin_client", lambda: engine)   # the recovery admin's client
    engine.bootstrap_reply = {"username": "admin@someless.internal", "secret": "made-by-stalwart"}
    process = FakeProcess()
    with app.app_context():
        setup.run(process)
        row = engine_module.state()
    assert [mode for mode, _ in process.starts] == ["bootstrap", "stop", "recovery", "stop", "normal"]
    assert process.starts[0] == ("bootstrap", True) and process.starts[2] == ("recovery", True)
    assert (row["admin_login"], row["admin_password"]) == ("admin@someless.internal", "made-by-stalwart")
    assert row["setup_step"] == "ready"
    bootstrap = next(arguments for kind, method, arguments in engine.calls if kind == "call" and method == "x:Bootstrap/set")
    assert bootstrap["update"]["singleton"]["dataStore"]["@type"] == "RocksDb"
    listeners = sorted(obj["name"] for obj in engine.objects["NetworkListener"].values())
    assert listeners == ["http", "submission", "submissions"]


def test_setup_resumes_where_it_stopped(app, engine, monkeypatch):
    monkeypatch.setattr(setup, "admin_client", lambda: engine)
    process = FakeProcess()
    with app.app_context():
        engine_module.remember(setup_step="provisioned")
        setup.run(process)
    assert [mode for mode, _ in process.starts] == ["normal"]


def test_listeners_made_once_when_provisioning_is_repeated(app, engine, monkeypatch):
    monkeypatch.setattr(setup, "admin_client", lambda: engine)
    engine.objects["NetworkListener"] = {"n0": {"name": "submission", "protocol": "smtp", "bind": {"[::]:17587": True}}}
    with app.app_context():
        engine_module.remember(setup_step="bootstrapped")
        setup.run(FakeProcess())
    names = sorted(obj["name"] for obj in engine.objects["NetworkListener"].values())
    assert names == ["http", "submission", "submissions"]


def test_listeners_never_use_privileged_ports():
    for listener in setup.LISTENERS:
        for address in listener["bind"]:
            assert int(address.rsplit(":", 1)[1]) > 1024


def test_a_wiped_engine_folder_is_set_up_again(app, engine, monkeypatch):
    """data/stalwart deleted (or restored without it): the panel still says ready, but
    Stalwart would start in bootstrap mode and never answer. Set it up again."""
    monkeypatch.setattr(setup, "admin_client", lambda: engine)
    engine.bootstrap_reply = {"username": "admin@someless.internal", "secret": "made-again"}
    process = FakeProcess(config_exists=False)
    with app.app_context():
        engine_module.remember(setup_step="ready", admin_login="admin@someless.internal", admin_password="old")
        setup.run(process)
        row = engine_module.state()

    assert [mode for mode, _ in process.starts] == ["bootstrap", "stop", "recovery", "stop", "normal"]
    assert row["admin_password"] == "made-again"
