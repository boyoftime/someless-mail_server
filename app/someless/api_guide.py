"""The API guide (/api-keys/docs): every call of the API (api.py), as in Postman: what it does and
its fields, beside its request (in cURL, JavaScript, Python and PHP, filled in with the panel's own
address and one of the admin's domains) and its response. Each request reads the key from the
SOMELESS_API_KEY environment variable, so the key never sits in the code."""
import json
import re

from markupsafe import escape

from .smtp_guide import highlight

LANGUAGES = [("curl", "cURL"), ("javascript", "JavaScript"), ("python", "Python"), ("php", "PHP")]
KEYWORDS = {
    "curl": "curl",
    "javascript": "const await new throw if true false null",
    "python": "import from if not raise True False None",
    "php": "true false null if exit",
    "json": "true false null",
}
STATUS = {200: "200 OK", 201: "201 Created", 404: "404 Not Found", 429: "429 Too Many Requests"}
EXAMPLE_PASSWORD = "Choose-A-Strong-1!"


def calls(base, domain):
    """The calls, in groups: each with its method, path, what it does, its fields (name, type,
    what it is, required), an example request in each language, and its response."""
    sender = {"id": 3, "name": "PineLoop INC", "email": f"no-reply@{domain}", "domain": domain, "has_mailbox": False,
              "disabled": False, "created_at": "2026-10-01T09:30:00+00:00"}
    mailbox = {"id": 7, "email": f"sales@{domain}", "name": "Sales Team", "domain": domain, "storage": "15 GB",
               "storage_bytes": 15 * 1024 ** 3, "used_bytes": 52428800, "send_limit_mb": 50,
               "disable_delete": {"webmail": False, "apps": False}, "aliases": [f"orders@{domain}"],
               "disabled": False, "refuse_mail": False, "picture_url": f"{base}/mailboxes/7/picture",
               "created_at": "2026-10-01T09:30:00+00:00"}
    disabled = ("disabled", "true or false", "Disable it, or enable it again. A sender and its mailbox (the same "
                "address) go together: nothing can send as it, and nobody can sign in to the mailbox (the webmail, mail "
                "apps, calendar apps). Its mail stays.")
    refuse_mail = ("refuse_mail", "true or false", "While its mailbox is disabled: new mail to it bounces back to whoever "
                   "sent it. False: new mail still arrives, and waits. Enabling turns it off.")
    name = ("name", "text", "What people see the mail come from, like PineLoop INC: up to 70 characters.")
    email = ("email", "text", "The address, at one of your authenticated domains.")
    password = ("password", "text", "Follows your mailbox password rules (the Password rules on the Mailboxes page).")
    storage = ("storage", "text", 'How much mail it holds, like "15 GB" or "500 MB".')
    send_limit = ("send_limit_mb", "number", "The most a message it sends may carry in files: 1 to 100 MB. 50 to start.")
    disable_delete = ("disable_delete", "object", '{"webmail": true or false, "apps": true or false}. webmail: nothing '
                      "is deleted in the webmail. apps: mail apps can't erase messages. Both false to start.")
    new_mailbox = {"email": f"sales@{domain}", "name": "Sales Team", "password": EXAMPLE_PASSWORD, "storage": "15 GB",
                   "send_limit_mb": 50, "disable_delete": {"webmail": False, "apps": False}, "aliases": [f"orders@{domain}"]}
    new = "newdomain.com"

    def records(state):   # a domain's records to add, as an answer shows them
        made = [("code", "Someless code", "Shows that the domain is yours.", "TXT", "@", "someless-code:7f3a9c2e5b1d4a60"),
                ("a", "Mail server address", f"Points mail.{new} at this server.", "A", "mail", "203.0.113.10"),
                ("spf", "SPF record", "Lets this server send the domain's mail.", "TXT", "@", f"v=spf1 a:mail.{new} mx ~all"),
                ("dkim", "DKIM record", "Signs the domain's mail, so nobody can fake it.", "TXT", "someless._domainkey",
                 "v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA… (the domain's own key, in full)"),
                ("dmarc", "DMARC record", "Tells other mail servers what to do with mail that fails these checks.", "TXT",
                 "_dmarc", "v=DMARC1; p=none")]
        listed = [{"key": key, "title": title, "purpose": purpose, "type": kind, "host": host,
                   "full_host": new if host == "@" else f"{host}.{new}", "value": value, "priority": None, "state": state,
                   "note": None} for key, title, purpose, kind, host, value in made]
        return [*listed, {"key": "mx", "title": "MX record", "purpose": "Sends the domain's incoming mail to this server.",
                          "type": "MX", "host": "@", "full_host": new, "value": f"mail.{new}", "priority": 10,
                          "state": state, "note": None}]

    added = {"id": 2, "name": new, "authenticated": False, "provider": "Cloudflare", "records": records("not checked"),
             "checked_at": None}
    authenticated = {**added, "authenticated": True, "records": records("found"), "checked_at": "2026-10-01T09:45:00+00:00"}
    domain_name = ("name", "text", "The domain, like example.com: the part of an email address after the @.")
    groups = [
        {"title": "Domains", "id": "domains", "calls": [
            {"method": "GET", "path": "/domains", "name": "List domains", "text": "Every domain, saying whether it's "
             "authenticated: senders and mailboxes can only be at authenticated ones.",
             "answer": {"domains": [{"name": domain, "authenticated": True}, {"name": new, "authenticated": False}]}},
            {"method": "POST", "path": "/domains", "name": "Add a domain", "text": "Add a domain. The answer lists the DNS "
             "records to add where its DNS is managed (its domain provider), each fitting what the domain has now: a note "
             "says when one of yours is to be changed instead, like its SPF record. Add them all, then authenticate it.",
             "status": 201, "fields": [(*domain_name, True)], "body": {"name": new}, "answer": {"domain": added}},
            {"method": "GET", "path": "/domains/{name}", "name": "Get a domain", "example": f"/domains/{new}",
             "text": "One domain, with its DNS records and how each one last checked: found, missing, different (there, "
             "but not as it should be), elsewhere (MX: its mail still goes to another service), or not checked.",
             "answer": {"domain": added}},
            {"method": "POST", "path": "/domains/{name}/authenticate", "name": "Authenticate a domain",
             "example": f"/domains/{new}/authenticate", "text": "Look its records up in DNS now. When they're all there, "
             "it's authenticated, and senders and mailboxes can be made at it; else the message says what's still to "
             "add or fix. New records can take a while to show up: check again later.",
             "answer": {"domain": authenticated, "message": f"{new} is authenticated."}},
            {"method": "DELETE", "path": "/domains/{name}", "name": "Delete a domain", "example": f"/domains/{new}",
             "text": "Delete a domain, with its senders. Not while it has mailboxes or aliases: delete those first.",
             "answer": {"deleted": True}},
        ]},
        {"title": "Senders", "id": "senders", "calls": [
            {"method": "GET", "path": "/senders", "name": "List senders", "text": "All your senders, the newest first.",
             "answer": {"senders": [sender]}},
            {"method": "POST", "path": "/senders", "name": "Add a sender", "text": "Add a sender.", "status": 201,
             "fields": [(*name, True), (*email, True)], "body": {"name": "PineLoop INC", "email": f"no-reply@{domain}"},
             "answer": {"sender": sender}},
            {"method": "GET", "path": "/senders/{id}", "name": "Get a sender", "example": "/senders/3", "text": "One sender.",
             "answer": {"sender": sender}},
            {"method": "PATCH", "path": "/senders/{id}", "name": "Change a sender", "example": "/senders/3", "text": "Change a sender: send only "
             "what changes. A sender with a mailbox keeps its address. Disabling it disables its mailbox too.",
             "fields": [(*name, False), (*email, False), (*disabled, False), (*refuse_mail, False)],
             "body": {"name": "PineLoop Ltd"}, "answer": {"sender": {**sender, "name": "PineLoop Ltd"}}},
            {"method": "DELETE", "path": "/senders/{id}", "name": "Delete a sender", "example": "/senders/3", "text": "Delete a sender. One with a "
             "mailbox stays until its mailbox is deleted.", "answer": {"deleted": True}},
        ]},
        {"title": "Mailboxes", "id": "mailboxes", "calls": [
            {"method": "GET", "path": "/mailboxes", "name": "List mailboxes", "text": "All your mailboxes, the newest first. used_bytes is how much "
             "mail each holds now (null while the mail engine can't say).", "answer": {"mailboxes": [mailbox]}},
            {"method": "POST", "path": "/mailboxes", "name": "Make a mailbox", "text": "Make a mailbox, with every option the panel has. Give name "
             "when the address isn't a sender yet, and the sender is added too, in the same call.", "status": 201,
             "fields": [(*email, True), (*password, True), (*storage, True),
                        ("name", "text", "The sender's name. Adds the sender when there's none at this address yet "
                         "(or renames the one there).", False),
                        (*send_limit, False), (*disable_delete, False),
                        ("aliases", "list", f'More addresses whose mail lands in it, like ["orders@{domain}"], '
                         "at your authenticated domains.", False)],
             "body": new_mailbox, "answer": {"mailbox": mailbox}},
            {"method": "GET", "path": "/mailboxes/{id}", "name": "Get a mailbox", "example": "/mailboxes/7", "text": "One mailbox.",
             "answer": {"mailbox": mailbox}},
            {"method": "PATCH", "path": "/mailboxes/{id}", "name": "Change a mailbox", "example": "/mailboxes/7", "text": "Change a mailbox: send "
             "only what changes (in disable_delete too). A new password signs out mail apps that use the old one. "
             "Disabling it disables its sender too.",
             "fields": [(*password, False), (*storage, False), (*send_limit, False), (*disable_delete, False),
                        (*disabled, False), (*refuse_mail, False)],
             "body": {"storage": "20 GB", "disable_delete": {"apps": True}},
             "answer": {"mailbox": {**mailbox, "storage": "20 GB", "storage_bytes": 20 * 1024 ** 3,
                                    "disable_delete": {"webmail": False, "apps": True}}}},
            {"method": "POST", "path": "/mailboxes/password", "name": "Reset a password", "text": "Reset a mailbox's password by its address: for "
             "someone who has forgotten theirs. Make sure it's really them in your app first. The webmail and mail apps "
             "signed in with the old password ask for the new one.",
             "fields": [("email", "text", "The mailbox's address.", True),
                        ("password", "text", "The new password. Follows your mailbox password rules (the Password rules "
                         "on the Mailboxes page).", True),
                        ("confirm_password", "text", "The new password again: the two have to match.", True)],
             "body": {"email": f"sales@{domain}", "password": EXAMPLE_PASSWORD, "confirm_password": EXAMPLE_PASSWORD},
             "answer": {"mailbox": mailbox}},
            {"method": "POST", "path": "/mailboxes/login", "name": "Check a mailbox's password", "text": "Check an address "
             "and password, for an app where people sign in with their mailbox. The answer says whether they match, and "
             "if they do, who it is: their name, to greet them (the one their mail goes out with), and their mailbox. Call "
             "it from your app's server, never from a browser, since the key must stay secret, and never keep the "
             "password. Wrong passwords count towards the webmail's sign-in lock (Settings, Miscellaneous in the panel): "
             "after too many in a row the address waits a while, however it signs in.",
             "fields": [("email", "text", "The address the person typed.", True),
                        ("password", "text", "The password they typed.", True)],
             "body": {"email": f"sales@{domain}", "password": EXAMPLE_PASSWORD},
             "answer": {"valid": True, "email": f"sales@{domain}", "name": "Sales Team",
                        "picture": "data:image/webp;base64,UklGRlYAAABXRUJQVlA4…", "mailbox": mailbox},
             "outcomes": [(200, {"valid": False, "reason": "wrong"},
                           "The address or the password is wrong: the same answer for both, so it never tells which "
                           "addresses have a mailbox."),
                          (200, {"valid": False, "reason": "disabled"},
                           "The password is right, but the mailbox is disabled: nobody can sign in to it."),
                          (429, {"valid": False, "reason": "locked", "retry_after": 300},
                           "Too many wrong passwords in a row: the address can try again after retry_after seconds "
                           "(also in the Retry-After header).")]},
            {"method": "GET", "path": "/mailboxes/{id}/picture", "name": "Get a profile picture", "example": "/mailboxes/7/picture",
             "text": "The mailbox's profile picture, as its owner chose it in the webmail (Settings, Profile): a "
             "WebP picture, 512 by 512 pixels, to show beside their name. A mailbox's picture_url says where it is, or is "
             "null without one; a password check's answer brings it too, ready to show.",
             "answer": "The picture itself: Content-Type image/webp.", "binary": True,
             "outcomes": [(404, {"error": "This mailbox has no profile picture."},
                           "There's no picture: show their initial instead.")]},
            {"method": "DELETE", "path": "/mailboxes/{id}", "name": "Delete a mailbox", "example": "/mailboxes/7", "text": "Delete a mailbox, its "
             "aliases and all the mail in it. This can't be undone. Its sender stays.", "answer": {"deleted": True}},
            {"method": "POST", "path": "/mailboxes/{id}/aliases", "name": "Add an alias", "example": "/mailboxes/7/aliases", "text": "Add an "
             "alias: another address whose mail lands in the mailbox.", "status": 201,
             "fields": [("email", "text", "The alias, at one of your authenticated domains.", True)],
             "body": {"email": f"shop@{domain}"},
             "answer": {"mailbox": {**mailbox, "aliases": [f"orders@{domain}", f"shop@{domain}"]}}},
            {"method": "DELETE", "path": "/mailboxes/{id}/aliases/{alias}", "name": "Delete an alias", "example": f"/mailboxes/7/aliases/orders@{domain}",
             "text": f"Delete an alias: {{alias}} is its address, like orders@{domain}.",
             "answer": {"mailbox": {**mailbox, "aliases": []}}},
        ]},
    ]
    for group in groups:
        for call in group["calls"]:
            call["id"] = "call-" + "-".join([call["method"].lower(), *re.findall(r"[a-z]+", call["path"])])
            call["status"] = STATUS[call.get("status", 200)]
            call["requests"] = _requests(call["method"], base + call.get("example", call["path"]), call.get("body"),
                                         call.get("binary", False))
            answer = call.pop("answer")
            if call.get("binary"):   # (a file, not JSON: what it is, in words)
                call["answer"] = {"code": answer, "html": escape(answer)}
            else:
                answer = json.dumps(answer, indent=2)
                call["answer"] = {"code": answer, "html": highlight(answer, "json", KEYWORDS)}
            call["outcomes"] = [{"status": STATUS[code], "ok": code < 400, "text": text,
                                 "code": json.dumps(other), "html": highlight(json.dumps(other), "json", KEYWORDS)}
                                for code, other, text in call.get("outcomes", [])]
    return groups


