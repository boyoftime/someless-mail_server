"""The mailbox's rules for its incoming mail, as one Sieve script in the mail engine (RFC 5228):
its auto-reply, its forwarding and its filters (Settings). They're kept here (webmail_settings,
webmail_rules), and each change writes the script again and makes it the active one. (The engine's
own auto-reply, JMAP VacationResponse, is a Sieve script of its own that switches the others
off: so it isn't used, and the auto-reply is written into this one.)

The script, in order: the auto-reply (within its dates), the forwarding, then the filters, each
"if" its conditions (all, any, or none needed), its actions: flags first (read, favorite), then
where it goes (a folder by its id, RFC 9042, so a renamed folder still works), forwarded, kept or
thrown away; "stop" skips the filters after it."""
import datetime
import json
import re

from flask import g

from ..db import get_db
from .jmap import MailError

SCRIPT = "someless"
USING = "urn:ietf:params:jmap:sieve"
PROPERTIES = ("from", "to", "cc", "any_recipient", "subject", "body", "header", "size", "sent_date")
TEXT_OPS = ("contains", "not_contains", "is", "is_not", "starts", "not_starts", "ends", "not_ends", "matches",
            "not_matches", "regex", "not_regex", "exists", "not_exists")
SIZE_OPS = ("greater", "less", "greater_or_equal", "less_or_equal")
DATE_OPS = ("after", "before", "on", "not_on", "on_or_after", "on_or_before")
ACTIONS = ("move", "copy", "forward", "read", "favorite", "keep", "discard", "delete")
LONGEST_NAME = 100
MOST_RULES = 100
MOST_CONDITIONS = 30
BIGGEST_SIZE = 2048 * 1024 ** 2   # PrivateEmail's "Size must not exceed 2048 MB"
HEADER_NAME = re.compile(r"^[!-9;-~]+$")   # printable ASCII, no spaces or colons
ADDRESS = re.compile(r"^[^@\s<>(),;:\"\[\]\\]+@[^@\s<>(),;:\"\[\]\\]+\.[^@\s<>(),;:\"\[\]\\]+$")


class RuleProblem(Exception):
    """A rule that can't be: what's wrong, in the words PrivateEmail uses."""


# --- kept here ---

def rules(mailbox_id):
    """The mailbox's filters, in their order: [{"id", "name", "enabled", "operator", "conditions",
    "actions", "stop"}]."""
    found = []
    for row in get_db().execute("SELECT id, name, enabled, rule FROM webmail_rules WHERE mailbox_id = ? ORDER BY position, id",
                                (mailbox_id,)):
        rule = json.loads(row["rule"] or "{}")
        found.append({"id": row["id"], "name": row["name"], "enabled": bool(row["enabled"]),
                      "operator": rule.get("operator", "all"), "conditions": rule.get("conditions", []),
                      "actions": rule.get("actions", []), "stop": bool(rule.get("stop"))})
    return found


def settings(mailbox_id):
    """Forwarding and the auto-reply, as kept: {"forward_to", "forward_on", "forward_keep",
    "reply_on", "reply_start", "reply_end", "reply_subject", "reply_html"}."""
    row = get_db().execute("SELECT forward_to, forward_on, forward_keep, reply_on, reply_start, reply_end, reply_subject,"
                           " reply_html FROM webmail_settings WHERE mailbox_id = ?", (mailbox_id,)).fetchone()
    if row is None:
        return {"forward_to": None, "forward_on": False, "forward_keep": True, "reply_on": False, "reply_start": None,
                "reply_end": None, "reply_subject": "", "reply_html": ""}
    kept = dict(row)
    for key in ("forward_on", "forward_keep", "reply_on"):
        kept[key] = bool(kept[key])
    kept["reply_subject"] = kept["reply_subject"] or ""
    kept["reply_html"] = kept["reply_html"] or ""
    return kept


def save_settings(mailbox_id, **values):
    database = get_db()
    database.execute("INSERT INTO webmail_settings (mailbox_id) VALUES (?) ON CONFLICT (mailbox_id) DO NOTHING", (mailbox_id,))
    for key, value in values.items():
        if key not in ("forward_to", "forward_on", "forward_keep", "reply_on", "reply_start", "reply_end", "reply_subject",
                       "reply_html"):
            raise ValueError(key)
        database.execute(f"UPDATE webmail_settings SET {key} = ? WHERE mailbox_id = ?",
                         (int(value) if isinstance(value, bool) else value, mailbox_id))
    database.commit()


