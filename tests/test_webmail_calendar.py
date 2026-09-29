"""The calendar in the webmail (webmail/calendar.py), as PrivateEmail's: events in the reader's own
time, repeating ones each time they happen; an event made, changed (one time of it, or all) and
deleted; invitations sent and answered; calendars shown, hidden, renamed. The engine is the
made-up one (jmap_fake.py)."""
import datetime
import zoneinfo

import pytest

from someless import mail_password
from someless.webmail import calendar, create_webmail_app
from jmap_fake import FakeJmap
from test_engine_sync import a_mailbox, a_sender, authenticated_domain

PASSWORD = "Mailbox-Pass-1!"
NAIROBI = zoneinfo.ZoneInfo("Africa/Nairobi")


@pytest.fixture
def jmap():
    return FakeJmap()


@pytest.fixture
def mail(app, jmap):
    domain_id = authenticated_domain(app)
    a_sender(app, domain_id, "ceo@pineloop.online")
    a_mailbox(app, "ceo@pineloop.online", domain_id, password_hash=mail_password.hash_password(PASSWORD))
    webmail = create_webmail_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "WTF_CSRF_ENABLED": False,
                                  "JMAP": lambda email: jmap})
    client = webmail.test_client()
    client.post("/login", data={"email": "ceo@pineloop.online", "password": PASSWORD})
    client.set_cookie("wm_tz", "Africa%2FNairobi")   # (as the page writes it)
    return client


def meeting(**extra):
    return {"title": "Weekly sync", "all_day": False, "start_date": "2026-10-05", "start_time": "09:00", "end_date": "2026-10-05",
            "end_time": "10:00", "repeat": None, "calendar": "cal0", "participants": [], "location": "Room 4",
            "description": "Numbers.", **extra}


def shown(mail, start="2026-10-01", end="2026-10-31"):
    return mail.get("/calendar/events", query_string={"start": start, "end": end}).get_json()["events"]


# --- the page and the calendars ---

def test_the_page_has_the_calendars_and_the_view(mail, jmap):
    page = mail.get("/calendar?view=month&date=2026-10-05").get_data(as_text=True)

    assert 'data-view="month"' in page and 'data-date="2026-10-05"' in page and "Create event" in page
    assert jmap.calendars["cal0"]["name"] == "Calendar"   # (the engine's own first name, as PrivateEmail says)
    for view in ("Daily", "Workdays", "Weekly", "Monthly"):
        assert f">{view}</button>" in page


def test_the_view_is_remembered(mail):
    mail.set_cookie("wm_calendar_view", "day")

    assert 'data-view="day"' in mail.get("/calendar").get_data(as_text=True)


def test_a_calendar_is_made_when_there_is_none(mail, jmap):
    jmap.calendars.clear()

    mail.get("/calendar")

    assert [one["name"] for one in jmap.calendars.values()] == ["Calendar"]


def test_a_calendar_is_hidden_renamed_and_coloured(mail, jmap):
    hidden = mail.post("/calendar/calendars/cal0", json={"visible": False}).get_json()
    assert jmap.calendars["cal0"]["isVisible"] is False and hidden["calendars"][0]["visible"] is False

    answer = mail.post("/calendar/calendars/cal0", json={"name": " Work ", "color": "#067F3A"})
    assert answer.get_json()["message"] == "Calendar settings saved"
    assert jmap.calendars["cal0"]["name"] == "Work" and jmap.calendars["cal0"]["color"] == "#067f3a"
    assert mail.post("/calendar/calendars/cal0", json={"color": "green"}).status_code == 400
    assert mail.post("/calendar/calendars/cal0", json={"name": " "}).status_code == 400
    assert mail.post("/calendar/calendars/nope", json={"visible": True}).status_code == 404


# --- events made ---

def test_an_event_is_made_in_the_readers_time(mail, jmap):
    answer = mail.post("/calendar/events", json=meeting())

    assert answer.status_code == 200 and answer.get_json()["message"] == "Event created"
    event = jmap.events[answer.get_json()["id"]]
    assert (event["title"], event["start"], event["timeZone"], event["duration"]) == ("Weekly sync", "2026-10-05T09:00:00",
                                                                                       "Africa/Nairobi", "PT1H")
    assert event["showWithoutTime"] is False and event["locations"]["l1"]["name"] == "Room 4"
    assert event["description"] == "Numbers." and event["calendarIds"] == {"cal0": True}
    assert "participants" not in event and jmap.scheduling == [False]


def test_an_all_day_event_over_days(mail, jmap):
    made = mail.post("/calendar/events", json=meeting(all_day=True, start_date="2026-10-07", end_date="2026-10-08")).get_json()["id"]

    event = jmap.events[made]
    assert (event["start"], event["duration"], event["showWithoutTime"]) == ("2026-10-07T00:00:00", "P2D", True)
    assert "timeZone" not in event


