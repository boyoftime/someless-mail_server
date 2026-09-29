"""The webmail's Settings (webmail/settings.py, webmail/sieve.py), as PrivateEmail's: the display
name, preferences, signatures, forwarding, the auto-reply and filters (the last three written into
the engine as one Sieve script), a new password, and the logins. The engine is the made-up one
(jmap_fake.py)."""
import pytest

from someless import mail_password
from someless.db import get_db
from someless.webmail import create_webmail_app, sieve
from jmap_fake import FakeJmap
from test_engine_sync import a_mailbox, a_sender, authenticated_domain

PASSWORD = "Mailbox-Pass-1!"
CHROME_ON_WINDOWS = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/128.0.0.0 Safari/537.36")


@pytest.fixture
def jmap():
    return FakeJmap()


@pytest.fixture
def mailbox(app):
    domain_id = authenticated_domain(app)
    a_sender(app, domain_id, "ceo@pineloop.online")
    return a_mailbox(app, "ceo@pineloop.online", domain_id, password_hash=mail_password.hash_password(PASSWORD),
                     aliases=("sales@pineloop.online",))


@pytest.fixture
def webmail(app, jmap, mailbox):
    return create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "WTF_CSRF_ENABLED": False,
                               "JMAP": lambda email: jmap})


@pytest.fixture
def mail(webmail):
    client = webmail.test_client()
    client.post("/login", data={"email": "ceo@pineloop.online", "password": PASSWORD},
                headers={"User-Agent": CHROME_ON_WINDOWS})
    client.get("/mail/inbox")   # (the Archive is made)
    return client


def post(mail, url, **body):
    return mail.post(url, json=body)


# --- the pages ---

def test_settings_shows_its_cards(mail):
    page = mail.get("/settings").get_data(as_text=True)

    for card in ("Profile", "System preferences", "Signature", "Forwarding", "Filters", "Auto-reply", "Spam management",
                 "Connect third-party apps", "Security Center"):
        assert f">{card}</h2>" in page, card
    assert "You have no signatures associated to your account" in page
    assert "There are currently no filters set for your account" in page
    assert "You don't have any forwarding rules set up yet" in page


@pytest.mark.parametrize("url, title", [("/settings/signatures", "Signatures"), ("/settings/auto-reply", "Auto-reply"),
                                        ("/settings/filters", "Filters applied to your account"),
                                        ("/settings/apps", "Connect third-party apps"), ("/settings/security", "Security Center")])
def test_each_part_of_settings_has_its_page(mail, url, title):
    response = mail.get(url)

    assert response.status_code == 200
    assert f'<h1 class="wm-settings-title">{title}</h1>' in response.get_data(as_text=True)


def test_the_help_center_answers_the_usual_questions(mail):
    page = mail.get("/settings/help").get_data(as_text=True)

    assert '<h1 class="wm-settings-title">Help center</h1>' in page
    for question in ("I cannot send or receive emails, what should I do?", "How can I connect my mailbox to a mail app?",
                     "How can I change my password?", "How can I set up email forwarding?"):
        assert question in page, question
    assert 'href="/settings/help"' in mail.get("/mail/inbox").get_data(as_text=True)   # (the bar's Help button)


def test_settings_needs_a_login(webmail):
    response = webmail.test_client().get("/settings")

    assert response.status_code == 302 and response.headers["Location"] == "/login"


# --- Profile: the display name ---

def test_the_display_name_is_what_mail_goes_out_with(mail):
    answer = post(mail, "/settings/profile", display_name="  Amani   Juma ")

    assert answer.status_code == 200
    assert answer.get_json() == {"message": "Name has been updated successfully.", "display_name": "Amani Juma"}
    assert mail.get("/compose/start").get_json()["froms"][0]["name"] == "Amani Juma"
    assert "Amani Juma" in mail.get("/settings").get_data(as_text=True)