# --- a rule, checked ---

def _text(value, most=1000):
    return " ".join(str(value or "").split())[:most]


def _condition(condition, depth=0):
    if not isinstance(condition, dict):
        raise RuleProblem("Filter condition requires an argument.")
    if "group" in condition:
        if depth:
            raise RuleProblem("Nested conditions group operator must be one of the predefined ones.")
        if condition.get("group") not in ("all", "any"):
            raise RuleProblem("Nested conditions group operator must be one of the predefined ones.")
        inner = [_condition(one, depth + 1) for one in condition.get("conditions") or []][:MOST_CONDITIONS]
        if not inner:
            raise RuleProblem("A nested conditions group needs at least one condition.")
        return {"group": condition["group"], "conditions": inner}
    prop, op = condition.get("prop"), condition.get("op")
    if prop not in PROPERTIES:
        raise RuleProblem("Mail property must be one of the predefined values.")
    allowed = SIZE_OPS if prop == "size" else DATE_OPS if prop == "sent_date" else TEXT_OPS
    if op not in allowed:
        raise RuleProblem("Operator must be one of the predefined ones.")
    made = {"prop": prop, "op": op}
    if prop == "header":
        names = [name.strip() for name in condition.get("headers") or [] if str(name).strip()]
        if not names:
            raise RuleProblem("At least one header name is required.")
        if any(not HEADER_NAME.match(name) for name in names):
            raise RuleProblem("A header name may contain only printable ASCII characters, without spaces or colons.")
        if len({name.lower() for name in names}) != len(names):
            raise RuleProblem("This header name is already listed.")
        made["headers"] = names[:10]
    if op in ("exists", "not_exists"):
        return made
    value = str(condition.get("value") or "").strip()
    if prop == "size":
        if not value.isdigit():
            raise RuleProblem("Size in bytes must be a whole number.")
        if int(value) <= 0:
            raise RuleProblem("Size must be greater than zero.")
        if int(value) > BIGGEST_SIZE:
            raise RuleProblem("Size must not exceed 2048 MB.")
        made["value"] = int(value)
    elif prop == "sent_date":
        try:
            made["value"] = datetime.date.fromisoformat(value).isoformat()
        except ValueError:
            raise RuleProblem("A date is required for this condition." if not value else "Please enter a valid date.")
    else:
        if not value:
            raise RuleProblem("Filter condition requires an argument.")
        if prop == "subject" and len(value) < 2:
            raise RuleProblem("Subject condition value must be at least 2 characters long.")
        if op in ("regex", "not_regex"):
            try:
                re.compile(value)
            except re.error:
                raise RuleProblem("That regular expression can't be used.")
        made["value"] = value[:1000]
    return made


def check(rule, folder_ids):
    """The rule as it's kept, or RuleProblem. folder_ids: the mailbox's folders (their JMAP ids)."""
    name = _text(rule.get("name"), LONGEST_NAME)
    if not name:
        raise RuleProblem("A name for the rule is required.")
    if len(name) < 2:
        raise RuleProblem("Rule name must be at least 2 characters long (without spaces at the ends).")
    operator = rule.get("operator", "all")
    if operator not in ("all", "any", "none"):
        raise RuleProblem("Operator must be one of the predefined ones.")
    conditions = [] if operator == "none" else [_condition(one) for one in rule.get("conditions") or []][:MOST_CONDITIONS]
    if operator != "none" and not conditions:
        raise RuleProblem("At least one condition or group is required.")
    actions = []
    for action in rule.get("actions") or []:
        kind = action.get("type") if isinstance(action, dict) else None
        if kind not in ACTIONS:
            raise RuleProblem("Choose what the filter does.")
        made = {"type": kind}
        if kind in ("move", "copy"):
            if action.get("folder") not in folder_ids:
                raise RuleProblem("Folder name is required for this action.")
            made["folder"] = action["folder"]
        if kind == "forward":
            address = str(action.get("address") or "").strip()
            if not address:
                raise RuleProblem("Email address is required for this action.")
            if len(address) > 254:
                raise RuleProblem("Email address cannot exceed 254 characters.")
            if not ADDRESS.match(address):
                raise RuleProblem("Enter a valid email address.")
            made["address"] = address
            made["keep"] = bool(action.get("keep", True))
        actions.append(made)
    if not actions:
        raise RuleProblem("Choose what the filter does.")
    return {"name": name, "enabled": bool(rule.get("enabled", True)), "operator": operator, "conditions": conditions,
            "actions": actions[:10], "stop": bool(rule.get("stop"))}


