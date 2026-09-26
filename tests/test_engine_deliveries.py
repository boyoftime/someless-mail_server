import base64
import hashlib
import hmac
import json

from someless import engine as engine_module
from someless.db import get_db
from someless.engine import deliveries

# As Stalwart has them: the DATA reply gives the queue id in hex, its events the same id as a number
QUEUE_ID, QUEUE_NUMBER = "49a58608ba00200", 331674694247776768


def signed(app, body):
    with app.app_context():
        key = engine_module.secret("webhook_secret").encode()
    return {"X-Signature": base64.b64encode(hmac.new(key, body, hashlib.sha256).digest()).decode(), "Content-Type": "application/json"}


def queued(app, queue_id=QUEUE_ID, to="you@gmail.com"):
    with app.app_context():
        deliveries.record(queue_id, sender_id=1, recipient=to)


def post(client, app, events, headers=None, remote="127.0.0.1"):
    body = json.dumps({"events": events}).encode()
    return client.post("/engine/events", data=body, headers=headers or signed(app, body),
                       environ_base={"REMOTE_ADDR": remote})


def status(app, queue_id=QUEUE_ID):
    with app.app_context():
        return deliveries.status(queue_id)


def test_a_delivered_event_marks_delivered(app, client):
    queued(app)

    response = post(client, app, [{"id": "1", "type": "delivery.delivered", "data": {
        "queueId": QUEUE_NUMBER, "to": "you@gmail.com", "hostname": "gmail-smtp-in.l.google.com", "code": 250,
        "details": "250 2.0.0 OK 1790434818 a1si"}}])

    assert response.status_code == 204
    assert status(app)["status"] == "delivered"
    assert status(app)["detail"] == "Delivered to gmail-smtp-in.l.google.com"


def test_bounce_event_marks_bounced(app, client):
    queued(app)

    post(client, app, [{"type": "delivery.dsn-perm-fail", "data": {
        "queueId": QUEUE_NUMBER, "to": "you@gmail.com", "hostname": "gmail-smtp-in.l.google.com",
        "details": "550 5.1.1 No such user", "total": 0}}])

    found = status(app)
    assert found["status"] == "bounced" and "No such user" in found["detail"]


def test_a_temporary_failure_is_retrying_and_delivery_later_wins(app, client):
    queued(app)

    post(client, app, [{"type": "delivery.dsn-temp-fail", "data": {"queueId": QUEUE_NUMBER, "details": "421 Try again later"}}])
    assert status(app)["status"] == "retrying"

    post(client, app, [{"type": "delivery.delivered", "data": {"queueId": QUEUE_NUMBER, "hostname": "mx.example.org"}}])
    post(client, app, [{"type": "delivery.dsn-temp-fail", "data": {"queueId": QUEUE_NUMBER, "details": "late"}}])
    assert status(app)["status"] == "delivered"


def test_events_for_mail_the_panel_did_not_send_are_ignored(app, client):
    response = post(client, app, [{"type": "delivery.delivered", "data": {"queueId": 12345, "hostname": "mx.example.org"}},
                                  {"type": "queue.message-queued", "data": {"queueId": QUEUE_NUMBER}}])

    assert response.status_code == 204


def test_events_need_the_signature(app, client):
    queued(app)

    response = post(client, app, [{"type": "delivery.delivered", "data": {"queueId": QUEUE_NUMBER}}], headers={"X-Signature": "bad"})

    assert response.status_code == 403
    assert status(app)["status"] == "queued"


def test_events_refused_from_outside_even_with_forwarded_header(app, client):
    queued(app)
    body = json.dumps({"events": [{"type": "delivery.delivered", "data": {"queueId": QUEUE_NUMBER}}]}).encode()

    response = client.post("/engine/events", data=body, headers={**signed(app, body), "X-Forwarded-For": "127.0.0.1"},
                           environ_base={"REMOTE_ADDR": "203.0.113.9"})

    assert response.status_code == 403
    assert status(app)["status"] == "queued"


def test_test_status_after_timeout(app, client, login, engine, monkeypatch):
    from test_engine_sync import a_sender, authenticated_domain
    a_sender(app, authenticated_domain(app), "no-reply@pineloop.online")
    with app.app_context():
        deliveries.record("old1", sender_id=1, recipient="you@gmail.com")
        get_db().execute("UPDATE deliveries SET created_at = created_at - 120")
        get_db().commit()
    login()

    found = client.get("/senders/1/tests/old1").get_json()

    assert found["status"] == "queued" and found["waited_long"] is True


def test_sending_a_test_uses_the_panels_account(app, client, login, engine, monkeypatch):
    from test_engine_sync import a_sender, authenticated_domain
    a_sender(app, authenticated_domain(app), "no-reply@pineloop.online")
    sent = {}

    def fake_send(from_address, sender_id, to, subject, text):
        sent.update(from_address=from_address, to=to)
        return "abc1"
    monkeypatch.setattr(deliveries, "send_test", fake_send)
    monkeypatch.setattr("someless.senders.ready_to_send", lambda: True)
    login()

    response = client.post("/senders/1/test", json={"to": "you@gmail.com", "subject": "Test", "text": "Hi"})

    assert response.get_json() == {"queue_id": "abc1"}
    assert sent == {"from_address": "no-reply@pineloop.online", "to": "you@gmail.com"}


def test_a_test_waits_for_the_engine_to_be_ready(app, client, login, engine):
    from test_engine_sync import a_sender, authenticated_domain
    a_sender(app, authenticated_domain(app), "no-reply@pineloop.online")
    login()

    response = client.post("/senders/1/test", json={"to": "you@gmail.com"})

    assert response.status_code == 409 and "Ready to send" in response.get_json()["problem"]


def test_the_last_test_shows_on_the_senders_card(app, client, login, engine):
    from test_engine_sync import a_sender, authenticated_domain
    a_sender(app, authenticated_domain(app), "no-reply@pineloop.online")
    queued(app)
    post(client, app, [{"type": "delivery.delivered", "data": {"queueId": QUEUE_NUMBER, "hostname": "gmail-smtp-in.l.google.com"}}])
    login()

    page = client.get("/senders").get_data(as_text=True)

    assert "Last test" in page and "Delivered to gmail-smtp-in.l.google.com" in page
    assert 'data-test-sender="1"' in page


def test_the_engine_reports_deliveries_to_the_panel(app, engine):
    from test_engine_sync import sync_now
    sync_now(app)
    sync_now(app)   # one, never two

    (hook,) = engine.objects["WebHook"].values()
    with app.app_context():
        key = engine_module.secret("webhook_secret")
    assert hook["url"] == "http://127.0.0.1:17080/engine/events"
    assert hook["eventsPolicy"] == "include" and "delivery.delivered" in hook["events"]
    assert hook["signatureKey"] == {"@type": "Value", "secret": key}


def test_the_reports_go_where_the_panel_is(app, engine):
    from test_engine_sync import sync_now
    sync_now(app)
    app.config["ENGINE_EVENTS_URL"] = "http://127.0.0.1:18080/engine/events"   # a panel on another port (the live tests)

    sync_now(app)

    (hook,) = engine.objects["WebHook"].values()
    assert hook["url"] == "http://127.0.0.1:18080/engine/events"
