"""The webmail's mail, as PrivateEmail's: the folders, the list (50 at a time, sorted and filtered
as chosen for each folder), the reading pane, and what's done to messages and folders. All of it
comes from the engine over JMAP, as the mailbox (jmap.py); nothing of the mail is kept here.

Addresses: /mail/<folder> (a folder's list), /mail/<folder>/<message> (with that message open),
/list/<folder>?after= (the next 50), /view/<folder> (its sort and filters), /do (a message
action), /folders (folder actions), /blob, /zip, /source and /print (a message's files, source
and printout), /search."""
import functools
import re
import tempfile
import urllib.parse
import zipfile

from flask import (Blueprint, Response, abort, current_app, g, get_template_attribute, redirect, render_template,
                   request, send_file, url_for)

from . import content, folders as folder_lib, login_required, messages, views
from .jmap import MailError, MailUnavailable, for_mailbox, ref
from ..db import get_db
from ..mailboxes import size_text as quota_text

bp = Blueprint("mail", __name__)

MAIL_PAGE = 50        # messages at a time: the newest with the page, then more as the list is scrolled down
SEARCH_PANEL = 8      # results in the search panel under the search field
IN_ONE_GO = 500       # messages changed in one call (the engine's limit is higher)
LONGEST_SEARCH = 200
MOST_AT_ONCE = 50_000  # messages one action can reach ("Select all")
FILTERS = {"unread": {"notKeyword": "$seen"}, "favorites": {"hasKeyword": "$flagged"},
           "important": {"operator": "OR", "conditions": [{"header": ["X-Priority", "1"]}, {"header": ["X-Priority", "2"]}]}}
SORTS = {"newest": ("receivedAt", False), "oldest": ("receivedAt", True), "largest": ("size", False), "smallest": ("size", True)}
UNAVAILABLE = "Your mail can't be reached right now. Try again in a moment."
WENT_WRONG = "Something went wrong. Try to reload the page."
GONE = "That folder isn't there any more."
# the files a browser may show on the page itself (a preview); anything else downloads
SHOWN_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "application/pdf"}
SEARCH = "search"     # the list's "folder" while searching


def _wants_json():
    return request.accept_mimetypes.best == "application/json" or request.is_json


def reachable(view):
    """The engine not answering, or refusing: said so, on the page or to the page's scripts."""
    @functools.wraps(view)
    def wrapped(**kwargs):
        try:
            return view(**kwargs)
        except MailUnavailable as error:
            current_app.logger.warning("the mail engine didn't answer: %s", error)
            problem, status = UNAVAILABLE, 503
        except MailError as error:
            current_app.logger.warning("the mail engine refused: %s", error)
            problem, status = WENT_WRONG, 502
        if _wants_json() or request.method != "GET":
            return {"problem": problem}, status
        return render_template("webmail-down.html", problem=problem, email=g.mailbox["email"]), status
    return wrapped


def _mail():
    return for_mailbox(g.mailbox["email"])


def _tree(mail):
    """The folders, in the order and folded as this mailbox keeps them (views.py). Kept from
    deleting (kept_mail): their menus offer none."""
    mailbox_id = g.mailbox["id"]
    tree = folder_lib.load(mail, views.folders_by_name(mailbox_id), views.collapsed(mailbox_id))
    if kept_mail():
        for folder in tree.list:
            folder["menu"] = [action for action in folder["menu"] if action not in DELETING]
    return tree


# Disable delete (the panel's Mailboxes page): nothing in the mailbox is deleted or put in the Trash
# in the webmail; moved elsewhere, yes. Its own drafts, unsent, still go when discarded.
KEPT = ("Deleting is switched off for this mailbox by its administrator. You can move messages to "
        "another folder, like the Archive, instead.")
DELETING = ("delete", "delete_all", "empty")


def kept_mail():
    """Whether the mailbox in sight is kept from deleting (a template global too)."""
    return bool(g.get("mailbox") is not None and g.mailbox["no_delete_webmail"])


def _to_trash(tree, folder):
    return folder is not None and (folder["role"] == "trash" or tree.in_trash(folder))


def _options(folder_key):
    """The list's sort and filters ("Sort and filter"), as chosen for the folder."""
    return views.list_options(g.mailbox["id"], folder_key)


def _condition(folder, filters, text=None):
    conditions = []
    if folder is not None:
        conditions.append({"inMailbox": folder["id"]})
    if text:
        conditions.append({"text": text})
    conditions += [FILTERS[name] for name in filters]
    if not conditions:
        return {}
    return conditions[0] if len(conditions) == 1 else {"operator": "AND", "conditions": conditions}


