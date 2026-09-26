"""Against a real Stalwart v0.16.23 (set STALWART_BIN to its binary). Skipped otherwise."""
import os
import smtplib
import socket
import ssl

import pytest

from someless import engine as engine_module
from someless.engine import setup
from someless.engine.process import Stalwart

pytestmark = pytest.mark.skipif(not os.environ.get("STALWART_BIN"), reason="set STALWART_BIN to run against Stalwart")


@pytest.fixture
def live(app, tmp_path):
    stalwart = Stalwart(os.environ["STALWART_BIN"], tmp_path / "stalwart")
    # never Let's Encrypt from a test: nothing here can be reached from outside anyway
    app.config.update(ENGINE_ENABLED=True, ENGINE_ACME_DIRECTORY="")
    try:
        with app.app_context():
            setup.run(stalwart)
        yield stalwart
    finally:
        stalwart.stop()


def test_first_setup_leaves_it_running_with_our_listeners(app, live):
    with app.app_context():
        assert engine_module.state()["setup_step"] == "ready"
        names = {listener["name"] for listener in engine_module.client().get("NetworkListener")}
    assert {"submission", "submissions", "http"} <= names
    socket.create_connection(("127.0.0.1", 17587), timeout=5).close()


def _live_domain_and_key(app):
    """example.com authenticated, with a Sender shop@example.com and a key for live-0001."""
    import hashlib
    import time

    from someless.db import get_db
    from someless.domain_records import new_keys
    db = get_db()
    domain_id = db.execute("INSERT INTO domains (name, authenticated, added_at) VALUES ('example.com', 1, 0)").lastrowid
    keys = new_keys()
    db.execute("INSERT INTO domain_keys (domain_id, code, dkim_selector, dkim_private, dkim_public) VALUES (?, ?, 'someless', ?, ?)",
               (domain_id, keys["code"], keys["dkim_private"], keys["dkim_public"]))
    db.execute("INSERT INTO senders (name, email, domain_id, created_at) VALUES ('Shop', 'shop@example.com', ?, 0)", (domain_id,))
    db.execute("INSERT INTO smtp_keys (name, key_hash, hint, variant, created_at, login) VALUES ('Live', ?, 'xxxx', 'standard', ?, 'live-0001')",
               (hashlib.sha256(b"live-key-0123456789").hexdigest(), time.time()))
    db.commit()
    return domain_id


def test_a_key_sends_as_a_sender_only(app, live):
    from someless.engine import sync
    with app.app_context():
        _live_domain_and_key(app)
        assert sync.run(), engine_module.state()["sync_error"]
        engine = engine_module.client()
        assert sync.reconcile(engine, sync.desired_state()) == []   # Stalwart kept it as sent: a second sync changes nothing
        assert engine.get("SystemSettings", ["singleton"])[0]["defaultHostname"] == "mail.example.com"
    context = ssl._create_unverified_context()
    with smtplib.SMTP("127.0.0.1", 17587, timeout=20) as smtp:
        smtp.starttls(context=context)
        smtp.login("live-0001", "live-key-0123456789")
        assert smtp.mail("shop@example.com")[0] == 250
        smtp.rset()
        code, _ = smtp.mail("someone-else@example.com")
    assert code == 501
    with smtplib.SMTP("127.0.0.1", 17587, timeout=20) as smtp:
        smtp.starttls(context=context)
        try:
            smtp.login("live-0001", "wrong")
            raise AssertionError("a wrong key logged in")
        except smtplib.SMTPAuthenticationError as error:
            assert error.smtp_code == 535


def test_a_domain_that_loses_authentication_leaves_the_engine(app, live):
    from someless.db import get_db
    from someless.engine import sync
    with app.app_context():
        domain_id = _live_domain_and_key(app)
        assert sync.run()
        get_db().execute("UPDATE domains SET authenticated = 0 WHERE id = ?", (domain_id,))
        get_db().commit()
        assert sync.run(), engine_module.state()["sync_error"]
        engine = engine_module.client()
        assert "example.com" not in {domain["name"] for domain in engine.get("Domain")}
        group = next(obj for obj in engine.get("Account") if obj["name"] == "someless-senders")
        assert not group.get("aliases")
        assert sync.reconcile(engine, sync.desired_state()) == []   # and a second sync changes nothing


def test_an_unreachable_lets_encrypt_still_leaves_keys_working(app, live):
    from someless.engine import sync
    app.config["ENGINE_ACME_DIRECTORY"] = "http://127.0.0.1:9/directory"   # nothing answers there
    with app.app_context():
        _live_domain_and_key(app)
        assert not sync.run()
        assert "ACME" in engine_module.state()["sync_error"]
    with smtplib.SMTP("127.0.0.1", 17587, timeout=20) as smtp:
        smtp.starttls(context=ssl._create_unverified_context())
        smtp.login("live-0001", "live-key-0123456789")
        assert smtp.mail("shop@example.com")[0] == 250


def test_a_test_email_is_followed_to_its_end(app, live):
    """The panel sends through the engine as someless-panel, and the engine's report of what
    became of it comes back to /engine/events (the panel runs on a free port for this)."""
    import threading
    import time

    from werkzeug.serving import make_server

    from someless.engine import deliveries, sync
    panel = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=panel.serve_forever, daemon=True).start()
    app.config["ENGINE_EVENTS_URL"] = f"http://127.0.0.1:{panel.server_port}/engine/events"
    try:
        with app.app_context():
            _live_domain_and_key(app)
            assert sync.run(), engine_module.state()["sync_error"]
            queue_id = deliveries.send_test("shop@example.com", 1, "nobody@example.invalid", "Live test", "Hello")
            assert queue_id
            for _ in range(30):   # .invalid never resolves: a bounce report has to come
                found = deliveries.status(queue_id)
                if found["status"] != "queued":
                    break
                time.sleep(1)
        assert found["status"] == "bounced", found
        assert found["detail"]
    finally:
        panel.shutdown()