def as_text(base):
    """The whole guide in plain text (Markdown), for an AI assistant to read: the public link
    (/api/s1/docs.md) and "Copy the whole guide". Open to anyone, so example.com stands in for the
    admin's own domains (an app finds them with GET /domains)."""
    lines = [
        "# The Someless Mail API", "",
        "An API for a Someless Mail server's senders and mailboxes: everything its panel can do with them, an app can "
        "do with these calls. This is the whole API in plain text, for AI assistants and developers.", "",
        "## Basics", "",
        f"- Base URL: `{base}`. Each call's path goes after it, like `{base}/mailboxes`.",
        "- Authentication: every call sends an API key in the header `Authorization: Bearer <API key>`. The server's "
        "admin makes keys in the panel, on the API keys page. A key starts with `sm_`.",
        "- Format: what's sent and every response is JSON (`Content-Type: application/json`).",
        "- Senders and mailboxes can only be at the server's authenticated domains: `GET /domains` lists every domain, "
        "saying whether it's authenticated. The examples here use `example.com` in their place.",
        "- A mailbox's display name is its sender's name. A mailbox is made for a sender: `POST /mailboxes` with `name` "
        "adds the sender too, in the same call.",
        "- A call does all it was asked or nothing at all. `PATCH` changes only the fields sent.",
        "- A sender and its mailbox (the same address) can be disabled, and enabled again, together: `PATCH` either one "
        "with `\"disabled\": true`. Nothing can send as a disabled sender, nobody can sign in to a disabled mailbox, and "
        "with `\"refuse_mail\": true` new mail to it bounces. No new mailbox is made for a disabled sender.", "",
        "## For AI assistants helping with an integration", "",
        "- Call the API from the app's server, never from a web page: the key must stay secret.",
        "- Read the key from an environment variable, `SOMELESS_API_KEY`: never in the code, a repository or a log.",
        "- Start with `GET /domains`, and make addresses at one of its authenticated domains. A new domain is added "
        "with `POST /domains`: its answer lists the DNS records to add at the domain provider; once they're added, "
        "`POST /domains/{name}/authenticate` checks them.",
        "- When a call is refused, show its `error` text to the person using the app: it says what to fix, plainly.", "",
        "## Errors", "",
        'A refused call answers `{"error": "…"}` with one of these statuses:', "",
        "- 400: refused, like an address at a domain that isn't authenticated, a password the server's rules don't "
        "take, an address already taken, or a field that isn't one of the call's.",
        "- 401: no API key, a wrong one, or one that has expired or been deleted.",
        "- 404: no sender, mailbox or alias with that id or address, or no such call.",
        "- 405: the call doesn't take that method.",
        "- 429: too many wrong keys from one IP address (10 within 10 minutes). Wait the number of seconds in the "
        "`Retry-After` header.",
    ]
    for group in calls(base, "example.com"):
        lines += ["", f"# {group['title']}"]
        for call in group["calls"]:
            lines += ["", f"## {call['method']} {call['path']}", "", call["text"], ""]
            if call.get("fields"):
                lines += ["| Field | Type | Required | What it is |", "|---|---|---|---|"]
                lines += [f"| `{name}` | {kind} | {'yes' if required else 'no'} | {text} |"
                          for name, kind, text, required in call["fields"]]
            else:
                lines.append("No fields: nothing to send but the key.")
            curl = next(request["code"] for request in call["requests"] if request["key"] == "curl")
            lines += ["", "Request:", "", "```bash", curl.rstrip("\n"), "```", "", f"Response: {call['status']}", ""]
            lines += [call["answer"]["code"]] if call.get("binary") else ["```json", call["answer"]["code"], "```"]
            if call["outcomes"]:
                lines += ["", "Other responses:", ""]
                lines += [f"- {other['status']} `{other['code']}`: {other['text']}" for other in call["outcomes"]]
    return "\n".join(lines) + "\n"


