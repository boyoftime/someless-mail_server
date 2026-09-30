"""The Mailboxes page (mailboxes.py): inboxes at the authenticated domains, each an account in
the mail engine, with its password (kept only as a hash), storage and aliases. A mailbox is made
for one of the senders: the sender first, then its mailbox."""
import html
import json
import re

from someless import mail_password, mailboxes
from someless.db import get_db
from test_engine_sync import authenticated_domain

GB = 1024 ** 3
MB = 1024 ** 2
GOOD = "Mailbox-Pass-1!"


def text(response):
    return html.unescape(response.get_data(as_text=True))


def plain(page):
    return re.sub(r"<[^>]+>", "", page)


def create(client, local="ceo", domain="pineloop.online", password=GOOD, confirm=None, storage="15", unit="GB",
           sender=True):
    """A mailbox for local@domain, made the way the dialog makes it: for a sender, added first
    (unless sender=False)."""
    email = f"{local}@{domain}"
    if sender:
        client.post("/senders", data={"name": local.title(), "email": email})   # (there already: refused, fine)
    return client.post("/mailboxes", data={"email": email, "password": password,
                                           "confirm": password if confirm is None else confirm,
                                           "storage": storage, "unit": unit})


def rows(app, table="mailboxes"):
    with app.app_context():
        return get_db().execute(f"SELECT * FROM {table} ORDER BY id").fetchall()


def test_mailboxes_need_login(client):
    assert client.get("/mailboxes").headers["Location"] == "/login"


def test_the_menu_has_mailboxes_after_senders(client, login):
    login()

    page = text(client.get("/mailboxes"))

    menu = page[page.index('<dialog class="side-menu"'):page.index("</dialog>")]
    labels = re.findall(r'<span class="side-menu-label">([^<]+)</span>', menu)
    assert labels.index("Mailboxes") == labels.index("Senders") + 1
    assert re.search(r'<a [^>]*href="/mailboxes"[^>]*aria-current="page"', menu)


def test_without_an_authenticated_domain_it_says_what_to_do_first(app, client, login):
    authenticated_domain(app, "notyet.org", authenticated=False)
    login()

    page = text(client.get("/mailboxes"))

    assert "Authenticate a domain first" in plain(page) and 'href="/domains"' in page
    assert 'name="local"' not in page


def a_sender(app, domain_id, email, name="Sender"):
    with app.app_context():
        get_db().execute("INSERT INTO senders (name, email, domain_id, created_at) VALUES (?, ?, ?, 0)", (name, email, domain_id))
        get_db().commit()


def test_the_create_dialog_offers_the_senders_without_a_mailbox(app, client, login):
    domain_id = authenticated_domain(app, "pineloop.online")
    elsewhere = authenticated_domain(app, "notyet.org", authenticated=False)
    a_sender(app, domain_id, "info@pineloop.online", "Info")
    a_sender(app, elsewhere, "hi@notyet.org")   # its domain isn't authenticated (any more)
    login()
    create(client)   # ceo@pineloop.online: a sender with its mailbox now

    page = text(client.get("/mailboxes"))

    dialog = page[page.index('id="create-mailbox-dialog"'):]
    select = re.search(r'<select[^>]*name="email"[^>]*>(.*?)</select>', dialog, re.S).group(1)
    assert re.findall(r'<option value="([^"]+)"', select) == ["info@pineloop.online"]
    assert "Info &lt;info@pineloop.online&gt;" in select or "Info <info@pineloop.online>" in select
    assert re.search(r'<select[^>]*name="unit"', dialog) and "GB" in dialog and "MB" in dialog
    assert 'name="password"' in dialog and 'name="confirm"' in dialog


def test_without_a_free_sender_the_dialog_says_to_add_one(app, client, login):
    authenticated_domain(app)
    login()

    page = text(client.get("/mailboxes"))

    dialog = page[page.index('id="create-mailbox-dialog"'):]
    dialog = dialog[:dialog.index("</dialog>")]
    assert 'href="/senders/new"' in dialog and "Add a sender first" in plain(dialog)
    assert 'name="password"' not in dialog


