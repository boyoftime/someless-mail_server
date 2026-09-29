"""Messages as the webmail shows them: a row in the list (webmail-message.html) and the message in
the reading pane (webmail-read.html), from what the engine keeps (JMAP Email). Times are the
reader's own: the page tells the webmail its time zone (the wm_tz cookie, webmail-app.js)."""
import datetime
import hashlib
import re
import urllib.parse
import zoneinfo

from flask import request

LIST_PROPERTIES = ["id", "threadId", "mailboxIds", "keywords", "from", "to", "cc", "subject", "preview", "receivedAt",
                   "size", "hasAttachment", "header:X-Priority:asText"]
READ_PROPERTIES = LIST_PROPERTIES + ["bcc", "replyTo", "sentAt", "messageId", "inReplyTo", "references", "blobId",
                                     "attachments", "textBody", "htmlBody", "bodyValues"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
NO_SUBJECT = "No Subject"


def zone_name():
    """The reader's time zone's name (Africa/Nairobi), or UTC: from the cookie the page writes, as
    cookies are written (Africa%2FNairobi)."""
    name = urllib.parse.unquote(request.cookies.get("wm_tz", "UTC"))[:64]
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return "UTC"
    return name


def zone():
    name = zone_name()
    return datetime.timezone.utc if name == "UTC" else zoneinfo.ZoneInfo(name)


def _when(iso):
    try:
        return datetime.datetime.fromisoformat((iso or "").replace("Z", "+00:00")).astimezone(zone())
    except ValueError:
        return None


def _clock(moment, padded):
    hour = (moment.hour - 1) % 12 + 1
    return f"{hour:02d}:{moment.minute:02d} {'PM' if moment.hour >= 12 else 'AM'}" if padded else \
        f"{hour}:{moment.minute:02d} {'PM' if moment.hour >= 12 else 'AM'}"


def list_time(iso, now=None):
    """06:51 PM today, Sep 23 this year, Sep 23, 2025 before."""
    moment = _when(iso)
    if moment is None:
        return ""
    now = now or datetime.datetime.now(zone())
    if moment.date() == now.date():
        return _clock(moment, padded=True)
    if moment.year == now.year:
        return f"{MONTHS[moment.month - 1][:3]} {moment.day}"
    return f"{MONTHS[moment.month - 1][:3]} {moment.day}, {moment.year}"


def full_time(iso, now=None):
    """September 18, 5:34 PM (with the year, when it isn't this one)."""
    moment = _when(iso)
    if moment is None:
        return ""
    now = now or datetime.datetime.now(zone())
    year = f", {moment.year}" if moment.year != now.year else ""
    return f"{MONTHS[moment.month - 1]} {moment.day}{year}, {_clock(moment, padded=False)}"


def size_text(size):
    """35.4 KB, 292.04 KB, 1.2 MB: as PrivateEmail writes a file's size."""
    size = size or 0
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.2f}".rstrip("0").rstrip(".") + f" {unit}"
        size /= 1024


def name_of(address):
    return (address.get("name") or "").strip() or address.get("email") or ""


def people(addresses):
    return ", ".join(name_of(address) for address in addresses or []) or ""


def initials(name):
    """AH for Amina Hassan, A for amina@example.com: the letters in a person's circle."""
    words = [word for word in re.split(r"[\s._-]+", (name or "").partition("@")[0]) if word[:1].isalnum()]
    return ((words[0][:1] + (words[1][:1] if len(words) > 1 else "")) if words else "?").upper()


def hue(email):
    """A person's colour in the list (0 to 359), always the same for the same address."""
    return int(hashlib.sha256((email or "").strip().lower().encode()).hexdigest()[:8], 16) % 360


def important(email):
    """Sent as high priority (X-Priority 1 or 2): PrivateEmail's "High Priority"."""
    value = (email.get("header:X-Priority:asText") or "").strip()
    return value[:1] in ("1", "2")


def row(email, folder, located=None):
    """A message in the list. folder: the one the list shows (Sent and Drafts show who it's to);
    located: the folder it's in, shown beside it (search results)."""
    keywords = email.get("keywords") or {}
    to_side = folder is not None and folder.get("role") in ("sent", "drafts")
    who = people(email.get("to")) if to_side else people(email.get("from"))
    first = ((email.get("to") if to_side else email.get("from")) or [{}])[0]   # (the one in the circle)
    address = (first.get("email") or "").strip().lower()
    return {
        "id": email["id"], "folder": located or folder, "located": located,
        "sender": who or ("(No recipients)" if to_side else "(Unknown sender)"),
        "subject": email.get("subject") or NO_SUBJECT, "preview": (email.get("preview") or "").strip(),
        "time": list_time(email.get("receivedAt")), "date": full_time(email.get("receivedAt")),
        "unread": "$seen" not in keywords, "flagged": "$flagged" in keywords, "answered": "$answered" in keywords,
        "forwarded": "$forwarded" in keywords, "draft": "$draft" in keywords, "attachment": bool(email.get("hasAttachment")),
        "important": important(email), "size": email.get("size") or 0,
        "who_email": address, "initials": initials(name_of(first)), "hue": hue(address),
    }


def _file(part):
    kind = (part.get("type") or "application/octet-stream").lower()
    name = part.get("name") or ("image" if kind.startswith("image/") else "attachment")
    base, dot, extension = name.rpartition(".")
    image = kind.startswith("image/") and kind != "image/svg+xml"
    inline = part.get("disposition") == "inline"
    return {"blob": part["blobId"], "name": name, "type": kind,
            "base": base if dot and base else name, "extension": dot + extension if dot and base else "",
            "size": size_text(part.get("size")), "bytes": part.get("size") or 0, "cid": part.get("cid"),
            "inline": inline, "image": image, "pdf": kind == "application/pdf",
            # a picture in what it says: shown there, not with the attachments
            "hidden": bool(part.get("cid")) and inline and image}


def view(email, folder):
    """The message in the reading pane (what it says is made in content.py)."""
    shown = row(email, folder)
    sender = (email.get("from") or [{}])[0]
    shown.update({
        "sender": name_of(sender) or "(Unknown sender)", "address": sender.get("email") or "",
        "to": email.get("to") or [], "cc": email.get("cc") or [], "bcc": email.get("bcc") or [],
        "reply_to": email.get("replyTo") or [], "blob": email.get("blobId"),
        "files": [_file(part) for part in email.get("attachments") or [] if part.get("blobId")],
        "in_spam": folder is not None and folder.get("role") == "junk",
        "in_trash": folder is not None and folder.get("role") == "trash",
        "in_archive": folder is not None and folder.get("role") == "archive",
    })
    return shown


def body(email):
    """What the message says: ("html", source) or ("text", source)."""
    values = email.get("bodyValues") or {}
    html_parts = [part for part in email.get("htmlBody") or [] if part.get("type") == "text/html"]
    if html_parts:
        return "html", "".join(values.get(part["partId"], {}).get("value", "") for part in html_parts)
    text_parts = [part for part in email.get("textBody") or [] if (part.get("type") or "text/plain").startswith("text/")]
    return "text", "\n".join(values.get(part["partId"], {}).get("value", "") for part in text_parts)
