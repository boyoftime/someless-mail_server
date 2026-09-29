"""Writing mail, as PrivateEmail's composer: a new message, a reply (to the sender, or to all), a
forward, or a draft picked up again. Files are attached by uploading them to the engine first
(/compose/upload); pictures can sit in what it says (sent with it, cid:). It's saved to Drafts
("Save as draft", and on its own as it's written) and sent with JMAP's EmailSubmission, after
which the engine moves it to Sent. The webmail-compose.js windows (and the reply under an open
message) use these:

  /compose/start?kind=new|reply|all|forward|draft&id=  what a composer starts with
  /compose/upload                                        a file, uploaded: {blobId, name, type, size}
  /compose/blob/<blob>                                   a picture uploaded, to show in the editor
  /compose/save, /compose/send, /compose/discard        the message, saved, sent, or its draft deleted
  /compose/suggest?q=                                    addresses to write to, as it's typed"""
import datetime
import html
import re
import time
from email.utils import getaddresses
from html.parser import HTMLParser

import nh3
from flask import Blueprint, Response, g, request, url_for

from . import content, login_required, messages, views
from .jmap import MailError, for_mailbox, ref
from .mail import _counts, _inbox_unread, _stream, _tree, reachable
from ..db import get_db

bp = Blueprint("compose", __name__, url_prefix="/compose")

MAX_FILE = 25 * 1024 ** 2          # one file ("Maximum allowed file size 25 MB")
MAX_ALL = 45 * 1024 ** 2           # all of them (the engine takes 50 MB a message, what it says included)
MOST_RECIPIENTS = 50               # PrivateEmail's "Recipient limit exceeded. The maximum number allowed per email is 50"
LONGEST_SUBJECT = 255
LONGEST_HTML = 8 * 1024 ** 2       # (a request to the engine is 10 MB at most)
SUGGESTIONS = 8
ADDRESS = re.compile(r"^[^@\s<>(),;:\"\[\]\\]+@[^@\s<>(),;:\"\[\]\\]+\.[^@\s<>(),;:\"\[\]\\]+$")
REPLY_PREFIX = re.compile(r"^\s*re\s*:", re.I)
FORWARD_PREFIX = re.compile(r"^\s*(fwd?|fw)\s*:", re.I)
DRAFT_OF = "X-Someless-Draft-Of"   # a draft's own note of what it answers (never sent)
SENT = "Message has been successfully sent"


def _mail():
    return for_mailbox(g.mailbox["email"])


# --- who it's from ---

def _own_addresses():
    """The addresses the mailbox has: its own, then its aliases."""
    rows = get_db().execute("SELECT email FROM mailbox_aliases WHERE mailbox_id = ? ORDER BY email", (g.mailbox["id"],))
    return [g.mailbox["email"]] + [row["email"] for row in rows]


def _display_name():
    """The name its mail goes out with: as set in Settings, else its sender's, else nothing."""
    name = views.display_name(g.mailbox["id"])
    if name:
        return name
    sender = get_db().execute("SELECT name FROM senders WHERE lower(email) = ?", (g.mailbox["email"],)).fetchone()
    return sender["name"] if sender else ""


def _identity(mail, address, name):
    """The engine's identity for sending as this address (made when there's none yet)."""
    found = mail.call(("Identity/get", {}))[0]["list"]
    for identity in found:
        if (identity.get("email") or "").lower() == address.lower():
            return identity["id"]
    result = mail.call(("Identity/set", {"create": {"new": {"name": name, "email": address}}}))[0]
    made = (result.get("created") or {}).get("new")
    if not made:
        raise MailError(f"Identity/set: {(result.get('notCreated') or {}).get('new')}")
    return made["id"]


# --- addresses ---