def test_a_mailbox_is_created(app, client, login, engine):
    domain_id = authenticated_domain(app)
    login()

    response = create(client)

    assert response.headers["Location"] == "/mailboxes"
    (row,) = rows(app)
    assert (row["email"], row["domain_id"], row["quota_bytes"]) == ("ceo@pineloop.online", domain_id, 15 * GB)
    assert mail_password.password_ok(row["password_hash"], GOOD) and GOOD not in row["password_hash"]
    assert engine.named("Account", "ceo")   # and the engine has it
    assert "ceo@pineloop.online" in plain(text(client.get("/mailboxes")))


def test_the_password_follows_the_password_rules_and_is_typed_twice(app, client, login):
    authenticated_domain(app)
    login()

    weak = create(client, password="short")
    mismatch = create(client, confirm="Mailbox-Pass-2!")

    assert weak.status_code == 400 and "at least 8 characters" in text(weak)
    assert mismatch.status_code == 400 and "don't match" in text(mismatch)
    assert 'id="create-mailbox-dialog"' in text(mismatch) and "data-open" in text(mismatch)   # opens again
    assert rows(app) == []


def test_storage_is_given_in_gb_or_mb(app, client, login):
    authenticated_domain(app)
    login()

    create(client, local="small", storage="500", unit="MB")
    create(client, local="half", storage="1.5", unit="GB")
    for storage in ("0", "abc", "-3", ""):
        assert create(client, local="bad", storage=storage).status_code == 400, storage

    assert [row["quota_bytes"] for row in rows(app)] == [500 * MB, int(1.5 * GB)]


def test_an_address_is_used_once(app, client, login):
    authenticated_domain(app)
    login()
    create(client)
    mailbox_id = rows(app)[0]["id"]
    client.post(f"/mailboxes/{mailbox_id}/aliases", data={"local": "hello", "domain": "pineloop.online"})

    again = create(client, local="CEO")
    alias = create(client, local="hello")

    assert again.status_code == 400 and "already" in text(again)
    assert alias.status_code == 400 and "already" in text(alias)
    assert len(rows(app)) == 1


def test_a_mailbox_is_made_for_a_sender(app, client, login):
    domain_id = authenticated_domain(app)
    a_sender(app, domain_id, "support@pineloop.online", "Support")
    login()

    assert create(client, local="support", sender=False).headers["Location"] == "/mailboxes"


def test_an_address_that_isnt_a_sender_gets_no_mailbox(app, client, login):
    authenticated_domain(app)
    login()

    refused = create(client, local="nobody", sender=False)

    assert refused.status_code == 400 and "isn't a sender" in text(refused) and 'href="/senders' in text(refused)
    assert rows(app) == []


def test_sizes_read_as_people_say_them():
    assert [mailboxes.size_text(size) for size in (500 * MB, 15 * GB, int(14.87 * GB), 1536 * MB, 0)] == [
        "500 MB", "15 GB", "14.87 GB", "1.5 GB", "0 MB"]


def test_edit_storage_starts_from_the_size_as_it_was_typed(app, client, login):
    authenticated_domain(app)
    login()
    for local, storage, unit in (("a", "15", "GB"), ("b", "14.87", "GB"), ("c", "500", "MB"), ("d", "1536", "MB")):
        create(client, local=local, storage=storage, unit=unit)

    page = text(client.get("/mailboxes"))

    found = re.findall(r'data-storage-for="(\w)@[^"]+" [^>]*data-size="([^"]+)" data-unit="(\w+)"', page)
    assert sorted(found) == [("a", "15", "GB"), ("b", "14.87", "GB"), ("c", "500", "MB"), ("d", "1.5", "GB")]


def test_each_mailbox_has_its_settings_with_disable_delete(app, client, login):
    authenticated_domain(app)
    login()
    create(client)

    page = text(client.get("/mailboxes"))

    gear = re.search(r'<button [^>]*data-keep-for="ceo@pineloop.online"[^>]*>', page).group(0)
    assert 'data-webmail="0"' in gear and 'data-apps="0"' in gear and 'data-tip="Mailbox settings"' in gear
    dialog = page.split('id="keep-dialog"')[1].split("</dialog>")[0]
    assert 'name="webmail"' in dialog and 'name="apps"' in dialog and "Disable delete" in dialog