def test_people_are_invited(mail, jmap):
    made = mail.post("/calendar/events", json=meeting(participants=["amina@elsewhere.example", "AMINA@elsewhere.example",
                                                                    "brian@logistics.example"])).get_json()["id"]

    event = jmap.events[made]
    assert event["organizerCalendarAddress"] == "mailto:ceo@pineloop.online"
    people = {person["calendarAddress"]: person for person in event["participants"].values()}
    assert people["mailto:ceo@pineloop.online"]["roles"]["owner"] and people["mailto:ceo@pineloop.online"]["participationStatus"] == "accepted"
    assert people["mailto:amina@elsewhere.example"]["participationStatus"] == "needs-action"
    assert people["mailto:amina@elsewhere.example"]["expectReply"] is True
    assert len(people) == 3 and jmap.scheduling == [True]   # (the engine sends them the invitation)


@pytest.mark.parametrize("change, problem", [
    ({"title": "  "}, "A valid event title is required"),
    ({"title": "T" * 256}, "Event title exceeds a 255 limit length."),
    ({"location": "L" * 256}, "Event location exceeds a 255 limit length."),
    ({"end_time": "08:00"}, "Event end time must be later than start time"),
    ({"end_date": "2026-10-04", "end_time": "11:00"}, "Event end date must be later than start date"),
    ({"all_day": True, "end_date": "2026-10-04"}, "Event end date must be later than start date"),
    ({"start_date": ""}, "Event start date is required"),
    ({"start_date": "2026-02-30"}, "Event start date is invalid"),
    ({"start_time": "25:00"}, "Event start time is invalid"),
    ({"participants": ["amina"]}, "One or more of the recipient email addresses is incorrect"),
    ({"repeat": {"frequency": "hourly"}}, "Choose how the event repeats."),
    ({"repeat": {"frequency": "daily", "until": "2026-10-01"}}, "End date must be on or after event start date"),
])
def test_an_event_is_checked_as_privateemail_checks_it(mail, change, problem):
    answer = mail.post("/calendar/events", json=meeting(**change))

    assert answer.status_code == 400 and answer.get_json()["problem"] == problem


@pytest.mark.parametrize("repeat, rule", [
    ({"frequency": "daily"}, {"@type": "RecurrenceRule", "frequency": "daily"}),
    ({"frequency": "weekly", "interval": 2, "days": ["we", "mo"]},
     {"@type": "RecurrenceRule", "frequency": "weekly", "interval": 2,
      "byDay": [{"@type": "NDay", "day": "mo"}, {"@type": "NDay", "day": "we"}]}),
    ({"frequency": "weekly"}, {"@type": "RecurrenceRule", "frequency": "weekly", "byDay": [{"@type": "NDay", "day": "mo"}]}),
    ({"frequency": "monthly"}, {"@type": "RecurrenceRule", "frequency": "monthly", "byMonthDay": [5]}),
    ({"frequency": "monthly", "ordinal": 1}, {"@type": "RecurrenceRule", "frequency": "monthly",
                                              "byDay": [{"@type": "NDay", "day": "mo", "nthOfPeriod": 1}]}),
    ({"frequency": "yearly", "count": 3}, {"@type": "RecurrenceRule", "frequency": "yearly", "count": 3}),
    ({"frequency": "daily", "until": "2026-10-09"}, {"@type": "RecurrenceRule", "frequency": "daily", "until": "2026-10-09T23:59:59"}),
])
def test_how_an_event_repeats(mail, jmap, repeat, rule):
    made = mail.post("/calendar/events", json=meeting(repeat=repeat)).get_json()["id"]

    assert jmap.events[made]["recurrenceRule"] == rule


# --- the events in view ---

def test_events_are_shown_in_the_readers_time(mail, jmap):
    jmap.add_event(title="From London", start="2026-10-05T07:00:00", timeZone="Europe/London", duration="PT30M")

    one = shown(mail)[0]

    assert (one["title"], one["start"], one["end"], one["all_day"]) == ("From London", "2026-10-05T09:00", "2026-10-05T09:30", False)


def test_a_repeating_event_is_shown_each_time(mail, jmap):
    mail.post("/calendar/events", json=meeting(repeat={"frequency": "weekly", "days": ["mo", "we"], "count": 4}))

    times = [(one["start"], one["repeats"]) for one in shown(mail)]

    assert times == [("2026-10-05T09:00", True), ("2026-10-07T09:00", True), ("2026-10-12T09:00", True), ("2026-10-14T09:00", True)]


