# Mail engine, step 1 (sending): implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stalwart runs inside the Someless Mail image, set up and kept in line by the panel, so apps send mail with SMTP keys (only as listed Senders, DKIM-signed) and the admin can send a test email and see it delivered.

**Architecture:**
- **Processes:** a Python supervisor (PID 1 in the container) runs Stalwart and gunicorn side by side.
- **The engine package:** the panel's new `someless.engine` package drives Stalwart through its JMAP management API. It covers first-time setup, an idempotent sync of domains, DKIM, key accounts and allowed senders, the Ready-to-send checks, and delivery reports.
- **Where Stalwart comes from:** our own open-source build (no Enterprise code), published as `ghcr.io/boyoftime/someless-stalwart:<version>` and copied into the main image.

**Tech stack:**
- Python 3.13, Flask 3.1, gunicorn (gthread), SQLite
- Stalwart v0.16.23 (Rust, built without `enterprise`)
- urllib, smtplib and dnspython from the standard library and existing deps; no new Python dependencies
- GitHub Actions: native amd64 and arm64 runners

**Spec:** `docs/superpowers/specs/2026-09-26-mail-engine-sending-design.md`

## Global Constraints

- **Version** stays `1.0.0`: `VERSION` in `app/someless/__init__.py` is not changed.
- **Stalwart pinned** to `v0.16.23`. Built with `--no-default-features --features "rocks"`; never `enterprise`.
- **No root.** Everything in the container runs as uid/gid 2001 after the entrypoint's `chown`; nothing binds a port below 1024.
- **Ports inside the container:**
  - 17080 panel
  - 17587 submission (STARTTLS)
  - 17465 submissions (implicit TLS)
  - 17081 ACME challenge relay only
  - 127.0.0.1:17880 Stalwart HTTP (management, never published)
- **Nothing listens on port 25.**
- **Stalwart's data** lives in `/data/stalwart/` (`config.json`, `db/`).
- **Stalwart's internal domain** is `someless.internal`. The panel's own sending account is `someless-panel`.
- **Key accounts:** one Stalwart account per SMTP key. The password is `{SHA256}` + base64 (with padding) of the key's stored hex digest. The aliases are every Sender address.
- **Key logins:** made from the key name as lowercase ASCII, up to 20 characters, plus `-` and 4 hex characters (e.g. `website-7f3a`); `key-xxxx` when the name has no usable characters.
- **Panel copy** follows the existing voice: plain words, sentence case, no inline form errors (the rope "board" shows problems), the user's own time zone for dates.
- **Commits:** the user commits and pushes with the commands we give at the end; the executor never runs `git commit` or `git push`. Every "Commit" step below is a checkpoint: run the whole test suite and move on.
- **Tests:** `.venv/Scripts/python -m pytest -q` on the dev machine (Windows, no Docker). Live Stalwart tests are opt-in: they need `STALWART_BIN` pointing at a Stalwart v0.16.23 binary (the official Windows build is fine for local testing only; it is never shipped).

## Review Focus

- **Stalwart down or restarting while the admin works.** Every panel page and action still works; changes are saved, a sync retries, and the page says "Mail engine catching up…". Tests: `test_sync_failure_is_kept_and_page_still_works` (Task 3) and `test_smtp_page_without_engine` (Task 5).
- **An SMTP key expires between hourly syncs.** It must stop working at the next sync, and the sync must never recreate an expired key's account. Test: `test_expired_key_account_removed` (Task 3).
- **A domain loses authentication after a re-check** (a DNS record removed). Its Stalwart domain, DKIM key and every alias at it go at the next sync, so no key can send as it. Test: `test_domain_losing_authentication_leaves_engine` (Task 3).
- **A forged delivery report from outside the container** (a `POST /engine/events` on the published port with `X-Forwarded-For: 127.0.0.1`). Must be refused (403) without touching `deliveries`. Test: `test_events_refused_from_outside_even_with_forwarded_header` (Task 6).
- **A test email to an address the remote server rejects at once.** The dialog must show "Bounced" with the remote reply, never stay "Queued" forever. After 60 s without a final event it says "still on its way". Tests: `test_bounce_event_marks_bounced` (Task 6) and `test_test_status_after_timeout` (Task 6).

---

### Task 1: The engine table and the management client

**Files:**
- Create: `app/someless/engine/__init__.py`
- Create: `app/someless/engine/client.py`
- Modify: `app/someless/db.py` (SCHEMA: `engine` table)
- Modify: `tests/conftest.py` (fake engine fixture)
- Create: `tests/engine_fake.py`
- Test: `tests/test_engine_client.py`

**Interfaces:**
- Produces:
  - `someless.engine.INTERNAL_DOMAIN = "someless.internal"`, `PANEL_ACCOUNT = "someless-panel"`, `API_URL = "http://127.0.0.1:17880"`
  - `state() -> sqlite3.Row` (the engine row)
  - `remember(**values) -> None`
  - `secret(name: str) -> str` (made once, then kept)
  - `enabled() -> bool` (`app.config["ENGINE_ENABLED"]`)
  - `client() -> EngineClient-like` (`app.config["ENGINE_CLIENT"]` factory if set, else `EngineClient(API_URL, basic=(state().admin_login, state().admin_password))`)
  - `someless.engine.client`:
    - `EngineClient(base_url, basic=None, token=None, timeout=5.0)` with `.call(method, arguments) -> dict`, `.get(kind, ids=None) -> list[dict]`, `.create(kind, obj) -> dict` (the created object, `id` included), `.update(kind, id_, patch) -> None`, `.destroy(kind, id_) -> None`, `.action(kind) -> None`
    - errors: `EngineUnavailable`, `EngineError`
  - `tests/engine_fake.py`: `FakeEngine` with the same methods, plus `.objects[kind][id]` and `.calls` (list of `(method, kind, payload)`)
  - `conftest.py` fixture `engine(app)`: sets `ENGINE_ENABLED=True` and `ENGINE_CLIENT=lambda: fake`, and yields the `FakeEngine`

- [ ] **Step 1: Write the failing tests** — `tests/test_engine_client.py`

```python
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
        first = engine.secret("admin_password")
        assert engine.secret("admin_password") == first
        assert len(first) >= 32
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_engine_client.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'someless.engine'`

- [ ] **Step 3: Implement.** Add to the `SCHEMA` in `app/someless/db.py` (after the `senders` table):

```sql
-- The mail engine, Stalwart (someless/engine/): how the panel reaches it, and how far its
-- first-time setup and the last sync got
CREATE TABLE IF NOT EXISTS engine (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    recovery_password TEXT,     -- Stalwart's recovery admin, for first-time setup only
    admin_login TEXT,           -- the admin account first-time setup made; the panel's API login
    admin_password TEXT,
    webhook_secret TEXT,        -- signs Stalwart's delivery reports to the panel
    panel_password TEXT,        -- the panel's own sending account (test emails)
    server_name TEXT,           -- chosen by the admin; empty: the default (engine/names.py)
    setup_step TEXT NOT NULL DEFAULT 'new',   -- new, bootstrapped, provisioned, ready
    synced_at REAL,
    sync_error TEXT
);
INSERT OR IGNORE INTO engine (id) VALUES (1);
```

`app/someless/engine/client.py`:

```python
"""Stalwart's management API (v0.16): JMAP over HTTP, one method per call, like
x:Domain/set (https://stalw.art/docs/development/api)."""
import base64
import json
import urllib.error
import urllib.request

USING = ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]


class EngineUnavailable(Exception):
    """Stalwart doesn't answer: not started yet, restarting, or stopped."""


class EngineError(Exception):
    """Stalwart answered, with an error."""


class EngineClient:
    def __init__(self, base_url, basic=None, token=None, timeout=5.0):
        self.url = base_url.rstrip("/") + "/jmap/"
        self.auth = (f"Bearer {token}" if token else
                     "Basic " + base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode() if basic else None)
        self.timeout = timeout

    def call(self, method, arguments):
        body = json.dumps({"using": USING, "methodCalls": [[method, arguments, "c"]]}).encode()
        headers = {"Content-Type": "application/json"}
        if self.auth:
            headers["Authorization"] = self.auth
        request = urllib.request.Request(self.url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                reply = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read()[:300].decode("utf-8", "replace")
            raise EngineError(f"{method}: HTTP {error.code} {detail}") from error
        except OSError as error:  # refused, reset, timed out (URLError is an OSError)
            raise EngineUnavailable(f"{method}: {error}") from error
        name, result, _ = reply["methodResponses"][0]
        if name == "error":
            raise EngineError(f"{method}: {result.get('type')} {result.get('description', '')}".strip())
        return result

    def get(self, kind, ids=None):
        return self.call(f"x:{kind}/get", {"ids": ids})["list"]

    def create(self, kind, obj):
        result = self.call(f"x:{kind}/set", {"create": {"new": obj}})
        if "new" not in (result.get("created") or {}):
            problem = (result.get("notCreated") or {}).get("new", {})
            raise EngineError(f"x:{kind}/set create: {problem.get('type')} {problem.get('description', '')}".strip())
        return result["created"]["new"]

    def update(self, kind, id_, patch):
        result = self.call(f"x:{kind}/set", {"update": {id_: patch}})
        if id_ in (result.get("notUpdated") or {}):
            problem = result["notUpdated"][id_]
            raise EngineError(f"x:{kind}/set update: {problem.get('type')} {problem.get('description', '')}".strip())

    def destroy(self, kind, id_):
        result = self.call(f"x:{kind}/set", {"destroy": [id_]})
        if id_ in (result.get("notDestroyed") or {}):
            problem = result["notDestroyed"][id_]
            raise EngineError(f"x:{kind}/set destroy: {problem.get('type')} {problem.get('description', '')}".strip())

    def action(self, kind):
        """Ask Stalwart to do something now, like ReloadSettings."""
        self.create("Action", {"@type": kind})
```

`app/someless/engine/__init__.py`:

```python
"""The mail engine: Stalwart, running beside the panel in the same container. The panel
sets it up (setup.py), keeps it in line with what the admin set here (sync.py), checks it's
ready to send (checks.py) and follows the mail it sends (deliveries.py).
Design: docs/superpowers/specs/2026-09-26-mail-engine-sending-design.md"""
import secrets

from flask import current_app

from ..db import get_db
from .client import EngineClient, EngineError, EngineUnavailable  # noqa: F401 (the package's API)

INTERNAL_DOMAIN = "someless.internal"  # Stalwart's own default domain; the key accounts live in it
PANEL_ACCOUNT = "someless-panel"       # the panel's own sending account (test emails)
API_URL = "http://127.0.0.1:17880"


def enabled():
    """Whether a mail engine runs beside this panel (in the container; not on a dev machine)."""
    return bool(current_app.config.get("ENGINE_ENABLED"))


def state():
    return get_db().execute("SELECT * FROM engine WHERE id = 1").fetchone()


def remember(**values):
    db = get_db()
    db.execute("UPDATE engine SET " + ", ".join(f"{name} = ?" for name in values) + " WHERE id = 1",
               tuple(values.values()))
    db.commit()


def secret(name):
    """A secret kept in the engine table, made the first time it's needed."""
    value = state()[name]
    if not value:
        value = secrets.token_urlsafe(32)
        remember(**{name: value})
    return value


def client():
    """The management client. The test suite puts a fake in ENGINE_CLIENT."""
    factory = current_app.config.get("ENGINE_CLIENT")
    if factory:
        return factory()
    row = state()
    return EngineClient(current_app.config.get("ENGINE_URL", API_URL), basic=(row["admin_login"], row["admin_password"]))
```

In `app/someless/__init__.py` `create_app`, set the default before `test_config` is applied: `ENGINE_ENABLED=os.environ.get("SOMELESS_ENGINE") == "1"` in `app.config.from_mapping(...)`.

`tests/engine_fake.py`:

```python
"""A made-up Stalwart for tests: its objects live in dicts, and every call is noted."""
import itertools

from someless.engine.client import EngineError


class FakeEngine:
    def __init__(self):
        self.objects = {}   # kind -> {id: object}
        self.calls = []     # (method, kind, payload)
        self.down = False
        self._ids = itertools.count(1)

    def _check(self):
        if self.down:
            from someless.engine.client import EngineUnavailable
            raise EngineUnavailable("fake engine is down")

    def get(self, kind, ids=None):
        self._check()
        self.calls.append(("get", kind, ids))
        found = self.objects.get(kind, {})
        return [dict(obj, id=id_) for id_, obj in found.items() if ids is None or id_ in ids]

    def create(self, kind, obj):
        self._check()
        self.calls.append(("create", kind, obj))
        id_ = f"{kind[0].lower()}{next(self._ids)}"
        self.objects.setdefault(kind, {})[id_] = dict(obj)
        return {"id": id_}

    def update(self, kind, id_, patch):
        self._check()
        self.calls.append(("update", kind, {id_: patch}))
        if id_ not in self.objects.get(kind, {}):
            raise EngineError(f"x:{kind}/set update: notFound")
        self.objects[kind][id_].update(patch)

    def destroy(self, kind, id_):
        self._check()
        self.calls.append(("destroy", kind, id_))
        self.objects.get(kind, {}).pop(id_, None)

    def action(self, kind):
        self._check()
        self.calls.append(("action", kind, None))

    def named(self, kind, name):
        """The object of this kind with this name (tests)."""
        return next((dict(obj, id=id_) for id_, obj in self.objects.get(kind, {}).items() if obj.get("name") == name), None)
```

Add to `tests/conftest.py`:

```python
from engine_fake import FakeEngine


@pytest.fixture
def engine(app):
    """A made-up mail engine beside the panel (tests that need one)."""
    fake = FakeEngine()
    fake.objects["Domain"] = {"d0": {"name": "someless.internal"}}
    fake.objects["Account"] = {"a0": {"name": "admin", "domainId": "d0"}}
    fake.objects["SystemSettings"] = {"singleton": {"defaultHostname": "someless.internal"}}
    app.config.update(ENGINE_ENABLED=True, ENGINE_CLIENT=lambda: fake)
    return fake
```

(`tests` is on `sys.path` through pytest's rootdir conftest, so `from engine_fake import FakeEngine` works. If it doesn't, add `pythonpath = ["tests"]` to the pytest config in `pyproject.toml` or `pytest.ini`, whichever the repo uses.)

- [ ] **Step 4: Run the tests and see them pass**

Run: `.venv/Scripts/python -m pytest -q tests/test_engine_client.py` → PASS; then the whole suite → all pass.

- [ ] **Step 5: Commit** (checkpoint: whole suite green)

---

### Task 2: Running Stalwart and its first-time setup (the spike lives here)

**Files:**
- Create: `app/someless/engine/process.py`
- Create: `app/someless/engine/setup.py`
- Test: `tests/test_engine_setup.py`
- Test: `tests/test_engine_live.py` (opt-in, with a real binary)

**Interfaces:**
- Consumes: Task 1's `EngineClient`, `state()`, `remember()`, `secret()`.
- Produces:
  - `Stalwart(binary, data_dir, http_port=17880)` with `.start(mode, recovery_password=None)` (mode: `"bootstrap"`, `"recovery"` or `"normal"`), `.stop(timeout=15)`, `.running() -> bool` and `.wait_until_up(timeout=60) -> None` (raises `EngineUnavailable`)
  - `setup.run(stalwart) -> None` (app context required; idempotent; ends with Stalwart running normally and `setup_step == "ready"`)
  - `setup.LISTENERS` (the three listeners)

**Spike first (Step 1).** Before writing tests, run the real Stalwart v0.16.23 on this machine and confirm the research's claims. Record what's true in the spec's "To verify first" list: mark each ✓, or write what differs.

- [ ] **Step 1: Spike with the real binary (throwaway script in the scratchpad)**

Download `stalwart-x86_64-pc-windows-msvc.zip` from https://github.com/stalwartlabs/stalwart/releases/tag/v0.16.23 into the scratchpad and unzip it. Then write `scratchpad/spike_stalwart.py`:

```python
"""Throwaway: does Stalwart v0.16.23 behave as the research says? Prints each finding."""
import json, os, subprocess, sys, time, urllib.request, base64, pathlib, shutil

BIN = sys.argv[1]
DATA = pathlib.Path(sys.argv[2]); shutil.rmtree(DATA, ignore_errors=True); DATA.mkdir(parents=True)
CONFIG = DATA / "config.json"
ADMIN = "recovery-pass-123456789"

def start(extra):
    env = {**os.environ, "CONFIG_PATH": str(CONFIG), "STALWART_RECOVERY_MODE_PORT": "17880",
           "STALWART_RECOVERY_ADMIN": f"admin:{ADMIN}", **extra}
    return subprocess.Popen([BIN, "--config", str(CONFIG)], env=env, cwd=DATA)

def call(method, args, auth=("admin", ADMIN)):
    body = json.dumps({"using": ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"], "methodCalls": [[method, args, "c"]]}).encode()
    request = urllib.request.Request("http://127.0.0.1:17880/jmap/", data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()})
    return json.load(urllib.request.urlopen(request, timeout=10))["methodResponses"][0]

def wait():
    for _ in range(60):
        try:
            urllib.request.urlopen("http://127.0.0.1:17880/jmap/session", timeout=2); return
        except urllib.error.HTTPError: return   # answering (401 is fine)
        except OSError: time.sleep(1)
    raise SystemExit("never came up")

p = start({}); wait()
print("bootstrap get:", call("x:Bootstrap/get", {"ids": ["singleton"]}))
print("bootstrap set:", call("x:Bootstrap/set", {"update": {"singleton": {
    "serverHostname": "someless.internal", "defaultDomain": "someless.internal",
    "requestTlsCertificate": False, "generateDkimKeys": False,
    "dataStore": {"@type": "RocksDb", "path": str(DATA / "db")}}}}))
p.terminate(); p.wait()
print("config.json:", CONFIG.read_text())
p = start({"STALWART_RECOVERY_MODE": "1"}); wait()
schema = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:17880/api/schema", headers={
    "Authorization": "Basic " + base64.b64encode(f"admin:{ADMIN}".encode()).decode()})).read()
(DATA / "schema.json").write_bytes(schema)
print("schema saved; object names containing 'isten':", sorted({k for k in json.loads(schema).get("objects", {}) if "isten" in k.lower()}) if schema.startswith(b"{") else schema[:200])
```

Run it: `.venv/Scripts/python scratchpad/spike_stalwart.py scratchpad/stalwart-win/stalwart.exe scratchpad/spike-data`. From its output and `schema.json`, write down the facts below. Extend the script and rerun until each one is answered. Each later step uses these facts.

1. the exact object name for listeners, and its fields for `bind`, `protocol`, `useTls` and `tlsImplicit`
2. whether listeners can be created in recovery mode, and whether a normal start then skips creating the defaults
3. which login `x:Bootstrap/set` returns (`updated.singleton.username`, `secret`), and that Basic auth with it works in normal mode
4. the Account object's fields for `name`, `domainId`, `credentials` and `aliases`
5. a `{SHA256}` password logging in over SMTP AUTH on 17587, with a bare login
6. `mustMatchSender` refusing a MAIL FROM that isn't an alias, and whether a DKIM-Signature appears on queued mail (`x:QueuedMessage/get`)
7. the WebHook object's fields (URL, event types, how it signs: header name and scheme) and the JSON Stalwart posts (use a tiny local HTTP server that prints request bodies)
8. the DATA reply text (`250 2.0.0 Message queued with id …`)

- [ ] **Step 2: Write the failing tests** — `tests/test_engine_setup.py`. These use a fake process, so no binary is needed.