@pytest.mark.parametrize("name, problem", [
    ("", "A new display name is required."),
    ("    ", "Your display name can't contain only spaces."),
    ("A" * 128, "Your name must be under 128 symbols."),
    ("Amani <CEO>", "The only symbols allowed are: .-_,'()|&"),
])
def test_a_display_name_is_checked_as_privateemail_checks_it(mail, name, problem):
    answer = post(mail, "/settings/profile", display_name=name)

    assert answer.status_code == 400 and answer.get_json()["problem"] == problem


# --- System preferences ---

def test_a_preference_is_switched(mail):
    answer = post(mail, "/settings/preferences", name="new_mail_sound", on=False)

    assert answer.get_json()["preferences"]["new_mail_sound"] is False
    assert post(mail, "/settings/preferences", name="notifications", on=True).get_json()["preferences"]["notifications"] is True
    assert post(mail, "/settings/preferences", name="dark_magic", on=True).status_code == 400


# --- Forwarding ---

def test_forwarding_is_written_into_the_mailboxs_script(mail, jmap):
    answer = post(mail, "/settings/forwarding", address="boss@example.com", on=True)

    assert answer.status_code == 200
    assert answer.get_json()["forwarding"] == {"address": "boss@example.com", "on": True, "keep": True}
    script = jmap.active_script()
    assert 'require ["copy"];' in script and 'redirect :copy "boss@example.com";' in script


def test_forwarding_without_a_copy_kept(mail, jmap):
    post(mail, "/settings/forwarding", address="boss@example.com", on=True)

    post(mail, "/settings/forwarding", keep=False)

    assert 'redirect "boss@example.com";' in jmap.active_script() and ":copy" not in jmap.active_script()


def test_forwarding_switched_off_keeps_the_address(mail, jmap):
    post(mail, "/settings/forwarding", address="boss@example.com", on=True)

    answer = post(mail, "/settings/forwarding", on=False)

    assert answer.get_json()["forwarding"] == {"address": "boss@example.com", "on": False, "keep": True}
    assert "redirect" not in jmap.active_script()


@pytest.mark.parametrize("address, problem", [
    ("", "Forwarding email address field can't be empty"),
    ("boss-at-example.com", "Email address must be in the correct format, e.g.: example@yourdomain.com"),
    ("CEO@pineloop.online", "You can't forward messages to your own mailbox, choose another one."),
    ("sales@pineloop.online", "You can't forward messages to your own mailbox, choose another one."),
])
def test_a_forwarding_address_is_checked(mail, address, problem):
    answer = post(mail, "/settings/forwarding", address=address, on=True)

    assert answer.status_code == 400 and answer.get_json()["problem"] == problem


def test_the_forwarding_address_is_deleted(mail, jmap):
    post(mail, "/settings/forwarding", address="boss@example.com", on=True)

    answer = post(mail, "/settings/forwarding/delete")

    assert answer.get_json()["message"] == "The forwarding address was deleted"
    assert "redirect" not in jmap.active_script()


def test_forwarding_stays_as_it_was_when_the_engine_refuses(mail, jmap, webmail, mailbox):
    jmap.refuse_script = "no"

    answer = post(mail, "/settings/forwarding", address="boss@example.com", on=True)

    assert answer.status_code == 502 and answer.get_json()["problem"] == "Failed to update forwarding settings."
    with webmail.app_context():
        assert sieve.settings(mailbox)["forward_to"] is None


# --- Auto-reply ---

def away(**extra):
    return {"on": True, "start_date": "2026-10-01", "start_time": "09:00", "end_date": "2026-10-05", "end_time": "17:00",
            "subject": "Away", "html": "<p>I'm away until Monday.</p>", **extra}