# --- the script ---

def _quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _literal(value):
    """A value for :matches, its own * and ? taken as they are."""
    return str(value).replace("\\", "\\\\").replace("*", "\\*").replace("?", "\\?")


def _test(condition, needs):
    if "group" in condition:
        inner = ", ".join(_test(one, needs) for one in condition["conditions"])
        return f"{'allof' if condition['group'] == 'all' else 'anyof'}({inner})"
    prop, op = condition["prop"], condition["op"]
    if prop == "size":
        value = condition["value"]
        return {"greater": f"size :over {value}", "less": f"size :under {value}",
                "greater_or_equal": f"not size :under {value}", "less_or_equal": f"not size :over {value}"}[op]
    if prop == "sent_date":
        needs.update(("date", "relational"))
        relation = {"after": "gt", "before": "lt", "on": "eq", "not_on": "ne", "on_or_after": "ge", "on_or_before": "le"}[op]
        return f'date :value "{relation}" "date" "date" {_quote(condition["value"])}'
    fields = {"from": ["from"], "to": ["to"], "cc": ["cc"], "any_recipient": ["to", "cc"], "subject": ["subject"],
              "header": condition.get("headers", [])}.get(prop)
    listed = "[" + ", ".join(_quote(field) for field in fields) + "]" if fields else ""
    if op in ("exists", "not_exists"):
        test = f"exists {listed}" if prop != "body" else "true"
        return test if op == "exists" else f"not {test}"
    negated = op.startswith("not_") or op == "is_not"
    base = {"contains": "contains", "not_contains": "contains", "is": "is", "is_not": "is", "starts": "starts",
            "not_starts": "starts", "ends": "ends", "not_ends": "ends", "matches": "matches", "not_matches": "matches",
            "regex": "regex", "not_regex": "regex"}[op]
    value = condition["value"]
    if base == "starts":
        match, pattern = ":matches", _quote(_literal(value) + "*")
    elif base == "ends":
        match, pattern = ":matches", _quote("*" + _literal(value))
    elif base == "regex":
        needs.add("regex")
        match, pattern = ":regex", _quote(value)
    else:
        match, pattern = f":{base}", _quote(value)
    if prop == "body":
        needs.add("body")
        test = f"body :text {match} {pattern}"
    elif prop in ("from", "to", "cc", "any_recipient"):
        test = f"address :all {match} {listed} {pattern}"
    else:
        test = f"header {match} {listed} {pattern}"
    return f"not {test}" if negated else test


def _actions(rule, folders, needs):
    lines = []
    ordered = sorted(rule["actions"], key=lambda action: 0 if action["type"] in ("read", "favorite") else 1)
    for action in ordered:
        kind = action["type"]
        if kind == "read":
            needs.add("imap4flags")
            lines.append('addflag "\\\\Seen";')
        elif kind == "favorite":
            needs.add("imap4flags")
            lines.append('addflag "\\\\Flagged";')
        elif kind in ("move", "copy", "delete"):
            folder = folders.get(action.get("folder")) if kind != "delete" else folders.get("trash")
            if not folder:
                continue
            needs.update(("fileinto", "mailbox", "mailboxid"))   # (the engine asks for "mailbox" with :mailboxid too)
            copy = ":copy " if kind == "copy" else ""
            if copy:
                needs.add("copy")
            lines.append(f"fileinto {copy}:mailboxid {_quote(folder['id'])} {_quote(folder['name'])};")
        elif kind == "forward":
            if action.get("keep", True):
                needs.add("copy")
                lines.append(f"redirect :copy {_quote(action['address'])};")
            else:
                lines.append(f"redirect {_quote(action['address'])};")
        elif kind == "keep":
            lines.append("keep;")
        elif kind == "discard":
            lines.append("discard;")
    if rule["stop"]:
        lines.append("stop;")
    return lines