```python
import pytest

from someless import engine as engine_module
from someless.engine import setup


class FakeProcess:
    """Stands in for Stalwart: records how it's started; the fake API answers meanwhile."""
    def __init__(self):
        self.starts = []

    def start(self, mode, recovery_password=None):
        self.starts.append((mode, bool(recovery_password)))

    def stop(self, timeout=15):
        self.starts.append(("stop", None))

    def wait_until_up(self, timeout=60):
        pass

    def running(self):
        return True


def test_first_setup_bootstraps_provisions_and_starts_normally(app, engine, monkeypatch):
    engine.objects["Bootstrap"] = {"singleton": {}}
    monkeypatch.setattr(setup, "admin_client", lambda: engine)   # the recovery admin's client
    engine.bootstrap_reply = {"username": "admin@someless.internal", "secret": "made-by-stalwart"}
    process = FakeProcess()
    with app.app_context():
        setup.run(process)
        row = engine_module.state()
    assert [mode for mode, _ in process.starts] == ["bootstrap", "stop", "recovery", "stop", "normal"]
    assert (row["admin_login"], row["admin_password"]) == ("admin@someless.internal", "made-by-stalwart")
    assert row["setup_step"] == "ready"
    listeners = sorted(obj["name"] for obj in engine.objects["Listener"].values())
    assert listeners == ["http", "submission", "submissions"]


def test_setup_resumes_where_it_stopped(app, engine, monkeypatch):
    monkeypatch.setattr(setup, "admin_client", lambda: engine)
    process = FakeProcess()
    with app.app_context():
        engine_module.remember(setup_step="provisioned")
        setup.run(process)
    assert [mode for mode, _ in process.starts] == ["normal"]


def test_listeners_never_use_privileged_ports():
    for listener in setup.LISTENERS:
        for address in listener["bind"]:
            assert int(address.rsplit(":", 1)[1]) > 1024
```

(The `engine` fixture shadows the module's name, hence `engine_module`. `FakeEngine` answers `call("x:Bootstrap/set", ...)` with `{"updated": {"singleton": fake.bootstrap_reply}}`: add a `call` method to `FakeEngine` in Task 1's fake: `def call(self, method, arguments): self.calls.append(("call", method, arguments)); return {"updated": {"singleton": self.bootstrap_reply}}` and `self.bootstrap_reply = {}` in `__init__`.)

- [ ] **Step 3: Run them and see them fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_engine_setup.py` → FAIL (no `someless.engine.setup`)

- [ ] **Step 4: Implement** `app/someless/engine/process.py`:

```python
"""The Stalwart process: started, stopped and watched by the supervisor (and the live tests).
Its modes: bootstrap (first start, no config.json yet), recovery (management only, used once
to set it up) and normal."""
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .client import EngineUnavailable


