"""The Undelivered folder (Settings > Undelivered mail): notices of mail that couldn't be delivered,
kept out of the Inbox once the mailbox switches it on. The engine files them as they come (a rule in
the mailbox's Sieve script, sieve.py), so its mail apps see them there too; the ones in the Inbox
already are moved in one go.

A notice is a delivery report (RFC 3464: Content-Type multipart/report; report-type=delivery-status),
as Someless Mail's own, Gmail's and Outlook's are, or mail from a mailer-daemon, as the plain ones of
older servers are (Exim's "Mail delivery failed: returning message to sender"). Mail from a
postmaster is one only when it's a report: a person writing from that address stays in the Inbox."""
from .folders import UNDELIVERED as FOLDER
from .jmap import MailError
from .mail import _apply, _every

# The same, in Sieve: what the engine files as it comes
SIEVE_TEST = 'anyof(header :contains "content-type" "delivery-status", address :localpart :is "from" "mailer-daemon")'
CHECKED = 500   # messages looked at in one call


def is_notice(email):
    """Whether a message (its "from" and "header:Content-Type:asText") is a notice."""
    sender = ((email.get("from") or [{}])[0].get("email") or "").rpartition("@")[0].lower()
    kind = (email.get("header:Content-Type:asText") or "").lower()
    return sender == "mailer-daemon" or "delivery-status" in kind


def notices_in(mail, folder):
    """The ids of the notices in the folder. (The engine's search finds who they're from, a
    mailer-daemon or a postmaster; whether each is a notice is checked on it.)"""
    candidates = _every(mail, {"operator": "AND", "conditions": [
        {"inMailbox": folder["id"]},
        {"operator": "OR", "conditions": [{"from": "mailer-daemon"}, {"from": "postmaster"}]}]})
    found = []
    for start in range(0, len(candidates), CHECKED):
        got = mail.call(("Email/get", {"ids": candidates[start:start + CHECKED],
                                       "properties": ["from", "header:Content-Type:asText"]}))[0]["list"]
        found += [email["id"] for email in got if is_notice(email)]
    return found


def waiting(mail, tree):
    """How many notices are in the Inbox."""
    inbox = tree.role("inbox")
    return len(notices_in(mail, inbox)) if inbox else 0


def make_folder(mail, tree):
    """The Undelivered folder's id, made when there's none."""
    folder = tree.role("undelivered")
    if folder:
        return folder["id"]
    result = mail.call(("Mailbox/set", {"create": {"undelivered": {"name": FOLDER}}}))[0]
    if "undelivered" not in (result.get("created") or {}):
        raise MailError(f"Mailbox/set: {(result.get('notCreated') or {}).get('undelivered')}")
    return result["created"]["undelivered"]["id"]


def move(mail, tree):
    """The notices in the Inbox, moved to the Undelivered folder (made if it's gone): how many."""
    folder_id = make_folder(mail, tree)
    ids = notices_in(mail, tree.role("inbox")) if tree.role("inbox") else []
    _apply(mail, {email_id: {"mailboxIds": {folder_id: True}} for email_id in ids})
    return len(ids)