def test_the_auto_reply_is_written_as_a_vacation_within_its_dates(mail, jmap):
    answer = mail.post("/settings/auto-reply", json=away())

    assert answer.status_code == 200 and answer.get_json()["message"] == "Auto-reply saved"
    script = jmap.active_script()
    assert '"vacation"' in script and '"date"' in script and '"relational"' in script
    assert 'currentdate :zone "+0000" :value "ge" "iso8601" "2026-10-01T09:00:00+00:00"' in script
    assert 'currentdate :zone "+0000" :value "le" "iso8601" "2026-10-05T17:00:00+00:00"' in script
    assert ('vacation :days 1 :subject "Away" :from "ceo@pineloop.online" '
            ':addresses ["ceo@pineloop.online", "sales@pineloop.online"] :mime text:') in script
    assert "I'm away until Monday." in script


def test_the_auto_reply_dates_are_in_the_readers_time_zone(mail, jmap):
    mail.set_cookie("wm_tz", "Africa/Nairobi")   # three hours ahead

    mail.post("/settings/auto-reply", json=away())

    assert '"2026-10-01T06:00:00+00:00"' in jmap.active_script()
    page = mail.get("/settings/auto-reply").get_data(as_text=True)
    assert 'value="2026-10-01"' in page and 'value="09:00"' in page   # shown in the reader's time again


def test_a_line_of_the_auto_reply_starting_with_a_dot_is_doubled(mail, jmap):
    mail.post("/settings/auto-reply", json=away(html="<p>Hi</p>\n.hidden"))

    assert "\n..hidden" in jmap.active_script()


@pytest.mark.parametrize("change, problem", [
    ({"start_date": ""}, "Start date is required."),
    ({"end_time": ""}, "End time is required."),
    ({"end_date": "2026-09-30"}, "End date must be after start date."),
    ({"end_date": "2026-10-01", "end_time": "08:00"}, "End time must be after start time."),
    ({"html": "<p> </p>"}, "Message body is required."),
    ({"start_date": "2026-13-01"}, "Start date is not valid."),
    ({"subject": "S" * 1001}, "Subject must be no more than 1,000 characters."),
])
def test_the_auto_reply_is_checked(mail, change, problem):
    answer = mail.post("/settings/auto-reply", json=away(**change))

    assert answer.status_code == 400 and answer.get_json()["problem"] == problem


def test_the_auto_reply_switched_off_leaves_the_script(mail, jmap):
    mail.post("/settings/auto-reply", json=away())

    mail.post("/settings/auto-reply", json=away(on=False))

    assert "vacation" not in jmap.active_script()


def test_forwarding_auto_reply_and_filters_share_one_active_script(mail, jmap):
    post(mail, "/settings/forwarding", address="boss@example.com", on=True)
    mail.post("/settings/auto-reply", json=away())
    mail.post("/settings/filters", json=a_rule(jmap))

    assert [script["name"] for script in jmap.scripts.values()] == ["someless"]
    script = jmap.active_script()
    assert script.index("vacation") < script.index('redirect :copy "boss@example.com"') < script.index("# Invoices")


# --- Signatures ---

def signatures(answer):
    return [(one["name"], bool(one["is_default"])) for one in answer.get_json()["signatures"]]


def test_the_first_signature_is_the_default(mail):
    answer = post(mail, "/settings/signatures", name="Work", html="<p>Amani, CEO</p>")

    assert answer.get_json()["message"] == "Your signature has been added."
    assert signatures(answer) == [("Work", True)]


def test_a_new_default_signature_takes_over(mail):
    post(mail, "/settings/signatures", name="Work", html="<p>Amani, CEO</p>")

    answer = post(mail, "/settings/signatures", name="Short", html="<p>A.</p>", default=True)

    assert sorted(signatures(answer)) == [("Short", True), ("Work", False)]


def test_a_signature_is_changed_made_the_default_and_deleted(mail):
    first = post(mail, "/settings/signatures", name="Work", html="<p>Amani</p>").get_json()["id"]
    second = post(mail, "/settings/signatures", name="Short", html="<p>A.</p>").get_json()["id"]

    changed = post(mail, f"/settings/signatures/{second}", name="Brief", html="<p>A. J.</p>", default=False)
    assert changed.get_json()["message"] == "Your changes have been saved successfully."
    made_default = post(mail, f"/settings/signatures/{second}/default")
    assert made_default.get_json()["message"] == "Brief has been set as the default signature"
    assert sorted(signatures(made_default)) == [("Brief", True), ("Work", False)]
    deleted = post(mail, f"/settings/signatures/{first}/delete")
    assert deleted.get_json()["message"] == "Work was deleted." and signatures(deleted) == [("Brief", True)]
    assert post(mail, f"/settings/signatures/{first}/delete").status_code == 404


