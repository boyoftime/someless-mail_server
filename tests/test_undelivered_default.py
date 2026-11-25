"""The Undelivered folder is on to begin with: every mailbox's notices of undelivered mail skip its
Inbox until its owner switches that off (webmail Settings). The rule that files them lives in the
engine (the mailbox's Sieve script), so the engine sync installs each mailbox's rules once its account
is there, a new mailbox's and the ones from before alike, whether or not its webmail is ever opened.
The engine and the mail are the made-up ones."""
import re

import pytest

from someless.db import get_db
from someless.webmail import sieve, views
from someless.webmail.jmap import MailUnavailable
from jmap_fake import FakeJmap
from test_engine_sync import a_mailbox, authenticated_domain, sync_now
from test_webmail_undelivered import RULE, switch, undelivered
from test_webmail_settings import jmap, mail, mailbox, post, webmail  # noqa: F401 (the fixtures)


def installed_at(app, mailbox_id):
    with app.app_context():
        return get_db().execute("SELECT rules_installed_at FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()[0]


@pytest.fixture
def boxes(app, engine):
    """The mail of each mailbox the sync reaches: {email: FakeJmap}."""
    made = {}
    app.config["JMAP"] = lambda email: made.setdefault(email, FakeJmap())
    return made


# --- on to begin with ---

def test_a_mailbox_starts_with_it_on(mail, mailbox):
    page = mail.get("/settings").get_data(as_text=True)

    assert re.search(r'role="switch" aria-checked="true"\s+data-wm-undelivered-switch', page)
    with mail.application.app_context():
        assert sieve.settings(mailbox)["undelivered_on"] is True


def test_switched_off_it_stays_off_whatever_else_is_saved(mail, mailbox):
    switch(mail, False)

    post(mail, "/settings/forwarding", address="amina@example.com", on=True)
    with mail.application.app_context():
        views.set_display_name(mailbox, "Lewis")
        get_db().commit()
        assert sieve.settings(mailbox)["undelivered_on"] is False
    assert re.search(r'aria-checked="false"\s+data-wm-undelivered-switch', mail.get("/settings").get_data(as_text=True))


def test_switched_on_again_it_is_on(mail, mailbox):
    switch(mail, False)
    switch(mail, True)

    with mail.application.app_context():
        assert sieve.settings(mailbox)["undelivered_on"] is True


# --- the rule in the engine, installed by the sync ---

def test_the_sync_installs_a_new_mailboxs_rule_and_folder(app, boxes):
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", authenticated_domain(app))

    assert sync_now(app)

    box = boxes["ceo@pineloop.online"]
    folder = undelivered(box)
    assert folder and RULE + f'\n    fileinto :mailboxid "{folder}" :create "Undelivered";' in box.active_script()
    assert installed_at(app, mailbox_id) is not None


def test_once_installed_it_isnt_installed_again(app, boxes, monkeypatch):
    a_mailbox(app, "ceo@pineloop.online", authenticated_domain(app))
    sync_now(app)
    written = []
    monkeypatch.setattr(sieve, "install", lambda mail, text: written.append(text))

    sync_now(app)

    assert written == []


def test_a_mailbox_switched_off_gets_its_rules_without_it(app, boxes):
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", authenticated_domain(app))
    with app.app_context():
        sieve.save_settings(mailbox_id, undelivered_on=False)

    sync_now(app)

    box = boxes["ceo@pineloop.online"]
    assert RULE not in (box.active_script() or "") and undelivered(box) is None


def test_its_own_filters_and_auto_reply_go_in_too(app, boxes):
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", authenticated_domain(app), aliases=("sales@pineloop.online",))
    with app.app_context():
        sieve.save_settings(mailbox_id, reply_on=True, reply_subject="Away", reply_html="<p>Back Monday</p>")

    sync_now(app)

    script = boxes["ceo@pineloop.online"].active_script()
    assert "vacation" in script and '"sales@pineloop.online"' in script and RULE in script


def test_a_disabled_mailbox_waits_until_its_enabled(app, boxes):
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", authenticated_domain(app))
    with app.app_context():
        get_db().execute("UPDATE mailboxes SET disabled = 1 WHERE id = ?", (mailbox_id,))
        get_db().commit()

    sync_now(app)

    assert "ceo@pineloop.online" not in boxes and installed_at(app, mailbox_id) is None


def test_the_engine_out_of_reach_leaves_it_for_the_next_sync(app, engine):
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", authenticated_domain(app))

    def unreachable(email):
        raise MailUnavailable("down")
    app.config["JMAP"] = unreachable

    assert sync_now(app)   # (the sync itself went through)
    assert installed_at(app, mailbox_id) is None

    box = FakeJmap()
    app.config["JMAP"] = lambda email: box
    sync_now(app)
    assert RULE in box.active_script() and installed_at(app, mailbox_id) is not None


def test_an_account_made_again_gets_its_rules_again(app, boxes, engine):
    mailbox_id = a_mailbox(app, "ceo@pineloop.online", authenticated_domain(app))
    sync_now(app)
    first = boxes.pop("ceo@pineloop.online")
    account = engine.named("Account", "ceo")
    del engine.objects["Account"][account["id"]]   # (gone from the engine: made again, without its old mail and rules)

    sync_now(app)

    again = boxes["ceo@pineloop.online"]
    assert again is not first and RULE in again.active_script()


def test_the_webmails_own_writing_counts_as_installed(mail, mailbox, app):
    switch(mail, False)

    assert installed_at(app, mailbox) is not None
