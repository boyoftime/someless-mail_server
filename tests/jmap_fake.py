"""A made-up mailbox on the mail engine, for the webmail's tests: its folders, mail and files in
dicts, answering the JMAP methods the webmail uses (RFC 8620/8621) as Stalwart does. Every call
is noted, and `down` makes it stop answering."""
import copy
import datetime
import io
import itertools
import re
import zoneinfo

from someless.webmail.jmap import MailError, MailUnavailable

ROLES = [("inbox", "Inbox"), ("drafts", "Drafts"), ("sent", "Sent Items"), ("junk", "Junk Mail"), ("trash", "Deleted Items")]
DEFAULT_TO = (("Ceo", "ceo@pineloop.online"),)


class Download(io.BytesIO):
    """What urllib hands back for a download: the bytes, and the headers they came with."""
    def __init__(self, data, content_type):
        super().__init__(data)
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(data))}
        self.status = 200


class FakeJmap:
    account_id = "c"

    def __init__(self):
        self.mailboxes = {}   # id -> {name, role, parentId, sortOrder}
        self.emails = {}      # id -> the email's properties (+ _text, _html, _raw)
        self.blobs = {}       # blobId -> (bytes, type)
        self.quota = {"used": 150 * 1024 ** 2, "hardLimit": 1024 ** 3}
        self.calls = []
        self.down = False
        self.state = 0
        self._ids = itertools.count(1)
        self._created = {}        # creation ids made in the request being answered (#draft)
        self.identities = [{"id": "i0", "name": "someless mailbox 1, password 1", "email": "ceo@pineloop.online"}]
        self.submissions = []     # what was handed over to be sent: {email, identity}
        self.refuse_create = None  # a SetError type Email/set create gives instead (overQuota...)
        self.refuse_send = None    # a SetError type EmailSubmission/set gives instead (invalidRecipients...)
        self.scripts = {}          # Sieve scripts: id -> {id, name, blobId, isActive, _text}
        self.refuse_script = None  # what the engine says of a script it won't take
        self.address_books = {"ab0": {"id": "ab0", "name": "Stalwart Address Book (ceo@pineloop.online)", "isDefault": True}}
        self.cards = {}            # contact cards: id -> the JSContact card
        self.calendars = {"cal0": {"id": "cal0", "name": "Stalwart Calendar (ceo@pineloop.online)", "isDefault": True,
                                   "isVisible": True, "color": None}}
        self.events = {}           # events: id -> the JSCalendar event
        self.scheduling = []       # each CalendarEvent/set: whether it asked for invitations to be sent
        for role, name in ROLES:
            self.add_mailbox(name, role)

    # --- setting it up (tests) ---

    def add_mailbox(self, name, role=None, parent=None, sort_order=0):
        mailbox_id = f"m{next(self._ids)}"
        self.mailboxes[mailbox_id] = {"name": name, "role": role, "parentId": parent, "sortOrder": sort_order}
        return mailbox_id

    def role(self, role):
        return next(id_ for id_, box in self.mailboxes.items() if box["role"] == role)

    def add(self, folder="inbox", subject="Hello", sender=("Amina Hassan", "amina@example.com"), to=DEFAULT_TO, cc=(),
            text="Hi, this is the message.", html=None, received="2026-09-28T18:51:00Z", unread=True, flagged=False,
            answered=False, forwarded=False, important=False, attachments=(), size=None, reply_to=(),
            content_type="text/plain; charset=utf-8"):
        email_id = f"e{next(self._ids)}"
        mailbox_id = self.mailboxes.get(folder) and folder or self.role(folder)
        keywords = {}
        if not unread:
            keywords["$seen"] = True
        for flag, keyword in ((flagged, "$flagged"), (answered, "$answered"), (forwarded, "$forwarded")):
            if flag:
                keywords[keyword] = True
        if folder == "drafts":
            keywords["$draft"] = True
        parts = []
        for number, attachment in enumerate(attachments):
            name, content_type, data = attachment[:3]
            cid = attachment[3] if len(attachment) > 3 else None
            blob_id = f"b{email_id}-{number}"
            self.blobs[blob_id] = (data, content_type)
            parts.append({"partId": str(10 + number), "blobId": blob_id, "name": name, "type": content_type,
                          "size": len(data), "disposition": "inline" if cid else "attachment", "cid": cid})
        raw = (f"From: {sender[0]} <{sender[1]}>\r\nTo: {', '.join(address for _, address in to)}\r\n"
               f"Subject: {subject}\r\nMessage-ID: <{email_id}@example.com>\r\n\r\n{text}\r\n").encode()
        self.blobs[f"raw-{email_id}"] = (raw, "message/rfc822")
        preview = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html) if html and not text else text).strip()[:256]
        self.emails[email_id] = {
            "id": email_id, "blobId": f"raw-{email_id}", "threadId": f"t{email_id}", "mailboxIds": {mailbox_id: True},
            "keywords": keywords, "from": [{"name": sender[0], "email": sender[1]}],
            "to": [{"name": name, "email": address} for name, address in to],
            "cc": [{"name": name, "email": address} for name, address in cc], "bcc": [],
            "replyTo": [{"name": name, "email": address} for name, address in reply_to] or None,
            "subject": subject, "preview": preview, "receivedAt": received, "sentAt": received.replace("Z", "+00:00"),
            "size": size or len(raw) + sum(part["size"] for part in parts), "hasAttachment": bool(parts),
            "attachments": parts, "messageId": [f"{email_id}@example.com"], "inReplyTo": None, "references": None,
            "header:X-Priority:asText": " 1" if important else None,
            "header:Content-Type:asText": f" {content_type}",
            "_text": text, "_html": html,
        }
        self.state += 1
        return email_id

    # --- what the webmail's client has (someless.webmail.jmap.Jmap) ---

    def _check(self):
        if self.down:
            raise MailUnavailable("the fake engine is down")

    def call(self, *calls, using=()):
        self._check()
        self._created = {}
        results = []
        for index, (name, arguments) in enumerate(calls):
            self.calls.append((name, copy.deepcopy(arguments)))
            arguments = self._resolve(arguments, results)
            method = getattr(self, "_" + name.replace("/", "_"), None)
            if method is None:
                raise MailError(f"unknownMethod: {name}")
            results.append(method(arguments))
        return results

    def upload(self, data, content_type):
        self._check()
        blob_id = f"up{next(self._ids)}"
        self.blobs[blob_id] = (data, content_type)
        return {"blobId": blob_id, "type": content_type, "size": len(data)}

    def download(self, blob_id, name="file", content_type="application/octet-stream"):
        self._check()
        if blob_id not in self.blobs:
            raise MailError("GET download: HTTP 404")
        data, stored_type = self.blobs[blob_id]
        return Download(data, stored_type)

    # --- the methods ---

    def _resolve(self, arguments, results):
        """Back-references ("#ids": {"resultOf": "0", "path": "/ids"}) to what earlier calls gave."""
        resolved = {}
        for key, value in arguments.items():
            if key.startswith("#"):
                source = results[int(value["resultOf"])]
                resolved[key[1:]] = _pointer(source, value["path"])
            else:
                resolved[key] = value
        return resolved

    def _counts(self, mailbox_id):
        inside = [email for email in self.emails.values() if mailbox_id in email["mailboxIds"]]
        return len(inside), sum(1 for email in inside if "$seen" not in email["keywords"])

    def _Mailbox_get(self, arguments):
        found = []
        for mailbox_id, box in self.mailboxes.items():
            if arguments.get("ids") is not None and mailbox_id not in arguments["ids"]:
                continue
            total, unread = self._counts(mailbox_id)
            found.append({"id": mailbox_id, **box, "totalEmails": total, "unreadEmails": unread})
        return {"accountId": self.account_id, "state": str(self.state), "list": found, "notFound": []}

    def _Mailbox_set(self, arguments):
        created, updated, destroyed, not_created, not_destroyed = {}, {}, [], {}, {}
        for key, box in (arguments.get("create") or {}).items():
            siblings = [other for other in self.mailboxes.values()
                        if other["parentId"] == box.get("parentId") and other["name"].lower() == box["name"].lower()]
            if siblings:
                not_created[key] = {"type": "invalidProperties", "description": "A mailbox with that name already exists."}
                continue
            created[key] = {"id": self.add_mailbox(box["name"], box.get("role"), box.get("parentId"), box.get("sortOrder", 0))}
        for mailbox_id, patch in (arguments.get("update") or {}).items():
            self.mailboxes[mailbox_id].update(patch)
            updated[mailbox_id] = None
        for mailbox_id in arguments.get("destroy") or []:
            if any(box["parentId"] == mailbox_id for box in self.mailboxes.values()):
                not_destroyed[mailbox_id] = {"type": "mailboxHasChild"}
                continue
            if self._counts(mailbox_id)[0] and not arguments.get("onDestroyRemoveEmails"):
                not_destroyed[mailbox_id] = {"type": "mailboxHasEmail"}
                continue
            for email_id in [id_ for id_, email in self.emails.items() if mailbox_id in email["mailboxIds"]]:
                del self.emails[email_id]
            del self.mailboxes[mailbox_id]
            destroyed.append(mailbox_id)
        self.state += 1
        return {"created": created, "updated": updated, "destroyed": destroyed, "notCreated": not_created,
                "notDestroyed": not_destroyed}

    def _matches(self, email, condition):
        if "operator" in condition:   # a FilterOperator
            results = [self._matches(email, inner) for inner in condition["conditions"]]
            return {"AND": all(results), "OR": any(results), "NOT": not any(results)}[condition["operator"]]
        for key, value in condition.items():
            if key == "inMailbox" and value not in email["mailboxIds"]:
                return False
            if key == "inMailboxOtherThan" and not set(email["mailboxIds"]) - set(value):
                return False
            if key == "hasKeyword" and value not in email["keywords"]:
                return False
            if key == "notKeyword" and value in email["keywords"]:
                return False
            if key == "hasAttachment" and email["hasAttachment"] != value:
                return False
            if key == "after" and not email["receivedAt"] > value:   # (ISO times in UTC compare as text)
                return False
            if key == "before" and not email["receivedAt"] < value:
                return False
            if key == "header" and value[0].lower() == "x-priority":
                if not (email["header:X-Priority:asText"] or "").strip().startswith(value[1] if len(value) > 1 else ""):
                    return False
            if key in ("text", "subject", "from", "to", "body"):
                haystack = {
                    "subject": email["subject"], "body": f"{email['_text']} {email['_html'] or ''}",
                    "from": " ".join(f"{a['name']} {a['email']}" for a in email["from"]),
                    "to": " ".join(f"{a['name']} {a['email']}" for a in email["to"] + email["cc"]),
                }
                haystack["text"] = " ".join(haystack.values())
                if value.lower() not in haystack[key].lower():
                    return False
        return True

    def _Email_query(self, arguments):
        found = [email for email in self.emails.values() if self._matches(email, arguments.get("filter") or {})]
        for rule in reversed(arguments.get("sort") or [{"property": "receivedAt", "isAscending": False}]):
            found.sort(key=lambda email: (email[rule["property"]], email["id"]), reverse=not rule.get("isAscending", True))
        ids = [email["id"] for email in found]
        start = arguments.get("position", 0)
        if arguments.get("anchor") is not None:
            if arguments["anchor"] not in ids:
                raise MailError("anchorNotFound")
            start = ids.index(arguments["anchor"]) + arguments.get("anchorOffset", 0)
        limit = arguments.get("limit")
        page = ids[start:start + limit] if limit is not None else ids[start:]
        result = {"accountId": self.account_id, "queryState": str(self.state), "position": start, "ids": page,
                  "canCalculateChanges": True}
        if arguments.get("calculateTotal"):
            result["total"] = len(ids)
        return result

    def _Email_get(self, arguments):
        found, missing = [], []
        wanted = arguments.get("properties")
        for email_id in arguments.get("ids") or []:
            email = self.emails.get(email_id)
            if email is None:
                missing.append(email_id)
                continue
            shown = {key: copy.deepcopy(value) for key, value in email.items() if not key.startswith("_")}
            text_part = {"partId": "1", "type": "text/plain"}
            html_part = {"partId": "2", "type": "text/html"}
            shown["textBody"] = [text_part]
            shown["htmlBody"] = [html_part] if email["_html"] else [text_part]
            values = {}
            if arguments.get("fetchTextBodyValues") or arguments.get("fetchAllBodyValues"):
                values["1"] = {"value": email["_text"], "isTruncated": False}
            if (arguments.get("fetchHTMLBodyValues") or arguments.get("fetchAllBodyValues")) and email["_html"]:
                values["2"] = {"value": email["_html"], "isTruncated": False}
            if values:
                shown["bodyValues"] = values
            if wanted is not None:
                shown = {key: value for key, value in shown.items() if key in wanted or key == "id"}
            found.append(shown)
        return {"accountId": self.account_id, "state": str(self.state), "list": found, "notFound": missing}

    def _Email_set(self, arguments):
        created, not_created = {}, {}
        for key, email in (arguments.get("create") or {}).items():
            if self.refuse_create:
                not_created[key] = {"type": self.refuse_create}
                continue
            email_id = f"e{next(self._ids)}"
            values = email.get("bodyValues") or {}
            structure = email.get("bodyStructure")
            if structure:   # (its parts as they're put together: the words, and the files among them)
                leaves = list(_leaves(structure))
                files = [part for part in leaves if part.get("blobId")]
                html_body = [part for part in leaves if part.get("partId") and part.get("type") == "text/html"]
                text_body = [part for part in leaves if part.get("partId") and part.get("type") == "text/plain"]
            else:
                files, html_body, text_body = email.get("attachments") or [], email.get("htmlBody") or [], email.get("textBody") or []
            parts = []
            for number, part in enumerate(files):
                data, _ = self.blobs.get(part["blobId"], (b"", part.get("type")))
                parts.append({"partId": str(10 + number), "blobId": part["blobId"], "name": part.get("name"),
                              "type": part.get("type"), "size": len(data), "disposition": part.get("disposition"),
                              "cid": part.get("cid")})
            html = next((values[part["partId"]]["value"] for part in html_body if part["partId"] in values), None)
            text = next((values[part["partId"]]["value"] for part in text_body if part["partId"] in values), "")
            raw = f"From: {email['from'][0]['email']}\r\nSubject: {email.get('subject', '')}\r\n\r\n{text}".encode()
            self.blobs[f"raw-{email_id}"] = (raw, "message/rfc822")
            self.emails[email_id] = {
                "id": email_id, "blobId": f"raw-{email_id}", "threadId": f"t{email_id}", "mailboxIds": dict(email["mailboxIds"]),
                "keywords": dict(email.get("keywords") or {}), "from": email.get("from") or [], "to": email.get("to") or [],
                "cc": email.get("cc") or [], "bcc": email.get("bcc") or [], "replyTo": email.get("replyTo"),
                "subject": email.get("subject") or "", "preview": re.sub(r"\s+", " ", text).strip()[:256],
                "receivedAt": "2026-09-28T20:00:00Z", "sentAt": email.get("sentAt"), "size": len(raw),
                "hasAttachment": any(part["disposition"] == "attachment" for part in parts), "attachments": parts,
                "messageId": [f"{email_id}@someless"], "inReplyTo": email.get("inReplyTo"), "references": email.get("references"),
                "header:X-Priority:asText": email.get("header:X-Priority:asText"),
                "header:X-Someless-Draft-Of:asText": email.get("header:X-Someless-Draft-Of:asText"),
                "_text": text, "_html": html, "_created": email,
            }
            created[key] = {"id": email_id, "blobId": f"raw-{email_id}", "threadId": f"t{email_id}", "size": len(raw)}
            self._created[key] = email_id
        updated, destroyed, not_updated = {}, [], {}
        for email_id, patch in (arguments.get("update") or {}).items():
            email = self.emails.get(email_id)
            if email is None:
                not_updated[email_id] = {"type": "notFound"}
                continue
            for path, value in patch.items():
                if path in ("keywords", "mailboxIds"):
                    email[path] = dict(value)
                elif path.startswith(("keywords/", "mailboxIds/")):
                    field, key = path.split("/", 1)
                    if value:
                        email[field][key] = True
                    else:
                        email[field].pop(key, None)
                else:
                    raise MailError(f"invalidPatch: {path}")
            updated[email_id] = None
        for email_id in arguments.get("destroy") or []:
            if self.emails.pop(email_id, None) is not None:
                destroyed.append(email_id)
        self.state += 1
        return {"created": created, "notCreated": not_created, "updated": updated, "destroyed": destroyed,
                "notUpdated": not_updated, "notDestroyed": {}}

    def _Quota_get(self, arguments):
        return {"list": [{"id": "q", "resourceType": "octets", "scope": "account", "types": ["Mail"], **self.quota}]}

    def _SieveScript_get(self, arguments):
        return {"accountId": self.account_id, "list": [dict(script) for script in self.scripts.values()], "notFound": []}

    def _SieveScript_set(self, arguments):
        created, updated, not_created = {}, {}, {}
        for key, script in (arguments.get("create") or {}).items():
            text = self.blobs.get(script["blobId"], (b"", ""))[0].decode()
            if self.refuse_script:
                not_created[key] = {"type": "invalidScript", "description": self.refuse_script}
                continue
            script_id = f"s{next(self._ids)}"
            self.scripts[script_id] = {"id": script_id, "name": script["name"], "blobId": script["blobId"], "isActive": False,
                                       "_text": text}
            created[key] = {"id": script_id}
            self._created[key] = script_id
        not_updated = {}
        for script_id, patch in (arguments.get("update") or {}).items():
            if self.refuse_script:
                not_updated[script_id] = {"type": "invalidScript", "description": self.refuse_script}
                continue
            self.scripts[script_id].update(patch)
            self.scripts[script_id]["_text"] = self.blobs.get(patch["blobId"], (b"", ""))[0].decode()
            updated[script_id] = None
        active = arguments.get("onSuccessActivateScript")
        if active and not self.refuse_script:
            active = self._created.get(active[1:]) if active.startswith("#") else active
            for script in self.scripts.values():
                script["isActive"] = script["id"] == active
        return {"created": created, "updated": updated, "notCreated": not_created, "notUpdated": not_updated}

    def active_script(self):
        return next((script["_text"] for script in self.scripts.values() if script["isActive"]), None)

    def _Identity_get(self, arguments):
        return {"accountId": self.account_id, "list": [dict(identity) for identity in self.identities], "notFound": []}

    def _Identity_set(self, arguments):
        created = {}
        for key, identity in (arguments.get("create") or {}).items():
            made = {"id": f"i{next(self._ids)}", "name": identity.get("name", ""), "email": identity["email"]}
            self.identities.append(made)
            created[key] = {"id": made["id"]}
        return {"created": created, "notCreated": {}}

    def _EmailSubmission_set(self, arguments):
        created, not_created = {}, {}
        for key, submission in (arguments.get("create") or {}).items():
            email_id = submission["emailId"]
            if email_id.startswith("#"):
                email_id = self._created.get(email_id[1:])
            if email_id not in self.emails:   # (the message it was to send wasn't made)
                not_created[key] = {"type": "invalidProperties", "properties": ["emailId"]}
                continue
            if self.refuse_send:
                not_created[key] = {"type": self.refuse_send}
                continue
            identity = next((one for one in self.identities if one["id"] == submission["identityId"]), None)
            self.submissions.append({"email": copy.deepcopy(self.emails[email_id]), "identity": identity})
            created[key] = {"id": f"s{next(self._ids)}"}
            patch = (arguments.get("onSuccessUpdateEmail") or {}).get("#" + key)
            if patch:
                self._Email_set({"update": {email_id: patch}})
        return {"created": created, "notCreated": not_created}

    # --- contacts (RFC 9610), as Stalwart has them ---

    def _AddressBook_get(self, arguments):
        return {"accountId": self.account_id, "list": [dict(book) for book in self.address_books.values()], "notFound": []}

    def _AddressBook_set(self, arguments):
        created = {}
        for key, book in (arguments.get("create") or {}).items():
            book_id = f"ab{next(self._ids)}"
            self.address_books[book_id] = {"id": book_id, "isDefault": False, **book}
            created[key] = {"id": book_id}
        for book_id, patch in (arguments.get("update") or {}).items():
            self.address_books[book_id].update(patch)
        return {"created": created, "updated": {key: None for key in arguments.get("update") or {}}, "notCreated": {}}

    def add_card(self, **card):
        card_id = f"card{next(self._ids)}"
        self.cards[card_id] = {"@type": "Card", "addressBookIds": {next(iter(self.address_books)): True}, **card, "id": card_id}
        return card_id

    def _ContactCard_query(self, arguments):
        wanted = (arguments.get("filter") or {}).get("inAddressBook")
        ids = [card_id for card_id, card in self.cards.items() if not wanted or wanted in card.get("addressBookIds", {})]
        position, limit = arguments.get("position", 0), arguments.get("limit") or len(ids)
        return {"ids": ids[position:position + limit], "position": position, "total": len(ids)}

    def _ContactCard_get(self, arguments):
        found, missing = [], []
        for card_id in arguments.get("ids") or list(self.cards):
            card = self.cards.get(card_id)
            if card is None:
                missing.append(card_id)
                continue
            wanted = arguments.get("properties")
            found.append({key: copy.deepcopy(value) for key, value in card.items() if not wanted or key in wanted or key == "id"})
        return {"accountId": self.account_id, "list": found, "notFound": missing}

    def _ContactCard_set(self, arguments):
        created, updated, destroyed, not_destroyed = {}, {}, [], {}
        for key, card in (arguments.get("create") or {}).items():
            created[key] = {"id": self.add_card(**copy.deepcopy(card))}
        for card_id, patch in (arguments.get("update") or {}).items():
            for name, value in patch.items():
                if value is None:
                    self.cards[card_id].pop(name, None)
                else:
                    self.cards[card_id][name] = copy.deepcopy(value)
            updated[card_id] = None
        for card_id in arguments.get("destroy") or []:
            if self.cards.pop(card_id, None) is None:
                not_destroyed[card_id] = {"type": "notFound"}
            else:
                destroyed.append(card_id)
        return {"created": created, "updated": updated, "destroyed": destroyed, "notDestroyed": not_destroyed, "notCreated": {}}

    # --- calendars (JMAP for Calendars, as Stalwart has it: one recurrenceRule; the times of a
    # repeating event have ids of their own, "<base>~<recurrenceId>") ---

    def _Calendar_get(self, arguments):
        return {"accountId": self.account_id, "list": [dict(one) for one in self.calendars.values()], "notFound": []}

    def _Calendar_set(self, arguments):
        created, updated = {}, {}
        for key, calendar in (arguments.get("create") or {}).items():
            calendar_id = f"cal{next(self._ids)}"
            self.calendars[calendar_id] = {"id": calendar_id, "isVisible": True, "isDefault": False, **calendar}
            created[key] = {"id": calendar_id}
        for calendar_id, patch in (arguments.get("update") or {}).items():
            self.calendars[calendar_id].update(patch)
            updated[calendar_id] = None
        return {"created": created, "updated": updated, "notCreated": {}}

    def add_event(self, **event):
        event_id = f"ev{next(self._ids)}"
        self.events[event_id] = {"@type": "Event", "calendarIds": {next(iter(self.calendars)): True}, "duration": "PT1H", **event,
                                 "id": event_id}
        return event_id

    def _times(self, event):
        """(recurrenceId, start) of each time an event happens (a few years of them at most)."""
        start = datetime.datetime.fromisoformat(event["start"])
        rule = event.get("recurrenceRule")
        if not rule:
            return [(None, start)]
        step = {"daily": datetime.timedelta(days=1), "weekly": datetime.timedelta(days=1)}.get(rule["frequency"])
        days = [one["day"] for one in rule.get("byDay") or []]
        until = datetime.datetime.fromisoformat(rule["until"]) if rule.get("until") else None
        found, moment, interval = [], start, rule.get("interval", 1)
        while len(found) < (rule.get("count") or 500) and moment.year < start.year + 3:
            if until and moment > until:
                break
            weekday = ["mo", "tu", "we", "th", "fr", "sa", "su"][moment.weekday()]
            weeks = (moment - start).days // 7
            if rule["frequency"] == "daily" and (moment - start).days % interval == 0:
                found.append(moment)
            elif rule["frequency"] == "weekly" and weekday in (days or [["mo", "tu", "we", "th", "fr", "sa", "su"][start.weekday()]]) \
                    and weeks % interval == 0:
                found.append(moment)
            elif rule["frequency"] in ("monthly", "yearly"):
                found.append(moment)
            if step:
                moment += step
            elif rule["frequency"] == "monthly":
                month = moment.month + interval
                moment = moment.replace(year=moment.year + (month - 1) // 12, month=(month - 1) % 12 + 1)
            else:
                moment = moment.replace(year=moment.year + interval)
        return [(moment.isoformat(), moment) for moment in found]

    def _instance(self, event, recurrence_id, start):
        overrides = event.get("recurrenceOverrides") or {}
        made = {key: copy.deepcopy(value) for key, value in event.items() if key not in ("recurrenceOverrides",)}
        made["start"] = start.isoformat() if isinstance(start, datetime.datetime) else start
        if recurrence_id:
            made.update(copy.deepcopy(overrides.get(recurrence_id) or {}))
            made.update({"id": f"{event['id']}~{recurrence_id}", "baseEventId": event["id"], "recurrenceId": recurrence_id})
            made.pop("recurrenceRule", None)
        return made

    def _utc(self, event):
        zone = event.get("timeZone")
        start = datetime.datetime.fromisoformat(event["start"])
        start = start.replace(tzinfo=zoneinfo.ZoneInfo(zone) if zone else datetime.timezone.utc).astimezone(datetime.timezone.utc)
        from someless.webmail.calendar import parse_duration
        return start, start + parse_duration(event.get("duration") or "PT0S")

    def _CalendarEvent_query(self, arguments):
        wanted = arguments.get("filter") or {}
        after = datetime.datetime.fromisoformat(wanted["after"].replace("Z", "+00:00")) if wanted.get("after") else None
        before = datetime.datetime.fromisoformat(wanted["before"].replace("Z", "+00:00")) if wanted.get("before") else None
        ids = []
        for event in self.events.values():
            times = self._times(event) if arguments.get("expandRecurrences") else [(None, datetime.datetime.fromisoformat(event["start"]))]
            for recurrence_id, start in times:
                if recurrence_id and (event.get("recurrenceOverrides") or {}).get(recurrence_id, {}).get("excluded"):
                    continue
                instance = self._instance(event, recurrence_id if arguments.get("expandRecurrences") else None, start)
                begins, ends = self._utc(instance)
                if (after and ends <= after) or (before and begins >= before):
                    continue
                ids.append(instance["id"])
        return {"ids": ids, "position": 0}

    def _event(self, event_id):
        if event_id in self.events:
            return self.events[event_id]
        base_id, _, recurrence_id = event_id.partition("~")
        base = self.events.get(base_id)
        if base is None or not recurrence_id:
            return None
        return self._instance(base, recurrence_id, recurrence_id)

    def _CalendarEvent_get(self, arguments):
        found, missing = [], []
        for event_id in arguments.get("ids") or list(self.events):
            event = self._event(event_id)
            if event is None:
                missing.append(event_id)
                continue
            wanted = arguments.get("properties")
            found.append({key: copy.deepcopy(value) for key, value in event.items() if not wanted or key in wanted or key == "id"})
        return {"accountId": self.account_id, "list": found, "notFound": missing}

    def _CalendarEvent_set(self, arguments):
        self.scheduling.append(bool(arguments.get("sendSchedulingMessages")))
        created, updated, destroyed, not_updated = {}, {}, [], {}
        for key, event in (arguments.get("create") or {}).items():
            created[key] = {"id": self.add_event(**copy.deepcopy(event))}
        for event_id, patch in (arguments.get("update") or {}).items():
            base_id, _, recurrence_id = event_id.partition("~")
            base = self.events.get(base_id)
            if base is None:
                not_updated[event_id] = {"type": "notFound"}
                continue
            if recurrence_id:
                target = base.setdefault("recurrenceOverrides", {}).setdefault(recurrence_id, {})
            else:
                target = base
            for name, value in patch.items():
                if "/" in name:   # a path into it ("participants/p1/participationStatus")
                    parts = name.split("/")
                    holder = target
                    if recurrence_id and parts[0] not in target:
                        target[parts[0]] = copy.deepcopy(base.get(parts[0]))
                        holder = target
                    for part in parts[:-1]:
                        holder = holder[part]
                    holder[parts[-1]] = value
                elif value is None:
                    target.pop(name, None)
                else:
                    target[name] = copy.deepcopy(value)
            updated[event_id] = None
        for event_id in arguments.get("destroy") or []:
            base_id, _, recurrence_id = event_id.partition("~")
            if recurrence_id and base_id in self.events:
                self.events[base_id].setdefault("recurrenceOverrides", {})[recurrence_id] = {"excluded": True}
                destroyed.append(event_id)
            elif self.events.pop(event_id, None) is not None:
                destroyed.append(event_id)
        return {"created": created, "updated": updated, "destroyed": destroyed, "notUpdated": not_updated, "notCreated": {}}


def _leaves(part):
    """A message's parts that aren't multipart, in order (its bodyStructure, as the engine reads it)."""
    if part.get("subParts"):
        for sub in part["subParts"]:
            yield from _leaves(sub)
    else:
        yield part


def _pointer(value, path):
    """A JSON pointer with * for every item of a list (RFC 8620, 3.7)."""
    parts = [part for part in path.split("/") if part]
    for index, part in enumerate(parts):
        if part == "*":
            rest = "/" + "/".join(parts[index + 1:])
            flat = []
            for item in value:
                got = _pointer(item, rest)
                flat.extend(got if isinstance(got, list) else [got])
            return flat
        value = value[part] if isinstance(value, dict) else value[int(part)]
    return value