def _query(folder, sort, filters, anchor=None, limit=MAIL_PAGE, text=None):
    prop, ascending = SORTS[sort]
    arguments = {"filter": _condition(folder, filters, text), "sort": [{"property": prop, "isAscending": ascending}],
                 "limit": limit, "calculateTotal": True, "collapseThreads": False}
    if anchor:
        arguments.update(anchor=anchor, anchorOffset=1)
    return arguments


def _list(mail, tree, folder, sort, filters, anchor=None, text=None, limit=MAIL_PAGE):
    """A piece of the list: (rows, the id to go on after, or None, how many in all)."""
    query, got = mail.call(("Email/query", _query(folder, sort, filters, anchor, limit, text)),
                           ("Email/get", {"#ids": ref(0, "Email/query", "/ids"), "properties": messages.LIST_PROPERTIES}))
    found = {email["id"]: email for email in got["list"]}
    emails = [found[email_id] for email_id in query["ids"] if email_id in found]
    # (a search of all the mail: each shows the folder it's in)
    rows = [messages.row(email, folder, located=tree.of(email) if text is not None and folder is None else None) for email in emails]
    total = query.get("total", 0)
    after = None
    if emails and query.get("position", 0) + len(query["ids"]) < total:
        after = emails[-1]["id"]
    return rows, after, total


def _list_url(folder_key, after, text=None, scope=None):
    arguments = {"folder": folder_key, "after": after}
    if text:
        arguments["q"] = text
    if scope:
        arguments["in"] = scope
    return url_for("mail.rows", **arguments)


def _storage(mail):
    """How full the mailbox is: the engine's count, against its size."""
    limit = g.mailbox["quota_bytes"]
    used = 0
    try:
        for quota in mail.call(("Quota/get", {"ids": None}))[0]["list"]:
            if quota.get("resourceType") == "octets":
                used = quota.get("used", 0)
                limit = quota.get("hardLimit") or limit
                break
    except MailError:
        pass
    percent = min(100.0, used * 100 / limit) if limit else 0
    return {"used": quota_text(used) if used >= 1024 ** 2 else messages.size_text(used), "quota": quota_text(limit),
            "percent": f"{percent:.1f}".rstrip("0").rstrip("."), "full": bool(limit) and used >= limit}


def _who():
    """The name the mailbox goes by: its sender's, else what's before the @."""
    email = g.mailbox["email"]
    sender = get_db().execute("SELECT name FROM senders WHERE lower(email) = ?", (email,)).fetchone()
    return sender["name"] if sender else email.partition("@")[0]


def _columns():
    """The widths the folders and the mail were dragged to (webmail-resize.js keeps them in the
    wm_columns cookie), for the page to come with them: CSS, or None to start as it does."""
    parts = request.cookies.get("wm_columns", "").split(",")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    side, mail = (int(part) for part in parts)
    if not (100 <= side <= 2000 and 100 <= mail <= 4000):   # webmail-app.css keeps them in their limits
        return None
    return f"--wm-side-width: {side}px; --wm-list-width: {mail}px"


def _counts(tree):
    return {folder["key"]: folder["count"] for folder in tree.list}


def _inbox_unread(tree):
    inbox = tree.role("inbox")
    return inbox["unread"] if inbox else 0


def _folders_html(tree, current=None):
    macro = get_template_attribute("webmail-folders.html", "folder_list")
    return str(macro(tree.tree, current))


def _search_args(text, scope):
    """What a message's link in the search results carries, to open it with the results beside it."""
    return {key: value for key, value in (("q", text), ("in", scope)) if value}


def _rows_html(found, folder_key, search=None):
    row = get_template_attribute("webmail-message.html", "message_row")
    return "".join(str(row(item, index, True, folder_key=folder_key, search=search)) for index, item in enumerate(found))


# --- the reading pane ---

def _open(mail, tree, email_id):
    """A message, opened: (what the pane shows, what it says as a page of its own). None when
    there's no such message. Opening it marks it read, and its folders count one fewer unread."""
    got = mail.call(("Email/get", {"ids": [email_id], "properties": messages.READ_PROPERTIES,
                                   "fetchHTMLBodyValues": True, "fetchTextBodyValues": True,
                                   "maxBodyValueBytes": 2_000_000}))[0]["list"]
    if not got:
        return None
    email = got[0]
    keywords = email.get("keywords") or {}
    if "$seen" not in keywords and "$draft" not in keywords:
        mail.call(("Email/set", {"update": {email_id: {"keywords/$seen": True}}}))
        email["keywords"] = {**keywords, "$seen": True}
        for mailbox_id in email.get("mailboxIds") or {}:
            folder = tree.by_id.get(mailbox_id)
            if folder:
                folder["unread"] = max(0, folder["unread"] - 1)
                if folder["role"] != "drafts":
                    folder["count"] = folder["unread"]
    folder = tree.of(email)
    shown = messages.view(email, folder)
    shown["actions"] = _reader_actions(tree, folder, shown)
    kind, source = messages.body(email)
    pictures = {part["cid"]: part for part in shown["files"] if part["cid"]}

    def picture_url(cid):
        part = pictures.get(cid)
        return url_for("mail.blob", email_id=email_id, blob_id=part["blob"], inline=1) if part and part["image"] else None

    prepared = content.from_html(source, picture_url) if kind == "html" else content.from_text(source)
    shown["cleaned"] = prepared.cleaned
    shown["kind"] = kind
    doc = render_template("webmail-body.html", body=prepared.html, kind=kind)
    return shown, doc


