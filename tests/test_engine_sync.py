import base64
import hashlib
import json
import re
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


def allowed(engine):
    """The addresses any logged-in account may send as: the Senders, in the send-as rule."""
    rule = engine.objects["MtaStageAuth"]["singleton"]["mustMatchSender"]
    return sorted(re.findall(r"sender == '([^']+)'", " ".join(match["if"] for match in rule["match"].values())))


def a_mailbox(app, email, domain_id, quota=1024 ** 3, password_hash="$pbkdf2-sha256$i=1,l=32$c2FsdA$aGFzaA",
              version=1, aliases=()):
    with app.app_context():
        db = get_db()
        mailbox_id = db.execute("INSERT INTO mailboxes (email, domain_id, quota_bytes, password_hash, password_version,"
                                " created_at) VALUES (?, ?, ?, ?, ?, 0)",
                                (email, domain_id, quota, password_hash, version)).lastrowid
        for alias in aliases:
            db.execute("INSERT INTO mailbox_aliases (mailbox_id, email, domain_id, created_at) VALUES (?, ?, ?, 0)",
                       (mailbox_id, alias, domain_id))
        db.commit()
        return mailbox_id


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
    assert allowed(engine) == []   # nobody may send as its addresses any more


def test_each_key_is_an_account_that_may_send_as_the_senders(app, engine):
    domain_id = authenticated_domain(app)
    a_sender(app, domain_id, "no-reply@pineloop.online")
    a_sender(app, domain_id, "news@pineloop.online")
    a_key(app)

    sync_now(app)

    account = engine.named("Account", "website-7f3a")
    assert account["credentials"] == {"0": {"@type": "Password", "secret": sync.sha256_secret(hashlib.sha256(KEY.encode()).hexdigest())}}
    assert account["domainId"] == "d0"   # someless.internal
    # the Senders are in the send-as rule: any account that has logged in may send as them
    assert allowed(engine) == ["news@pineloop.online", "no-reply@pineloop.online"]
    assert not account.get("memberGroupIds")


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

    assert engine.named("Account", "someless-panel")["domainId"] == "d0"
    assert allowed(engine) == ["no-reply@pineloop.online"]


def test_the_webmail_has_its_own_account_that_opens_the_mailboxes(app, engine):
    sync_now(app)

    account = engine.named("Account", "someless-webmail")
    assert account["domainId"] == "d0"
    # it may act for any mailbox (user%someless-webmail), and only from inside the container
    assert account["permissions"] == {"@type": "Merge", "enabledPermissions": {"impersonate": True}}
    credential = account["credentials"]["0"]
    assert credential["allowedIps"] == {"127.0.0.1": True}
    with app.app_context():
        password = engine_module.secret("webmail_password")
    assert credential["secret"] == sync.sha256_secret(hashlib.sha256(password.encode()).hexdigest())


def test_the_webmail_account_is_put_right_when_it_isnt(app, engine):
    sync_now(app)
    account_id = next(id_ for id_, obj in engine.objects["Account"].items() if obj["name"] == "someless-webmail")
    engine.objects["Account"][account_id]["permissions"] = {"@type": "Inherit"}   # (an older install's)

    sync_now(app)

    assert engine.named("Account", "someless-webmail")["permissions"]["enabledPermissions"] == {"impersonate": True}


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

    assert allowed(engine) == ["hello@pineloop.online"]


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
    assert allowed(engine) == ["no-reply@pineloop.online"]
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


def test_the_send_as_rule_reads_as_the_engine_wants_it():
    assert sync.send_as_rule(["a@x.com", "b@y.com"]) == {
        "match": {"0": {"if": "sender == 'a@x.com' || sender == 'b@y.com'", "then": "false"}}, "else": "true"}
    assert sync.send_as_rule([]) == {"match": {}, "else": "true"}   # every account sends as itself only
    assert sync.send_as_rule(["o'brien@x.com", "b@y.com"]) == {   # a quote can't go in the rule: left out
        "match": {"0": {"if": "sender == 'b@y.com'", "then": "false"}}, "else": "true"}