def test_a_signature_name_is_checked(mail):
    answer = post(mail, "/settings/signatures", name="N" * 51, html="<p>x</p>")

    assert answer.status_code == 400 and answer.get_json()["problem"] == "Signature name max length is 50 symbols"


def test_a_signature_keeps_its_pictures(mail):
    picture = "data:image/jpeg;base64," + "A" * 120_000   # (a logo, made at most 600 pixels wide by the page)

    answer = post(mail, "/settings/signatures", name="Work", html=f'<p>Amani</p><img src="{picture}" width="300" alt="">')

    assert answer.status_code == 200
    assert picture in answer.get_json()["signatures"][0]["html"]


def test_a_signature_too_big_is_refused(mail):
    picture = "data:image/png;base64," + "A" * 2_100_000

    answer = post(mail, "/settings/signatures", name="Work", html=f'<img src="{picture}">')

    assert answer.status_code == 400
    assert answer.get_json()["problem"] == "This signature is too large. Use smaller pictures, or fewer of them."


def test_a_signature_loses_its_scripts(mail):
    answer = post(mail, "/settings/signatures", name="Work", html='<p onclick="steal()">Hi<script>steal()</script></p>')

    html = answer.get_json()["signatures"][0]["html"]
    assert "onclick" not in html and "<script" not in html and "Hi" in html


# --- Filters ---

def a_rule(jmap, **extra):
    return {"name": "Invoices", "operator": "all",
            "conditions": [{"prop": "subject", "op": "contains", "value": "invoice"}],
            "actions": [{"type": "move", "folder": jmap.role("archive")}], "stop": False, **extra}


def test_a_filter_is_made_and_written_into_the_script(mail, jmap):
    answer = mail.post("/settings/filters", json=a_rule(jmap))

    assert answer.status_code == 200
    assert answer.get_json()["message"] == "New filter was created! You can find your new filter at the end of the list."
    assert [rule["name"] for rule in answer.get_json()["rules"]] == ["Invoices"]
    script = jmap.active_script()
    assert 'require ["fileinto", "mailbox", "mailboxid"];' in script   # (the engine asks for "mailbox" with :mailboxid)
    assert 'if allof(header :contains ["subject"] "invoice") {' in script
    assert f'    fileinto :mailboxid "{jmap.role("archive")}" "Archive";' in script
    assert "Filters" in mail.get("/settings").get_data(as_text=True) and "1 filter</strong>" in mail.get("/settings").get_data(as_text=True)


def test_a_filter_is_changed(mail, jmap):
    rule_id = mail.post("/settings/filters", json=a_rule(jmap)).get_json()["rules"][0]["id"]

    answer = mail.post(f"/settings/filters/{rule_id}", json=a_rule(jmap, name="Bills", stop=True))

    assert answer.get_json()["message"] == "The filter has been updated successfully."
    assert "# Bills" in jmap.active_script() and "stop;" in jmap.active_script()


def test_a_filter_switched_off_leaves_the_script_until_it_is_on_again(mail, jmap):
    rule_id = mail.post("/settings/filters", json=a_rule(jmap)).get_json()["rules"][0]["id"]

    off = mail.post(f"/settings/filters/{rule_id}/toggle", json={"enabled": False})
    assert off.get_json()["rules"][0]["enabled"] is False and "# Invoices" not in jmap.active_script()
    mail.post(f"/settings/filters/{rule_id}/toggle", json={"enabled": True})
    assert "# Invoices" in jmap.active_script()