def test_an_all_day_event_is_on_its_own_dates_wherever_its_read(mail, jmap):
    jmap.add_event(title="Offsite", start="2026-10-07T00:00:00", duration="P2D", showWithoutTime=True)
    mail.set_cookie("wm_tz", "Pacific%2FKiritimati")

    one = shown(mail)[0]

    assert (one["start"], one["end"], one["all_day"]) == ("2026-10-07T00:00", "2026-10-09T00:00", True)


def test_only_the_dates_asked_for(mail, jmap):
    jmap.add_event(title="September", start="2026-09-20T09:00:00", timeZone="Africa/Nairobi")
    jmap.add_event(title="October", start="2026-10-20T09:00:00", timeZone="Africa/Nairobi")

    assert [one["title"] for one in shown(mail)] == ["October"]
    assert mail.get("/calendar/events", query_string={"start": "2026-10-31", "end": "2026-10-01"}).status_code == 400
    assert mail.get("/calendar/events", query_string={"start": "2026-01-01", "end": "2027-06-01"}).status_code == 400


def test_a_hidden_calendars_events_are_not_shown(mail, jmap):
    jmap.add_event(title="Hidden", start="2026-10-20T09:00:00", timeZone="Africa/Nairobi")
    jmap.calendars["cal0"]["isVisible"] = False

    assert shown(mail) == []


# --- an event, opened ---

def test_an_event_opens_with_its_people_and_repeat(mail, jmap):
    mail.post("/calendar/events", json=meeting(participants=["amina@elsewhere.example"],
                                               repeat={"frequency": "weekly", "days": ["mo"], "count": 3}))
    second = shown(mail)[1]

    event = mail.get(f"/calendar/events/{second['id']}").get_json()["event"]

    assert event["repeats"] and event["rule"]["frequency"] == "weekly" and event["rule"]["count"] == 3
    assert event["is_organizer"] and event["status"] is None and event["calendar_name"] == "Calendar"
    assert {(person["email"], person["status"], person["organizer"]) for person in event["participants"]} == {
        ("ceo@pineloop.online", "accepted", True), ("amina@elsewhere.example", "needs-action", False)}
    assert mail.get("/calendar/events/nope").status_code == 404


def invitation(jmap, **extra):
    return jmap.add_event(title="Supplier call", start="2026-10-08T10:00:00", timeZone="Africa/Nairobi", duration="PT45M",
                          organizerCalendarAddress="mailto:boss@elsewhere.example",
                          participants={"o": {"calendarAddress": "mailto:boss@elsewhere.example", "roles": {"owner": True}},
                                        "me": {"calendarAddress": "mailto:ceo@pineloop.online", "participationStatus": "needs-action"}},
                          **extra)


def test_an_invitation_is_answered(mail, jmap):
    event_id = invitation(jmap)
    event = mail.get(f"/calendar/events/{event_id}").get_json()["event"]
    assert event["status"] == "needs-action" and not event["is_organizer"]

    answer = mail.post(f"/calendar/events/{event_id}/reply", json={"status": "accepted"})

    assert answer.get_json()["message"] == "Event Accepted"
    assert jmap.events[event_id]["participants"]["me"]["participationStatus"] == "accepted" and jmap.scheduling[-1] is True
    assert mail.post(f"/calendar/events/{event_id}/reply", json={"status": "maybe"}).status_code == 400


def test_only_the_organizer_changes_an_event(mail, jmap):
    event_id = invitation(jmap)

    answer = mail.post(f"/calendar/events/{event_id}", json=meeting())

    assert answer.status_code == 403 and answer.get_json()["problem"] == "Only the organizer can edit this event."


def test_an_answer_needs_to_be_invited(mail, jmap):
    event_id = jmap.add_event(title="Mine", start="2026-10-08T10:00:00", timeZone="Africa/Nairobi")

    assert mail.post(f"/calendar/events/{event_id}/reply", json={"status": "accepted"}).status_code == 400


# --- events changed and deleted ---

def test_an_event_is_changed(mail, jmap):
    made = mail.post("/calendar/events", json=meeting()).get_json()["id"]

    answer = mail.post(f"/calendar/events/{made}", json=meeting(title="Budget review", start_time="14:00", end_time="15:30"))

    assert answer.get_json()["message"] == "Event updated"
    event = jmap.events[made]
    assert (event["title"], event["start"], event["duration"]) == ("Budget review", "2026-10-05T14:00:00", "PT1H30M")


