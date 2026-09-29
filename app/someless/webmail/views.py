"""What the webmail remembers of how each mailbox likes its mail shown, as PrivateEmail does: per
folder, the list's sort and filters ("Sort and filter") and whether the folders inside it are
folded away; and whether the folders go by name ("Sort alphabetically", in a folder's menu).
Kept here, so it's the same on every computer the mailbox is opened on."""
from ..db import get_db

SORTS = ("newest", "oldest", "largest", "smallest")
FILTERS = ("unread", "favorites", "important")   # PrivateEmail's Unread, Favorites and High Priority


def list_options(mailbox_id, folder):
    """The folder's (sort, [filters])."""
    row = get_db().execute("SELECT sort, filters FROM webmail_views WHERE mailbox_id = ? AND folder = ?",
                           (mailbox_id, folder)).fetchone()
    if row is None:
        return "newest", []
    sort = row["sort"] if row["sort"] in SORTS else "newest"
    return sort, [name for name in FILTERS if name in (row["filters"] or "").split(",")]


def save_list_options(mailbox_id, folder, sort, filters):
    database = get_db()
    database.execute("INSERT INTO webmail_views (mailbox_id, folder, sort, filters) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT (mailbox_id, folder) DO UPDATE SET sort = excluded.sort, filters = excluded.filters",
                     (mailbox_id, folder, sort if sort in SORTS else "newest",
                      ",".join(name for name in FILTERS if name in filters)))
    database.commit()


def collapsed(mailbox_id):
    """The folders whose own folders are folded away: their keys."""
    rows = get_db().execute("SELECT folder FROM webmail_views WHERE mailbox_id = ? AND collapsed = 1", (mailbox_id,))
    return {row["folder"] for row in rows}


def set_collapsed(mailbox_id, folder, folded):
    database = get_db()
    database.execute("INSERT INTO webmail_views (mailbox_id, folder, collapsed) VALUES (?, ?, ?) "
                     "ON CONFLICT (mailbox_id, folder) DO UPDATE SET collapsed = excluded.collapsed",
                     (mailbox_id, folder, 1 if folded else 0))
    database.commit()


def folders_by_name(mailbox_id):
    row = get_db().execute("SELECT folders_by_name FROM webmail_settings WHERE mailbox_id = ?", (mailbox_id,)).fetchone()
    return bool(row and row["folders_by_name"])


def set_folders_by_name(mailbox_id, on):
    database = get_db()
    database.execute("INSERT INTO webmail_settings (mailbox_id, folders_by_name) VALUES (?, ?) "
                     "ON CONFLICT (mailbox_id) DO UPDATE SET folders_by_name = excluded.folders_by_name",
                     (mailbox_id, 1 if on else 0))
    database.commit()


def display_name(mailbox_id):
    """The name the mailbox's mail goes out with, as set in Settings (None: not set)."""
    row = get_db().execute("SELECT display_name FROM webmail_settings WHERE mailbox_id = ?", (mailbox_id,)).fetchone()
    return row["display_name"] if row and row["display_name"] else None


def set_display_name(mailbox_id, name):
    database = get_db()
    database.execute("INSERT INTO webmail_settings (mailbox_id, display_name) VALUES (?, ?) "
                     "ON CONFLICT (mailbox_id) DO UPDATE SET display_name = excluded.display_name", (mailbox_id, name))
    database.commit()


PREFERENCES = ("new_mail_sound", "notifications")


def preferences(mailbox_id):
    """The mailbox's system preferences: {"new_mail_sound": bool, "notifications": bool}."""
    row = get_db().execute("SELECT new_mail_sound, notifications FROM webmail_settings WHERE mailbox_id = ?",
                           (mailbox_id,)).fetchone()
    return {"new_mail_sound": bool(row["new_mail_sound"]) if row else True,
            "notifications": bool(row["notifications"]) if row else False}


def set_preference(mailbox_id, name, on):
    if name not in PREFERENCES:
        raise ValueError(name)
    database = get_db()
    database.execute(f"INSERT INTO webmail_settings (mailbox_id, {name}) VALUES (?, ?) "
                     f"ON CONFLICT (mailbox_id) DO UPDATE SET {name} = excluded.{name}", (mailbox_id, 1 if on else 0))
    database.commit()


def signatures(mailbox_id):
    """The mailbox's signatures, the default first, then by name."""
    return [dict(row) for row in get_db().execute(
        "SELECT id, name, html, is_default FROM webmail_signatures WHERE mailbox_id = ? ORDER BY is_default DESC, name COLLATE NOCASE",
        (mailbox_id,))]


def forget(mailbox_id):
    """A mailbox deleted: what was kept for it goes too."""
    database = get_db()
    for table in ("webmail_views", "webmail_settings", "webmail_signatures", "webmail_rules", "webmail_logins"):
        database.execute(f"DELETE FROM {table} WHERE mailbox_id = ?", (mailbox_id,))