def test_filters_run_in_the_order_they_are_dragged_to(mail, jmap):
    first = mail.post("/settings/filters", json=a_rule(jmap)).get_json()["rules"][0]["id"]
    second = mail.post("/settings/filters", json=a_rule(jmap, name="Receipts")).get_json()["rules"][1]["id"]

    answer = mail.post("/settings/filters/order", json={"ids": [second, first]})

    assert [rule["name"] for rule in answer.get_json()["rules"]] == ["Receipts", "Invoices"]
    assert jmap.active_script().index("# Receipts") < jmap.active_script().index("# Invoices")


def test_filters_are_deleted_together(mail, jmap):
    first = mail.post("/settings/filters", json=a_rule(jmap)).get_json()["rules"][0]["id"]
    second = mail.post("/settings/filters", json=a_rule(jmap, name="Receipts")).get_json()["rules"][1]["id"]

    answer = mail.post("/settings/filters/delete", json={"ids": [first, second]})

    assert answer.get_json()["message"] == "The selected filters have been removed." and answer.get_json()["rules"] == []
    assert "fileinto" not in jmap.active_script()


def test_a_filter_the_engine_refuses_is_not_kept(mail, jmap):
    jmap.refuse_script = "no"

    answer = mail.post("/settings/filters", json=a_rule(jmap))

    assert answer.status_code == 502
    jmap.refuse_script = None
    assert mail.get("/settings/filters").get_data(as_text=True).count("Invoices") == 0


def test_another_mailboxs_filter_is_out_of_reach(app, mail, jmap):
    with app.app_context():
        database = get_db()
        other = database.execute("INSERT INTO mailboxes (email, domain_id, quota_bytes, password_hash, created_at)"
                                 " VALUES ('x@pineloop.online', 1, 1, 'h', 0)").lastrowid
        rule_id = database.execute("INSERT INTO webmail_rules (mailbox_id, position, name, enabled, rule) VALUES (?, 1, 'Theirs', 1, '{}')",
                                   (other,)).lastrowid
        database.commit()

    assert mail.post(f"/settings/filters/{rule_id}", json=a_rule(jmap)).status_code == 404
    assert mail.post(f"/settings/filters/{rule_id}/toggle", json={"enabled": False}).status_code == 404


@pytest.mark.parametrize("change, problem", [
    ({"name": ""}, "A name for the rule is required."),
    ({"name": " x "}, "Rule name must be at least 2 characters long (without spaces at the ends)."),
    ({"conditions": []}, "At least one condition or group is required."),
    ({"conditions": [{"prop": "subject", "op": "contains", "value": "a"}]}, "Subject condition value must be at least 2 characters long."),
    ({"conditions": [{"prop": "from", "op": "contains", "value": ""}]}, "Filter condition requires an argument."),
    ({"conditions": [{"prop": "size", "op": "greater", "value": "big"}]}, "Size in bytes must be a whole number."),
    ({"conditions": [{"prop": "size", "op": "greater", "value": str(3000 * 1024 ** 2)}]}, "Size must not exceed 2048 MB."),
    ({"conditions": [{"prop": "sent_date", "op": "on", "value": "soon"}]}, "Please enter a valid date."),
    ({"conditions": [{"prop": "header", "op": "contains", "value": "x", "headers": []}]}, "At least one header name is required."),
    ({"conditions": [{"prop": "header", "op": "contains", "value": "x", "headers": ["X Spam"]}]},
     "A header name may contain only printable ASCII characters, without spaces or colons."),
    ({"conditions": [{"group": "all", "conditions": [{"group": "any", "conditions": []}]}]},
     "Nested conditions group operator must be one of the predefined ones."),
    ({"conditions": [{"prop": "from", "op": "sounds_like", "value": "x"}]}, "Operator must be one of the predefined ones."),
    ({"actions": []}, "Choose what the filter does."),
    ({"actions": [{"type": "move", "folder": "nowhere"}]}, "Folder name is required for this action."),
    ({"actions": [{"type": "forward", "address": "boss"}]}, "Enter a valid email address."),
])
def test_a_filter_is_checked_as_privateemail_checks_it(mail, jmap, change, problem):
    answer = mail.post("/settings/filters", json=a_rule(jmap, **change))

    assert answer.status_code == 400 and answer.get_json()["problem"] == problem


