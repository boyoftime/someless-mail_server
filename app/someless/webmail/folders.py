"""A mailbox's folders as PrivateEmail shows them: Inbox, Drafts, Sent, Archive, Spam and Trash
first (the engine's roles for them), each with the folders made inside it, then the mailbox's own
folders. Drafts counts all its mail; the others, what's unread. The mailbox's own folders go in
the order they were made, or by name ("Sort alphabetically", in a folder's menu), and a folder's
own folders can be folded away. The engine has no Archive to begin with: it's made the first time
the folders are looked at.

What a folder's menu offers follows PrivateEmail: folders go four deep at most, none go in
Drafts, Sent or Spam, the mailbox's own folders can be renamed, moved and deleted, the Trash is
emptied, and the rest can have all their messages deleted."""
import unicodedata

from .jmap import MailError

# (role, key in the address bar, name, icon)
STANDARD = [("inbox", "inbox", "Inbox", "inbox"), ("drafts", "drafts", "Drafts", "drafts"), ("sent", "sent", "Sent", "sent"),
            ("archive", "archive", "Archive", "archive"), ("junk", "spam", "Spam", "spam"), ("trash", "trash", "Trash", "trash")]
KEYS = {role: key for role, key, _, _ in STANDARD}
PROPERTIES = ["name", "role", "parentId", "sortOrder", "totalEmails", "unreadEmails"]
LONGEST_NAME = 60
MAX_DEPTH = 3            # the top level is 0: four levels in all
NO_FOLDERS_IN = ("drafts", "sent", "junk")
NAME_MARKS = set("!@#$%^&*()_+-={}[];:'\"<.,|\\?`~")   # besides letters, digits and spaces


def name_allowed(name):
    """Letters, digits, spaces and the marks PrivateEmail allows: no slashes, no symbols."""
    if name in (".", ".."):
        return False
    for character in name:
        kind = unicodedata.category(character)
        if not (kind[0] in "LMN" or kind in ("Pd", "Pc") or character.isspace() or character in NAME_MARKS):
            return False
    return True