def _requests(method, url, body, binary=False):
    """The request in each language: its code, and its code coloured. binary: the answer is a file
    (a picture), saved as one, not read as JSON."""
    made = {"curl": _curl, "javascript": _javascript, "python": _python, "php": _php}
    if binary:
        made = {"curl": _curl_file, "javascript": _javascript_file, "python": _python_file, "php": _php_file}
    return [{"key": key, "name": name, "code": code, "html": highlight(code, key, KEYWORDS)}
            for key, name in LANGUAGES for code in [made[key](method, url, body)]]


# --- what's sent, as each language writes it: the fields one to a line, what's inside them inline ---

STEP = {"json": 2, "python": 4, "php": 4}
WORDS = {"json": {True: "true", False: "false", None: "null"}, "python": {True: "True", False: "False", None: "None"},
         "php": {True: "true", False: "false", None: "null"}}


def _inline(value, style):
    if isinstance(value, dict):
        between = " => " if style == "php" else ": "
        fields = ", ".join(json.dumps(key) + between + _inline(item, style) for key, item in value.items())
        return f"[{fields}]" if style == "php" else f"{{{fields}}}"
    if isinstance(value, list):
        return "[" + ", ".join(_inline(item, style) for item in value) + "]"
    if isinstance(value, bool) or value is None:
        return WORDS[style][value]
    return json.dumps(value)