def test_one_time_of_a_repeating_event_is_moved(mail, jmap):
    made = mail.post("/calendar/events", json=meeting(repeat={"frequency": "weekly", "days": ["mo"], "count": 3})).get_json()["id"]
    second = shown(mail)[1]

    mail.post(f"/calendar/events/{second['id']}", json=meeting(title="Moved", start_date="2026-10-12", start_time="11:00",
                                                               end_date="2026-10-12", end_time="12:00", scope="this"))

    assert jmap.events[made]["recurrenceOverrides"]["2026-10-12T09:00:00"]["start"] == "2026-10-12T11:00:00"
    assert [(one["title"], one["start"]) for one in shown(mail)] == [("Weekly sync", "2026-10-05T09:00"), ("Moved", "2026-10-12T11:00"),
                                                                      ("Weekly sync", "2026-10-19T09:00")]
    assert "recurrenceRule" in jmap.events[made]   # (the series still repeats)


def test_all_times_of_a_repeating_event_move_together(mail, jmap):
    made = mail.post("/calendar/events", json=meeting(repeat={"frequency": "weekly", "days": ["mo"], "count": 3})).get_json()["id"]
    second = shown(mail)[1]

    mail.post(f"/calendar/events/{second['id']}", json=meeting(start_date="2026-10-12", start_time="10:30", end_date="2026-10-12",
                                                               end_time="11:30", scope="all",
                                                               repeat={"frequency": "weekly", "days": ["mo"], "count": 3}))

    assert jmap.events[made]["start"] == "2026-10-05T10:30:00"
    assert [one["start"] for one in shown(mail)] == ["2026-10-05T10:30", "2026-10-12T10:30", "2026-10-19T10:30"]


def test_one_time_of_a_repeating_event_is_deleted(mail, jmap):
    made = mail.post("/calendar/events", json=meeting(repeat={"frequency": "daily", "count": 3})).get_json()["id"]
    middle = shown(mail)[1]

    answer = mail.post(f"/calendar/events/{middle['id']}/delete", json={"scope": "this"})

    assert answer.get_json()["message"] == "Event Deleted"
    assert [one["start"] for one in shown(mail)] == ["2026-10-05T09:00", "2026-10-07T09:00"]
    assert made in jmap.events


def test_all_times_of_a_repeating_event_are_deleted(mail, jmap):
    made = mail.post("/calendar/events", json=meeting(repeat={"frequency": "daily", "count": 3})).get_json()["id"]
    middle = shown(mail)[1]

    mail.post(f"/calendar/events/{middle['id']}/delete", json={"scope": "all"})

    assert made not in jmap.events and shown(mail) == []


def test_removing_everyone_invited_cancels_it_for_them(mail, jmap):
    made = mail.post("/calendar/events", json=meeting(participants=["amina@elsewhere.example"])).get_json()["id"]

    mail.post(f"/calendar/events/{made}", json=meeting(participants=[]))

    assert "participants" not in jmap.events[made] and jmap.scheduling[-1] is True


def test_answers_so_far_are_kept_when_the_event_changes(mail, jmap):
    made = mail.post("/calendar/events", json=meeting(participants=["amina@elsewhere.example"])).get_json()["id"]
    key = next(key for key, person in jmap.events[made]["participants"].items() if "amina" in person["calendarAddress"])
    jmap.events[made]["participants"][key]["participationStatus"] = "accepted"

    mail.post(f"/calendar/events/{made}", json=meeting(title="Weekly sync (moved)", participants=["amina@elsewhere.example",
                                                                                                "brian@logistics.example"]))

    people = {person["calendarAddress"]: person["participationStatus"] for person in jmap.events[made]["participants"].values()}
    assert people == {"mailto:ceo@pineloop.online": "accepted", "mailto:amina@elsewhere.example": "accepted",
                      "mailto:brian@logistics.example": "needs-action"}


# --- times ---

@pytest.mark.parametrize("text, span", [
    ("PT1H", datetime.timedelta(hours=1)), ("PT1H30M", datetime.timedelta(minutes=90)), ("P2D", datetime.timedelta(days=2)),
    ("P1W", datetime.timedelta(weeks=1)), ("P1DT2H", datetime.timedelta(days=1, hours=2)), ("PT45S", datetime.timedelta(seconds=45)),
    ("nonsense", datetime.timedelta(0)),
])
def test_durations_are_read(text, span):
    assert calendar.parse_duration(text) == span


@pytest.mark.parametrize("span, text", [
    (datetime.timedelta(hours=1), "PT1H"), (datetime.timedelta(minutes=90), "PT1H30M"), (datetime.timedelta(days=2), "P2D"),
    (datetime.timedelta(days=1, hours=2), "P1DT2H"), (datetime.timedelta(0), "PT0S"),
])
def test_durations_are_written(span, text):
    assert calendar.format_duration(span) == text


def test_an_event_without_a_time_zone_is_the_readers_own_time():
    start, end, all_day = calendar.placed({"start": "2026-10-05T09:00:00", "duration": "PT1H"}, NAIROBI)

    assert (start.isoformat(), end.isoformat(), all_day) == ("2026-10-05T09:00:00", "2026-10-05T10:00:00", False)