def test_deleting_is_switched_off_in_the_webmail_and_in_mail_apps(app, client, login):
    authenticated_domain(app)
    login()
    create(client)
    box = rows(app)[0]

    both = client.post(f"/mailboxes/{box['id']}/keep", data={"webmail": "on", "apps": "on"})
    both_page = plain(text(client.get("/mailboxes")))
    webmail_only = client.post(f"/mailboxes/{box['id']}/keep", data={"webmail": "on"})
    kept = rows(app)[0]
    client.post(f"/mailboxes/{box['id']}/keep", data={})
    again = rows(app)[0]
    page = plain(text(client.get("/mailboxes")))

    assert both.headers["Location"] == "/mailboxes" and webmail_only.headers["Location"] == "/mailboxes"
    assert "Deleting is now switched off for ceo@pineloop.online in the webmail and in mail apps." in both_page
    assert "Deleting is switched off in the webmail and in mail apps." in both_page   # (on its card)
    assert (kept["no_delete_webmail"], kept["no_delete_apps"]) == (1, 0)
    assert (again["no_delete_webmail"], again["no_delete_apps"]) == (0, 0)
    assert "ceo@pineloop.online can delete messages again." in page and "Deleting is switched off" not in page


def test_mailboxes_are_searched_by_address(app, client, login):
    authenticated_domain(app)
    login()
    for local in ("amy", "zed"):
        create(client, local=local)

    page = text(client.get("/mailboxes?q=ZED"))

    assert "data-mailbox-search" in page and 'value="ZED"' in page
    assert re.search(r'data-mailbox="amy@pineloop\.online[^"]*" hidden', page)   # (filtered out)
    assert re.search(r'data-mailbox="zed@pineloop\.online[^"]*">', page)
    assert re.search(r'class="mailbox-no-match" hidden', page)


def test_a_mailbox_is_found_by_its_alias_and_a_search_finding_none_says_so(app, client, login):
    authenticated_domain(app)
    login()
    create(client, local="amy")
    box = rows(app)[0]
    client.post(f"/mailboxes/{box['id']}/aliases", data={"local": "hello", "domain": "pineloop.online"})

    found = text(client.get("/mailboxes?q=hello"))
    none = text(client.get("/mailboxes?q=nobody"))

    assert re.search(r'data-mailbox="amy@pineloop\.online hello@pineloop\.online">', found)
    assert re.search(r'class="mailbox-no-match">No mailboxes match “<span data-search-text>nobody</span>”', none)


def test_the_newest_mailbox_is_listed_first(app, client, login):
    authenticated_domain(app)
    login()
    for local in ("amy", "zed", "mia"):
        create(client, local=local)

    page = text(client.get("/mailboxes"))

    assert re.findall(r'data-storage-for="(\w+)@', page) == ["mia", "zed", "amy"]


def test_the_list_shows_each_mailboxs_storage_use(app, client, login, engine):
    authenticated_domain(app)
    login()
    create(client)
    account = next(obj for obj in engine.objects["Account"].values() if obj.get("name") == "ceo")
    account["usedDiskQuota"] = int(0.15 * GB)   # what the engine says it holds

    page = plain(text(client.get("/mailboxes")))

    assert "1.0% used" in page and "14.85 GB available" in page


def test_the_password_changes(app, client, login, engine):
    authenticated_domain(app)
    login()
    create(client)
    before = rows(app)[0]

    response = client.post(f"/mailboxes/{before['id']}/password", data={"password": "Brand-New-456!", "confirm": "Brand-New-456!"})

    after = rows(app)[0]
    assert response.headers["Location"] == "/mailboxes"
    assert mail_password.password_ok(after["password_hash"], "Brand-New-456!")
    assert after["password_version"] == before["password_version"] + 1   # the engine gets it at the next sync
    bad = client.post(f"/mailboxes/{before['id']}/password", data={"password": "Brand-New-456!", "confirm": "other"})
    assert bad.status_code == 400


