"""The Undelivered folder (webmail/undelivered.py, Settings > Undelivered mail): once a mailbox
switches it on, notices about mail that couldn't be delivered skip its Inbox and go to a folder of
their own, filed by the engine as they come (the mailbox's Sieve script), so mail apps see it too.
The ones in the Inbox already can be moved there in one go. The engine is the made-up one."""
import re

from someless.webmail import sieve
from test_webmail import folder_names, text
from test_webmail_settings import jmap, mail, mailbox, post, webmail  # noqa: F401 (the fixtures)

DSN = 'multipart/report; report-type=delivery-status; boundary="b1"'
DAEMON = ("Mail Delivery Subsystem", "MAILER-DAEMON@someless.internal")
RULE = 'if anyof(header :contains "content-type" "delivery-status", address :localpart :is "from" "mailer-daemon") {'


def undelivered(jmap):
    found = [box_id for box_id, box in jmap.mailboxes.items() if box["name"] == "Undelivered" and not box["parentId"]]
    assert len(found) <= 1, found
    return found[0] if found else None


def notices(jmap):
    """Notices of every kind, in the Inbox, and mail that isn't one: {name: id}."""
    return {
        "ours": jmap.add(subject="Failed to deliver message", sender=DAEMON, content_type=DSN),
        "old host": jmap.add(subject="Mail delivery failed: returning message to sender",   # no report: plain text
                             sender=("Mail Delivery System", "Mailer-Daemon@cpl109.main-hosting.eu")),
        "outlook": jmap.add(subject="Undeliverable: Invoice", sender=("Microsoft Outlook", "postmaster@outlook.com"),
                            content_type=DSN),
        "a person": jmap.add(subject="Your delisting request", sender=("Postmaster Team", "postmaster@outlook.com")),
        "a friend": jmap.add(subject="Lunch?", sender=("Amina Hassan", "amina@example.com")),
        "archived": jmap.add(folder="archive", subject="Failed to deliver message", sender=DAEMON, content_type=DSN),
    }


def switch(mail, on):
    return post(mail, "/settings/undelivered", on=on)


def test_settings_has_the_card_switched_off_to_begin_with(mail):
    page = mail.get("/settings").get_data(as_text=True)

    assert ">Undelivered mail</h2>" in page
    assert re.search(r'role="switch" aria-checked="false"\s+data-wm-undelivered-switch', page)


def test_switching_it_on_makes_the_folder_and_the_rule(mail, jmap):
    answer = switch(mail, True)

    assert answer.status_code == 200
    assert answer.get_json()["on"] is True
    assert answer.get_json()["message"] == "Notices about undelivered mail now go to the Undelivered folder"
    folder = undelivered(jmap)
    assert folder
    script = jmap.active_script()
    block = script[script.index(RULE):]
    assert block.startswith(RULE + f'\n    fileinto :mailboxid "{folder}" :create "Undelivered";\n    stop;\n}}')
    assert re.search(r'require \[[^\]]*"fileinto"[^\]]*"mailbox"[^\]]*"mailboxid"', script)
    with mail.application.app_context():
        from someless.db import get_db
        mailbox_id = get_db().execute("SELECT id FROM mailboxes WHERE email = 'ceo@pineloop.online'").fetchone()[0]
        assert sieve.settings(mailbox_id)["undelivered_on"] is True


def test_it_comes_after_forwarding_and_before_the_filters(mail, jmap):
    """Forwarded like any mail, then filed before a filter can take it elsewhere."""
    post(mail, "/settings/forwarding", address="boss@example.com", on=True)
    archive = next(box_id for box_id, box in jmap.mailboxes.items() if box["role"] == "archive")
    post(mail, "/settings/filters", name="Invoices", operator="all",
         conditions=[{"prop": "subject", "op": "contains", "value": "Invoice"}],
         actions=[{"type": "move", "folder": archive}])

    switch(mail, True)

    script = jmap.active_script()
    assert script.index("redirect :copy") < script.index(RULE) < script.index("# Invoices")


def test_switching_it_on_says_how_many_notices_wait_in_the_inbox(mail, jmap):
    notices(jmap)

    assert switch(mail, True).get_json()["waiting"] == 3   # ours, the old host's and Outlook's: not the person's


