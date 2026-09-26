import base64
import hashlib
import json
import time

from someless import engine as engine_module
from someless.db import get_db
from someless.engine import sync

KEY = "k" * 64


def authenticated_domain(app, name="pineloop.online", authenticated=True):
    with app.app_context():
        db = get_db()
        domain_id = db.execute("INSERT INTO domains (name, authenticated, added_at) VALUES (?, ?, 0)",
                               (name, int(authenticated))).lastrowid
        db.execute("INSERT INTO domain_keys (domain_id, code, dkim_selector, dkim_private, dkim_public) VALUES (?, 'c', 'someless', ?, 'k')",
                   (domain_id, f"PEM-{name}"))
        db.commit()
        return domain_id


def a_sender(app, domain_id, email):
    with app.app_context():
        get_db().execute("INSERT INTO senders (name, email, domain_id, created_at) VALUES ('S', ?, ?, 0)", (email, domain_id))
        get_db().commit()


def a_key(app, login="website-7f3a", expires_at=None, key=KEY):
    with app.app_context():
        get_db().execute("INSERT INTO smtp_keys (name, key_hash, hint, variant, created_at, expires_at, login) VALUES ('Website', ?, 'xxxx', 'standard', 0, ?, ?)",
                         (hashlib.sha256(key.encode()).hexdigest(), expires_at, login))
        get_db().commit()


def sync_now(app):
    with app.app_context():
        return sync.run()


def test_the_secret_format_is_sha256_base64():
    digest = hashlib.sha256(b"abc").hexdigest()
    assert sync.sha256_secret(digest) == "{SHA256}" + base64.b64encode(hashlib.sha256(b"abc").digest()).decode()


def test_an_authenticated_domain_gets_its_dkim_key(app, engine):
    authenticated_domain(app)

    assert sync_now(app)

    domain = engine.named("Domain", "pineloop.online")
    assert domain["dkimManagement"] == {"@type": "Manual"}
    dkim = [obj for obj in engine.objects["DkimSignature"].values() if obj["domainId"] == domain["id"]]
    assert dkim == [{"@type": "Dkim1RsaSha256", "domainId": domain["id"], "selector": "someless",
                     "privateKey": {"@type": "Text", "secret": "PEM-pineloop.online"}}]


def test_a_domain_not_authenticated_stays_out(app, engine):
    authenticated_domain(app, "cloudnix.net", authenticated=False)

    sync_now(app)

    assert engine.named("Domain", "cloudnix.net") is None


def test_domain_losing_authentication_leaves_engine(app, engine):
    domain_id = authenticated_domain(app)
    a_sender(app, domain_id, "no-reply@pineloop.online")
    a_key(app)
    sync_now(app)
    with app.app_context():
        get_db().execute("UPDATE domains SET authenticated = 0 WHERE id = ?", (domain_id,))
        get_db().commit()

    sync_now(app)

    assert engine.named("Domain", "pineloop.online") is None
    assert not engine.objects.get("DkimSignature")
    assert engine.named("Account", "someless-senders")["aliases"] == {}


def test_each_key_is_an_account_that_may_send_as_the_senders(app, engine):
    domain_id = authenticated_domain(app)
    a_sender(app, domain_id, "no-reply@pineloop.online")
    a_sender(app, domain_id, "news@pineloop.online")
    a_key(app)

    sync_now(app)

    account = engine.named("Account", "website-7f3a")
    assert account["credentials"] == {"0": {"@type": "Password", "secret": sync.sha256_secret(hashlib.sha256(KEY.encode()).hexdigest())}}
    assert account["domainId"] == "d0"   # someless.internal
    # an address can be one account's only, so the Senders are the addresses of one group,
    # and a key's account may send as them by being in it
    group = engine.named("Account", "someless-senders")
    assert group["@type"] == "Group" and group["domainId"] == "d0"
    assert account["memberGroupIds"] == {group["id"]: True}
    domain = engine.named("Domain", "pineloop.online")["id"]
    assert sorted(alias["name"] for alias in group["aliases"].values()) == ["news", "no-reply"]
    assert {alias["domainId"] for alias in group["aliases"].values()} == {domain}


def test_expired_key_account_removed(app, engine):
    authenticated_domain(app)
    a_key(app, expires_at=time.time() + 60)
    sync_now(app)
    with app.app_context():
        get_db().execute("UPDATE smtp_keys SET expires_at = ?", (time.time() - 1,))
        get_db().commit()

    sync_now(app)
    sync_now(app)   # and never comes back

    assert engine.named("Account", "website-7f3a") is None


def test_the_panel_has_its_own_account(app, engine):
    domain_id = authenticated_domain(app)
    a_sender(app, domain_id, "no-reply@pineloop.online")

    sync_now(app)

    group = engine.named("Account", "someless-senders")
    assert engine.named("Account", "someless-panel")["memberGroupIds"] == {group["id"]: True}
    assert [alias["name"] for alias in group["aliases"].values()] == ["no-reply"]


def test_stalwarts_own_admin_and_domain_are_left_alone(app, engine):
    sync_now(app)

    assert engine.named("Account", "admin") and engine.named("Domain", "someless.internal")