def _block(body, style, indent):
    """The body over several lines, starting where the line it's on left off, at this indent."""
    between = " => " if style == "php" else ": "
    opening, closing = ("[", "]") if style == "php" else ("{", "}")
    inner = " " * (indent + STEP[style])
    lines = [inner + json.dumps(key) + between + _inline(item, style) for key, item in body.items()]
    joined = ",\n".join(lines) + ("" if style == "json" else ",")   # (JSON takes no comma after the last)
    return f"{opening}\n{joined}\n{' ' * indent}{closing}"


def _curl(method, url, body):
    lines = [f'curl "{url}"' if method == "GET" else f'curl -X {method} "{url}"',
             '  -H "Authorization: Bearer $SOMELESS_API_KEY"']
    if body is not None:
        lines += ['  -H "Content-Type: application/json"', "  -d '" + _block(body, "json", 2) + "'"]
    return " \\\n".join(lines) + "\n"


def _javascript(method, url, body):
    options = [] if method == "GET" else [f'  method: "{method}",']
    headers = ['    "Authorization": "Bearer " + process.env.SOMELESS_API_KEY,']
    if body is not None:
        headers.append('    "Content-Type": "application/json",')
    options.append("  headers: {\n" + "\n".join(headers) + "\n  },")
    if body is not None:
        options.append("  body: JSON.stringify(" + _block(body, "json", 2) + "),")
    return (f'const response = await fetch("{url}", {{\n' + "\n".join(options) + "\n});\n"
            "const answer = await response.json();\n"
            "if (!response.ok) throw new Error(answer.error);\n")


