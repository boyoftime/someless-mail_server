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
    assert listeners == ["http", "imaps", "pop3s", "smtp", "submission", "submissions"]


def all_listeners(engine):
    engine.objects["NetworkListener"] = {f"old{index}": dict(listener) for index, listener in enumerate(setup.LISTENERS)}


def test_setup_resumes_where_it_stopped(app, engine, monkeypatch):
    monkeypatch.setattr(setup, "admin_client", lambda: engine)
    all_listeners(engine)
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
    assert names == ["http", "imaps", "pop3s", "smtp", "submission", "submissions"]


def test_the_listeners_receive_mail_and_serve_mail_apps():
    ports = {listener["name"]: [int(address.rsplit(":", 1)[1]) for address in listener["bind"]] for listener in setup.LISTENERS}
    assert ports == {"submission": [17587], "submissions": [17465], "http": [17880],
                     "smtp": [25], "imaps": [17993], "pop3s": [17995]}
    # only receiving is on a low port: other mail servers deliver to 25 and nowhere else, and
    # Stalwart treats port 25 as the one mail comes in on (no login asked, SPF and DMARC checked)
    implicit_tls = sorted(listener["name"] for listener in setup.LISTENERS if listener.get("tlsImplicit"))
    assert implicit_tls == ["imaps", "pop3s", "submissions"]


def test_an_older_install_gets_the_new_listeners_at_start(app, engine, monkeypatch):
    """Listeners bind when Stalwart starts: the missing ones are made, then it starts again."""
    monkeypatch.setattr(setup, "admin_client", lambda: engine)
    engine.objects["NetworkListener"] = {f"old{index}": dict(listener) for index, listener in enumerate(setup.LISTENERS)
                                         if listener["name"] in ("submission", "submissions", "http")}
    process = FakeProcess()
    with app.app_context():
        engine_module.remember(setup_step="ready")
        setup.run(process)

    names = sorted(obj["name"] for obj in engine.objects["NetworkListener"].values())
    assert names == ["http", "imaps", "pop3s", "smtp", "submission", "submissions"]
    assert [mode for mode, _ in process.starts] == ["normal", "stop", "normal"]


def test_a_start_with_every_listener_starts_once(app, engine, monkeypatch):
    monkeypatch.setattr(setup, "admin_client", lambda: engine)
    all_listeners(engine)
    process = FakeProcess()
    with app.app_context():
        engine_module.remember(setup_step="ready")
        setup.run(process)

    assert [mode for mode, _ in process.starts] == ["normal"]


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