def _reader_actions(tree, folder, shown):
    """What the reading pane's bar offers for a message in this folder (as PrivateEmail's)."""
    role = folder["root"] if folder else None
    in_archive = bool(folder) and folder["root"] == "archive"
    return {
        "archive": bool(tree.role("archive")) and not in_archive and role != "drafts",
        "inbox": bool(tree.role("inbox")) and in_archive,
        "spam": role not in ("drafts", "sent"),
        "not_spam": bool(folder) and folder["role"] == "junk",
        "draft": shown["draft"] or role == "drafts",
    }


def _page(folder_key, email_id=None, text=None, scope=None):
    mail = _mail()
    tree = _tree(mail)
    searching = folder_key == SEARCH
    folder = tree.by_key.get(scope) if searching else tree.by_key.get(folder_key)
    # gone meanwhile (deleted or moved from another device, a draft saved again under a new id):
    # its folder, or the Inbox, saying so (webmail-read.js), never a bare error page
    if not searching and folder is None:
        return redirect(url_for("mail.folder", folder="inbox", gone="folder"))
    opened = None
    if email_id is not None:
        opened = _open(mail, tree, email_id)
        if opened is None:
            if searching:
                return redirect(url_for("mail.search", q=text or "", **({"in": scope} if scope else {}), gone="message"))
            return redirect(url_for("mail.folder", folder=folder_key, gone="message"))
    sort, filters = _options(folder_key)
    rows, after, total = _list(mail, tree, folder, sort, filters, text=text if searching else None)
    next_url = _list_url(folder_key, after, text, scope) if after else None
    name = _who()
    return render_template(
        "webmail-mail.html", email=g.mailbox["email"], name=name, initial=name[:1].upper(), tree=tree.tree,
        folders=tree.list, folder=folder, folder_key=folder_key, searching=searching, query=text or "", scope=scope,
        folder_path=tree.path(folder) if folder else "", messages=rows, next_url=next_url, total=total,
        sort=sort, filters=filters, storage=_storage(mail), columns=_columns(),
        by_name=views.folders_by_name(g.mailbox["id"]), inbox_unread=_inbox_unread(tree),
        preferences=views.preferences(g.mailbox["id"]),
        actions=_list_actions(tree, folder, searching), search=_search_args(text, scope) if searching else None,
        open_message=opened[0] if opened else None, body_doc=opened[1] if opened else None)


def _list_actions(tree, folder, searching):
    """What a message in this list can have done to it (the selection panel, the right-click menu)."""
    root = folder["root"] if folder else None
    in_archive = bool(folder) and root == "archive"
    return {
        "drafts": root == "drafts",
        "archive": bool(tree.role("archive")) and not in_archive and root != "drafts" and not searching,
        "inbox": bool(tree.role("inbox")) and in_archive and not searching,
        "spam": root not in ("drafts", "sent") and not searching,
        "not_spam": bool(folder) and folder["role"] == "junk" and not searching,
    }


@bp.get("/")
@login_required
def home():
    return redirect(url_for("mail.folder", folder="inbox"))


@bp.get("/mail/<folder>")
@login_required
@reachable
def folder(folder):
    return _page(folder)


@bp.get("/mail/<folder>/<email_id>")
@login_required
@reachable
def message(folder, email_id):
    """A message in the reading pane: the whole page (its link, a refresh), or just the pane for
    webmail-read.js: {"html", "subject", "counts", "unread"}. Opening it marks it read."""
    if not _wants_json():
        return _page(folder, email_id, text=request.args.get("q") if folder == SEARCH else None,
                     scope=request.args.get("in") if folder == SEARCH else None)
    mail = _mail()
    tree = _tree(mail)
    opened = _open(mail, tree, email_id)
    if opened is None:
        return {"problem": "This message isn't there any more."}, 404
    shown, doc = opened
    view = get_template_attribute("webmail-read.html", "message_view")
    return {"html": str(view(shown, g.mailbox["email"], doc)), "subject": shown["subject"], "counts": _counts(tree),
            "unread": _inbox_unread(tree)}


