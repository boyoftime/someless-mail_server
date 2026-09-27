"""Settings > Miscellaneous > Automatic domain checks: every domain's DNS looked at again on a
schedule (domain_checks.py), so a record deleted at the registrar is noticed by itself."""
import html
import re
import time

from someless import domain_checks, domain_records
from someless.db import get_db
from test_engine_sync import authenticated_domain


def text(response):
    return html.unescape(response.get_data(as_text=True))


def plain(page):
    return re.sub(r"<[^>]+>", "", page)


def saved(app):
    with app.app_context():
        return domain_checks.settings()


def save(client, **form):
    return client.post("/settings/miscellaneous/domain-checks", data=form)


def test_settings_has_a_miscellaneous_tab(client, login):
    login()

    page = text(client.get("/settings/miscellaneous"))

    tabs = page[page.index('<nav class="page-tabs"'):]
    tabs = tabs[:tabs.index("</nav>")]
    assert '<a class="page-tab" href="/settings/miscellaneous" aria-current="page">' in tabs and "Miscellaneous" in tabs
    assert '<a class="page-tab" href="/settings">' in tabs and '<a class="page-tab" href="/settings/mail-server">' in tabs


def test_the_card_starts_off(client, login):
    login()

    page = text(client.get("/settings/miscellaneous"))

    assert "Automatic domain checks" in page
    assert re.search(r'<input type="checkbox" role="switch" name="enabled"(?![^>]*checked)[^>]*>', page)
    assert [value for value in re.findall(r'name="every" value="([^"]+)"', page)] == ["1", "2", "6", "12", "24", "custom"]


def test_switching_on_with_a_preset(app, client, login):
    login()

    response = save(client, enabled="on", every="6")

    assert response.headers["Location"] == "/settings/miscellaneous"
    assert (saved(app)["enabled"], saved(app)["every_hours"]) == (1, 6)
    assert "every 6 hours" in plain(text(client.get("/settings/miscellaneous")))


def test_a_custom_time_in_hours_or_days(app, client, login):
    login()

    save(client, enabled="on", every="custom", amount="30", unit="hours")
    assert saved(app)["every_hours"] == 30
    assert "every 1 day and 6 hours" in plain(text(client.get("/settings/miscellaneous")))

    save(client, enabled="on", every="custom", amount="3", unit="days")
    assert saved(app)["every_hours"] == 72


def test_a_custom_time_that_cant_be_is_refused(app, client, login):
    login()

    for amount, unit in (("0", "hours"), ("abc", "hours"), ("31", "days"), ("2.5", "hours")):
        response = save(client, enabled="on", every="custom", amount=amount, unit=unit)
        assert response.status_code == 400, (amount, unit)
        assert "data-board=\"error\"" in text(response)
    assert saved(app)["enabled"] == 0


def test_switching_off(app, client, login):
    login()
    save(client, enabled="on", every="2")

    save(client, every="2")

    assert saved(app)["enabled"] == 0


def test_the_times_read_as_people_say_them():
    assert [domain_checks.describe(hours) for hours in (1, 2, 24, 30, 48, 49)] == [
        "1 hour", "2 hours", "1 day", "1 day and 6 hours", "2 days", "2 days and 1 hour"]


def test_a_check_is_due_when_on_and_the_time_has_come(app):
    with app.app_context():
        assert not domain_checks.due()   # off
        domain_checks.save(enabled=True, every_hours=2)
        assert domain_checks.due()       # never ran yet
        get_db().execute("UPDATE domain_checks SET last_run = ?", (time.time() - 3600,))
        get_db().commit()
        assert not domain_checks.due()
        get_db().execute("UPDATE domain_checks SET last_run = ?", (time.time() - 7300,))
        get_db().commit()
        assert domain_checks.due()


def test_a_domain_whose_records_were_deleted_is_noticed(app, engine, monkeypatch):
    domain_id = authenticated_domain(app)
    seen = []

    def records_gone(name, keys, address):
        seen.append(address)
        return "mail", {}, {key: {"state": "missing", "detail": ""} for key in domain_records.AUTHENTICATING}
    monkeypatch.setattr(domain_records, "look", records_gone)
    with app.app_context():
        domain_checks.remember_address("194.163.167.106")
        domain_checks.save(enabled=True, every_hours=6)

        changed = domain_checks.run()

        assert changed == [("pineloop.online", False)]
        assert get_db().execute("SELECT authenticated FROM domains WHERE id = ?", (domain_id,)).fetchone()[0] == 0
        assert domain_checks.settings()["last_run"] is not None
    assert seen == ["194.163.167.106"]          # checked against this server's own address
    assert engine.named("Domain", "pineloop.online") is None   # and the engine let it go


def test_the_panel_remembers_its_public_address(app, client, login):
    app.config["SERVER_NAME"] = "194.163.167.106:17080"   # opened by the server's public address
    domain_id = authenticated_domain(app)
    login()

    client.get(f"/domains/{domain_id}")

    assert saved(app)["server_address"] == "194.163.167.106"


def test_switching_off_needs_no_interval(app, client, login):
    """The switch off greys How often out; switching off still saves (with the interval kept)."""
    login()
    save(client, enabled="on", every="12")

    response = save(client)   # nothing but the switch, now off

    assert response.headers["Location"] == "/settings/miscellaneous"
    assert (saved(app)["enabled"], saved(app)["every_hours"]) == (0, 12)


def test_save_waits_for_a_change(client, login):
    """Save is locked until something in the form changes (save-when-changed.js)."""
    login()

    page = text(client.get("/settings/miscellaneous"))

    assert re.search(r'<form[^>]*class="card-form checks-form"[^>]*data-save-when-changed', page)


def test_after_a_problem_save_is_ready_at_once(client, login):
    login()

    page = text(save(client, enabled="on", every="custom", amount="0", unit="hours"))

    form = re.search(r'<form[^>]*class="card-form checks-form"[^>]*>', page).group(0)
    assert "data-save-when-changed" not in form   # what's typed isn't saved yet: it can be saved as it is
