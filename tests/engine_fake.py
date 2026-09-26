"""A made-up Stalwart for tests: its objects live in dicts, and every call is noted."""
import itertools

from someless.engine.client import EngineError, EngineUnavailable


class FakeEngine:
    def __init__(self):
        self.objects = {}   # kind -> {id: object}
        self.calls = []     # (method, kind, payload)
        self.down = False
        self.bootstrap_reply = {}
        self.fail_on = set()  # kinds whose create Stalwart refuses (like an ACME account it can't register)
        self._ids = itertools.count(1)

    def _check(self):
        if self.down:
            raise EngineUnavailable("fake engine is down")

    def call(self, method, arguments):
        self._check()
        self.calls.append(("call", method, arguments))
        return {"updated": {"singleton": self.bootstrap_reply}}

    def get(self, kind, ids=None):
        self._check()
        self.calls.append(("get", kind, ids))
        found = self.objects.get(kind, {})
        return [dict(obj, id=id_) for id_, obj in found.items() if ids is None or id_ in ids]

    def create(self, kind, obj):
        self._check()
        self.calls.append(("create", kind, obj))
        if kind in self.fail_on:
            raise EngineError(f"x:{kind}/set create: invalidProperties (fake)")
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