@bp.get("/list/<folder>")
@login_required
@reachable
def rows(folder):
    """The next piece of the list, as the page shows it (webmail-list.js): {"html", "next", "total"}."""
    mail = _mail()
    tree = _tree(mail)
    searching = folder == SEARCH
    text = request.args.get("q", "").strip()[:LONGEST_SEARCH] if searching else None
    scope = request.args.get("in") if searching else None
    shown_folder = tree.by_key.get(scope) if searching else tree.by_key.get(folder)
    if not searching and shown_folder is None:
        return {"problem": GONE}, 404
    sort, filters = _options(folder)
    try:
        found, after, total = _list(mail, tree, shown_folder, sort, filters, anchor=request.args.get("after") or None, text=text)
    except MailError:
        return {"problem": "Not a message in the list."}, 400
    answer = {"html": _rows_html(found, folder, _search_args(text, scope) if searching else None),
              "next": _list_url(folder, after, text, scope) if after else None, "total": total,
              "counts": _counts(tree), "unread": _inbox_unread(tree)}
    if not request.args.get("after"):   # the list from its start (a refresh, live): the folders as they are now too
        answer["folders"] = _folders_html(tree, None if searching else folder)
    return answer


@bp.post("/view/<folder>")
@login_required
@reachable
def list_view(folder):
    """The folder's sort and filters, chosen ("Sort and filter"; {"sort", "filters"}): kept for
    next time, and the list's first piece as they have it."""
    data = request.get_json(silent=True) or {}
    sort = data.get("sort") if data.get("sort") in SORTS else "newest"
    filters = [name for name in views.FILTERS if name in (data.get("filters") or [])]
    mail = _mail()
    tree = _tree(mail)
    searching = folder == SEARCH
    text = (data.get("q") or "").strip()[:LONGEST_SEARCH] if searching else None
    scope = data.get("in") if searching else None
    shown_folder = tree.by_key.get(scope) if searching else tree.by_key.get(folder)
    if not searching and shown_folder is None:
        return {"problem": GONE}, 404
    views.save_list_options(g.mailbox["id"], folder, sort, filters)
    found, after, total = _list(mail, tree, shown_folder, sort, filters, text=text)
    return {"html": _rows_html(found, folder, _search_args(text, scope) if searching else None),
            "next": _list_url(folder, after, text, scope) if after else None, "total": total, "sort": sort,
            "filters": filters}


# --- what's done to messages ---

ACTIONS = ("read", "unread", "flag", "unflag", "archive", "inbox", "move", "spam", "notspam", "delete")


def _in_chunks(items, size=IN_ONE_GO):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _apply(mail, patches, destroy=()):
    for chunk in _in_chunks(patches.items()):
        mail.call(("Email/set", {"update": dict(chunk)}))
    for chunk in _in_chunks(destroy):
        mail.call(("Email/set", {"destroy": chunk}))


def _moved(count, where):
    return f'Email moved to "{where}"' if count == 1 else f'Emails moved to "{where}"'


def _every(mail, condition):
    """The ids of every message that meets the condition (up to MOST_AT_ONCE)."""
    found, position = [], 0
    while len(found) < MOST_AT_ONCE:
        ids = mail.call(("Email/query", {"filter": condition, "position": position, "limit": 1000,
                                         "collapseThreads": False}))[0]["ids"]
        found += ids
        if len(ids) < 1000:
            break
        position += len(ids)
    return found[:MOST_AT_ONCE]


def _chosen_ids(mail, tree, data):
    """The messages an action is for: the ids ticked, or ("Select all") every one the list has."""
    everything = data.get("all")
    if isinstance(everything, dict):
        folder_key = everything.get("folder")
        searching = folder_key == SEARCH
        folder = tree.by_key.get(everything.get("in")) if searching else tree.by_key.get(folder_key)
        if not searching and folder is None:
            return None
        text = (everything.get("q") or "").strip()[:LONGEST_SEARCH] if searching else None
        if searching and not text:
            return []
        return _every(mail, _condition(folder, _options(folder_key)[1], text))
    return [str(email_id) for email_id in data.get("ids") or [] if email_id][:MOST_AT_ONCE]