def test_the_ones_waiting_move_in_one_go(mail, jmap):
    made = notices(jmap)
    switch(mail, True)

    answer = post(mail, "/settings/undelivered/move")

    assert answer.status_code == 200 and answer.get_json()["message"] == 'Moved 3 notices to "Undelivered"'
    assert answer.get_json()["waiting"] == 0
    folder = undelivered(jmap)
    for name in ("ours", "old host", "outlook"):
        assert jmap.emails[made[name]]["mailboxIds"] == {folder: True}, name
    for name in ("a person", "a friend"):
        assert jmap.emails[made[name]]["mailboxIds"] == {jmap.role("inbox"): True}, name
    assert folder not in jmap.emails[made["archived"]]["mailboxIds"]   # only the Inbox's


def test_one_notice_moved_is_one_notice(mail, jmap):
    jmap.add(subject="Failed to deliver message", sender=DAEMON, content_type=DSN)
    switch(mail, True)

    assert post(mail, "/settings/undelivered/move").get_json()["message"] == 'Moved 1 notice to "Undelivered"'


def test_nothing_to_move_says_so(mail, jmap):
    switch(mail, True)

    answer = post(mail, "/settings/undelivered/move").get_json()

    assert answer["message"] == "There are no notices in your Inbox to move" and answer["warning"] is True


def test_switching_it_off_keeps_the_folder_and_its_mail(mail, jmap):
    switch(mail, True)
    folder = undelivered(jmap)
    kept = jmap.add(folder=folder, subject="Failed to deliver message", sender=DAEMON, content_type=DSN)

    answer = switch(mail, False)

    assert answer.get_json()["on"] is False
    assert answer.get_json()["message"] == "Notices about undelivered mail now stay in your Inbox"
    assert RULE not in jmap.active_script()
    assert undelivered(jmap) == folder and kept in jmap.emails


def test_the_folder_shows_between_spam_and_trash(mail, jmap):
    switch(mail, True)

    page = text(mail.get("/mail/inbox"))

    assert folder_names(page) == ["Inbox", "Drafts", "Sent", "Archive", "Spam", "Undelivered", "Trash"]
    folder = re.search(r'<div class="wm-folder[^"]*"[^>]*data-folder="undelivered"[^>]*>', page).group(0)
    assert 'data-role="undelivered"' in folder
    assert re.search(r'data-name="Undelivered"[^>]*data-menu="read_all unread_all delete_all"', page)   # no folders in it, no renaming


def test_a_folder_of_that_name_made_before_is_the_one(mail, jmap):
    before = jmap.add_mailbox("Undelivered")

    switch(mail, True)

    assert undelivered(jmap) == before


def test_the_engine_refusing_leaves_it_off(mail, jmap):
    jmap.refuse_script = "no"

    answer = switch(mail, True)

    assert answer.status_code == 502
    assert answer.get_json()["problem"] == "Failed to update the Undelivered folder setting."
    assert re.search(r'aria-checked="false"\s+data-wm-undelivered-switch', mail.get("/settings").get_data(as_text=True))


def test_the_settings_page_offers_to_move_the_ones_waiting(mail, jmap):
    switch(mail, True)
    jmap.add(subject="Failed to deliver message", sender=DAEMON, content_type=DSN)

    page = mail.get("/settings").get_data(as_text=True)

    assert re.search(r'aria-checked="true"\s+data-wm-undelivered-switch', page)
    assert 'data-wm-undelivered-waiting="1"' in page and ">Move them</button>" in page


def test_without_the_folder_known_the_rule_files_by_name():
    kept = {"forward_to": None, "forward_on": False, "forward_keep": True, "reply_on": False, "reply_start": None,
            "reply_end": None, "reply_subject": "", "reply_html": "", "undelivered_on": True}

    script = sieve.script(kept, [], {}, ["ceo@pineloop.online"])

    assert RULE + '\n    fileinto :create "Undelivered";\n    stop;\n}' in script


def test_the_readme_tells_of_it():
    from pathlib import Path
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    webmail = readme[readme.index("What they find there:"):readme.index("**On HTTPS, at `webmail.example.com`:**")]

    assert "**Undelivered folder:**" in webmail and "Settings → Undelivered mail" in webmail
    assert "hidden while you write" not in readme and "eye button" not in readme   # (the signature's in view now)