def test_nothing_changes_when_nothing_changed(app, engine):
    authenticated_domain(app)
    a_key(app)
    sync_now(app)
    engine.calls.clear()

    sync_now(app)

    assert [call for call in engine.calls if call[0] != "get"] == []


def test_sync_failure_is_kept_and_page_still_works(app, engine, client, login):
    engine.down = True
    authenticated_domain(app)

    assert sync_now(app) is False
    with app.app_context():
        assert "down" in engine_module.state()["sync_error"]
    login()
    assert client.get("/smtp").status_code == 200


def test_views_sync_after_changes(app, engine, client, login):
    authenticated_domain(app)
    login()

    client.post("/senders", data={"name": "PineLoop", "email": "hello@pineloop.online"})

    assert engine.named("Account", "someless-senders")["aliases"]


def test_the_server_name_gets_its_certificate(app, engine):
    authenticated_domain(app)

    sync_now(app)

    domain = engine.named("Domain", "pineloop.online")
    provider = next(iter(engine.objects["AcmeProvider"]))
    assert domain["certificateManagement"] == {"@type": "Automatic", "acmeProviderId": provider,
                                               "subjectAlternativeNames": {"mail.pineloop.online": True}}
    assert engine.objects["SystemSettings"]["singleton"]["defaultHostname"] == "mail.pineloop.online"
    assert engine.objects["AcmeProvider"][provider]["challengeType"] == "Http01"


def test_a_certificate_for_the_server_name_becomes_the_default(app, engine):
    authenticated_domain(app)
    sync_now(app)
    engine.objects["Certificate"] = {"c1": {"subjectAlternativeNames": {"mail.pineloop.online": True}}}

    sync_now(app)

    assert engine.objects["SystemSettings"]["singleton"]["defaultCertificateId"] == "c1"
    assert ("action", "ReloadTlsCertificates", None) in engine.calls


def test_a_certificate_problem_does_not_hold_up_the_rest(app, engine):
    domain_id = authenticated_domain(app)
    a_sender(app, domain_id, "no-reply@pineloop.online")
    a_key(app)
    engine.fail_on.add("AcmeProvider")   # Let's Encrypt can't be reached

    assert sync_now(app) is False

    assert engine.named("Account", "website-7f3a")   # keys and Senders still go through
    assert engine.named("Account", "someless-senders")["aliases"]
    assert ("action", "ReloadSettings", None) in engine.calls
    with app.app_context():
        assert "AcmeProvider" in engine_module.state()["sync_error"]


def test_no_certificates_where_there_is_no_acme(app, engine):
    app.config["ENGINE_ACME_DIRECTORY"] = ""   # a test or a machine that can't be reached from outside
    authenticated_domain(app)

    assert sync_now(app)

    assert not engine.objects.get("AcmeProvider")
    assert engine.objects["SystemSettings"]["singleton"]["defaultHostname"] == "mail.pineloop.online"


def test_engine_status_command(app, engine):
    runner = app.test_cli_runner()

    result = runner.invoke(args=["engine", "status"])
    assert result.exit_code == 1 and "new" in result.output   # not set up yet

    with app.app_context():
        engine_module.remember(setup_step="ready")
    sync_now(app)
    result = runner.invoke(args=["engine", "status"])
    assert result.exit_code == 0 and "ready" in result.output and "synced" in result.output


def test_check_again_asks_lets_encrypt_again(app, engine, client, login):
    """Stalwart orders the certificate once, when the domain turns Automatic; if the proxy
    host came later, "Check again" asks for a new order, at most every 10 minutes."""
    authenticated_domain(app)
    sync_now(app)
    domain = engine.named("Domain", "pineloop.online")["id"]
    login()

    client.post("/smtp/checks")
    client.post("/smtp/checks")   # straight after: not again (Let's Encrypt allows 5 failed checks an hour)

    orders = [call for call in engine.calls if call[:2] == ("create", "Task")]
    assert orders == [("create", "Task", {"@type": "AcmeRenewal", "domainId": domain})]


def test_no_new_order_once_the_certificate_is_in(app, engine, client, login):
    authenticated_domain(app)
    sync_now(app)
    engine.objects["Certificate"] = {"c1": {"subjectAlternativeNames": {"mail.pineloop.online": True},
                                            "notValidAfter": "2099-01-01T00:00:00Z"}}
    login()

    client.post("/smtp/checks")

    assert not [call for call in engine.calls if call[:2] == ("create", "Task")]


def test_an_unexpected_engine_reply_never_breaks_a_save(app, engine, client, login, monkeypatch):
    domain_id = authenticated_domain(app)
    monkeypatch.setattr(engine, "get", lambda kind, ids=None: (_ for _ in ()).throw(TypeError("odd reply")))
    login()

    response = client.post("/senders", data={"name": "PineLoop", "email": "hello@pineloop.online"})

    assert response.status_code == 302   # saved, and on to the list
    with app.app_context():
        assert get_db().execute("SELECT 1 FROM senders WHERE domain_id = ?", (domain_id,)).fetchone()
        assert "odd reply" in engine_module.state()["sync_error"]