@bp.post("/do")
@login_required
@reachable
def act():
    """A message action ({"action", "ids" or "all", "to"}): {"counts", "unread", "message",
    "left"} (left: whether they left the folder they were in; message: what the toast says)."""
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action not in ACTIONS:
        return {"problem": "Choose what to do with the messages."}, 400
    mail = _mail()
    tree = _tree(mail)
    ids = _chosen_ids(mail, tree, data)
    if ids is None:
        return {"problem": GONE}, 404
    if not ids:
        return {"problem": "No messages selected"}, 400
    target = None
    if action in ("archive", "inbox", "spam", "notspam", "move"):
        target = tree.by_key.get(data.get("to")) if action == "move" else \
            tree.role({"archive": "archive", "inbox": "inbox", "spam": "junk", "notspam": "inbox"}[action])
        if target is None:
            names = {"archive": "Archive", "inbox": "Inbox", "spam": "Spam", "notspam": "Inbox"}
            return {"problem": f"'{names[action]}' folder data is missing." if action in names else GONE}, 404
        if action == "move" and target["role"] in ("drafts", "sent"):
            return {"problem": f"Messages can't be moved to {target['label']}."}, 400
    if kept_mail() and _to_trash(tree, target):
        return {"problem": KEPT}, 403
    emails = []
    for chunk in _in_chunks(ids):
        emails += mail.call(("Email/get", {"ids": chunk, "properties": ["mailboxIds", "keywords"]}))[0]["list"]
    if kept_mail() and action == "delete" and not all("$draft" in (email.get("keywords") or {}) for email in emails):
        return {"problem": KEPT}, 403   # (drafts, unsent, go as ever)
    if target is not None and emails and all(set(email["mailboxIds"]) == {target["id"]} for email in emails):
        return {"counts": _counts(tree), "unread": _inbox_unread(tree), "left": False, "warning": True,
                "message": f'Message is already in "{tree.path(target)}" folder'}
    trash = tree.role("trash")
    patches, destroy = {}, []
    for email in emails:
        if action in ("read", "unread"):
            patches[email["id"]] = {"keywords/$seen": True if action == "read" else None}
        elif action in ("flag", "unflag"):
            patches[email["id"]] = {"keywords/$flagged": True if action == "flag" else None}
        elif action == "delete":
            if trash is None or any(tree.in_trash(tree.by_id.get(mailbox_id)) for mailbox_id in email["mailboxIds"]):
                destroy.append(email["id"])   # in the Trash already: gone for good
            else:
                patches[email["id"]] = {"mailboxIds": {trash["id"]: True}}
        else:
            patch = {"mailboxIds": {target["id"]: True}}
            if action == "spam":
                patch.update({"keywords/$junk": True, "keywords/$notjunk": None})
            elif action == "notspam":
                patch.update({"keywords/$junk": None, "keywords/$notjunk": True})
            patches[email["id"]] = patch
    _apply(mail, patches, destroy)
    count = len(emails)
    message = None
    if action in ("archive", "inbox", "move"):
        message = _moved(count, tree.path(target))
    elif action == "spam":
        message = "Email moved to spam" if count == 1 else "Emails moved to spam"
    elif action == "notspam":
        message = ('Email moved to "Inbox" and marked as not spam' if count == 1
                   else 'Emails moved to "Inbox" and marked as not spam')
    elif action == "delete":
        message = "Selected messages have been deleted" if destroy and not patches else _moved(count, "Trash")
    tree = _tree(mail)
    return {"counts": _counts(tree), "unread": _inbox_unread(tree), "message": message,
            "left": action in ("archive", "inbox", "move", "spam", "notspam", "delete"),
            "to": target["key"] if target else None}


# --- what's done to folders ---

def _name_problem(name, tree, parent, same=None):
    if not name:
        return "Folder name is required"
    if len(name) > folder_lib.LONGEST_NAME:
        return f"Folder name max length is {folder_lib.LONGEST_NAME} symbols"
    if not folder_lib.name_allowed(name):
        return "Not allowed characters were used for the folder name"
    siblings = parent["kids"] if parent else tree.tree
    if any(folder is not same and folder["label"].casefold() == name.casefold() for folder in siblings):
        return f'A folder named "{name}" already exists'
    return None


def _depth_problem(tree, parent, moving=None):
    if parent is not None and parent["root"] in folder_lib.NO_FOLDERS_IN:
        return f"Folders can't go in {tree.path(parent)}."
    below = max((folder["depth"] - moving["depth"] for folder in tree.inside(moving)), default=0) if moving else 0
    depth = (parent["depth"] + 1 if parent else 0) + below
    if depth > folder_lib.MAX_DEPTH:
        return f"Ooops, you cannot create more than {folder_lib.MAX_DEPTH + 1} levels of subfolders"
    return None


def _all_in(mail, folder, condition=None):
    """Every message in the folder (that meets the condition): their ids."""
    return _every(mail, {"operator": "AND", "conditions": [{"inMailbox": folder["id"]}, condition]} if condition
                  else {"inMailbox": folder["id"]})


def _message_count(tree, folder):
    return sum(inner["total"] for inner in tree.inside(folder))