def test_the_storage_changes(app, client, login):
    authenticated_domain(app)
    login()
    create(client)
    mailbox_id = rows(app)[0]["id"]

    client.post(f"/mailboxes/{mailbox_id}/storage", data={"storage": "20", "unit": "GB"})

    assert rows(app)[0]["quota_bytes"] == 20 * GB


def test_aliases_come_and_go_as_many_as_wanted(app, client, login, engine):
    authenticated_domain(app)
    authenticated_domain(app, "cloudnix.net")
    login()
    create(client)
    mailbox_id = rows(app)[0]["id"]

    for local, domain in (("hello", "pineloop.online"), ("sales", "pineloop.online"), ("ceo", "cloudnix.net")):
        client.post(f"/mailboxes/{mailbox_id}/aliases", data={"local": local, "domain": domain})

    aliases = rows(app, "mailbox_aliases")
    assert [alias["email"] for alias in aliases] == ["hello@pineloop.online", "sales@pineloop.online", "ceo@cloudnix.net"]
    box = engine.named("Account", "ceo")
    assert sorted(alias["name"] for alias in box["aliases"].values()) == ["ceo", "hello", "sales"]

    client.post(f"/mailboxes/{mailbox_id}/aliases/{aliases[0]['id']}/delete")

    assert [alias["email"] for alias in rows(app, "mailbox_aliases")] == ["sales@pineloop.online", "ceo@cloudnix.net"]


def test_a_mailbox_is_deleted_with_its_aliases(app, client, login, engine):
    authenticated_domain(app)
    login()
    create(client)
    mailbox_id = rows(app)[0]["id"]
    client.post(f"/mailboxes/{mailbox_id}/aliases", data={"local": "hello", "domain": "pineloop.online"})

    response = client.post(f"/mailboxes/{mailbox_id}/delete")

    assert response.headers["Location"] == "/mailboxes"
    assert rows(app) == [] and rows(app, "mailbox_aliases") == []
    assert engine.named("Account", "ceo") is None


def test_each_mailbox_has_its_configuration_details(app, client, login):
    authenticated_domain(app)
    login()
    create(client)

    page = text(client.get("/mailboxes"))

    details = page[page.index('id="config-dialog"'):]
    details = details[:details.index("</dialog>")]
    for value in ("mail.pineloop.online", "993", "465", "587", "995"):
        assert f'data-copy="{value}"' in details, value
    assert "IMAP" in details and "SMTP" in details and "POP3" in details
    assert 'data-config-email="ceo@pineloop.online"' in page   # the username, filled in per mailbox


def test_a_note_says_when_a_domains_mail_doesnt_come_here_yet(app, client, login):
    domain_id = authenticated_domain(app)
    login()
    create(client)

    with app.app_context():
        get_db().execute("UPDATE domain_keys SET checks = ? WHERE domain_id = ?",
                         (json.dumps({"mx": {"state": "elsewhere", "detail": ""}}), domain_id))
        get_db().commit()
    assert "pineloop.online's MX record" in plain(text(client.get("/mailboxes")))

    with app.app_context():
        get_db().execute("UPDATE domain_keys SET checks = ? WHERE domain_id = ?",
                         (json.dumps({"mx": {"state": "found", "detail": ""}}), domain_id))
        get_db().commit()
    assert "MX record" not in plain(text(client.get("/mailboxes")))


def test_a_domain_with_mailboxes_cant_be_deleted(app, client, login):
    domain_id = authenticated_domain(app)
    login()
    create(client)

    response = client.post(f"/domains/{domain_id}/delete")

    assert response.headers["Location"] == "/domains"
    with app.app_context():
        assert get_db().execute("SELECT 1 FROM domains WHERE id = ?", (domain_id,)).fetchone()
    assert "Delete its mailboxes first" in text(client.get("/domains"))


def test_storage_typed_with_a_comma_means_what_people_mean(app, client, login):
    authenticated_domain(app)
    login()

    create(client, local="thousand", storage="1,000", unit="MB")   # a thousands separator
    create(client, local="half", storage="1,5", unit="GB")         # a decimal comma

    assert [row["quota_bytes"] for row in rows(app)] == [1000 * MB, int(1.5 * GB)]


