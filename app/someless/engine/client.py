"""Stalwart's management API (v0.16): JMAP over HTTP, one method per call, like
x:Domain/set (https://stalw.art/docs/development/api)."""
import base64
import json
import urllib.error
import urllib.request

USING = ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]
ACTION_TIMEOUT = 30.0  # seconds: reloading settings rebuilds Stalwart's whole setup


class EngineUnavailable(Exception):
    """Stalwart doesn't answer: not started yet, restarting, or stopped."""


class EngineError(Exception):
    """Stalwart answered, with an error."""


def _problem(result):
    return f"{result.get('type')} {result.get('description', '')}".strip()


class EngineClient:
    def __init__(self, base_url, basic=None, token=None, timeout=5.0):
        self.url = base_url.rstrip("/") + "/jmap/"
        if token:
            self.auth = f"Bearer {token}"
        elif basic:
            self.auth = "Basic " + base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
        else:
            self.auth = None
        self.timeout = timeout

    def call(self, method, arguments, timeout=None):
        body = json.dumps({"using": USING, "methodCalls": [[method, arguments, "c"]]}).encode()
        headers = {"Content-Type": "application/json"}
        if self.auth:
            headers["Authorization"] = self.auth
        request = urllib.request.Request(self.url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                reply = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read()[:300].decode("utf-8", "replace")
            raise EngineError(f"{method}: HTTP {error.code} {detail}".strip()) from error
        except OSError as error:  # refused, reset, timed out (URLError is an OSError too)
            raise EngineUnavailable(f"{method}: {error}") from error
        name, result, _ = reply["methodResponses"][0]
        if name == "error":
            raise EngineError(f"{method}: {_problem(result)}")
        return result

    def get(self, kind, ids=None):
        return self.call(f"x:{kind}/get", {"ids": ids})["list"]

    def create(self, kind, obj, timeout=None):
        result = self.call(f"x:{kind}/set", {"create": {"new": obj}}, timeout)
        if "new" not in (result.get("created") or {}):
            raise EngineError(f"x:{kind}/set create: {_problem((result.get('notCreated') or {}).get('new', {}))}")
        return result["created"]["new"]

    def update(self, kind, id_, patch):
        result = self.call(f"x:{kind}/set", {"update": {id_: patch}})
        if id_ in (result.get("notUpdated") or {}):
            raise EngineError(f"x:{kind}/set update: {_problem(result['notUpdated'][id_])}")

    def destroy(self, kind, id_):
        result = self.call(f"x:{kind}/set", {"destroy": [id_]})
        if id_ in (result.get("notDestroyed") or {}):
            raise EngineError(f"x:{kind}/set destroy: {_problem(result['notDestroyed'][id_])}")

    def action(self, kind):
        """Ask Stalwart to do something now, like ReloadSettings."""
        self.create("Action", {"@type": kind}, max(self.timeout, ACTION_TIMEOUT))