@bp.post("/folders")
@login_required
@reachable
def create_folder():
    """A new folder, in another ("Create subfolder") or at the top ({"name", "parent"})."""
    data = request.get_json(silent=True) or {}
    name = " ".join((data.get("name") or "").split())
    mail = _mail()
    tree = _tree(mail)
    parent = None
    if data.get("parent"):
        parent = tree.by_key.get(data.get("parent"))
        if parent is None:
            return {"problem": GONE}, 404
    problem = _name_problem(name, tree, parent) or _depth_problem(tree, parent)
    if problem:
        return {"problem": problem}, 400
    result = mail.call(("Mailbox/set", {"create": {"new": {"name": name, "parentId": parent["id"] if parent else None}}}))[0]
    if "new" not in (result.get("created") or {}):
        return {"problem": f'A folder named "{name}" already exists'}, 400
    if parent is not None and parent["collapsed"]:
        views.set_collapsed(g.mailbox["id"], parent["key"], False)   # opened, to show the new one
    tree = _tree(mail)
    made = tree.by_id.get(result["created"]["new"]["id"])
    return {"counts": _counts(tree), "key": made["key"] if made else None, "html": _folders_html(tree, data.get("current")),
            "name": name}


@bp.post("/folders/order")
@login_required
@reachable
def folder_order():
    """The mailbox's own folders by name, or in the order they were made ("Sort alphabetically")."""
    data = request.get_json(silent=True) or {}
    views.set_folders_by_name(g.mailbox["id"], bool(data.get("by_name")))
    tree = _tree(_mail())
    return {"html": _folders_html(tree, data.get("current")), "by_name": bool(data.get("by_name"))}


FOLDER_ACTIONS = ("rename", "move", "to_archive", "to_inbox", "delete", "delete_all", "empty", "read_all", "unread_all",
                  "archive_all", "inbox_all", "collapse", "expand")