def _python(method, url, body):
    arguments = [f'    "{url}",', '    headers={"Authorization": "Bearer " + key},']
    if body is not None:
        arguments.append("    json=" + _block(body, "python", 4) + ",")
    return ("import os\n\nimport requests  # pip install requests\n\n"
            'key = os.environ["SOMELESS_API_KEY"]\n'
            f"response = requests.{method.lower()}(\n" + "\n".join(arguments) + "\n)\n"
            "answer = response.json()\n"
            "if not response.ok:\n"
            '    raise SystemExit(answer["error"])\n')


def _php(method, url, body):
    options = [] if method == "GET" else [f'    CURLOPT_CUSTOMREQUEST => "{method}",']
    options.append("    CURLOPT_RETURNTRANSFER => true,")
    headers = ['        "Authorization: Bearer " . getenv("SOMELESS_API_KEY"),']
    if body is not None:
        headers.append('        "Content-Type: application/json",')
    options.append("    CURLOPT_HTTPHEADER => [\n" + "\n".join(headers) + "\n    ],")
    if body is not None:
        options.append("    CURLOPT_POSTFIELDS => json_encode(" + _block(body, "php", 4) + "),")
    return ("<?php\n"
            f'$curl = curl_init("{url}");\n'
            "curl_setopt_array($curl, [\n" + "\n".join(options) + "\n]);\n"
            "$answer = json_decode(curl_exec($curl), true);\n"
            "if (curl_getinfo($curl, CURLINFO_RESPONSE_CODE) >= 400) {\n"
            '    exit($answer["error"]);\n'
            "}\n")