def parse_addresses(values):
    """What was typed in To, Cc or Bcc: [{"name", "email"}], and the ones that aren't addresses."""
    found, wrong, seen = [], [], set()
    for value in values or []:
        if isinstance(value, dict):
            pairs = [(value.get("name") or "", value.get("email") or "")]
        else:
            pairs = getaddresses([str(value)])
        for name, address in pairs:
            address = address.strip()
            if not address:
                continue
            if not ADDRESS.match(address) or len(address) > 254:
                wrong.append(address)
                continue
            if address.lower() in seen:
                continue
            seen.add(address.lower())
            found.append({"name": " ".join((name or "").split())[:200] or None, "email": address})
    return found, wrong


# --- what it says ---

class _Text(HTMLParser):
    """HTML as plain text: paragraphs and line breaks kept, links as "words (address)"."""
    BLOCKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table", "ul", "ol", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.links = [], 0, []

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head", "title"):
            self.skip += 1
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in self.BLOCKS:
            self.out.append("\n")
        if tag == "a":
            self.links.append(dict(attrs).get("href") or "")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head", "title"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCKS and tag != "li":   # (the next item starts its own line)
            self.out.append("\n")
        if tag == "a" and self.links:
            href = self.links.pop()
            if href.startswith(("http:", "https:")) and not "".join(self.out).rstrip().endswith(href):
                self.out.append(f" ({href})")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(re.sub(r"\s+", " ", data))