# --- the script, piece by piece ---

FOLDERS = {"f1": {"id": "f1", "name": "Archive"}, "f2": {"id": "f2", "name": "Work/Bills"},
           "trash": {"id": "t1", "name": "Trash"}}
KEPT = {"forward_to": None, "forward_on": False, "forward_keep": True, "reply_on": False, "reply_start": None, "reply_end": None,
        "reply_subject": "", "reply_html": ""}


def written(conditions=(), actions=({"type": "keep"},), operator="all", stop=False):
    rule = {"name": "R", "enabled": True, "operator": operator, "conditions": list(conditions), "actions": list(actions), "stop": stop}
    return sieve.script(KEPT, [rule], FOLDERS, ["ceo@pineloop.online"])


@pytest.mark.parametrize("condition, test", [
    ({"prop": "from", "op": "is", "value": "amina@example.com"}, 'address :all :is ["from"] "amina@example.com"'),
    ({"prop": "any_recipient", "op": "contains", "value": "sales"}, 'address :all :contains ["to", "cc"] "sales"'),
    ({"prop": "subject", "op": "not_contains", "value": "spam"}, 'not header :contains ["subject"] "spam"'),
    ({"prop": "subject", "op": "starts", "value": "Re*"}, 'header :matches ["subject"] "Re\\\\**"'),
    ({"prop": "subject", "op": "ends", "value": "done?"}, 'header :matches ["subject"] "*done\\\\?"'),
    ({"prop": "header", "op": "exists", "headers": ["X-Spam", "X-Junk"]}, 'exists ["X-Spam", "X-Junk"]'),
    ({"prop": "body", "op": "contains", "value": "unsubscribe"}, 'body :text :contains "unsubscribe"'),
    ({"prop": "subject", "op": "regex", "value": "^\\d+$"}, 'header :regex ["subject"] "^\\\\d+$"'),
    ({"prop": "size", "op": "greater", "value": 1000}, "size :over 1000"),
    ({"prop": "size", "op": "less_or_equal", "value": 1000}, "not size :over 1000"),
    ({"prop": "sent_date", "op": "on_or_after", "value": "2026-10-01"}, 'date :value "ge" "date" "date" "2026-10-01"'),
])
def test_each_condition_becomes_its_sieve_test(condition, test):
    assert f"if allof({test}) {{" in written([condition])


def test_a_filter_with_no_conditions_takes_every_mail():
    assert "if true {" in written(operator="none")


def test_any_condition_and_a_group_inside():
    script = written([{"prop": "from", "op": "contains", "value": "bank"},
                      {"group": "all", "conditions": [{"prop": "subject", "op": "contains", "value": "bill"},
                                                      {"prop": "size", "op": "greater", "value": 10}]}], operator="any")

    assert 'if anyof(address :all :contains ["from"] "bank", allof(header :contains ["subject"] "bill", size :over 10)) {' in script


def test_flags_come_before_the_mail_is_moved_and_stop_ends_it():
    script = written(operator="none", stop=True,
                     actions=[{"type": "copy", "folder": "f2"}, {"type": "read"}, {"type": "favorite"},
                              {"type": "forward", "address": "a@example.com", "keep": False}, {"type": "delete"}])

    lines = [line.strip() for line in script.splitlines()]
    body = lines[lines.index("if true {") + 1:]
    assert body[:6] == ['addflag "\\\\Seen";', 'addflag "\\\\Flagged";', 'fileinto :copy :mailboxid "f2" "Work/Bills";',
                        'redirect "a@example.com";', 'fileinto :mailboxid "t1" "Trash";', "stop;"]
    assert lines[0] == 'require ["copy", "fileinto", "imap4flags", "mailbox", "mailboxid"];'