@bp.post("/folders/<folder>")
@login_required
@reachable
def folder_act(folder):
    """Something done to a folder ({"action", "name", "to", "current"}), as its menu offers:
    rename, move (or into the Archive or the Inbox), delete (to the Trash; from the Trash, for
    good), delete all its messages, empty the Trash, mark all read or unread, move all to the
    Archive or the Inbox, and fold or unfold the folders inside it. {"counts", "message",
    "html", "gone"} (gone: the folder being shown is no more)."""
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action not in FOLDER_ACTIONS:
        return {"problem": "Choose what to do with the folder."}, 400
    mail = _mail()
    tree = _tree(mail)
    chosen = tree.by_key.get(folder)
    if chosen is None:
        return {"problem": GONE}, 404
    if kept_mail() and (action in DELETING or (action == "move" and _to_trash(tree, tree.by_key.get(data.get("to") or "")))):
        return {"problem": KEPT}, 403
    if action not in chosen["menu"] and action not in ("move", "collapse", "expand"):
        return {"problem": f'"{chosen["label"]}" can\'t do that.'}, 400
    if action == "move" and not chosen["own"]:
        return {"problem": f'"{chosen["label"]}" is one of your mailbox\'s own folders: it stays.'}, 400
    message, warning, gone = None, False, []
    if action in ("collapse", "expand"):
        views.set_collapsed(g.mailbox["id"], chosen["key"], action == "collapse")
        return {"ok": True}
    if action == "rename":
        name = " ".join((data.get("name") or "").split())
        if name == chosen["label"]:
            return {"counts": _counts(tree), "html": _folders_html(tree, data.get("current")), "message": None}
        problem = _name_problem(name, tree, tree.by_id.get(chosen["parent"]) if chosen["parent"] else None, same=chosen)
        if problem:
            return {"problem": problem}, 400
        mail.call(("Mailbox/set", {"update": {chosen["id"]: {"name": name}}}))
        message = f'Folder "{chosen["label"]}" has been renamed to "{name}"'
    elif action in ("move", "to_archive", "to_inbox"):
        if action == "move":
            parent = tree.by_key.get(data.get("to")) if data.get("to") else None
            if data.get("to") and parent is None:
                return {"problem": GONE}, 404
        else:
            parent = tree.role("archive" if action == "to_archive" else "inbox")
        if parent is not None and parent in tree.inside(chosen):
            return {"problem": "A folder can't go inside itself."}, 400
        current_parent = tree.by_id.get(chosen["parent"]) if chosen["parent"] else None
        if parent is current_parent:
            return {"problem": f'"{chosen["label"]}" is there already.'}, 400
        problem = _name_problem(chosen["label"], tree, parent, same=chosen) or _depth_problem(tree, parent, chosen)
        if problem:
            return {"problem": problem}, 400
        mail.call(("Mailbox/set", {"update": {chosen["id"]: {"parentId": parent["id"] if parent else None}}}))
        count = _message_count(tree, chosen)
        message = (f'Moved folder "{chosen["label"]}" and {count} message(s) to "{tree.path(parent)}" folder' if parent
                   else f'Moved folder "{chosen["label"]}" and {count} message(s) to the top')
    elif action == "delete":
        trash = tree.role("trash")
        if tree.in_trash(chosen) or trash is None:
            for inner in reversed(tree.inside(chosen)):   # the folders inside it first
                mail.call(("Mailbox/set", {"destroy": [inner["id"]], "onDestroyRemoveEmails": True}))
            message = f'The "{chosen["label"]}" was permanently deleted'
        else:
            problem = _name_problem(chosen["label"], tree, trash, same=chosen)
            if problem:   # the Trash has one of that name: this one goes in with a number
                number = 2
                while _name_problem(f'{chosen["label"]} ({number})', tree, trash):
                    number += 1
                mail.call(("Mailbox/set", {"update": {chosen["id"]: {"name": f'{chosen["label"]} ({number})'}}}))
            mail.call(("Mailbox/set", {"update": {chosen["id"]: {"parentId": trash["id"]}}}))
            message = f'Moved folder "{chosen["label"]}" and {_message_count(tree, chosen)} message(s) to "Trash" folder'
        gone = [inner["key"] for inner in tree.inside(chosen)]
    elif action == "delete_all":
        ids = _all_in(mail, chosen)
        if not ids:
            message, warning = f'Folder "{chosen["label"]}" contains no messages', True
        elif tree.in_trash(chosen):
            _apply(mail, {}, ids)
            message = f'"{chosen["label"]}" has been cleared'
        else:
            trash = tree.role("trash")
            if trash is None:
                return {"problem": "'Trash' folder data is missing."}, 404
            _apply(mail, {email_id: {"mailboxIds": {trash["id"]: True}} for email_id in ids})
            message = f'Moved {len(ids)} message(s) to "Trash" folder'
    elif action == "empty":
        ids = []
        for inner in tree.inside(chosen):
            ids += _all_in(mail, inner)
        _apply(mail, {}, ids)
        for inner in reversed(tree.inside(chosen)[1:]):   # the Trash's folders go too
            mail.call(("Mailbox/set", {"destroy": [inner["id"]], "onDestroyRemoveEmails": True}))
        gone = [inner["key"] for inner in tree.inside(chosen)[1:]]
        message = "Trash has been cleared"
    elif action in ("read_all", "unread_all"):
        condition = {"notKeyword": "$seen"} if action == "read_all" else {"hasKeyword": "$seen"}
        value = True if action == "read_all" else None
        _apply(mail, {email_id: {"keywords/$seen": value} for email_id in _all_in(mail, chosen, condition)})
    elif action in ("archive_all", "inbox_all"):
        target = tree.role("archive" if action == "archive_all" else "inbox")
        ids = _all_in(mail, chosen)
        if not ids:
            message, warning = f'Folder "{chosen["label"]}" contains no messages', True
        else:
            _apply(mail, {email_id: {"mailboxIds": {target["id"]: True}} for email_id in ids})
            message = f'All emails moved to "{target["label"]}"'
    tree = _tree(mail)
    current = data.get("current")
    return {"counts": _counts(tree), "unread": _inbox_unread(tree), "message": message, "warning": warning,
            "html": _folders_html(tree, current), "gone": bool(current) and current in gone and current not in tree.by_key}


# --- a message's files, source and printout ---

def _email(mail, email_id, properties):
    got = mail.call(("Email/get", {"ids": [email_id], "properties": properties}))[0]["list"]
    if not got:
        abort(404)
    return got[0]


def _file_name(subject, otherwise):
    """A subject as a file's name: without the marks files can't have, its spaces single."""
    return " ".join(re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", subject or "").split())[:80] or otherwise


def _disposition(kind, name):
    ascii_name = re.sub(r'[^A-Za-z0-9 ._-]', "_", name)[:120] or "file"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(name[:200])}"


def _stream(download, chunk=64 * 1024):
    try:
        while True:
            data = download.read(chunk)
            if not data:
                break
            yield data
    finally:
        download.close()