class Folders:
    def __init__(self, boxes, by_name=False, collapsed=()):
        self.by_id, self.list, self.tree = {}, [], []
        standard = {}
        for box in boxes:
            if box.get("role") in KEYS and box.get("role") not in standard:
                standard[box["role"]] = box
        own = [box for box in boxes if box not in standard.values()]
        ids = {box["id"] for box in boxes}
        made = {box["id"]: place for place, box in enumerate(boxes)}   # the engine lists them as they were made
        children = {}
        for box in own:
            parent = box.get("parentId") if box.get("parentId") in ids else None   # an orphan: at the top
            children.setdefault(parent, []).append(box)

        def order(box):
            return (box["name"].casefold(),) if by_name else (box.get("sortOrder") or 0, made[box["id"]])

        def add(parent_box, parent, depth, root):
            for box in sorted(children.get(parent_box, []), key=order):
                folder = self._add(box, "f-" + box["id"], box["name"], None, None, depth, root, parent, collapsed)
                add(box["id"], folder, depth + 1, root)

        for role, key, name, icon in STANDARD:
            if role in standard:
                folder = self._add(standard[role], key, name, icon, role, 0, role, None, collapsed)
                add(standard[role]["id"], folder, 1, role)
        add(None, None, 0, None)
        self.by_key = {folder["key"]: folder for folder in self.list}
        for folder in self.list:
            folder["menu"] = self._menu(folder)

    def _add(self, box, key, name, icon, role, depth, root, parent, collapsed):
        total, unread = box.get("totalEmails", 0), box.get("unreadEmails", 0)
        folder = {"id": box["id"], "key": key, "role": role, "label": name, "name": box["name"], "icon": icon, "depth": depth,
                  "parent": box.get("parentId") if parent else None, "total": total, "unread": unread,
                  "count": total if role == "drafts" else unread, "own": role is None, "root": root,
                  "kids": [], "collapsed": key in collapsed}
        self.by_id[box["id"]] = folder
        self.list.append(folder)
        (parent["kids"] if parent else self.tree).append(folder)
        return folder

    def _menu(self, folder):
        """What the folder's menu offers, in its order (webmail-folders.js draws it)."""
        archive, inbox = self.role("archive"), self.role("inbox")
        root = folder["root"]
        items = []
        if self.can_hold_folders(folder):
            items.append("subfolder")
        if folder["own"]:
            items.append("rename")
        if archive and (folder["role"] == "inbox" or (folder["own"] and root == "inbox")):
            items.append("archive_all")
        if archive and folder["own"] and root == "inbox":
            items.append("to_archive")
        if inbox and (folder["role"] == "archive" or (folder["own"] and root == "archive")):
            items.append("inbox_all")
        if inbox and folder["own"] and root == "archive":
            items.append("to_inbox")
        if folder["role"] != "drafts":
            items += ["read_all", "unread_all"]
        if folder["role"] != "trash":
            items.append("delete_all")
        if folder["own"]:
            items.append("delete")
        if folder["role"] == "trash":
            items.append("empty")
        return items

    def can_hold_folders(self, folder):
        return folder["depth"] < MAX_DEPTH and folder["root"] not in NO_FOLDERS_IN

    def role(self, role):
        key = KEYS.get(role)
        return self.by_key.get(key) if key else None

    def of(self, email):
        """The folder a message is in (the first, when it's in several)."""
        return next((self.by_id[mailbox_id] for mailbox_id in email.get("mailboxIds") or {} if mailbox_id in self.by_id), None)

    def children(self, folder):
        return folder["kids"]

    def inside(self, folder):
        """The folder and all the folders in it, however deep."""
        found = [folder]
        for child in folder["kids"]:
            found.extend(self.inside(child))
        return found

    def in_trash(self, folder):
        """Whether the folder is the Trash, or somewhere inside it."""
        return folder is not None and folder["root"] == "trash"

    def path(self, folder):
        """Its name with the folders it's in: Clients / Acme."""
        names = []
        while folder is not None:
            names.append(folder["label"])
            folder = self.by_id.get(folder["parent"]) if folder["parent"] else None
        return " / ".join(reversed(names))

    def engine_path(self, folder):
        """Its path as the engine names it (Inbox/Clients), for Sieve's fileinto."""
        names = []
        while folder is not None:
            names.append(folder["name"])
            folder = self.by_id.get(folder["parent"]) if folder["parent"] else None
        return "/".join(reversed(names))

    def destinations(self):
        """Where messages can be moved to: all but Drafts and Sent (as PrivateEmail)."""
        return [folder for folder in self.list if folder["role"] not in ("drafts", "sent")]


def load(jmap, by_name=False, collapsed=()):
    """The mailbox's folders (Archive made first, when there's none)."""
    boxes = jmap.call(("Mailbox/get", {"properties": PROPERTIES}))[0]["list"]
    if not any(box.get("role") == "archive" for box in boxes):
        if not any(not box.get("parentId") and box["name"].casefold() == "archive" for box in boxes):
            try:
                result = jmap.call(("Mailbox/set", {"create": {"archive": {"name": "Archive", "role": "archive"}}}))[0]
                if "archive" not in (result.get("created") or {}):
                    jmap.call(("Mailbox/set", {"create": {"archive": {"name": "Archive"}}}))
            except MailError:
                pass   # shown without it: the next look makes it
            boxes = jmap.call(("Mailbox/get", {"properties": PROPERTIES}))[0]["list"]
        named = next((box for box in boxes if not box.get("parentId") and box["name"].casefold() == "archive"), None)
        if named is not None and not any(box.get("role") == "archive" for box in boxes):
            named["role"] = "archive"   # one the engine wouldn't mark as the Archive: taken as it
    return Folders(boxes, by_name, collapsed)
