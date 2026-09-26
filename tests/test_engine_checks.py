from someless.engine import checks


def run(app, **probes):
    with app.app_context():
        return {check.key: check for check in checks.run_checks("194.163.167.106")}


def test_without_a_domain_nothing_can_send(app, engine, monkeypatch):
    monkeypatch.setattr(checks, "port25_open", lambda: True)
    monkeypatch.setattr(checks, "reverse_name", lambda ip: None)
    monkeypatch.setattr(checks, "addresses_of", lambda name: [])

    found = run(app)

    assert found["server-name"].state == "missing"
    with app.app_context():
        assert not checks.can_send(list(found.values()))


def test_a_blocked_port_25_and_no_reverse_dns_are_warnings(app, engine, monkeypatch):
    from test_engine_sync import a_sender, authenticated_domain
    domain_id = authenticated_domain(app)
    a_sender(app, domain_id, "no-reply@pineloop.online")
    engine.objects["Certificate"] = {"c1": {"subjectAlternativeNames": {"mail.pineloop.online": True}, "notValidAfter": "2099-01-01T00:00:00Z"}}
    monkeypatch.setattr(checks, "port25_open", lambda: False)
    monkeypatch.setattr(checks, "reverse_name", lambda ip: "vmi123.contaboserver.net")
    monkeypatch.setattr(checks, "addresses_of", lambda name: ["194.163.167.106"])

    found = run(app)

    assert found["port25"].state == "warning" and "provider" in found["port25"].detail
    assert found["reverse-dns"].state == "warning" and "mail.pineloop.online" in found["reverse-dns"].detail
    with app.app_context():
        assert checks.can_send(list(found.values()))


def test_no_certificate_explains_the_proxy_step(app, engine, monkeypatch):
    from test_engine_sync import a_sender, authenticated_domain
    a_sender(app, authenticated_domain(app), "no-reply@pineloop.online")
    monkeypatch.setattr(checks, "port25_open", lambda: True)
    monkeypatch.setattr(checks, "reverse_name", lambda ip: "mail.pineloop.online")
    monkeypatch.setattr(checks, "addresses_of", lambda name: ["194.163.167.106"])

    found = run(app)

    assert found["certificate"].state == "missing"
    assert "17081" in found["certificate"].detail


def test_a_sender_counts_only_at_an_authenticated_domain(app, engine, monkeypatch):
    from test_engine_sync import a_sender, authenticated_domain
    authenticated_domain(app)
    a_sender(app, authenticated_domain(app, "cloudnix.net", authenticated=False), "hello@cloudnix.net")

    found = run(app)

    assert found["sender"].state == "missing"   # nothing can send as hello@cloudnix.net
