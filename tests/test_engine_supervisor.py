from pathlib import Path

from someless import engine as engine_module
from someless.engine import supervisor
from someless.engine.client import EngineUnavailable


def test_only_challenges_are_relayed():
    asked = []

    def fetch(path):
        asked.append(path)
        return 200, b"token.thumbprint"

    assert supervisor.challenge_reply("/.well-known/acme-challenge/abc_DEF-123", fetch) == (200, b"token.thumbprint")
    for path in ["/", "/jmap/", "/login", "/.well-known/acme-challenge/../../jmap", "/.well-known/acme-challenge/",
                 "/.well-known/acme-challenge/abc?x=1"]:
        assert supervisor.challenge_reply(path, fetch) == (404, b"")
    assert asked == ["/.well-known/acme-challenge/abc_DEF-123"]


def test_restarts_wait_longer_each_time():
    assert [supervisor.backoff(n) for n in range(8)] == [1, 2, 4, 8, 16, 32, 60, 60]


class BrokenStalwart:
    """Starts, but never answers."""
    data_dir = "/data/stalwart"
    config = Path(__file__)   # stands in for its config.json, which is there

    def __init__(self):
        self.stopped = False

    def start(self, mode="normal", recovery_password=None):
        pass

    def wait_until_up(self, timeout=60):
        raise EngineUnavailable("Stalwart exited with 1")

    def stop(self, timeout=15):
        self.stopped = True

    def running(self):
        return False


def test_an_engine_that_wont_start_doesnt_stop_the_panel(app, engine):
    stalwart = BrokenStalwart()
    with app.app_context():
        engine_module.remember(setup_step="ready")

    assert supervisor.bring_up(app, stalwart) is False   # reported; the panel starts anyway

    assert stalwart.stopped


def test_an_engine_that_starts_is_synced(app, engine):
    class Working(BrokenStalwart):
        def wait_until_up(self, timeout=60):
            pass
    with app.app_context():
        engine_module.remember(setup_step="ready")

    assert supervisor.bring_up(app, Working()) is True

    assert engine.named("Account", "someless-panel")   # the first sync ran


def test_the_relay_says_whose_it_is():
    """So an admin checking the proxy host sees it reaches Someless Mail (README, Troubleshooting)."""
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    relay = ThreadingHTTPServer(("127.0.0.1", 0), supervisor._Relay)
    threading.Thread(target=relay.serve_forever, daemon=True).start()
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{relay.server_port}/login", timeout=5)
        raise AssertionError("the relay answered /login")
    except urllib.error.HTTPError as error:
        assert error.code == 404 and b"Someless Mail" in error.read()
    finally:
        relay.shutdown()


def test_the_relay_drops_connections_that_say_nothing(monkeypatch):
    """17081 is open to the internet: a connection that never sends a request can't hold a thread."""
    import socket
    import threading
    import time
    from http.server import ThreadingHTTPServer

    assert supervisor._Relay.timeout and supervisor._Relay.timeout <= 30   # its own, not the default (none)
    monkeypatch.setattr(supervisor._Relay, "timeout", 0.3)                 # shorter, for the test
    relay = ThreadingHTTPServer(("127.0.0.1", 0), supervisor._Relay)
    threading.Thread(target=relay.serve_forever, daemon=True).start()
    try:
        silent = socket.create_connection(("127.0.0.1", relay.server_port), timeout=5)
        time.sleep(1)
        assert silent.recv(100) == b""   # closed by the relay
        silent.close()
    finally:
        relay.shutdown()


def test_a_bad_host_header_is_refused_not_a_crash():
    assert supervisor._fetch_from_stalwart("/.well-known/acme-challenge/abc", "mail.example.com\r\nX: y") == (503, b"")


def test_the_panel_starts_before_the_engine_is_set_up(monkeypatch):
    """So the first start shows "Preparing your Someless Mail server" instead of no page at all."""
    started = []

    class Panel:
        returncode = 0

        def poll(self):
            return 0   # it stops at once, and so does the supervisor

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    class Relay:
        def __init__(self, *args):
            pass

        def serve_forever(self):
            pass

        def shutdown(self):
            pass

    def popen(command):
        started.append("webmail" if command == supervisor.WEBMAIL_GUNICORN else "panel")
        return Panel()

    monkeypatch.setattr(supervisor.subprocess, "Popen", popen)
    monkeypatch.setattr(supervisor, "bring_up", lambda app, stalwart: started.append("engine") or True)
    monkeypatch.setattr(supervisor, "ThreadingHTTPServer", Relay)
    monkeypatch.setattr("someless.create_app", lambda: object())

    supervisor.main()

    assert started == ["panel", "webmail", "engine"]


def test_the_webmail_is_its_own_site_on_17090():
    command = supervisor.WEBMAIL_GUNICORN
    assert command[command.index("--bind") + 1] == "0.0.0.0:17090"
    assert command[-1] == "someless.webmail:create_webmail_app()"
    assert "--preload" in command and "gthread" in command


def test_domains_are_checked_when_it_is_time(app, monkeypatch):
    from someless import domain_checks
    ran = []
    monkeypatch.setattr(domain_checks, "run", lambda: ran.append("checked") or [])
    with app.app_context():
        domain_checks.save(enabled=True, every_hours=1)

    supervisor.check_domains_if_due(app)
    assert ran == ["checked"]

    with app.app_context():
        domain_checks.save(enabled=False, every_hours=1)
    supervisor.check_domains_if_due(app)
    assert ran == ["checked"]   # off: nothing