def test_the_old_senders_group_goes(app, engine):
    """Senders used to be a group's addresses, with every key's account in the group."""
    engine.objects["Account"]["g1"] = {"@type": "Group", "name": "someless-senders", "domainId": "d0",
                                       "aliases": {"0": {"name": "no-reply", "domainId": "d9"}}}
    engine.objects["Account"]["k1"] = {"@type": "User", "name": "website-7f3a", "domainId": "d0", "memberGroupIds": {"g1": True}}
    a_key(app)

    sync_now(app)

    assert engine.named("Account", "someless-senders") is None
    assert engine.named("Account", "website-7f3a")["memberGroupIds"] == {}


def test_a_mailbox_is_an_account_in_its_domain(app, engine):
    domain_id = authenticated_domain(app)
    a_mailbox(app, "ceo@pineloop.online", domain_id, quota=15 * 1024 ** 3, aliases=["hello@pineloop.online", "boss@pineloop.online"])

    sync_now(app)

    domain = engine.named("Domain", "pineloop.online")["id"]
    box = engine.named("Account", "ceo")
    assert (box["@type"], box["domainId"], box["quotas"]) == ("User", domain, {"maxDiskQuota": 15 * 1024 ** 3})
    assert box["credentials"] == {"0": {"@type": "Password", "secret": "$pbkdf2-sha256$i=1,l=32$c2FsdA$aGFzaA"}}
    assert sorted(alias["name"] for alias in box["aliases"].values()) == ["boss", "hello"]
    assert {alias["domainId"] for alias in box["aliases"].values()} == {domain}


def test_a_mailbox_kept_from_deleting_in_mail_apps_cant_erase_there(app, engine):
    """Disable delete, in mail apps (the Mailboxes page): the engine itself refuses erasing a
    message (IMAP expunge, POP delete) or a folder (IMAP delete) for it; switched off, as before."""
    domain_id = authenticated_domain(app)
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", domain_id)
    sync_now(app)
    assert engine.named("Account", "ceo")["permissions"] == {"@type": "Inherit"}

    with app.app_context():
        get_db().execute("UPDATE mailboxes SET no_delete_apps = 1 WHERE id = ?", (mailbox_id,))
        get_db().commit()
    sync_now(app)
    kept = engine.named("Account", "ceo")["permissions"]
    engine.calls.clear()
    sync_now(app)
    again = [call for call in engine.calls if call[0] != "get"]
    with app.app_context():
        get_db().execute("UPDATE mailboxes SET no_delete_apps = 0 WHERE id = ?", (mailbox_id,))
        get_db().commit()
    sync_now(app)

    assert kept["@type"] == "Merge" and kept["disabledPermissions"] == {"imapExpunge": True, "imapDelete": True, "pop3Dele": True}
    assert again == []   # (as it is already: nothing sent)
    assert engine.named("Account", "ceo")["permissions"] == {"@type": "Inherit"}


def test_a_mailbox_change_reaches_the_engine_and_only_then(app, engine):
    domain_id = authenticated_domain(app)
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", domain_id)
    sync_now(app)
    engine.calls.clear()
    sync_now(app)
    assert [call for call in engine.calls if call[0] != "get"] == []   # nothing changed: nothing sent

    with app.app_context():
        get_db().execute("UPDATE mailboxes SET quota_bytes = ?, password_hash = 'NEW', password_version = 2 WHERE id = ?",
                         (2 * 1024 ** 3, mailbox_id))
        get_db().commit()
    sync_now(app)

    box = engine.named("Account", "ceo")
    assert box["quotas"] == {"maxDiskQuota": 2 * 1024 ** 3}
    assert box["credentials"] == {"0": {"@type": "Password", "secret": "NEW"}}


def test_a_deleted_mailbox_leaves_the_engine(app, engine):
    domain_id = authenticated_domain(app)
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", domain_id)
    sync_now(app)
    with app.app_context():
        get_db().execute("DELETE FROM mailboxes WHERE id = ?", (mailbox_id,))
        get_db().commit()

    sync_now(app)

    assert engine.named("Account", "ceo") is None
    assert engine.named("Account", "admin")   # Stalwart's own stays