def test_a_switched_off_filter_is_left_out():
    rule = {"name": "Off", "enabled": False, "operator": "none", "conditions": [], "actions": [{"type": "discard"}], "stop": False}

    assert "discard" not in sieve.script(KEPT, [rule], FOLDERS, ["ceo@pineloop.online"])


def test_quotes_in_a_value_cannot_break_out_of_it():
    script = written([{"prop": "subject", "op": "contains", "value": 'x" { discard; } if true { "'}])

    assert '"x\\" { discard; } if true { \\""' in script


# --- Connect third-party apps ---

def test_the_apps_page_has_the_servers_and_ports(mail):
    page = mail.get("/settings/apps").get_data(as_text=True)

    assert "Account information" in page and "Your mailbox password." in page
    assert "mail.pineloop.online" in page
    for port in ("993", "995", "465", "587"):
        assert port in page
    assert "http://localhost/dav/cal/ceo@pineloop.online/" in page and "http://localhost/dav/card/ceo@pineloop.online/" in page


def test_an_apple_profile_is_downloaded(mail):
    response = mail.get("/settings/apps/profile")

    assert response.status_code == 200 and response.mimetype == "application/x-apple-aspen-config"
    assert b"ceo@pineloop.online" in response.data and b"<integer>993</integer>" in response.data


# --- Security Center ---

def test_a_new_password_logs_out_and_logs_in_again(webmail, mail, mailbox):
    answer = post(mail, "/settings/password", current=PASSWORD, password="Brand-New-Pass-2!", confirm="Brand-New-Pass-2!")

    assert answer.status_code == 200 and answer.get_json()["login"] == "/login"
    assert mail.get("/mail/inbox").headers["Location"] == "/login"
    assert "Your password was changed. Log in with the new one." in mail.get("/login").get_data(as_text=True)
    assert "Your password was changed" not in mail.get("/login").get_data(as_text=True)   # said once
    wrong = mail.post("/login", data={"email": "ceo@pineloop.online", "password": PASSWORD})
    assert wrong.status_code == 400
    right = mail.post("/login", data={"email": "ceo@pineloop.online", "password": "Brand-New-Pass-2!"})
    assert right.status_code == 302 and mail.get("/mail/inbox").status_code == 200
    with webmail.app_context():
        assert get_db().execute("SELECT password_version FROM mailboxes WHERE id = ?", (mailbox,)).fetchone()[0] == 2


@pytest.mark.parametrize("body, problem", [
    ({"current": "wrong", "password": "Brand-New-Pass-2!", "confirm": "Brand-New-Pass-2!"}, "Your current password is wrong."),
    ({"current": PASSWORD, "password": "Brand-New-Pass-2!", "confirm": "Brand-New-Pass-3!"},
     "The two passwords don't match. Type the same password in both."),
    ({"current": PASSWORD, "password": "short1!", "confirm": "short1!"}, "The password must be at least 8 characters."),
    ({"current": PASSWORD, "password": PASSWORD, "confirm": PASSWORD}, "The new password is the one you have. Choose another."),
])
def test_a_new_password_is_checked(mail, body, problem):
    answer = mail.post("/settings/password", json=body)

    assert answer.status_code == 400 and answer.get_json()["problem"] == problem
    assert mail.get("/mail/inbox").status_code == 200   # still logged in


def test_the_security_center_lists_the_logins(mail):
    page = mail.get("/settings/security").get_data(as_text=True)

    assert "Chrome on Windows" in page and "127.0.0.1" in page
    assert 'data-rule="length"' in page and "At least 8 characters" in page


def test_only_the_last_fifty_logins_are_kept(webmail, mailbox):
    client = webmail.test_client()
    for _ in range(52):
        client.post("/login", data={"email": "ceo@pineloop.online", "password": PASSWORD})
        client.post("/logout")

    with webmail.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM webmail_logins WHERE mailbox_id = ?", (mailbox,)).fetchone()[0] == 50
