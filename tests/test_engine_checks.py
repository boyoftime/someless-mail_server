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


# the real lookups (conftest stands them in for every test; these tests check them)
from someless.engine.checks import addresses_of as real_addresses_of, reverse_name as real_reverse_name  # noqa: E402
from someless.engine.checks import greeting as real_greeting  # noqa: E402


def fake_dns(monkeypatch, usual, at_source):
    """The usual DNS (which may keep old answers) and the zone's own name servers, who hold the new ones."""
    from someless import domain_records
    monkeypatch.setattr(domain_records, "lookup", lambda name, rdtype: usual.get((name, rdtype), []))
    monkeypatch.setattr(domain_records, "lookup_at", lambda servers, name, rdtype: (
        at_source.get((name, rdtype), []) if servers == ["203.0.113.53"] else None))


def test_reverse_dns_is_asked_of_the_providers_own_name_servers(monkeypatch):
    # 192.0.2.10: an address for documentation, so the real DNS knows nothing of it
    fake_dns(monkeypatch, usual={
        ("2.0.192.in-addr.arpa", "NS"): ["ns1.provider.test."],
        ("ns1.provider.test", "A"): ["203.0.113.53"],
        ("10.2.0.192.in-addr.arpa", "PTR"): ["vmi2876893.provider.test."],   # the old name, kept for a day
    }, at_source={("10.2.0.192.in-addr.arpa", "PTR"): ["mail.pineloop.test."]})

    assert real_reverse_name("192.0.2.10") == "mail.pineloop.test"


def test_reverse_dns_falls_back_to_the_usual_dns(monkeypatch):
    fake_dns(monkeypatch, usual={("10.2.0.192.in-addr.arpa", "PTR"): ["mail.pineloop.test."]}, at_source={})

    assert real_reverse_name("192.0.2.10") == "mail.pineloop.test"


def test_the_server_names_a_record_is_asked_at_its_source(monkeypatch):
    fake_dns(monkeypatch, usual={
        ("pineloop.test", "NS"): ["dns1.registrar.test."],
        ("dns1.registrar.test", "A"): ["203.0.113.53"],
        # the usual DNS remembers there was no such name a minute ago
    }, at_source={("mail.pineloop.test", "A"): ["192.0.2.10"]})

    assert real_addresses_of("mail.pineloop.test") == ["192.0.2.10"]


def ready_to_send(app, engine, monkeypatch):
    from test_engine_sync import a_sender, authenticated_domain
    a_sender(app, authenticated_domain(app), "no-reply@pineloop.online")
    engine.objects["Certificate"] = {"c1": {"subjectAlternativeNames": {"mail.pineloop.online": True}, "notValidAfter": "2099-01-01T00:00:00Z"}}
    monkeypatch.setattr(checks, "addresses_of", lambda name: ["194.163.167.106"])


def test_incoming_ports_that_reach_the_mail_engine_are_ticked(app, engine, monkeypatch):
    ready_to_send(app, engine, monkeypatch)
    asked = []
    monkeypatch.setattr(checks, "greeting", lambda host, port, tls: asked.append((host, port, tls)) or "220 same")

    found = run(app)

    assert [found[key].state for key in ("port25-in", "imap", "pop3")] == ["ok", "ok", "ok"]
    # asked the way the world does, by the server name, and compared with the engine's own answer
    assert ("mail.pineloop.online", 25, False) in asked and ("127.0.0.1", 25, False) in asked
    assert ("mail.pineloop.online", 993, True) in asked and ("127.0.0.1", 17993, True) in asked
    assert ("mail.pineloop.online", 995, True) in asked and ("127.0.0.1", 17995, True) in asked


def test_a_port_that_doesnt_reach_it_says_how_to_open_it(app, engine, monkeypatch):
    ready_to_send(app, engine, monkeypatch)
    monkeypatch.setattr(checks, "greeting", lambda host, port, tls: "220 same" if host == "127.0.0.1" else None)

    found = run(app)

    for key, mapping, rule in (("port25-in", '"25:25"', "sudo ufw allow 25/tcp"), ("imap", '"993:17993"', "sudo ufw allow 993/tcp"),
                               ("pop3", '"995:17995"', "sudo ufw allow 995/tcp")):
        assert found[key].state == "warning", key
        assert mapping in found[key].detail and rule in found[key].detail, key
    with app.app_context():
        assert checks.can_send(list(found.values()))   # sending doesn't wait for them


def test_another_server_on_the_port_isnt_taken_for_this_one(app, engine, monkeypatch):
    ready_to_send(app, engine, monkeypatch)
    monkeypatch.setattr(checks, "greeting", lambda host, port, tls: (
        "220 mail.pineloop.online Stalwart ESMTP at your service" if host == "127.0.0.1" else "220 old-server ESMTP Postfix"))

    assert run(app)["port25-in"].state == "warning"


def test_with_the_engine_down_the_ports_arent_checked(app, engine, monkeypatch):
    ready_to_send(app, engine, monkeypatch)
    engine.down = True

    found = run(app)

    assert not {"port25-in", "imap", "pop3"} & set(found)


def test_a_greeting_is_the_first_line_a_server_says():
    import socket
    import threading
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve():
        conn, _ = listener.accept()
        conn.sendall(b"220 mail.example.com ESMTP\r\n250 more\r\n")
        conn.close()
    threading.Thread(target=serve, daemon=True).start()

    assert real_greeting("127.0.0.1", port, False) == "220 mail.example.com ESMTP"
    listener.close()
    assert real_greeting("127.0.0.1", port, False) is None   # nothing there any more


def test_ready_to_receive_too_once_every_incoming_port_reaches_the_engine(app, engine, monkeypatch):
    ready_to_send(app, engine, monkeypatch)
    monkeypatch.setattr(checks, "greeting", lambda host, port, tls: "220 same")
    with app.app_context():
        assert checks.can_receive(list(run(app).values()))

    checks.forget()
    monkeypatch.setattr(checks, "greeting", lambda host, port, tls: None if port == 995 else "220 same")
    with app.app_context():
        assert not checks.can_receive(list(run(app).values()))   # one short is enough
    assert not checks.can_receive([])                              # not checked (engine down)


def test_the_card_says_send_and_receive_when_both_are_ready(app, engine, client, login, monkeypatch):
    ready_to_send(app, engine, monkeypatch)
    monkeypatch.setattr(checks, "greeting", lambda host, port, tls: "220 same")
    monkeypatch.setattr(checks, "port25_open", lambda: True)
    login()

    page = client.get("/smtp").get_data(as_text=True)

    assert '<h2 class="smtp-title" id="ready-title">Ready to send and receive</h2>' in page