def test_a_domain_with_mailboxes_stays_when_it_loses_authentication(app, engine):
    """Destroying it would lose their mail: it stays, and mail keeps arriving."""
    domain_id = authenticated_domain(app)
    a_mailbox(app, "ceo@pineloop.online", domain_id)
    sync_now(app)
    with app.app_context():
        get_db().execute("UPDATE domains SET authenticated = 0 WHERE id = ?", (domain_id,))
        get_db().commit()

    sync_now(app)

    assert engine.named("Domain", "pineloop.online") and engine.named("Account", "ceo")


def mailbox_accounts(engine, local):
    """The engine's accounts with this name outside someless.internal."""
    return [dict(obj, id=id_) for id_, obj in engine.objects["Account"].items() if obj.get("name") == local and obj.get("domainId") != "d0"]


def test_a_mailbox_named_admin_is_kept_in_line_like_any_other(app, engine):
    """admin@yourdomain is a mailbox like the rest: found again by the next sync, not made twice,
    and gone when it's deleted. The engine's own admin (in someless.internal) stays."""
    domain_id = authenticated_domain(app)
    mailbox_id = a_mailbox(app, "admin@pineloop.online", domain_id)
    assert sync_now(app)
    with app.app_context():
        assert sync.reconcile(engine, sync.desired_state()) == []
    assert len(mailbox_accounts(engine, "admin")) == 1

    with app.app_context():
        get_db().execute("DELETE FROM mailboxes WHERE id = ?", (mailbox_id,))
        get_db().commit()
    assert sync_now(app)

    assert mailbox_accounts(engine, "admin") == []
    assert engine.objects["Account"]["a0"]["name"] == "admin"


def test_a_mailbox_made_again_at_the_same_address_gets_a_new_account(app, engine):
    """Deleted and made again before a sync (the engine was down): the new one has its own
    password, and none of the old one's mail."""
    domain_id = authenticated_domain(app)
    first = a_mailbox(app, "ceo@pineloop.online", domain_id, password_hash="$pbkdf2-sha256$i=1,l=32$b2xk$b2xk")
    assert sync_now(app)
    (old,) = mailbox_accounts(engine, "ceo")
    with app.app_context():
        get_db().execute("DELETE FROM mailboxes WHERE id = ?", (first,))
        get_db().commit()
    a_mailbox(app, "ceo@pineloop.online", domain_id, password_hash="$pbkdf2-sha256$i=1,l=32$bmV3$bmV3")

    assert sync_now(app)

    (new,) = mailbox_accounts(engine, "ceo")
    assert new["id"] != old["id"]
    assert new["credentials"]["0"]["secret"] == "$pbkdf2-sha256$i=1,l=32$bmV3$bmV3"


def test_an_alias_moves_to_another_mailbox_in_one_sync(app, engine):
    """The engine has an address on one account only: it leaves the old mailbox before it
    joins the new one."""
    domain_id = authenticated_domain(app)
    a_mailbox(app, "zeta@pineloop.online", domain_id, aliases=["hi@pineloop.online"])
    alpha = a_mailbox(app, "alpha@pineloop.online", domain_id)
    assert sync_now(app)
    with app.app_context():
        get_db().execute("UPDATE mailbox_aliases SET mailbox_id = ? WHERE email = 'hi@pineloop.online'", (alpha,))
        get_db().commit()

    assert sync_now(app), sync_error(app)

    names = {local: sorted(alias["name"] for alias in (mailbox_accounts(engine, local)[0].get("aliases") or {}).values())
             for local in ("alpha", "zeta")}
    assert names == {"alpha": ["hi"], "zeta": []}


