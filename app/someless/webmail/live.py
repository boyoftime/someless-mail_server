"""New mail as it comes, without a refresh (webmail-live.js): the page keeps a WebSocket open to
/live, and the webmail listens for the mailbox to the mail engine's push (JMAP's EventSource,
RFC 8620 7.3). When mail is delivered to the Inbox the page is told who it's from (the sound, the
notification, the list); when anything else changes (read on a phone, moved in a mail app) just
that something did, and it brings its list and counts up to date.

Each open tab keeps one of the webmail's threads while it's open (the supervisor gives it many).
The engine's stream says nothing between changes, so it's opened again every so often, and the
page is pinged then (proxies close connections that stay quiet)."""
import json
import socket
import time

from flask import current_app, g, request
from flask_sock import Sock
from simple_websocket import ConnectionClosed

from . import messages
from .jmap import MailError, MailUnavailable, for_mailbox, ref

sock = Sock()
QUIET_FOR = 25        # seconds without a word from the engine: its stream opened again, the page pinged
DOWN_WAIT = 5         # seconds before trying the engine again when it doesn't answer
NEWEST = 5            # new messages told about at once (the rest are counted)


def _inbox(mail):
    boxes = mail.call(("Mailbox/get", {"properties": ["role"]}))[0]["list"]
    return next((box["id"] for box in boxes if box.get("role") == "inbox"), None)


def _latest(mail, inbox):
    """When the newest message in the Inbox came (ISO), or None."""
    if inbox is None:
        return None
    _, got = mail.call(("Email/query", {"filter": {"inMailbox": inbox}, "sort": [{"property": "receivedAt", "isAscending": False}],
                                        "limit": 1}),
                       ("Email/get", {"#ids": ref(0, "Email/query", "/ids"), "properties": ["receivedAt"]}))
    return got["list"][0]["receivedAt"] if got["list"] else None


def _arrived(mail, inbox, since):
    """The messages that came to the Inbox after `since`: (how many, the newest few, the newest's time)."""
    condition = {"inMailbox": inbox}
    if since:
        condition = {"operator": "AND", "conditions": [condition, {"after": since}]}
    query, got = mail.call(("Email/query", {"filter": condition, "sort": [{"property": "receivedAt", "isAscending": False}],
                                            "limit": NEWEST, "calculateTotal": True}),
                           ("Email/get", {"#ids": ref(0, "Email/query", "/ids"),
                                          "properties": ["from", "subject", "preview", "receivedAt", "keywords"]}))
    found = [email for email in got["list"] if email.get("receivedAt") != since]
    newest = [{"id": email["id"], "from": messages.people(email.get("from")) or "(Unknown sender)",
               "subject": email.get("subject") or messages.NO_SUBJECT, "preview": (email.get("preview") or "")[:140]}
              for email in found if "$seen" not in (email.get("keywords") or {})]
    latest = max([email["receivedAt"] for email in found] + ([since] if since else []), default=since)
    return max(query.get("total", 0), len(found)), newest, latest


def _changes(stream):
    """The engine's StateChanges, one set of changed types after another, as they come."""
    data = []
    while True:
        line = stream.readline()
        if not line:
            return   # (the engine closed it: opened again)
        text = line.decode("utf-8", "replace").rstrip("\r\n")
        if text.startswith("data:"):
            data.append(text[5:].strip())
        elif not text and data:
            try:
                change = json.loads("".join(data))
            except ValueError:
                change = {}
            data = []
            types = set()
            for account in (change.get("changed") or {}).values():
                types.update(account)
            if types:
                yield types


def _same_site():
    """Only the webmail's own pages may open it (a page elsewhere can't listen in with its cookies)."""
    origin = request.headers.get("Origin")
    if not origin:
        return True
    return origin.rstrip("/") == request.host_url.rstrip("/")


@sock.route("/live")
def live(ws):
    if g.mailbox is None or not _same_site():
        ws.close(reason=1008, message="Log in again.")
        return
    mail = for_mailbox(g.mailbox["email"])
    since, inbox = None, None
    while True:
        try:
            if inbox is None:
                inbox = _inbox(mail)
                since = _latest(mail, inbox)
            with mail.events(QUIET_FOR) as stream:
                for types in _changes(stream):
                    if "EmailDelivery" in types and inbox:
                        count, newest, since = _arrived(mail, inbox, since)
                        if newest:
                            ws.send(json.dumps({"type": "new", "count": count, "messages": newest}))
                            continue
                    if types & {"Email", "Mailbox", "EmailDelivery"}:
                        ws.send(json.dumps({"type": "changed"}))
        except (TimeoutError, socket.timeout):
            pass   # quiet for a while: the page pinged, the stream opened again
        except (MailUnavailable, MailError) as error:
            current_app.logger.info("live: the mail engine's push: %s", error)
            inbox = None
            time.sleep(DOWN_WAIT)
        except ConnectionClosed:
            return
        try:
            ws.send(json.dumps({"type": "ping"}))
        except ConnectionClosed:
            return