@bp.get("/blob/<email_id>/<blob_id>")
@login_required
@reachable
def blob(email_id, blob_id):
    """One of a message's files: downloaded, or (?inline=1) shown, for pictures and PDFs only."""
    mail = _mail()
    email = _email(mail, email_id, ["attachments"])
    part = next((part for part in email.get("attachments") or [] if part.get("blobId") == blob_id), None)
    if part is None:
        abort(404)
    name = part.get("name") or "attachment"
    kind = (part.get("type") or "application/octet-stream").lower()
    inline = request.args.get("inline") == "1" and kind in SHOWN_TYPES
    download = mail.download(blob_id, name, kind)
    response = Response(_stream(download), mimetype=kind if inline else "application/octet-stream")
    response.headers["Content-Disposition"] = _disposition("inline" if inline else "attachment", name)
    response.headers["X-Content-Type-Options"] = "nosniff"
    if not (inline and kind == "application/pdf"):   # (the browser's PDF viewer doesn't open in a sandbox)
        response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
    response.headers["Cache-Control"] = "private, max-age=3600"
    if part.get("size"):
        response.headers["Content-Length"] = str(part["size"])
    return response


@bp.get("/zip/<email_id>")
@login_required
@reachable
def zip_all(email_id):
    """All of a message's files, in one zip ("Save all")."""
    mail = _mail()
    email = _email(mail, email_id, ["attachments", "subject"])
    parts = [part for part in email.get("attachments") or [] if part.get("blobId")]
    if not parts:
        abort(404)
    spool = tempfile.SpooledTemporaryFile(max_size=20 * 1024 ** 2)
    used = set()
    with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED) as archive:
        for part in parts:
            name = (part.get("name") or "attachment").replace("/", "_").replace("\\", "_")
            base, dot, extension = name.rpartition(".")
            number = 2
            while name.lower() in used:   # the same name twice: file (2).pdf
                name = f"{base or extension} ({number}){dot + extension if base else ''}"
                number += 1
            used.add(name.lower())
            download = mail.download(part["blobId"], part.get("name") or "attachment", part.get("type") or "")
            with download, archive.open(name, "w") as out:
                while True:
                    data = download.read(64 * 1024)
                    if not data:
                        break
                    out.write(data)
    spool.seek(0)
    return send_file(spool, mimetype="application/zip", as_attachment=True,
                     download_name=f"{_file_name(email.get('subject'), 'attachments')}.zip")


@bp.get("/source/<email_id>")
@login_required
@reachable
def source(email_id):
    """The message as it came, headers and all: to read (View source), or ?download=1 (Download)."""
    mail = _mail()
    email = _email(mail, email_id, ["blobId", "subject"])
    with mail.download(email["blobId"], "message.eml", "message/rfc822") as download:
        raw = download.read()
    if request.args.get("download") == "1":
        response = Response(raw, mimetype="message/rfc822")
        response.headers["Content-Disposition"] = _disposition("attachment", f"{_file_name(email.get('subject'), 'message')}.eml")
        return response
    return Response(raw.decode("utf-8", "replace"), mimetype="text/plain",
                    headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@bp.get("/print/<email_id>")
@login_required
@reachable
def print_view(email_id):
    """The message on a page of its own, to print (it asks the browser to, as it opens)."""
    mail = _mail()
    tree = _tree(mail)
    got = mail.call(("Email/get", {"ids": [email_id], "properties": messages.READ_PROPERTIES,
                                   "fetchHTMLBodyValues": True, "fetchTextBodyValues": True}))[0]["list"]
    if not got:
        abort(404)
    email = got[0]
    shown = messages.view(email, tree.of(email))
    kind, text = messages.body(email)
    pictures = {part["cid"]: part for part in shown["files"] if part["cid"]}

    def picture_url(cid):
        part = pictures.get(cid)
        return url_for("mail.blob", email_id=email_id, blob_id=part["blob"], inline=1) if part and part["image"] else None

    prepared = content.from_html(text, picture_url) if kind == "html" else content.from_text(text)
    response = Response(render_template("webmail-print.html", message=shown, body=prepared.html, email=g.mailbox["email"]))
    response.headers["Content-Security-Policy"] = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                   "img-src 'self' data: https: http:; font-src 'self'")
    return response


# --- search ---

@bp.get("/search")
@login_required
@reachable
def search():
    """Messages that say something (the search field): the panel under the field as you type
    ({"html", "total"}), or all of them, in the list (Enter, or "All results")."""
    text = request.args.get("q", "").strip()[:LONGEST_SEARCH]
    scope = request.args.get("in") or None
    if not text:
        return {"html": "", "total": 0} if _wants_json() else redirect(url_for("mail.folder", folder=scope or "inbox"))
    if not _wants_json():
        return _page(SEARCH, text=text, scope=scope)
    mail = _mail()
    tree = _tree(mail)
    folder = tree.by_key.get(scope) if scope else None
    found, _, total = _list(mail, tree, folder, "newest", [], text=text, limit=SEARCH_PANEL)
    panel = get_template_attribute("webmail-search.html", "search_panel")
    return {"html": str(panel(found, text, total, folder, url_for("mail.search", q=text, **({"in": scope} if scope else {})))),
            "total": total}