def save_mailbox_rules(client, min_length="8", letters=True, numbers=True, special=True, json=False):
    data = {"min_length": min_length}
    for name, forced in [("require_letters", letters), ("require_numbers", numbers), ("require_special", special)]:
        if forced:
            data[name] = "on"
    return client.post("/mailboxes/password-rules", data=data, headers={"Accept": "application/json"} if json else {})


def test_the_password_rules_can_be_changed_from_the_mailbox_dialogs(app, client, login):
    a_sender(app, authenticated_domain(app), "ceo@pineloop.online")   # so the dialog has its password fields
    login()

    page = text(client.get("/mailboxes"))

    create_dialog = page[page.index('id="create-mailbox-dialog"'):page.index("</dialog>", page.index('id="create-mailbox-dialog"'))]
    assert 'data-dialog-open="mailbox-rules-dialog"' in create_dialog
    rules = page[page.index('id="mailbox-rules-dialog"'):]
    rules = rules[:rules.index("</dialog>")]
    assert 'action="/mailboxes/password-rules"' in rules and "data-save-in-place" in rules
    assert re.search(r'<input type="range"[^>]*name="min_length"[^>]*value="8"', rules)
    assert 'src="/static/js/password-rules-dialog.js?v=' in page


def test_mailbox_password_rules_are_their_own(app, client, login):
    """Mailbox passwords guard mail apps' logins from anywhere: their rules are set apart from
    the admin's own."""
    authenticated_domain(app)
    login()

    response = save_mailbox_rules(client, min_length="12", special=False)

    assert response.headers["Location"] == "/mailboxes"
    assert create(client, password="Abcdefgh123").status_code == 400    # 11 characters
    assert create(client, password="Abcdefghi123").headers["Location"] == "/mailboxes"   # 12, no special needed
    with app.app_context():
        admin_rules = get_db().execute("SELECT * FROM password_rules WHERE id = 1").fetchone()
    assert (admin_rules["min_length"], admin_rules["require_special"]) == (8, 1)
    page = text(client.get("/mailboxes"))
    assert "At least 12 characters" in page and 'data-rule="special"' not in page


def test_saving_the_rules_in_place_answers_with_them(app, client, login):
    authenticated_domain(app)
    login()

    answer = save_mailbox_rules(client, min_length="10", letters=False, json=True).get_json()

    assert answer["min_length"] == 10
    assert [rule["key"] for rule in answer["rules"]] == ["length", "number", "special"]
    assert answer["rules"][0]["label"] == "At least 10 characters"
    assert save_mailbox_rules(client, min_length="13", json=True).status_code == 400


# --- how large a message it may send ---

def test_a_new_mailbox_may_send_50_mb_at_a_time(app, client, login):
    authenticated_domain(app)
    login()

    create(client)

    assert rows(app)[0]["send_limit_mb"] == 50
    page = text(client.get("/mailboxes"))
    assert 'data-sending-for="ceo@pineloop.online"' in page and 'data-limit="50"' in page


def test_the_sending_limit_changes(app, client, login, engine):
    authenticated_domain(app)
    login()
    create(client)
    mailbox_id = rows(app)[0]["id"]

    response = client.post(f"/mailboxes/{mailbox_id}/sending", data={"limit": "100"})

    assert response.status_code == 302 and rows(app)[0]["send_limit_mb"] == 100
    assert "ceo@pineloop.online can now send up to 100 MB at a time." in text(client.get("/mailboxes"))
    assert "authenticated_as == 'ceo@pineloop.online'" in str(engine.objects["MtaStageData"]["singleton"]["maxMessageSize"])


def test_the_sending_limit_is_from_1_to_100_mb(app, client, login):
    authenticated_domain(app)
    login()
    create(client)
    mailbox_id = rows(app)[0]["id"]

    for limit in ("0", "101", "abc", "", "2.5"):
        response = client.post(f"/mailboxes/{mailbox_id}/sending", data={"limit": limit})
        assert response.status_code == 400, limit
        assert "Choose a size from 1 to 100 MB." in text(response)
    assert rows(app)[0]["send_limit_mb"] == 50