# --- a file for an answer (a profile picture): saved as picture.webp ---

def _curl_file(method, url, body):
    return f'curl --fail -o picture.webp "{url}" \\\n  -H "Authorization: Bearer $SOMELESS_API_KEY"\n'


def _javascript_file(method, url, body):
    return (f'const response = await fetch("{url}", {{\n'
            '  headers: { "Authorization": "Bearer " + process.env.SOMELESS_API_KEY },\n'
            "});\n"
            "if (!response.ok) throw new Error((await response.json()).error);\n"
            "const picture = Buffer.from(await response.arrayBuffer());   // image/webp: save it, or send it on\n")


def _python_file(method, url, body):
    return ("import os\n\nimport requests  # pip install requests\n\n"
            'key = os.environ["SOMELESS_API_KEY"]\n'
            f'response = requests.get("{url}", headers={{"Authorization": "Bearer " + key}})\n'
            "if not response.ok:\n"
            '    raise SystemExit(response.json()["error"])\n'
            'with open("picture.webp", "wb") as file:\n'
            "    file.write(response.content)\n")


def _php_file(method, url, body):
    return ("<?php\n"
            f'$curl = curl_init("{url}");\n'
            "curl_setopt_array($curl, [\n"
            "    CURLOPT_RETURNTRANSFER => true,\n"
            '    CURLOPT_HTTPHEADER => ["Authorization: Bearer " . getenv("SOMELESS_API_KEY")],\n'
            "]);\n"
            "$picture = curl_exec($curl);\n"
            "if (curl_getinfo($curl, CURLINFO_RESPONSE_CODE) >= 400) {\n"
            '    exit(json_decode($picture, true)["error"]);\n'
            "}\n"
            'file_put_contents("picture.webp", $picture);\n')