def _vacation(kept, own, needs):
    """The auto-reply: once a day to each sender, between its dates (in UTC, as kept)."""
    if not (kept["reply_on"] and kept["reply_html"]):
        return []
    needs.update(("vacation", "date", "relational"))
    body = (f"Content-Type: text/html; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n"
            f"<!doctype html><html><body>{kept['reply_html']}</body></html>")
    stuffed = "\n".join("." + line if line.startswith(".") else line for line in body.replace("\r\n", "\n").split("\n"))
    addresses = "[" + ", ".join(_quote(address) for address in own) + "]"
    subject = _quote(kept["reply_subject"] or "Auto-reply")
    command = [f"vacation :days 1 :subject {subject} :from {_quote(own[0])} :addresses {addresses} :mime text:", stuffed, ".", ";"]
    dates = []
    if kept.get("reply_start"):
        dates.append(f'currentdate :zone "+0000" :value "ge" "iso8601" {_quote(kept["reply_start"])}')
    if kept.get("reply_end"):
        dates.append(f'currentdate :zone "+0000" :value "le" "iso8601" {_quote(kept["reply_end"])}')
    if not dates:
        return command
    return [f"if allof({', '.join(dates)}) {{"] + ["    " + line if index == 0 else line for index, line in enumerate(command)] + ["}"]


def script(kept, rule_list, folders, own):
    """The whole script. folders: {folder id: {"id", "name"}, "trash": {...}}; own: the mailbox's
    addresses (the auto-reply's :from and :addresses)."""
    needs = set()
    body = ["# Written by the Someless webmail (Settings): auto-reply, forwarding and filters.",
            "# Changed there, it's written again."]
    body += _vacation(kept, own, needs)
    if kept["forward_on"] and kept["forward_to"]:
        if kept["forward_keep"]:
            needs.add("copy")
            body.append(f"redirect :copy {_quote(kept['forward_to'])};")
        else:
            body.append(f"redirect {_quote(kept['forward_to'])};")
    for rule in rule_list:
        if not rule["enabled"]:
            continue
        actions = _actions(rule, folders, needs)
        if not actions:
            continue
        if rule["operator"] == "none":
            head = "if true {"
        else:
            tests = [_test(condition, needs) for condition in rule["conditions"]]
            head = f"if {'allof' if rule['operator'] == 'all' else 'anyof'}({', '.join(tests)}) {{"
        body.append(f"# {rule['name'].replace(chr(10), ' ')}")
        body.append(head)
        body += ["    " + line for line in actions]
        body.append("}")
    require = f"require [{', '.join(_quote(extension) for extension in sorted(needs))}];" if needs else ""
    return "\n".join(([require] if require else []) + body) + "\n"


def install(mail, text):
    """The script into the engine, as the mailbox's active one (MailError when it won't take it)."""
    upload = mail.upload(text.encode("utf-8"), "application/sieve")
    found = mail.call(("SieveScript/get", {}), using=[USING])[0]["list"]
    mine = next((one for one in found if one.get("name") == SCRIPT), None)
    if mine:
        result = mail.call(("SieveScript/set", {"update": {mine["id"]: {"blobId": upload["blobId"]}},
                                                "onSuccessActivateScript": mine["id"]}), using=[USING])[0]
        if mine["id"] not in (result.get("updated") or {}):
            raise MailError(f"SieveScript/set: {(result.get('notUpdated') or {}).get(mine['id'])}")
    else:
        result = mail.call(("SieveScript/set", {"create": {"new": {"name": SCRIPT, "blobId": upload["blobId"]}},
                                                "onSuccessActivateScript": "#new"}), using=[USING])[0]
        if "new" not in (result.get("created") or {}):
            raise MailError(f"SieveScript/set: {(result.get('notCreated') or {}).get('new')}")


def write(mail, tree, own):
    """The mailbox's rules, written again into the engine (after any change in Settings)."""
    folders = {folder["id"]: {"id": folder["id"], "name": tree.engine_path(folder)} for folder in tree.list}
    trash = tree.role("trash")
    if trash:
        folders["trash"] = folders[trash["id"]]
    install(mail, script(settings(g.mailbox["id"]), rules(g.mailbox["id"]), folders, own))