class Stalwart:
    def __init__(self, binary, data_dir, http_port=17880):
        self.binary = str(binary)
        self.data_dir = Path(data_dir)
        self.config = self.data_dir / "config.json"
        self.http_port = http_port
        self.process = None

    def start(self, mode="normal", recovery_password=None):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "CONFIG_PATH": str(self.config)}
        if mode in ("bootstrap", "recovery"):
            env["STALWART_RECOVERY_MODE_PORT"] = str(self.http_port)
            env["STALWART_RECOVERY_ADMIN"] = f"admin:{recovery_password}"
        if mode == "recovery":
            env["STALWART_RECOVERY_MODE"] = "1"
        self.process = subprocess.Popen([self.binary, "--config", str(self.config)], env=env, cwd=self.data_dir)

    def running(self):
        return self.process is not None and self.process.poll() is None

    def stop(self, timeout=15):
        if not self.running():
            return
        self.process.terminate()
        try:
            self.process.wait(timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def wait_until_up(self, timeout=60):
        """Until its HTTP side answers (any answer; 401 included)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.running():
                raise EngineUnavailable(f"Stalwart exited with {self.process.returncode}")
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.http_port}/jmap/session", timeout=2)
                return
            except urllib.error.HTTPError:
                return
            except OSError:
                time.sleep(0.5)
        raise EngineUnavailable("Stalwart didn't come up in time")
```

`app/someless/engine/setup.py`. Replace the object and field names marked `# spike` with the facts from Step 1, if they differ.

```python
"""First-time setup of Stalwart, done by the supervisor before the panel starts: it happens
once, and picks up where it left off if interrupted (the engine table's setup_step).
new -> bootstrap mode: Bootstrap/set writes config.json and makes the admin account
bootstrapped -> recovery mode: our listeners (high ports, no port 25)
provisioned -> a normal start
"""
from pathlib import Path

from . import API_URL, INTERNAL_DOMAIN, remember, secret, state
from .client import EngineClient

# Nothing below 1024: Stalwart runs as the app's own user, not root. Nothing on port 25:
# receiving mail comes later.
LISTENERS = [  # spike: object and field names
    {"name": "submission", "protocol": "smtp", "bind": {"[::]:17587": True}},
    {"name": "submissions", "protocol": "smtp", "bind": {"[::]:17465": True}, "tlsImplicit": True},
    {"name": "http", "protocol": "http", "bind": {"127.0.0.1:17880": True}, "useTls": False},
]


def admin_client():
    """Stalwart's recovery admin, which first-time setup signs in as."""
    return EngineClient(API_URL, basic=("admin", secret("recovery_password")), timeout=20)


def run(stalwart):
    step = state()["setup_step"]
    if step == "new":
        stalwart.start("bootstrap", secret("recovery_password"))
        stalwart.wait_until_up()
        updated = admin_client().call("x:Bootstrap/set", {"update": {"singleton": {
            "serverHostname": INTERNAL_DOMAIN, "defaultDomain": INTERNAL_DOMAIN,
            "requestTlsCertificate": False, "generateDkimKeys": False,
            "dataStore": {"@type": "RocksDb", "path": str(Path(stalwart.data_dir) / "db")},
        }}})["updated"]["singleton"]   # spike: where the made admin login and password come back
        remember(admin_login=updated["username"], admin_password=updated["secret"], setup_step="bootstrapped")
        stalwart.stop()
        step = "bootstrapped"
    if step == "bootstrapped":
        stalwart.start("recovery", secret("recovery_password"))
        stalwart.wait_until_up()
        client = admin_client()
        existing = {listener["name"] for listener in client.get("Listener")}
        for listener in LISTENERS:
            if listener["name"] not in existing:
                client.create("Listener", listener)
        remember(setup_step="provisioned")
        stalwart.stop()
    stalwart.start("normal")
    stalwart.wait_until_up()
    remember(setup_step="ready")
```

- [ ] **Step 5: Run the tests and see them pass.** Whole suite green.

- [ ] **Step 6: Live test (opt-in)** — `tests/test_engine_live.py`. It grows in Tasks 3 and 6.

```python
"""Against a real Stalwart v0.16.23 (set STALWART_BIN to its binary). Skipped otherwise."""
import os

import pytest

from someless import engine as engine_module
from someless.engine import setup
from someless.engine.process import Stalwart

pytestmark = pytest.mark.skipif(not os.environ.get("STALWART_BIN"), reason="set STALWART_BIN to run against Stalwart")


@pytest.fixture
def live(app, tmp_path):
    stalwart = Stalwart(os.environ["STALWART_BIN"], tmp_path / "stalwart")
    app.config.update(ENGINE_ENABLED=True)
    with app.app_context():
        setup.run(stalwart)
        yield stalwart
    stalwart.stop()


def test_first_setup_leaves_it_running_with_our_listeners(app, live):
    with app.app_context():
        assert engine_module.state()["setup_step"] == "ready"
        names = {listener["name"] for listener in engine_module.client().get("Listener")}
    assert {"submission", "submissions", "http"} <= names
    import socket
    socket.create_connection(("127.0.0.1", 17587), timeout=5).close()
```

Run: `STALWART_BIN=<path to stalwart.exe> .venv/Scripts/python -m pytest -q tests/test_engine_live.py` → PASS.

- [ ] **Step 7: Commit** (checkpoint)

---

### Task 3: Sync (domains, DKIM keys, key accounts, allowed senders)

**Files:**
- Create: `app/someless/engine/sync.py`
- Modify: `app/someless/domains.py` (sync after a check changes authentication, and after a delete)
- Modify: `app/someless/smtp.py` (sync after a key is made or deleted)
- Modify: `app/someless/senders.py` (sync after add, edit, delete)
- Test: `tests/test_engine_sync.py`, extend `tests/test_engine_live.py`

**Interfaces:**
- Consumes: Task 1 `client()`, `remember()`, `secret()`, `enabled()`, `INTERNAL_DOMAIN`, `PANEL_ACCOUNT`.
- Produces:
  - `sha256_secret(hex_digest: str) -> str`
  - `desired_state() -> dict` with `domains: {name: private_pem}`, `accounts: {login: secret}`, `senders: [email]`
  - `reconcile(client, desired) -> list[str]` (the changes made, like `"create Domain example.com"`)
  - `run() -> bool` (never raises; records `synced_at` or `sync_error`)
  - `after_change() -> None` (the views call it: runs `run()` when `enabled()`)

- [ ] **Step 1: Write the failing tests** — `tests/test_engine_sync.py`

```python
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
    assert engine.named("Account", "website-7f3a")["aliases"] == {}


def test_each_key_is_an_account_that_may_send_as_the_senders(app, engine):
    domain_id = authenticated_domain(app)
    a_sender(app, domain_id, "no-reply@pineloop.online")
    a_sender(app, domain_id, "news@pineloop.online")
    a_key(app)

    sync_now(app)

    account = engine.named("Account", "website-7f3a")
    assert account["credentials"] == {"0": {"@type": "Password", "secret": sync.sha256_secret(hashlib.sha256(KEY.encode()).hexdigest())}}
    assert account["domainId"] == "d0"   # someless.internal
    domain = engine.named("Domain", "pineloop.online")["id"]
    assert sorted(alias["name"] for alias in account["aliases"].values()) == ["news", "no-reply"]
    assert {alias["domainId"] for alias in account["aliases"].values()} == {domain}


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

    account = engine.named("Account", "someless-panel")
    assert [alias["name"] for alias in account["aliases"].values()] == ["no-reply"]


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
    domain_id = authenticated_domain(app)
    login()

    client.post("/senders", data={"name": "PineLoop", "email": "hello@pineloop.online"})

    assert engine.named("Account", "someless-panel")["aliases"]
```

- [ ] **Step 2: Run them and see them fail** — `.venv/Scripts/python -m pytest -q tests/test_engine_sync.py` → FAIL (no `sync`)

- [ ] **Step 3: Implement** `app/someless/engine/sync.py`:

```python
"""Keeping Stalwart in line with the panel: the panel is where the admin changes anything;
Stalwart gets what it needs to send. A sync reads what Stalwart has, works out what it
should have, and makes only the difference, so running it again changes nothing.
Someless owns its Stalwart: every Domain but someless.internal and every Account but admin is
the panel's to make and remove."""
import base64
import contextlib
import threading
import time
from pathlib import Path

from flask import current_app

from ..db import get_db
from . import INTERNAL_DOMAIN, PANEL_ACCOUNT, client, enabled, remember, secret
from .client import EngineError, EngineUnavailable

MANUAL = {"@type": "Manual"}
_thread_lock = threading.Lock()


def sha256_secret(hex_digest):
    """A password as Stalwart takes it pre-hashed: {SHA256} and the digest in base64."""
    return "{SHA256}" + base64.b64encode(bytes.fromhex(hex_digest)).decode()


def desired_state():
    db = get_db()
    domains = {row["name"]: row["dkim_private"] for row in db.execute(
        "SELECT domains.name, domain_keys.dkim_private FROM domains JOIN domain_keys ON domain_keys.domain_id = domains.id"
        " WHERE domains.authenticated = 1")}
    senders = [row["email"] for row in db.execute(
        "SELECT senders.email FROM senders JOIN domains ON domains.id = senders.domain_id WHERE domains.authenticated = 1"
        " ORDER BY senders.email")]
    now = time.time()
    accounts = {row["login"]: sha256_secret(row["key_hash"]) for row in db.execute(
        "SELECT login, key_hash FROM smtp_keys WHERE expires_at IS NULL OR expires_at > ?", (now,))}
    import hashlib
    accounts[PANEL_ACCOUNT] = sha256_secret(hashlib.sha256(secret("panel_password").encode()).hexdigest())
    return {"domains": domains, "accounts": accounts, "senders": senders}


def reconcile(engine, desired):
    done = []
    domains = {obj["name"]: obj for obj in engine.get("Domain")}
    internal_id = domains[INTERNAL_DOMAIN]["id"]
    # domains: every authenticated one, and no other (someless.internal aside)
    for name in desired["domains"]:
        if name not in domains:
            domains[name] = {"name": name, **engine.create("Domain", {
                "name": name, "dkimManagement": MANUAL, "certificateManagement": MANUAL, "dnsManagement": MANUAL})}
            done.append(f"create Domain {name}")
    signatures = engine.get("DkimSignature")
    for name, obj in list(domains.items()):
        if name != INTERNAL_DOMAIN and name not in desired["domains"]:
            for signature in signatures:
                if signature["domainId"] == obj["id"]:
                    engine.destroy("DkimSignature", signature["id"])
            engine.destroy("Domain", obj["id"])
            del domains[name]
            done.append(f"destroy Domain {name}")
    # each domain's DKIM key: the one already published in its DNS
    signed = {(signature["domainId"], signature["selector"]) for signature in engine.get("DkimSignature")}
    for name, pem in desired["domains"].items():
        if (domains[name]["id"], "someless") not in signed:
            engine.create("DkimSignature", {"@type": "Dkim1RsaSha256", "domainId": domains[name]["id"], "selector": "someless",
                                            "privateKey": {"@type": "Text", "secret": pem}})
            done.append(f"create DkimSignature {name}")
    # accounts: one per key (and the panel's), each allowed to send as every Sender
    aliases = {}
    for index, email in enumerate(desired["senders"]):
        local, domain = email.rsplit("@", 1)
        if domain in domains:
            aliases[str(index)] = {"name": local, "domainId": domains[domain]["id"], "enabled": True}
    accounts = {obj["name"]: obj for obj in engine.get("Account") if obj.get("domainId") == internal_id and obj["name"] != "admin"}
    for login, password in desired["accounts"].items():
        if login not in accounts:
            engine.create("Account", {"@type": "User", "name": login, "domainId": internal_id,
                                      "roles": {"@type": "User"}, "permissions": {"@type": "Inherit"},
                                      "encryptionAtRest": {"@type": "Disabled"},
                                      "credentials": {"0": {"@type": "Password", "secret": password}},
                                      "aliases": aliases})
            done.append(f"create Account {login}")
        elif _alias_set(accounts[login].get("aliases")) != _alias_set(aliases):
            engine.update("Account", accounts[login]["id"], {"aliases": aliases})
            done.append(f"update Account {login}")
    for login, obj in accounts.items():
        if login not in desired["accounts"]:
            engine.destroy("Account", obj["id"])
            done.append(f"destroy Account {login}")
    if done:
        engine.action("ReloadSettings")
    return done


def _alias_set(aliases):
    return {(alias["name"], alias["domainId"]) for alias in (aliases or {}).values()}


@contextlib.contextmanager
def _lock():
    """One sync at a time: across gunicorn's workers and the hourly one (a file lock), and
    within a process (a thread lock)."""
    path = Path(current_app.config["DATA_DIR"]) / "engine.lock"
    with _thread_lock, open(path, "a") as handle:
        try:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        except ImportError:   # Windows (development): the thread lock is enough
            pass
        yield


def run():
    """Bring Stalwart in line. Never raises: a failure is kept for the page, and the next sync
    (after the next change, or the hourly one) tries again."""
    try:
        with _lock():
            done = reconcile(client(), desired_state())
    except (EngineUnavailable, EngineError, KeyError) as error:
        remember(sync_error=str(error))
        current_app.logger.warning("mail engine sync failed: %s", error)
        return False
    remember(synced_at=time.time(), sync_error=None)
    if done:
        current_app.logger.info("mail engine sync: %s", "; ".join(done))
    return True


def after_change():
    """What the views call after a change the engine needs to know about."""
    if enabled():
        run()
```

Wire the triggers:
- `domains.py`: after `domain_records.save(...)` in `check()`, and in `authenticate()` when the look re-checked (results saved), and after the delete, call `engine_sync.after_change()` (`from .engine import sync as engine_sync`).
- `smtp.py`: after the key insert in `generate()` and after the delete.
- `senders.py`: after `add`, `update` and `delete` commits.

Move the `import hashlib` in `desired_state` to the module's imports (it's inline above only to keep the snippet short).

- [ ] **Step 4: Run and pass.** Whole suite green.

- [ ] **Step 5: Live checks** — extend `tests/test_engine_live.py` with a test that sends on 17587. A fresh Stalwart has no certificate yet, so use an unverified TLS context.

```python
import smtplib
import ssl


def test_a_key_sends_as_a_sender_only(app, live):
    from someless.db import get_db
    from someless.engine import sync
    import hashlib, time
    with app.app_context():
        db = get_db()
        domain_id = db.execute("INSERT INTO domains (name, authenticated, added_at) VALUES ('example.com', 1, 0)").lastrowid
        from someless.domain_records import new_keys
        keys = new_keys()
        db.execute("INSERT INTO domain_keys (domain_id, code, dkim_selector, dkim_private, dkim_public) VALUES (?, ?, 'someless', ?, ?)",
                   (domain_id, keys["code"], keys["dkim_private"], keys["dkim_public"]))
        db.execute("INSERT INTO senders (name, email, domain_id, created_at) VALUES ('Shop', 'shop@example.com', ?, 0)", (domain_id,))
        db.execute("INSERT INTO smtp_keys (name, key_hash, hint, variant, created_at, login) VALUES ('Live', ?, 'xxxx', 'standard', ?, 'live-0001')",
                   (hashlib.sha256(b"live-key-0123456789").hexdigest(), time.time()))
        db.commit()
        assert sync.run()
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
```

Run it with `STALWART_BIN` set → PASS.

- [ ] **Step 6: Commit** (checkpoint)

---

### Task 4: One login per SMTP key

**Files:**
- Create: `app/someless/logins.py`
- Modify: `app/someless/db.py` (`LATER_COLUMNS`: `("smtp_keys", "login", "TEXT")`, then fill logins for rows without one)
- Modify: `app/someless/smtp.py` (a login on create; `login` in the page's keys)
- Modify: `app/someless/templates/smtp.html` (key dialog, keys table, settings card)
- Modify: `app/someless/smtp_guide.py` and `app/someless/templates/smtp-docs.html` (`SOMELESS_SMTP_LOGIN`)
- Test: `tests/test_smtp.py` (update and add)

**Interfaces:**
- Produces: `someless.logins.make_login(name: str, taken: set[str]) -> str`

- [ ] **Step 1: Write the failing tests** (add to `tests/test_smtp.py`; update the old assertions as noted)

```python
from someless.logins import make_login


def test_logins_are_made_from_the_key_name():
    assert re.fullmatch(r"website-[0-9a-f]{4}", make_login("Website", set()))
    assert re.fullmatch(r"my-shop-2026-[0-9a-f]{4}", make_login("My Shop 2026!", set()))
    assert re.fullmatch(r"unicode-[0-9a-f]{4}", make_login("Ünïcödé ✨", set()))
    assert re.fullmatch(r"key-[0-9a-f]{4}", make_login("✨✨", set()))
    assert len(make_login("a" * 50, set())) == 25


def test_a_new_key_comes_with_its_own_login(client, login, app):
    login()

    page = text(generate(client))

    row = keys_in_db(app)[0]
    assert re.fullmatch(r"website-[0-9a-f]{4}", row["login"])
    dialog = page[page.index('id="key-dialog"'):]
    assert f'data-copy="{row["login"]}"' in dialog     # copied with its own button
    assert row["login"] in plain(text(client.get("/smtp")))  # and listed with the key


def test_keys_from_before_get_a_login(tmp_path):
    import sqlite3
    from someless import create_app
    with sqlite3.connect(tmp_path / "someless.db") as db:
        db.execute("CREATE TABLE smtp_keys (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, key_hash TEXT NOT NULL,"
                   " hint TEXT NOT NULL, variant TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL)")
        db.execute("INSERT INTO smtp_keys (name, key_hash, hint, variant, created_at) VALUES ('Old app', 'h', 'xxxx', 'standard', 0)")

    create_app({"TESTING": True, "DATA_DIR": str(tmp_path)})

    with sqlite3.connect(tmp_path / "someless.db") as db:
        (login,) = db.execute("SELECT login FROM smtp_keys").fetchone()
    assert re.fullmatch(r"old-app-[0-9a-f]{4}", login)
```

Update `test_the_smtp_settings_say_how_to_connect`: the page no longer shows the old `smtp_settings` login. Assert `"The login of the key you use" in page`, and drop the `login_name` assertions.

Update `test_the_guide_shows_six_languages_with_these_settings`: replace `login_name in code` with `"SOMELESS_SMTP_LOGIN" in code`.

- [ ] **Step 2: Run and fail.**

- [ ] **Step 3: Implement.** `app/someless/logins.py`:

```python
"""Logins for SMTP keys: made from the key's name, so an app's settings say which key it uses
(website-7f3a). Stalwart allows one password per login, so each key has its own."""
import re
import secrets
import unicodedata


def make_login(name, taken):
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    stem = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:20].strip("-") or "key"
    while True:
        login = f"{stem}-{secrets.token_hex(2)}"
        if login not in taken:
            return login
```

`db.py`: add `("smtp_keys", "login", "TEXT")` to `LATER_COLUMNS`, and after `_add_later_columns(db)` call `_fill_key_logins(db)`:

```python
def _fill_key_logins(db):
    """Keys made before each had a login get one (logins.py)."""
    from .logins import make_login
    taken = {row[0] for row in db.execute("SELECT login FROM smtp_keys WHERE login IS NOT NULL")}
    for key_id, name in db.execute("SELECT id, name FROM smtp_keys WHERE login IS NULL").fetchall():
        login = make_login(name, taken)
        taken.add(login)
        db.execute("UPDATE smtp_keys SET login = ? WHERE id = ?", (login, key_id))
    db.commit()
```

Add `login TEXT` to the `smtp_keys` CREATE TABLE in `SCHEMA` for new databases too.

`smtp.py`:
- `generate()`: `login = make_login(typed["name"], {row[0] for row in db.execute("SELECT login FROM smtp_keys")})`, inserted with the key. Pass `new_login=login` to `_page`.
- `_page()`: add `"login": row["login"]` to each key.
- `docs()`: pass no login to `smtp_guide.examples` (next bullet).

`smtp.html`:
- **Settings card:** replace the Login row with `<dt>Login</dt><dd><span class="dns-box is-placeholder">The login of the key you use</span><span class="dns-full">Each key has its own, shown with it below.</span></dd>`.
- **Keys table:** add a `Login` column between Key and Created: `<td>{{ copy_box(key.login, "Copy the login") }}</td>`. Add `{% from "copy-box.html" import copy_box %}` if it isn't already imported, and set the "No keys match" row's `colspan` to 7.
- **Key dialog:** above the key's field, add `<div class="field"><span class="field-label">Login</span>{{ copy_box(new_login, "Copy the login") }}</div>`. Change the hint under the key to "Use them together: the login, and this key as the password."

`smtp_guide.py`:
- Replace every `"@LOGIN@"` with each language's read of `SOMELESS_SMTP_LOGIN`, the way each example already reads `SOMELESS_SMTP_KEY`:
  - Python: `os.environ["SOMELESS_SMTP_LOGIN"]`
  - Node: `process.env.SOMELESS_SMTP_LOGIN`
  - PHP: `getenv("SOMELESS_SMTP_LOGIN")`
  - Java: `System.getenv("SOMELESS_SMTP_LOGIN")`
  - C#: `Environment.GetEnvironmentVariable("SOMELESS_SMTP_LOGIN")`
  - Go: `os.Getenv("SOMELESS_SMTP_LOGIN")`
- Remove `("@LOGIN@", login)` from `examples()`, and its `login` parameter.

`smtp-docs.html`:
- **Settings card, Login row:** "The login of your key (on SMTP & API)".
- **Password row:** "Your SMTP key".
- **"Keep the key out of your code":** now mentions both variables.
- **In apps and plugins, Username row:** "The login of your key".

- [ ] **Step 4: Run and pass.** Whole suite green.

- [ ] **Step 5: Commit** (checkpoint)

---

### Task 5: Server name, certificate, Ready-to-send checklist, challenge relay

**Files:**
- Create: `app/someless/engine/names.py`
- Create: `app/someless/engine/checks.py`
- Modify: `app/someless/engine/sync.py` (server name, ACME, default certificate)
- Modify: `app/someless/smtp.py` (the checklist; a server name picker; the SMTP server shown)
- Modify: `app/someless/templates/smtp.html` (the checklist card replaces `.smtp-note`)
- Modify: `app/someless/static/css/style.css` (checklist styles)
- Test: `tests/test_engine_checks.py`, add to `tests/test_engine_sync.py` and `tests/test_smtp.py`

**Interfaces:**
- Consumes: `sync.reconcile`, `client()`, `state()`, `remember()`; `domain_records.server_address(host)`; `HOST_CHOICES`.
- Produces:
  - `names.server_names() -> list[str]` (each authenticated domain's `<mail_host>.<domain>`, sorted by domain)
  - `names.server_name() -> str | None` (the chosen one if still valid, else the first, else None)
  - `checks.Check = namedtuple("Check", "key title state detail")` (state: `"ok"`, `"missing"` or `"warning"`)
  - `checks.run_checks(address) -> list[Check]`, `checks.can_send(checks) -> bool`
  - probes to monkeypatch in tests: `checks.port25_open() -> bool`, `checks.reverse_name(ip) -> str | None`, `checks.addresses_of(name) -> list[str]`
  - `desired_state()` gains `server_name`
  - `reconcile` also sets `SystemSettings.defaultHostname`, keeps one `AcmeProvider` (`Http01`), sets `certificateManagement: Automatic` on the server name's domain with that one name, and sets `SystemSettings.defaultCertificateId` once a matching `Certificate` exists
  - route `POST /smtp/server-name` (form field `server_name`)

- [ ] **Step 1: Failing tests** — `tests/test_engine_checks.py`

```python
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
```

Add to `tests/test_engine_sync.py`:

```python
def test_the_server_name_gets_its_certificate(app, engine):
    authenticated_domain(app)

    sync_now(app)

    domain = engine.named("Domain", "pineloop.online")
    provider = next(iter(engine.objects["AcmeProvider"]))
    assert domain["certificateManagement"] == {"@type": "Automatic", "acmeProviderId": provider,
                                               "subjectAlternativeNames": {"mail.pineloop.online": True}}
    assert engine.objects["SystemSettings"]["singleton"]["defaultHostname"] == "mail.pineloop.online"
    assert engine.objects["AcmeProvider"][provider]["challengeType"] == "Http01"
```

Add to `tests/test_smtp.py`:

```python
def test_smtp_page_without_engine(client, login):
    login()
    page = plain(text(client.get("/smtp")))
    assert "Ready to send" in page and "mail engine isn't running here" in page
```

- [ ] **Step 2: Run and fail.**

- [ ] **Step 3: Implement** `engine/names.py`:

```python
"""The server's name: what it greets other servers with, its certificate is for, apps connect
to, and its reverse DNS should say. One of the authenticated domains' mail names."""
from ..db import get_db
from ..domain_records import HOST_CHOICES
from . import state


def server_names():
    return [f"{row['mail_host'] or HOST_CHOICES[0]}.{row['name']}" for row in get_db().execute(
        "SELECT domains.name, domain_keys.mail_host FROM domains JOIN domain_keys ON domain_keys.domain_id = domains.id"
        " WHERE domains.authenticated = 1 ORDER BY domains.name")]


def server_name():
    names = server_names()
    chosen = state()["server_name"]
    return chosen if chosen in names else (names[0] if names else None)
```

`engine/checks.py`:

```python
"""Ready to send? The checklist at the top of SMTP & API: what's done, and what to do next.
Engine, server name, certificate and a Sender are needed to send; port 25 and reverse DNS are
warnings (mail may go out, but land in spam or bounce)."""
import socket
import time
from collections import namedtuple
from datetime import datetime, timezone

import dns.resolver
import dns.reversename

from ..db import get_db
from . import client, enabled
from .client import EngineError, EngineUnavailable
from .names import server_name

Check = namedtuple("Check", "key title state detail")
NEEDED = ("engine", "server-name", "certificate", "sender")
_cache = {}


def port25_open():
    try:
        socket.create_connection(("gmail-smtp-in.l.google.com", 25), timeout=5).close()
        return True
    except OSError:
        return False


def reverse_name(ip):
    try:
        answer = dns.resolver.resolve(dns.reversename.from_address(ip), "PTR", lifetime=4)
        return str(answer[0]).rstrip(".").lower()
    except Exception:
        return None


def addresses_of(name):
    try:
        return [item.to_text() for item in dns.resolver.resolve(name, "A", lifetime=4)]
    except Exception:
        return []


def run_checks(address):
    name = server_name()
    found = []
    try:
        certificates = client().get("Certificate") if enabled() else None
        found.append(Check("engine", "Mail engine running", "ok", ""))
    except (EngineUnavailable, EngineError):
        certificates = None
    if not enabled():
        found.append(Check("engine", "Mail engine running", "missing", "The mail engine isn't running here: it runs in the Someless Mail container."))
    elif certificates is None:
        found.append(Check("engine", "Mail engine running", "missing", "The mail engine isn't answering. It restarts by itself; if this lasts, restart the container."))
    if not name:
        found.append(Check("server-name", "Server name", "missing", "Authenticate a domain first: the server takes its mail name."))
    elif address and address not in addresses_of(name):
        found.append(Check("server-name", "Server name points here", "missing", f"{name} doesn't point to {address} yet: add its A record on the domain's Authenticate page."))
    else:
        found.append(Check("server-name", "Server name points here", "ok", name))
    now = datetime.now(timezone.utc).isoformat()
    has_certificate = bool(name) and any(name in (cert.get("subjectAlternativeNames") or {}) and cert.get("notValidAfter", "") > now
                                         for cert in (certificates or []))
    found.append(Check("certificate", "Certificate", "ok" if has_certificate else "missing",
                       "" if has_certificate else (
                           f"Let's Encrypt checks {name or 'the server name'} on port 80. In Nginx Proxy Manager, add a proxy host for it "
                           "pointing to someless-mail on port 17081 (no SSL needed there); without a proxy, map port 80 to 17081.")))
    found.append(_cached("port25", lambda: Check("port25", "Outgoing port 25", "ok", "") if port25_open() else Check(
        "port25", "Outgoing port 25", "warning", "Your VPS provider blocks outgoing port 25. Ask them to open it; mail can't reach other servers until then.")))
    if name and address:
        ptr = _cached(f"ptr {address}", lambda: reverse_name(address))
        found.append(Check("reverse-dns", "Reverse DNS", "ok", "") if ptr == name else Check(
            "reverse-dns", "Reverse DNS", "warning", f"At your VPS provider, set the reverse DNS of {address} to {name}."))
    has_sender = get_db().execute("SELECT 1 FROM senders LIMIT 1").fetchone() is not None
    found.append(Check("sender", "A sender", "ok" if has_sender else "missing", "" if has_sender else "Add one on the Senders page."))
    return found


def can_send(found):
    return all(check.state == "ok" for check in found if check.key in NEEDED)


def _cached(key, make, seconds=300):
    value, at = _cache.get(key, (None, 0))
    if time.time() - at > seconds:
        value = make()
        _cache[key] = (value, time.time())
    return value


def forget():
    """Check again: nothing cached."""
    _cache.clear()
```

`sync.py`:
- `desired_state()` adds `"server_name": names.server_name()`.
- `reconcile()` adds, after the DKIM step:

```python
    # the server's name: greeting, certificate (Let's Encrypt, HTTP-01 through the relay), default for clients without SNI
    settings = engine.get("SystemSettings", ["singleton"])[0]
    wanted = desired["server_name"] or INTERNAL_DOMAIN
    if settings.get("defaultHostname") != wanted:
        engine.update("SystemSettings", "singleton", {"defaultHostname": wanted})
        done.append(f"update SystemSettings defaultHostname {wanted}")
    if desired["server_name"]:
        providers = engine.get("AcmeProvider")
        provider = providers[0]["id"] if providers else engine.create("AcmeProvider", {
            "challengeType": "Http01",
            "contact": {f"postmaster@{desired['server_name'].split('.', 1)[1]}": True}})["id"]
        server_domain = desired["server_name"].split(".", 1)[1]
        for name, obj in domains.items():
            if name == INTERNAL_DOMAIN:
                continue
            want = ({"@type": "Automatic", "acmeProviderId": provider, "subjectAlternativeNames": {desired["server_name"]: True}}
                    if name == server_domain else MANUAL)
            if obj.get("certificateManagement") != want:
                engine.update("Domain", obj["id"], {"certificateManagement": want})
                done.append(f"update Domain {name} certificate")
        for certificate in engine.get("Certificate"):
            if desired["server_name"] in (certificate.get("subjectAlternativeNames") or {}) and settings.get("defaultCertificateId") != certificate["id"]:
                engine.update("SystemSettings", "singleton", {"defaultCertificateId": certificate["id"]})
                engine.action("ReloadTlsCertificates")
                done.append("update SystemSettings defaultCertificateId")
                break
```

(Also make the Domain listing pass `certificateManagement` through: `domains` already holds each object from `get`, so it does.)

`smtp.py`:
- `_page()`:
  - checks: `checks.run_checks(domain_records.server_address(request.host))`, plus `can_send`
  - server name options: `names.server_names()`, and the chosen one: `names.server_name()`
  - `_server_name()` becomes `names.server_name() or <old fallback>`
  - pass `engine_error=state()["sync_error"]` when `enabled()`
- New route:

```python
@bp.post("/server-name")
@login_required
def choose_server_name():
    chosen = request.form.get("server_name", "")
    if chosen in names.server_names():
        engine_state.remember(server_name=chosen)
        engine_sync.after_change()
        flash(f"The server is {chosen} now.", "success")
    return redirect(url_for("smtp.index"))


@bp.post("/checks")
@login_required
def check_again():
    checks.forget()
    return redirect(url_for("smtp.index"))
```

`smtp.html`: replace `<p class="smtp-note">…</p>` with:

```html
<section class="ready-card{% if can_send %} is-ready{% endif %}" aria-labelledby="ready-title">
  <div class="ready-head">
    <h2 class="smtp-title" id="ready-title">{{ "Ready to send" if can_send else "Ready to send? Not yet" }}</h2>
    <form method="post" action="{{ url_for('smtp.check_again') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <button class="button button-quiet" type="submit" data-busy-label="Checking…"><span class="button-spinner" aria-hidden="true"></span><span class="button-label">Check again</span></button>
    </form>
  </div>
  {% if engine_error %}<p class="ready-catching-up">Mail engine catching up… ({{ engine_error }})</p>{% endif %}
  <ul class="ready-list">
    {% for check in checks %}
    <li class="ready-item is-{{ check.state }}">
      <span class="ready-mark" aria-hidden="true"></span>
      <span class="ready-title">{{ check.title }}</span>
      {% if check.detail %}<span class="ready-detail">{{ check.detail }}</span>{% endif %}
    </li>
    {% endfor %}
  </ul>
  {% if server_names | length > 1 %}
  <form method="post" action="{{ url_for('smtp.choose_server_name') }}" class="server-name-form">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <label class="field-label" for="server-name">Server name</label>
    <select id="server-name" name="server_name" data-dropdown onchange="this.form.requestSubmit()">
      {% for name in server_names %}<option value="{{ name }}"{% if name == server_name %} selected{% endif %}>{{ name }}</option>{% endfor %}
    </select>
  </form>
  {% endif %}
</section>
```

`style.css`, the checklist:
- `.ready-card`: the card, like `.smtp-card`.
- `.ready-item`: a grid with the mark, the title, and the detail below it.
- `.ready-mark`:
  - a 20px circle
  - `is-ok`: green with a tick (a CSS `::after` check glyph)
  - `is-missing`: red outline
  - `is-warning`: amber
- `.ready-card.is-ready`: a green glow border like `.dns-ready`.
- `.ready-catching-up`: in amber.

- [ ] **Step 4: Run and pass.**

- [ ] **Step 5: Commit** (checkpoint)

---

### Task 6: Delivery reports and the test email

**Files:**
- Create: `app/someless/engine/deliveries.py` (blueprint `engine`, `POST /engine/events`; `send_test()`; `record()`; `status()`)
- Modify: `app/someless/db.py` (`deliveries` table)
- Modify: `app/someless/engine/sync.py` (keep one WebHook object)
- Modify: `app/someless/senders.py` (`POST /senders/<id>/test` and `GET /senders/<id>/tests/<queue_id>`), `templates/senders.html` (the button, the dialog, the last result), `static/js/senders-page.js` (the dialog and polling)
- Modify: `app/someless/__init__.py` (register the blueprint; exempt `/engine/events` from CSRF)
- Test: `tests/test_engine_deliveries.py`, extend `tests/test_engine_live.py`

**Interfaces:**
- Consumes: `secret("webhook_secret")`, `secret("panel_password")`, `PANEL_ACCOUNT`, `checks.run_checks`/`can_send`.
- Produces:
  - `deliveries.send_test(from_address, sender_id, to, subject, text) -> str` (the queue id; raises `SendFailed` with the server's reply)
  - `deliveries.status(queue_id) -> dict` with keys `status`, `detail`, `recipient`
  - `deliveries.SMTP_HOST = "127.0.0.1"`, `deliveries.SMTP_PORT = 17587`
  - the `deliveries` table

Webhook facts come from Task 2's spike. The code below assumes:
- the signature arrives as `X-Signature`: base64 HMAC-SHA256 of the body
- the body is `{"events": [{"type": "...", "data": {...}}]}`
- the event data carries `queueId`, `to` (or `rcpt`) and `response` (or `reason`)

Adjust `_parse()` if the spike found otherwise.

- [ ] **Step 1: Failing tests** — `tests/test_engine_deliveries.py`

```python
import base64
import hashlib
import hmac
import json

import pytest

from someless import engine as engine_module
from someless.db import get_db
from someless.engine import deliveries


def signed(app, body):
    with app.app_context():
        key = engine_module.secret("webhook_secret").encode()
    return {"X-Signature": base64.b64encode(hmac.new(key, body, hashlib.sha256).digest()).decode(), "Content-Type": "application/json"}


def queued(app, queue_id="7f3a", to="you@gmail.com"):
    with app.app_context():
        deliveries.record(queue_id, sender_id=1, recipient=to)


def post(client, app, events, headers=None, remote="127.0.0.1"):
    body = json.dumps({"events": events}).encode()
    return client.post("/engine/events", data=body, headers=headers or signed(app, body),
                       environ_base={"REMOTE_ADDR": remote})


def test_a_delivered_event_marks_delivered(app, client):
    queued(app)

    response = post(client, app, [{"type": "delivery.delivered", "data": {"queueId": "7f3a", "to": "you@gmail.com", "hostname": "gmail-smtp-in.l.google.com"}}])

    assert response.status_code == 204
    with app.app_context():
        assert deliveries.status("7f3a")["status"] == "delivered"
        assert "gmail-smtp-in.l.google.com" in deliveries.status("7f3a")["detail"]


def test_bounce_event_marks_bounced(app, client):
    queued(app)

    post(client, app, [{"type": "delivery.dsn-perm-fail", "data": {"queueId": "7f3a", "to": "you@gmail.com", "response": "550 5.1.1 No such user"}}])

    with app.app_context():
        found = deliveries.status("7f3a")
    assert found["status"] == "bounced" and "No such user" in found["detail"]


def test_events_need_the_signature(app, client):
    queued(app)

    response = post(client, app, [{"type": "delivery.delivered", "data": {"queueId": "7f3a"}}], headers={"X-Signature": "bad"})

    assert response.status_code == 403
    with app.app_context():
        assert deliveries.status("7f3a")["status"] == "queued"


def test_events_refused_from_outside_even_with_forwarded_header(app, client):
    queued(app)
    body = json.dumps({"events": [{"type": "delivery.delivered", "data": {"queueId": "7f3a"}}]}).encode()

    response = client.post("/engine/events", data=body, headers={**signed(app, body), "X-Forwarded-For": "127.0.0.1"},
                           environ_base={"REMOTE_ADDR": "203.0.113.9"})

    assert response.status_code == 403


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
```

- [ ] **Step 2: Run and fail.**

- [ ] **Step 3: Implement.** `db.py` SCHEMA:

```sql
-- Test emails the panel sent, and what became of them (Stalwart's delivery reports, engine/deliveries.py)
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id TEXT NOT NULL,
    sender_id INTEGER,
    recipient TEXT NOT NULL,
    status TEXT NOT NULL,          -- queued, delivered, retrying, bounced
    detail TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
```

`engine/deliveries.py`:

```python
"""Test emails, and what becomes of them. The panel sends through the engine like any app
(its own account, someless-panel), and Stalwart reports each delivery back here: a POST to
/engine/events from inside the container, signed with the webhook secret."""
import base64
import hashlib
import hmac
import json
import re
import smtplib
import ssl
import time
from email.message import EmailMessage

from flask import Blueprint, abort, request

from ..db import get_db
from . import PANEL_ACCOUNT, secret

bp = Blueprint("engine", __name__, url_prefix="/engine")
SMTP_HOST, SMTP_PORT = "127.0.0.1", 17587
QUEUED = re.compile(rb"queued with id ([0-9A-Za-z]+)", re.I)
FINAL = {"delivery.delivered": "delivered", "delivery.dsn-perm-fail": "bounced", "delivery.rcpt-to-rejected": "bounced"}
RETRY = ("delivery.dsn-temp-fail", "delivery.rcpt-to-failed", "delivery.greeting-failed", "delivery.connect-error")


class SendFailed(Exception):
    """The engine refused the test email; the message is its reply."""


def send_test(from_address, sender_id, to, subject, text):
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = from_address, to, subject
    message.set_content(text)
    context = ssl._create_unverified_context()   # loopback inside the container
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.starttls(context=context)
            smtp.login(PANEL_ACCOUNT, secret("panel_password"))
            smtp.mail(from_address)
            code, reply = smtp.rcpt(to)
            if code >= 400:
                raise SendFailed(reply.decode("utf-8", "replace"))
            code, reply = smtp.data(message.as_bytes())
    except (smtplib.SMTPException, OSError) as error:
        raise SendFailed(str(error)) from error
    found = QUEUED.search(reply)
    if code >= 400 or not found:
        raise SendFailed(reply.decode("utf-8", "replace"))
    queue_id = found.group(1).decode()
    record(queue_id, sender_id, to)
    return queue_id


def record(queue_id, sender_id, recipient):
    now = time.time()
    db = get_db()
    db.execute("INSERT INTO deliveries (queue_id, sender_id, recipient, status, created_at, updated_at) VALUES (?, ?, ?, 'queued', ?, ?)",
               (queue_id, sender_id, recipient, now, now))
    db.commit()


def status(queue_id):
    row = get_db().execute("SELECT * FROM deliveries WHERE queue_id = ? ORDER BY id DESC LIMIT 1", (queue_id,)).fetchone()
    if row is None:
        return None
    return {"status": row["status"], "detail": row["detail"], "recipient": row["recipient"],
            "waited_long": row["status"] in ("queued", "retrying") and time.time() - row["created_at"] > 60}


def last_for(sender_id):
    return get_db().execute("SELECT * FROM deliveries WHERE sender_id = ? ORDER BY id DESC LIMIT 1", (sender_id,)).fetchone()


def _from_inside():
    # the socket's own address: ProxyFix keeps it here before it trusts X-Forwarded-For
    original = request.environ.get("werkzeug.proxy_fix.orig", {}).get("REMOTE_ADDR", request.environ.get("REMOTE_ADDR"))
    return original in ("127.0.0.1", "::1")


def _signed(body):
    expected = base64.b64encode(hmac.new(secret("webhook_secret").encode(), body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, request.headers.get("X-Signature", ""))


def _parse(event):
    data = event.get("data") or {}
    queue_id = str(data.get("queueId") or data.get("QueueId") or "")
    detail = data.get("response") or data.get("reason") or data.get("hostname") or ""
    return queue_id, event.get("type", ""), str(detail)


@bp.post("/events")
def events():
    body = request.get_data()
    if not _from_inside() or not _signed(body):
        abort(403)
    db = get_db()
    for event in json.loads(body or b"{}").get("events", []):
        queue_id, kind, detail = _parse(event)
        new = FINAL.get(kind) or ("retrying" if kind in RETRY else None)
        if queue_id and new:
            if new == "delivered" and detail:
                detail = f"Delivered to {detail}"
            db.execute("UPDATE deliveries SET status = ?, detail = ?, updated_at = ? WHERE queue_id = ? AND status != 'delivered'",
                       (new, detail, time.time(), queue_id))
    db.commit()
    return "", 204
```

`__init__.py`: `from .engine import deliveries as engine_deliveries`, then `app.register_blueprint(engine_deliveries.bp)` and `csrf.exempt(engine_deliveries.bp)`.

`sync.py`, in `reconcile()`, keep one `WebHook`. Field names come from the spike.

```python
    hooks = engine.get("WebHook")
    wanted_hook = {"url": "http://127.0.0.1:17080/engine/events", "signatureKey": {"@type": "Text", "secret": desired["webhook_secret"]},
                   "events": {name: True for name in ("delivery.delivered", "delivery.dsn-perm-fail", "delivery.rcpt-to-rejected",
                                                      "delivery.dsn-temp-fail", "delivery.completed")}}
    if not hooks:
        engine.create("WebHook", wanted_hook)
        done.append("create WebHook")
```

`desired_state()` adds `"webhook_secret": secret("webhook_secret")`.

`senders.py`:

```python
from .engine import checks, deliveries, enabled
from .domain_records import server_address


def ready_to_send():
    return enabled() and checks.can_send(checks.run_checks(server_address(request.host)))


@bp.post("/<int:sender_id>/test")
@login_required
def send_test(sender_id):
    sender = _sender(sender_id)
    data = request.get_json(silent=True) or {}
    to = (data.get("to") or "").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", to):
        return {"problem": "Type the address to send the test to."}, 400
    if not ready_to_send():
        return {"problem": "The mail engine isn't ready to send yet: see Ready to send on the SMTP & API page."}, 409
    try:
        queue_id = deliveries.send_test(sender["email"], sender_id, to,
                                        (data.get("subject") or "Test from Someless Mail").strip()[:200],
                                        (data.get("text") or "It works!").strip()[:5000])
    except deliveries.SendFailed as error:
        return {"problem": f"The mail engine refused it: {error}"}, 502
    return {"queue_id": queue_id}


@bp.get("/<int:sender_id>/tests/<queue_id>")
@login_required
def test_status(sender_id, queue_id):
    found = deliveries.status(queue_id)
    return found if found else ({"problem": "No such test email."}, 404)
```

In `index()`, add each sender's `last_test` (`deliveries.last_for(id)`: status, recipient, updated_at as ISO for `local-time.js`).

`senders.html`, on each card:
- next to Edit: `<button type="button" class="button button-quiet sender-test" data-test-sender="{{ sender.id }}" data-sender-name="{{ sender.name }} <{{ sender.email }}>">Send test email</button>`
- in the facts: a "Last test" line when there is one
- one dialog, `#test-dialog`:
  - a To input
  - Subject (prefilled "Test from Someless Mail")
  - Text (prefilled "It works! This is a test from Someless Mail.")
  - a live status line: `<p class="test-status" role="status" aria-live="polite">`
  - Cancel and Send buttons

`senders-page.js`:
- **Open:** the button opens the dialog.
- **Send:** POSTs JSON with the CSRF token from the page's `<input name=csrf_token>` in the `X-CSRFToken` header. On `problem`, show it on the board (`window.somelessBoard.show({type: "error", ...})`).
- **Poll:** on `queue_id`, poll `GET /senders/<id>/tests/<queue_id>` every 2 s, up to 30 times, showing:
  - "Queued…"
  - "Delivered to …" in green
  - "Bounced: …" in red
  - "Trying again later: …" in amber
  - when `waited_long` and nothing final: "Still on its way; the result will show on the card."

- [ ] **Step 4: Run and pass.** Whole suite green.

- [ ] **Step 5: Live** — extend `tests/test_engine_live.py`:
  - send a test through `deliveries.send_test` from the sender to `nobody@example.invalid`
  - assert a queue id comes back
  - wait up to 30 s for `deliveries.status(queue_id)["status"]` to leave `queued`: `.invalid` doesn't resolve, so a bounce or retry event must arrive through the webhook

  PASS with `STALWART_BIN` set.

- [ ] **Step 6: Commit** (checkpoint)

---

### Task 7: The supervisor, the challenge relay, the image, CI and the README

**Files:**
- Create: `app/someless/engine/supervisor.py`
- Create: `docker/someless-run` (a shell wrapper: `exec python -m someless.engine.supervisor "$@"`)
- Modify: `docker/entrypoint.sh` (also create `/data/stalwart`)
- Modify: `Dockerfile` (copy in Stalwart and its docs; the new CMD; `ENV SOMELESS_ENGINE=1 SOMELESS_STALWART=/usr/local/bin/stalwart`; EXPOSE)
- Create: `stalwart/VERSION` (`v0.16.23`), `stalwart/Dockerfile`, `.github/workflows/stalwart.yml`
- Modify: `.github/workflows/docker.yml` (smoke test: Stalwart up, submission port answering, a key sending as a Sender; run the engine unit tests)
- Modify: `docker-compose.yml`, `README.md`
- Test: `tests/test_engine_supervisor.py`

**Interfaces:**
- Consumes: `Stalwart`, `setup.run`, `sync.run`.
- Produces:
  - `supervisor.challenge_reply(path: str, fetch) -> tuple[int, bytes]`: `fetch(path) -> (status, body)`; only `/.well-known/acme-challenge/<token>` is relayed, everything else is `(404, b"")`
  - `supervisor.main()`

- [ ] **Step 1: Failing tests** — `tests/test_engine_supervisor.py`

```python
from someless.engine import supervisor


def test_only_challenges_are_relayed():
    asked = []

    def fetch(path):
        asked.append(path)
        return 200, b"token.thumbprint"

    assert supervisor.challenge_reply("/.well-known/acme-challenge/abc_DEF-123", fetch) == (200, b"token.thumbprint")
    for path in ["/", "/jmap/", "/login", "/.well-known/acme-challenge/../../jmap", "/.well-known/acme-challenge/"]:
        assert supervisor.challenge_reply(path, fetch) == (404, b"")
    assert asked == ["/.well-known/acme-challenge/abc_DEF-123"]


def test_restarts_wait_longer_each_time():
    assert [supervisor.backoff(n) for n in range(8)] == [1, 2, 4, 8, 16, 32, 60, 60]
```

- [ ] **Step 2: Run and fail.**

- [ ] **Step 3: Implement** `engine/supervisor.py`:

```python
"""PID 1 in the container: runs Stalwart and the panel side by side.
- first-time setup of Stalwart (setup.py), then Stalwart normally, then gunicorn
- restarts Stalwart if it stops (waiting longer each time) or when the panel asks (SIGUSR1)
- a sync every hour (keys expiring, anything that drifted)
- the Let's Encrypt relay on 17081: only /.well-known/acme-challenge/<token>, answered by
  Stalwart's own HTTP side on 127.0.0.1:17880, which is never published
- stops both on SIGTERM; if gunicorn stops, so does everything (Docker restarts the container)"""
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHALLENGE = re.compile(r"^/\.well-known/acme-challenge/[A-Za-z0-9_-]+$")
GUNICORN = ["gunicorn", "--bind", "0.0.0.0:17080", "--workers", "2", "--worker-class", "gthread", "--threads", "4",
            "--preload", "--no-control-socket", "--access-logfile", "-", "someless:create_app()"]


def backoff(attempt):
    return min(60, 2 ** attempt)


def challenge_reply(path, fetch):
    if not CHALLENGE.match(path):
        return 404, b""
    return fetch(path)


def _fetch_from_stalwart(path, host):
    request = urllib.request.Request(f"http://127.0.0.1:17880{path}", headers={"Host": host or "localhost"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read(4096)
    except urllib.error.HTTPError as error:
        return error.code, b""
    except OSError:
        return 503, b""


class _Relay(BaseHTTPRequestHandler):
    def do_GET(self):
        status, body = challenge_reply(self.path, lambda path: _fetch_from_stalwart(path, self.headers.get("Host")))
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    from someless import create_app
    from someless.engine import setup, sync
    from someless.engine.process import Stalwart

    app = create_app()
    stalwart = Stalwart(os.environ.get("SOMELESS_STALWART", "/usr/local/bin/stalwart"), "/data/stalwart")
    relay = ThreadingHTTPServer(("0.0.0.0", 17081), _Relay)
    threading.Thread(target=relay.serve_forever, daemon=True).start()
    with app.app_context():
        setup.run(stalwart)          # ends with Stalwart running normally
        sync.run()
    panel = subprocess.Popen(GUNICORN)
    stopping = threading.Event()
    restart = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGUSR1, lambda *_: restart.set())
    attempt, next_sync = 0, time.monotonic() + 3600
    while not stopping.is_set():
        if panel.poll() is not None:
            break
        if restart.is_set() or not stalwart.running():
            restart.clear()
            stalwart.stop()
            time.sleep(backoff(attempt) if not stalwart.running() and attempt else 0)
            stalwart.start("normal")
            attempt = attempt + 1 if attempt < 10 else attempt
        elif attempt and stalwart.running():
            attempt = 0
        if time.monotonic() >= next_sync:
            with app.app_context():
                sync.run()
            next_sync = time.monotonic() + 3600
        stopping.wait(1)
    panel.terminate()
    stalwart.stop()
    try:
        panel.wait(15)
    except subprocess.TimeoutExpired:
        panel.kill()
    return panel.returncode or 0


if __name__ == "__main__":
    sys.exit(main())
```

`docker/someless-run`:

```sh
#!/bin/sh
# The container's main process as the someless user: Stalwart and the panel (engine/supervisor.py).
exec python -m someless.engine.supervisor "$@"
```

`docker/entrypoint.sh`: change `mkdir -p /data/someless` to `mkdir -p /data/someless /data/stalwart`.

`stalwart/VERSION`:
```
v0.16.23
```

`stalwart/Dockerfile`:

```dockerfile
# Stalwart, built from its open-source code (AGPL-3.0) without the Enterprise parts, for
# Someless Mail to copy into its image. Built by .github/workflows/stalwart.yml.
FROM rust:slim-trixie AS build
ARG STALWART_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libclang-19-dev git ca-certificates pkg-config \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${STALWART_VERSION}" https://github.com/stalwartlabs/stalwart /src
WORKDIR /src
RUN cargo build --release -p stalwart --no-default-features --features "rocks"
RUN mkdir -p /out/doc \
 && cp target/release/stalwart /out/stalwart \
 && cp -r LICENSES /out/doc/LICENSES \
 && cp Cargo.lock /out/doc/Cargo.lock \
 && printf 'Stalwart %s, built from https://github.com/stalwartlabs/stalwart/tree/%s (commit %s)\nwithout the enterprise feature: cargo build --release -p stalwart --no-default-features --features rocks\nLicence: AGPL-3.0-only (LICENSES/AGPL-3.0-only.txt). Third-party crates and versions: Cargo.lock\n' \
    "${STALWART_VERSION}" "${STALWART_VERSION}" "$(git rev-parse HEAD)" > /out/doc/SOURCE

FROM debian:trixie-slim
COPY --from=build /out/stalwart /usr/local/bin/stalwart
COPY --from=build /out/doc /usr/share/doc/stalwart
```

`.github/workflows/stalwart.yml`:

```yaml
name: Build Stalwart (open source)

on:
  workflow_dispatch:
  push:
    branches: [main]
    paths: [stalwart/**]

permissions:
  contents: read
  packages: write

env:
  IMAGE: ghcr.io/boyoftime/someless-stalwart

jobs:
  build:
    strategy:
      matrix:
        include:
          - platform: linux/amd64
            runner: ubuntu-latest
          - platform: linux/arm64
            runner: ubuntu-24.04-arm
    runs-on: ${{ matrix.runner }}
    steps:
      - uses: actions/checkout@v7
      - id: version
        run: echo "version=$(cat stalwart/VERSION)" >> "$GITHUB_OUTPUT"
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: build
        uses: docker/build-push-action@v7
        with:
          context: stalwart
          platforms: ${{ matrix.platform }}
          build-args: STALWART_VERSION=${{ steps.version.outputs.version }}
          outputs: type=image,name=${{ env.IMAGE }},push-by-digest=true,name-canonical=true,push=true
          cache-from: type=gha,scope=stalwart-${{ matrix.runner }}
          cache-to: type=gha,mode=max,scope=stalwart-${{ matrix.runner }}
      - run: |
          mkdir -p /tmp/digests
          touch "/tmp/digests/${DIGEST#sha256:}"
        env:
          DIGEST: ${{ steps.build.outputs.digest }}
      - uses: actions/upload-artifact@v5
        with:
          name: digest-${{ matrix.runner }}
          path: /tmp/digests/*

  merge:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/download-artifact@v5
        with:
          path: /tmp/digests
          pattern: digest-*
          merge-multiple: true
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - run: |
          version=$(cat stalwart/VERSION)
          cd /tmp/digests
          docker buildx imagetools create -t "$IMAGE:$version" $(printf "$IMAGE@sha256:%s " *)
```

`Dockerfile` changes:
- after the `FROM`: `ARG STALWART_IMAGE=ghcr.io/boyoftime/someless-stalwart:v0.16.23`
- a stage alias at the top: `FROM ${STALWART_IMAGE} AS stalwart`, then `FROM python:3.13-slim-trixie`
- `COPY --from=stalwart /usr/local/bin/stalwart /usr/local/bin/stalwart` and `COPY --from=stalwart /usr/share/doc/stalwart /usr/share/doc/stalwart`
- `COPY --chmod=755 docker/someless-run /usr/local/bin/someless-run`
- `ENV SOMELESS_ENGINE=1 SOMELESS_STALWART=/usr/local/bin/stalwart`
- `RUN mkdir -p /data/stalwart` in the user block, with `chown`
- `EXPOSE 17080 17587 17465 17081`
- `CMD ["someless-run"]`

Keep the comment explaining gunicorn's flags; it moves to `GUNICORN` in `supervisor.py`.

`docker-compose.yml`:

```yaml
services:
  someless-mail:
    image: ghcr.io/boyoftime/someless-mail:1.0.0
    container_name: someless-mail
    restart: unless-stopped
    ports:
      - "17080:17080"   # web interface
      - "587:17587"     # apps send mail (STARTTLS)
      - "465:17465"     # apps send mail (TLS from the start)
      # - "80:17081"    # only without a reverse proxy: Let's Encrypt's check (nothing else answers here)
    volumes:
      - ./data:/data    # all your data, in a "data" folder next to this file
```

`docker.yml` smoke test additions, after the existing checks:

```bash
          # the mail engine: set up and answering on the submission port
          for i in $(seq 1 60); do
            (exec 3<>/dev/tcp/127.0.0.1/17587) 2>/dev/null && break
            sleep 1
          done
          docker exec smoke python - <<'EOF'
          import smtplib, ssl
          with smtplib.SMTP("127.0.0.1", 17587, timeout=20) as smtp:
              assert smtp.ehlo()[0] == 250
              smtp.starttls(context=ssl._create_unverified_context())
              assert b"AUTH" in smtp.ehlo()[1]
          EOF
          docker exec smoke sh -c 'cd /opt/someless/app && flask --app someless engine status'
```

Publish port `-p 17587:17587` in the smoke `docker run` line. Also add a `flask engine status` CLI to `engine/cli.py`, registered in `create_app` with `app.cli.add_command(engine_cli.cli)`. It prints `setup_step`, `synced_at` and `sync_error`, and exits 1 unless `setup_step == "ready"`.

`README.md`:
- Ports table: 587 and 465 are live now.
- The Let's Encrypt proxy-host step.
- Reverse DNS and outgoing port 25.
- Backing up covers `data/stalwart/`.
- Credits: "Mail engine: Stalwart v0.16.23, built from source without Enterprise features (AGPL-3.0); licence and source link in the image at `/usr/share/doc/stalwart/`".
- Update the Status paragraph at the top: sending works; receiving comes next.

- [ ] **Step 4: Run and pass** the whole suite.

- [ ] **Step 5: Commit** (checkpoint). Then give the user the upload commands. Tell them to run the "Build Stalwart (open source)" workflow first (Actions → Run workflow), because the main image copies from its output, and to confirm ports 587, 465 and 17081 are free on the server (`sudo ss -tulpn`).

---

## After the tasks

- The user runs the Stalwart build workflow, then pushes; the main workflow builds and smoke-tests the image.
- On the VPS:
  - pull and up (with the path)
  - add the Nginx Proxy Manager proxy host for the server name (port 17081)
  - set the reverse DNS at the provider
  - on SMTP & API, check that Ready to send is all ticked
  - send a test email to Gmail from Senders, and check the DKIM, SPF and DMARC pass in the headers
