import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from someless import engine
from someless.engine.client import EngineClient, EngineError, EngineUnavailable


@pytest.fixture
def stalwart_api():
    """A made-up Stalwart API: answers each POST /jmap/ with the next canned reply."""
    seen, replies = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            status, reply = replies.pop(0)
            data = json.dumps(reply).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", seen, replies
    server.shutdown()


def answer(name, result):
    return 200, {"methodResponses": [[name, result, "c"]], "sessionState": "x"}


def test_a_call_is_a_jmap_request_with_basic_auth(stalwart_api):
    url, seen, replies = stalwart_api
    replies.append(answer("x:Domain/get", {"list": [{"id": "a", "name": "example.com"}]}))

    domains = EngineClient(url, basic=("admin", "pw")).get("Domain")

    assert domains == [{"id": "a", "name": "example.com"}]
    assert seen[0]["path"] == "/jmap/"
    assert seen[0]["auth"] == "Basic YWRtaW46cHc="
    assert seen[0]["body"] == {"using": ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"],
                               "methodCalls": [["x:Domain/get", {"ids": None}, "c"]]}


def test_create_returns_the_new_object(stalwart_api):
    url, seen, replies = stalwart_api
    replies.append(answer("x:Domain/set", {"created": {"new": {"id": "b7"}}}))

    created = EngineClient(url).create("Domain", {"name": "example.com"})

    assert created == {"id": "b7"}
    assert seen[0]["body"]["methodCalls"][0][1] == {"create": {"new": {"name": "example.com"}}}


def test_a_refused_create_is_an_error(stalwart_api):
    url, _, replies = stalwart_api
    replies.append(answer("x:Domain/set", {"notCreated": {"new": {"type": "invalidProperties", "description": "bad"}}}))

    with pytest.raises(EngineError, match="invalidProperties"):
        EngineClient(url).create("Domain", {})


def test_a_method_error_is_an_error(stalwart_api):
    url, _, replies = stalwart_api
    replies.append(answer("error", {"type": "forbidden"}))

    with pytest.raises(EngineError, match="forbidden"):
        EngineClient(url).get("Domain")


def test_nothing_listening_is_unavailable():
    with pytest.raises(EngineUnavailable):
        EngineClient("http://127.0.0.1:9", timeout=1).get("Domain")


def test_secrets_are_made_once(app):
    with app.app_context():
        first = engine.secret("recovery_password")
        assert engine.secret("recovery_password") == first
        assert len(first) >= 32


def test_an_action_waits_longer_than_a_lookup():
    """Reloading settings rebuilds Stalwart's whole setup: it can take seconds."""
    import time

    class Slow(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            time.sleep(1.5)
            data = json.dumps({"methodResponses": [["x:Action/set", {"created": {"new": {"id": "r1"}}}, "c"]]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        slow = EngineClient(f"http://127.0.0.1:{server.server_port}", timeout=1.0)
        with pytest.raises(EngineUnavailable):
            slow.get("Domain")
        slow.action("ReloadSettings")   # no timeout
    finally:
        server.shutdown()
