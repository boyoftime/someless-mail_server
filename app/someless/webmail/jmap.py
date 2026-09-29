"""The webmail's way into a mailbox's mail: JMAP (RFC 8620 and 8621) on the mail engine, signed
in as the mailbox by the webmail's own engine account, which may act for any mailbox
(impersonation: mailbox%someless-webmail@someless.internal) and only from inside the container.
No mailbox's password is kept anywhere for this. The tests put a made-up engine in the app's
JMAP config (tests/jmap_fake.py)."""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from flask import current_app, g

from .. import engine

USING = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail", "urn:ietf:params:jmap:submission",
         "urn:ietf:params:jmap:quota", "urn:ietf:params:jmap:vacationresponse"]
TIMEOUT = 20.0   # seconds


class MailUnavailable(Exception):
    """The engine doesn't answer: starting, restarting or stopped."""


class MailError(Exception):
    """The engine answered, with an error."""


def ref(call_index, name, path):
    """A back-reference to what an earlier call in the same request gave (RFC 8620, 3.7)."""
    return {"resultOf": str(call_index), "name": name, "path": path}


class Jmap:
    def __init__(self, email, password, base_url=engine.API_URL, timeout=TIMEOUT):
        self.email = email
        self.base = base_url.rstrip("/")
        login = f"{email}%{engine.WEBMAIL_ACCOUNT}@{engine.INTERNAL_DOMAIN}"
        self.auth = "Basic " + base64.b64encode(f"{login}:{password}".encode()).decode()
        self.timeout = timeout
        self._account_id = None

    def _open(self, method, path, body=None, content_type=None, timeout=None):
        headers = {"Authorization": self.auth}
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        try:
            return urllib.request.urlopen(request, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as error:
            detail = error.read()[:300].decode("utf-8", "replace")
            raise MailError(f"{method} {path.split('?')[0]}: HTTP {error.code} {detail}".strip()) from error
        except OSError as error:   # refused, reset, timed out
            raise MailUnavailable(f"{method} {path.split('?')[0]}: {error}") from error

    @property
    def account_id(self):
        if self._account_id is None:
            with self._open("GET", "/jmap/session") as response:
                session = json.load(response)
            self._account_id = session["primaryAccounts"]["urn:ietf:params:jmap:mail"]
        return self._account_id

    def call(self, *calls, using=()):
        """Method calls, (name, arguments) each, in one request (the account is filled in). A
        call can use an earlier one's result: {"#ids": ref(0, "Email/query", "/ids")}. Their
        results, in the same order; MailError when any failed. using: more capabilities than
        the mail's (Sieve's, contacts', calendars')."""
        method_calls = [[name, {"accountId": self.account_id, **arguments}, str(index)]
                        for index, (name, arguments) in enumerate(calls)]
        body = json.dumps({"using": USING + [one for one in using if one not in USING], "methodCalls": method_calls}).encode()
        with self._open("POST", "/jmap/", body, "application/json") as response:
            reply = json.load(response)
        results = {}
        for name, result, call_id in reply["methodResponses"]:
            if name == "error":
                raise MailError(f"{calls[int(call_id)][0]}: {result.get('type')} {result.get('description', '')}".strip())
            results.setdefault(call_id, result)   # the first answer to each call (others follow some calls)
        return [results[str(index)] for index in range(len(calls))]

    def upload(self, data, content_type):
        """A file for the mailbox (an attachment on its way): {"blobId", "type", "size"}."""
        with self._open("POST", f"/jmap/upload/{self.account_id}/", data, content_type or "application/octet-stream") as response:
            return json.load(response)

    def events(self, timeout):
        """The engine's push for the mailbox (JMAP's EventSource, RFC 8620 7.3): a stream to read
        lines from ("event: state", "data: {StateChange}"). It says nothing between changes: a
        read that waits longer than timeout seconds raises TimeoutError."""
        return self._open("GET", "/jmap/eventsource/?types=*&closeafter=no&ping=0", timeout=timeout)

    def download(self, blob_id, name="file", content_type="application/octet-stream"):
        """A file of the mailbox's, to read from (and close)."""
        path = "/jmap/download/{}/{}/{}?accept={}".format(
            urllib.parse.quote(self.account_id, safe=""), urllib.parse.quote(blob_id, safe=""),
            urllib.parse.quote(name or "file", safe=""), urllib.parse.quote(content_type or "application/octet-stream", safe=""))
        return self._open("GET", path, timeout=60)


def for_mailbox(email):
    """The logged-in mailbox's mail, for this request."""
    if "jmap" not in g:
        factory = current_app.config.get("JMAP")
        if factory:
            g.jmap = factory(email)
        else:
            g.jmap = Jmap(email, engine.secret("webmail_password"), current_app.config.get("ENGINE_URL", engine.API_URL))
    return g.jmap