def test_a_deleted_mailboxs_address_can_be_an_alias_at_once(app, engine):
    domain_id = authenticated_domain(app)
    zeta = a_mailbox(app, "zeta@pineloop.online", domain_id)
    alpha = a_mailbox(app, "alpha@pineloop.online", domain_id)
    assert sync_now(app)
    with app.app_context():
        db = get_db()
        db.execute("DELETE FROM mailboxes WHERE id = ?", (zeta,))
        db.execute("INSERT INTO mailbox_aliases (mailbox_id, email, domain_id, created_at) VALUES (?, 'zeta@pineloop.online', ?, 0)",
                   (alpha, domain_id))
        db.commit()

    assert sync_now(app), sync_error(app)

    assert [alias["name"] for alias in mailbox_accounts(engine, "alpha")[0]["aliases"].values()] == ["zeta"]
    assert mailbox_accounts(engine, "zeta") == []


def test_a_mailbox_the_engine_refuses_doesnt_hold_up_the_rest(app, engine):
    domain_id = authenticated_domain(app)
    engine.refuse_names = {"bad"}
    a_mailbox(app, "bad@pineloop.online", domain_id)
    a_mailbox(app, "good@pineloop.online", domain_id)

    assert not sync_now(app)   # the refusal is kept for the page

    assert mailbox_accounts(engine, "good")
    assert engine.objects.get("WebHook")   # and what comes after mailboxes still happens
    assert "invalidProperties" in sync_error(app)


def test_senders_are_matched_whatever_their_case():
    rule = sync.send_as_rule(["Shop@Example.com"])

    assert rule["match"]["0"]["if"] == "sender == 'shop@example.com'"


def sync_error(app):
    with app.app_context():
        return engine_module.state()["sync_error"]


# --- how large a message each mailbox may send (the Mailboxes page) ---

def test_the_size_rule_lets_each_mailbox_send_as_much_as_its_limit():
    assert sync.size_rule({"a@x.com": 50, "b@y.com": 50, "c@z.com": 100}) == {"match": {
        "0": {"if": "authenticated_as == 'a@x.com' || authenticated_as == 'b@y.com'", "then": str(sync.in_a_message(50))},
        "1": {"if": "authenticated_as == 'c@z.com'", "then": str(sync.in_a_message(100))}},
        "else": "104857600"}
    assert sync.size_rule({}) == {"match": {}, "else": "104857600"}   # mail from elsewhere: as the engine takes it
    assert sync.size_rule({"o'brien@x.com": 50, "b@y.com": 50}) == {"match": {   # a quote can't go in the rule
        "0": {"if": "authenticated_as == 'b@y.com'", "then": str(sync.in_a_message(50))}}, "else": "104857600"}


def test_files_up_to_the_limit_fit_in_the_message_allowed():
    for limit in (1, 50, 100):
        files = limit * 1024 ** 2
        assert sync.in_a_message(limit) > files * 4 // 3 + files // 76 * 2   # base64, a third larger, in lines of 76


def test_the_engine_takes_what_the_mailboxes_may_send(app, engine):
    domain_id = authenticated_domain(app)
    a_mailbox(app, "ceo@pineloop.online", domain_id)
    a_mailbox(app, "sales@pineloop.online", domain_id)
    with app.app_context():
        get_db().execute("UPDATE mailboxes SET send_limit_mb = 100 WHERE email = 'sales@pineloop.online'")
        get_db().commit()

    sync_now(app)

    rule = engine.objects["MtaStageData"]["singleton"]["maxMessageSize"]
    assert rule == sync.size_rule({"ceo@pineloop.online": 50, "sales@pineloop.online": 100})
    assert engine.objects["Jmap"]["singleton"]["maxUploadSize"] >= 100 * 1024 ** 2
    assert engine.objects["Email"]["singleton"]["maxAttachmentSize"] >= 100 * 1024 ** 2
    assert engine.objects["Email"]["singleton"]["maxMessageSize"] >= sync.in_a_message(100)
    assert engine.objects["Imap"]["singleton"]["maxRequestSize"] >= sync.in_a_message(100)
    assert ("action", "ReloadSettings", None) in engine.calls
    with app.app_context():
        assert sync.reconcile(engine, sync.desired_state()) == []   # and a second sync changes nothing