def to_text(source):
    parser = _Text()
    parser.feed(source or "")
    parser.close()
    lines = [line.strip() for line in "".join(parser.out).split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


BLOB_SRC = re.compile(r"/compose/blob/([A-Za-z0-9_-]+)")


def clean_outgoing(source, inline):
    """What was written, safe to send: formatting only (as a message is shown, content.py), and
    the pictures uploaded into it (/compose/blob/<blob>) as the parts sent with it (cid:)."""
    by_blob = {part["blobId"]: part for part in inline}

    def attribute(tag, name, value):
        if tag == "img" and name == "src":
            found = BLOB_SRC.search(value or "")
            if found and found.group(1) in by_blob:
                return "cid:" + by_blob[found.group(1)]["cid"]
            if value.lower().startswith(("http:", "https:", "cid:")) or re.match(r"data:image/(png|gif|jpe?g|webp);", value, re.I):
                return value
            return None
        if tag == "a" and name == "href":
            return value if value.strip().lower().startswith(content.LINK_SCHEMES + ("#",)) else None
        return value

    return nh3.clean(source or "", tags=content.TAGS - {"style"}, attributes=content.ATTRIBUTES,
                     attribute_filter=attribute, url_schemes={"http", "https", "mailto", "tel", "cid", "data"},
                     link_rel=None, strip_comments=True, clean_content_tags={"script", "style", "title"})


def _text_html(source):
    """A message in plain text, for the editor: its lines as lines (the editor keeps no pre-wrap)."""
    return content.from_text(source).html.replace("\r\n", "\n").replace("\n", "<br>")


def _for_editor(source, email_id, parts):
    """A message's HTML, to go in the editor: cleaned as when it's read, its pictures shown from
    the engine (/compose/blob), and no <style> (the editor's page is shared)."""
    pictures = {part["cid"]: part for part in parts if part.get("cid") and part.get("image")}

    def picture_url(cid):
        part = pictures.get(cid)
        return url_for("compose.blob", blob_id=part["blob"], type=part["type"]) if part else None

    prepared = content.from_html(source, picture_url)
    return re.sub(r"<style\b[^>]*>.*?</style>", "", prepared.html, flags=re.S | re.I)


def quote_time(iso):
    """When a message came, in a reply's quote: September 28, 2026 at 8:59 PM."""
    try:
        moment = datetime.datetime.fromisoformat((iso or "").replace("Z", "+00:00")).astimezone(messages.zone())
    except ValueError:
        return ""
    hour = (moment.hour - 1) % 12 + 1
    return f"{messages.MONTHS[moment.month - 1]} {moment.day}, {moment.year} at {hour}:{moment.minute:02d} {'PM' if moment.hour >= 12 else 'AM'}"


def _quote(email, title, parts):
    """The message quoted under a reply or a forward, as PrivateEmail quotes it: a line saying
    what it is, who it was from and to, when, its subject, then what it said."""
    kind, source = messages.body(email)
    said = _for_editor(source, email["id"], parts) if kind == "html" else _text_html(source)
    lines = [("From", ", ".join(address.get("email") or "" for address in email.get("from") or []))]
    if email.get("to"):
        lines.append(("To", ", ".join(address.get("email") or "" for address in email["to"])))
    if email.get("cc"):
        lines.append(("Cc", ", ".join(address.get("email") or "" for address in email["cc"])))
    lines.append(("Date", quote_time(email.get("sentAt") or email.get("receivedAt"))))
    lines.append(("Subject", email.get("subject") or ""))
    head = "".join(f"<div>{html.escape(label)}: {html.escape(value)}</div>" for label, value in lines)
    return (f'<p><br></p><blockquote type="cite" class="wm-quote" style="margin:0">'
            f'<p class="wm-quote-title">{html.escape(title)}</p><div class="wm-quote-head">{head}</div>'
            f"<div>{said}</div></blockquote>")


# --- what a composer starts with ---

def _parts(email):
    """A message's files, as the composer keeps them."""
    found = []
    for part in email.get("attachments") or []:
        if not part.get("blobId"):
            continue
        shown = messages._file(part)
        found.append({"blobId": part["blobId"], "name": shown["name"], "type": shown["type"], "size": part.get("size") or 0,
                      "cid": part.get("cid"), "inline": shown["hidden"], "image": shown["image"], "blob": part["blobId"]})
    return found


def _people(addresses):
    return [{"name": address.get("name"), "email": address.get("email")} for address in addresses or [] if address.get("email")]


def _signature_html():
    signatures = views.signatures(g.mailbox["id"])
    chosen = next((signature for signature in signatures if signature["is_default"]), None)
    return chosen


def _load(mail, email_id):
    got = mail.call(("Email/get", {"ids": [email_id], "properties": messages.READ_PROPERTIES + [f"header:{DRAFT_OF}:asText"],
                                   "fetchHTMLBodyValues": True, "fetchTextBodyValues": True,
                                   "maxBodyValueBytes": 4_000_000}))[0]["list"]
    return got[0] if got else None


@bp.get("/start")
@login_required
@reachable
def start():
    """A composer's fields and what it says, to start with: {from, froms, to, cc, bcc, subject,
    html, attachments, important, reply, draft, signatures}."""
    kind = request.args.get("kind", "new")
    if kind not in ("new", "reply", "all", "forward", "draft"):
        return {"problem": "Choose what to write."}, 400
    mail = _mail()
    own = _own_addresses()
    name = _display_name()
    started = {"kind": kind, "from": own[0], "froms": [{"email": address, "name": name} for address in own],
               "to": [], "cc": [], "bcc": [], "subject": "", "html": "", "attachments": [], "important": False,
               "reply": None, "draft": None, "signatures": views.signatures(g.mailbox["id"]),
               "limits": {"file": MAX_FILE, "all": MAX_ALL, "recipients": MOST_RECIPIENTS}}
    signature = _signature_html()
    if kind == "new":
        if signature:
            started["html"] = f'<p><br></p><div class="wm-signature" data-signature="{signature["id"]}">{signature["html"]}</div>'
        return started
    email = _load(mail, request.args.get("id", ""))
    if email is None:
        return {"problem": "Message not sent. Original email no longer exists." if kind != "draft"
                else "This draft isn't there any more."}, 404
    parts = _parts(email)
    mine = {address.lower() for address in own}
    if kind == "draft":
        kind_, source = messages.body(email)
        started.update({
            "from": next((address["email"] for address in email.get("from") or [] if address.get("email", "").lower() in mine), own[0]),
            "to": _people(email.get("to")), "cc": _people(email.get("cc")), "bcc": _people(email.get("bcc")),
            "subject": email.get("subject") or "", "attachments": parts, "important": messages.important(email),
            "html": _for_editor(source, email["id"], parts) if kind_ == "html" else _text_html(source),
            "draft": email["id"],
        })
        note = (email.get(f"header:{DRAFT_OF}:asText") or "").strip()
        if ":" in note:
            answer, original = note.split(":", 1)
            started["reply"] = {"kind": answer, "id": original, "inReplyTo": email.get("inReplyTo"),
                                "references": email.get("references")}
        return started
    # a reply or a forward: from the address it came to, when it's one of the mailbox's
    came_to = [address.get("email", "") for address in (email.get("to") or []) + (email.get("cc") or [])]
    started["from"] = next((address for address in came_to if address.lower() in mine), own[0])
    subject = email.get("subject") or ""
    message_id = (email.get("messageId") or [None])[0]
    references = (email.get("references") or []) + ([message_id] if message_id else [])
    if kind in ("reply", "all"):
        senders = _people(email.get("from"))
        reply_to = [person for person in _people(email.get("replyTo")) if person["email"].lower() not in mine]
        if reply_to:
            to = reply_to
        elif any(person["email"].lower() in mine for person in senders):
            to = _people(email.get("to"))   # (one of the mailbox's own: to whom it went)
        else:
            to = senders
        cc, bcc = [], []
        if kind == "all":
            have = {person["email"].lower() for person in to}
            for person in _people(email.get("to")):
                if person["email"].lower() not in mine | have:
                    to.append(person)
                    have.add(person["email"].lower())
            cc = [person for person in _people(email.get("cc")) if person["email"].lower() not in mine | have]
            bcc = [person for person in _people(email.get("bcc")) if person["email"].lower() not in mine | have]
        title = f"Replying to {', '.join(person['email'] for person in to)} on {quote_time(email.get('sentAt') or email.get('receivedAt'))}"
        started.update({"to": to, "cc": cc, "bcc": bcc,
                        "subject": subject if REPLY_PREFIX.match(subject) else f"Re: {subject}".strip(),
                        "html": _quote(email, title, parts), "attachments": [part for part in parts if part["inline"]],
                        "reply": {"kind": "reply", "id": email["id"], "inReplyTo": [message_id] if message_id else None,
                                  "references": references or None, "title": title}})
    else:
        sender = ", ".join(person["email"] for person in _people(email.get("from")))
        title = f"Forwarding email from {sender} at {quote_time(email.get('sentAt') or email.get('receivedAt'))}"
        started.update({"subject": subject if FORWARD_PREFIX.match(subject) else f"Fwd: {subject}".strip(),
                        "html": _quote(email, title, parts), "attachments": parts,
                        "reply": {"kind": "forward", "id": email["id"], "inReplyTo": None,
                                  "references": references or None, "title": title}})
    if signature:   # the signature goes above the quote
        started["html"] = (f'<p><br></p><div class="wm-signature" data-signature="{signature["id"]}">{signature["html"]}</div>'
                           + started["html"])
    return started


# --- files ---

@bp.post("/upload")
@login_required
@reachable
def upload():
    """A file for a message on its way (Attach file, a picture put in what it says, one dropped
    on the composer): uploaded to the engine as it is."""
    sent = request.files.get("file")
    if sent is None:
        return {"problem": "Files upload failed"}, 400
    data = sent.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        return {"problem": f"Maximum allowed file size {MAX_FILE // 1024 ** 2} MB"}, 413
    kind = (sent.mimetype or "application/octet-stream").lower()
    if request.form.get("picture") and kind not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
        return {"problem": "File type is not supported"}, 400
    made = _mail().upload(data, kind)
    name = (sent.filename or "attachment").replace("\\", "/").rsplit("/", 1)[-1][:200] or "attachment"
    return {"blobId": made["blobId"], "name": name, "type": kind, "size": made.get("size", len(data))}


@bp.get("/blob/<blob_id>")
@login_required
@reachable
def blob(blob_id):
    """A picture uploaded (or in a draft, or a message forwarded), to show in the editor."""
    kind = (request.args.get("type") or "").lower()
    if kind not in ("image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"):
        kind = "application/octet-stream"
    download = _mail().download(blob_id, "picture", kind)
    response = Response(_stream(download), mimetype=kind)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


# --- saving and sending ---

class Problem(Exception):
    def __init__(self, message, title=None, status=400):
        super().__init__(message)
        self.message, self.title, self.status = message, title, status


def _message(data, tree, mail, draft):
    """The Email to make from what the composer sent (Problem when it can't be sent)."""
    own = {address.lower() for address in _own_addresses()}
    sender = (data.get("from") or g.mailbox["email"]).strip()
    if sender.lower() not in own:
        raise Problem("You can't send from that address.")
    to, wrong_to = parse_addresses(data.get("to"))
    cc, wrong_cc = parse_addresses(data.get("cc"))
    bcc, wrong_bcc = parse_addresses(data.get("bcc"))
    wrong = wrong_to + wrong_cc + wrong_bcc
    if not draft:
        if wrong:
            raise Problem(f"Invalid email address: {wrong[0]}")
        if not to and not cc:
            raise Problem("Enter at least one email address in the 'To:' or 'Cc:' fields")
    if len(to) + len(cc) + len(bcc) > MOST_RECIPIENTS:
        raise Problem(f"Recipient limit exceeded. The maximum number allowed per email is {MOST_RECIPIENTS}")
    subject = " ".join(str(data.get("subject") or "").split())
    if len(subject) > LONGEST_SUBJECT:
        raise Problem(f"Subject max length is {LONGEST_SUBJECT} symbols")
    written = str(data.get("html") or "")
    if len(written) > LONGEST_HTML:
        raise Problem("The maximum size for an outgoing email is 50 MB.", "Email wasn't sent")
    files = []
    for part in data.get("attachments") or []:
        if not isinstance(part, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", str(part.get("blobId") or "")):
            continue
        inline = bool(part.get("inline")) and bool(part.get("cid"))
        files.append({"blobId": part["blobId"], "type": str(part.get("type") or "application/octet-stream")[:100],
                      "name": str(part.get("name") or "attachment")[:200], "size": int(part.get("size") or 0),
                      "disposition": "inline" if inline else "attachment",
                      **({"cid": re.sub(r"[^A-Za-z0-9._@-]", "", str(part["cid"]))[:120]} if inline else {})})
    if sum(part["size"] for part in files) > MAX_ALL:
        raise Problem(f"All files should not exceed {MAX_ALL // 1024 ** 2} MB")
    shown_inline = [part for part in files if part["disposition"] == "inline"]
    html_body = clean_outgoing(written, shown_inline)
    used = set(re.findall(r'src="cid:([^"]+)"', html_body))
    files = [part for part in files if part["disposition"] == "attachment" or part.get("cid") in used]
    drafts = tree.role("drafts")
    if drafts is None:
        raise Problem("'Drafts' folder data is missing.")
    name = _display_name()
    email = {
        "mailboxIds": {drafts["id"]: True}, "keywords": {"$draft": True, "$seen": True},
        "from": [{"name": name or None, "email": sender}], "to": to, "cc": cc, "bcc": bcc, "subject": subject,
        "htmlBody": [{"partId": "html", "type": "text/html"}], "textBody": [{"partId": "text", "type": "text/plain"}],
        "bodyValues": {"html": {"value": f"<!doctype html><html><body>{html_body}</body></html>"},
                       "text": {"value": to_text(html_body)}},
        "attachments": [{key: value for key, value in part.items() if key != "size"} for part in files],
        "sentAt": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    reply = data.get("reply") if isinstance(data.get("reply"), dict) else None
    if reply:
        in_reply_to = [str(value)[:300] for value in reply.get("inReplyTo") or [] if value][:5]
        references = [str(value)[:300] for value in reply.get("references") or [] if value][-30:]
        if in_reply_to:
            email["inReplyTo"] = in_reply_to
        if references:
            email["references"] = references
        if draft and reply.get("id") and reply.get("kind") in ("reply", "forward"):
            email[f"header:{DRAFT_OF}:asText"] = f"{reply['kind']}:{reply['id']}"
    if data.get("important"):
        email["header:X-Priority:asText"] = "1 (Highest)"
        email["header:Importance:asText"] = "high"
    return email


def _create_error(result, key):
    return ((result.get("notCreated") or {}).get(key) or {})


@bp.post("/save")
@login_required
@reachable
def save():
    """The message kept in Drafts ("Save as draft", or on its own as it's written: quiet). The
    draft it was before goes: a message in the engine can't be changed, only made again."""
    data = request.get_json(silent=True) or {}
    mail = _mail()
    tree = _tree(mail)
    try:
        email = _message(data, tree, mail, draft=True)
    except Problem as problem:
        return {"problem": problem.message}, problem.status
    result = mail.call(("Email/set", {"create": {"draft": email}}))[0]
    made = (result.get("created") or {}).get("draft")
    if not made:
        error = _create_error(result, "draft")
        if error.get("type") == "overQuota":
            return {"problem": "To save this message as a draft, delete old emails or add more storage.",
                    "title": "Your storage is full"}, 507
        return {"problem": "Your message has not been saved"}, 502
    old = str(data.get("draft") or "")
    if old and old != made["id"]:
        mail.call(("Email/set", {"destroy": [old]}))
    tree = _tree(mail)
    return {"draft": made["id"], "counts": _counts(tree), "unread": _inbox_unread(tree),
            "message": None if data.get("quiet") else ("Your drafts message has been successfully updated" if old
                                                         else "Your message has been successfully saved to drafts")}


SEND_ERRORS = {
    "invalidRecipients": ("Delivery failed due to invalid recipient address.", "Email was saved to Draft, please check and try again."),
    "noRecipients": ("Email wasn't sent", "Enter at least one email address in the 'To:' or 'Cc:' fields"),
    "tooManyRecipients": ("Email wasn't sent", f"Recipient limit exceeded. The maximum number allowed per email is {MOST_RECIPIENTS}"),
    "tooLarge": ("Email wasn't sent", "The maximum size for an outgoing email is 50 MB."),
    "forbiddenFrom": ("Email wasn't sent", "You can't send from that address. Email was saved to Draft."),
    "forbiddenToSend": ("Email wasn't sent because outgoing email limit reached.", "Email was saved to Draft, please try again later."),
    "overQuota": ("Email quota exceeded", "Your email was sent, but not saved due to quota limits. Please increase your quota."),
}


@bp.post("/send")
@login_required
@reachable
def send():
    """The message sent: made in Drafts, handed to the engine to deliver, and moved to Sent once
    it's on its way. A reply marks what it answers as answered; a forward, as forwarded. When
    the engine won't send it, it stays in Drafts, and the board says why."""
    data = request.get_json(silent=True) or {}
    mail = _mail()
    tree = _tree(mail)
    try:
        email = _message(data, tree, mail, draft=False)
    except Problem as problem:
        return {"problem": problem.message, "title": problem.title}, problem.status
    sent_folder = tree.role("sent")
    drafts = tree.role("drafts")
    identity = _identity(mail, email["from"][0]["email"], email["from"][0]["name"] or "")
    on_success = {f"mailboxIds/{drafts['id']}": None, "keywords/$draft": None}
    if sent_folder:
        on_success[f"mailboxIds/{sent_folder['id']}"] = True
    made, submitted = mail.call(
        ("Email/set", {"create": {"draft": email}}),
        ("EmailSubmission/set", {"create": {"send": {"identityId": identity, "emailId": "#draft"}},
                                 "onSuccessUpdateEmail": {"#send": on_success}}))
    created = (made.get("created") or {}).get("draft")
    if not created:
        error = _create_error(made, "draft")
        if error.get("type") == "overQuota":
            return {"problem": "To send this email, add more storage or delete old emails.", "title": "Your storage is full"}, 507
        return {"problem": "Message has not been sent", "title": "Email wasn't sent"}, 502
    old = str(data.get("draft") or "")
    if old and old != created["id"]:
        mail.call(("Email/set", {"destroy": [old]}))
    if not (submitted.get("created") or {}).get("send"):
        error = _create_error(submitted, "send")
        title, problem = SEND_ERRORS.get(error.get("type"), ("Email wasn't sent", "Email was saved to Draft, please try again later."))
        tree = _tree(mail)
        return {"problem": problem, "title": title, "draft": created["id"], "saved": True, "counts": _counts(tree),
                "unread": _inbox_unread(tree)}, 422
    reply = data.get("reply") if isinstance(data.get("reply"), dict) else None
    if reply and reply.get("id") and reply.get("kind") in ("reply", "forward"):
        keyword = "$answered" if reply["kind"] == "reply" else "$forwarded"
        try:
            mail.call(("Email/set", {"update": {str(reply["id"]): {f"keywords/{keyword}": True}}}))
        except MailError:
            pass   # (what it answered went meanwhile: it's sent all the same)
    forget_known(g.mailbox["id"])   # (who it went to: suggested next time)
    tree = _tree(mail)
    return {"message": SENT, "counts": _counts(tree), "unread": _inbox_unread(tree)}


@bp.post("/discard")
@login_required
@reachable
def discard():
    """A draft thrown away (the composer's Discard): gone for good."""
    data = request.get_json(silent=True) or {}
    draft = str(data.get("draft") or "")
    mail = _mail()
    if draft:
        got = mail.call(("Email/get", {"ids": [draft], "properties": ["keywords"]}))[0]["list"]
        if got and "$draft" in (got[0].get("keywords") or {}):
            mail.call(("Email/set", {"destroy": [draft]}))
    tree = _tree(mail)
    return {"counts": _counts(tree), "unread": _inbox_unread(tree)}


# --- addresses to write to ---

_KNOWN = {}   # mailbox id -> (when, [{"name", "email"}]): the people it writes to and hears from
KNOWN_FOR = 300   # seconds


def _known(mail):
    kept = _KNOWN.get(g.mailbox["id"])
    if kept and time.monotonic() - kept[0] < KNOWN_FOR:
        return kept[1]
    tree = _tree(mail)
    people, seen = [], set()
    mine = {address.lower() for address in _own_addresses()}
    for role, fields in (("sent", ["to", "cc", "bcc"]), ("inbox", ["from", "replyTo"])):
        folder = tree.role(role)
        if folder is None:
            continue
        _, got = mail.call(("Email/query", {"filter": {"inMailbox": folder["id"]}, "limit": 300,
                                            "sort": [{"property": "receivedAt", "isAscending": False}]}),
                           ("Email/get", {"#ids": ref(0, "Email/query", "/ids"), "properties": fields}))
        for email in got["list"]:
            for field in fields:
                for address in email.get(field) or []:
                    key = (address.get("email") or "").lower()
                    if key and key not in seen and key not in mine:
                        seen.add(key)
                        people.append({"name": address.get("name") or None, "email": address.get("email")})
    _KNOWN[g.mailbox["id"]] = (time.monotonic(), people)
    return people


@bp.get("/suggest")
@login_required
@reachable
def suggest():
    """Addresses that begin with what's typed (a name or an address): the mailbox's contacts and
    the people it has mailed, or heard from."""
    typed = request.args.get("q", "").strip().lower()[:100]
    if not typed:
        return {"people": []}
    mail = _mail()
    people = []
    try:
        from . import contacts
        people += contacts.addresses(mail)
    except (ImportError, AttributeError, MailError):
        pass
    people += _known(mail)
    found, seen = [], set()
    for person in people:
        key = person["email"].lower()
        if key in seen:
            continue
        name = (person.get("name") or "").lower()
        if key.startswith(typed) or name.startswith(typed) or any(word.startswith(typed) for word in name.split()):
            seen.add(key)
            found.append(person)
        if len(found) >= SUGGESTIONS:
            break
    return {"people": found}


def forget_known(mailbox_id):
    _KNOWN.pop(mailbox_id, None)
