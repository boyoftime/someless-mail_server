"""The calendar, as PrivateEmail's: the mailbox's calendars and events, kept in the mail engine
(JMAP for Calendars: each event a JSCalendar object, RFC 8984 and its update), so phones and mail
apps see the same ones (CalDAV, dav.py). The page draws a month, a week, the working week or a
day (webmail-calendar.js) from the events of the dates in view, which come from here in the
reader's own time zone, repeating ones as each time they happen. An event is made, changed or
deleted here: one time of a repeating event ("this event only") or all of them; with people
invited, the engine sends them the invitation (iMIP), and an invitation received is answered
here (Accept, Maybe, Decline)."""
import datetime
import re
import zoneinfo

from flask import Blueprint, g, render_template, request

from . import login_required
from .compose import _own_addresses
from .jmap import MailError, for_mailbox
from .mail import reachable
from .messages import zone, zone_name

bp = Blueprint("calendar", __name__, url_prefix="/calendar")

USING = ["urn:ietf:params:jmap:calendars"]
VIEWS = ("month", "week", "workweek", "day")
DEFAULT_CALENDAR = "Calendar"
COLORS = ("#3b63e6", "#602fcc", "#0f6bd0", "#067f3a", "#c04900", "#d93a3a", "#b18a00", "#0e8a8a")
LONGEST_TITLE = 255
LONGEST_LOCATION = 255
LONGEST_DESCRIPTION = 10_000
MOST_PARTICIPANTS = 250
MOST_DAYS = 366            # the most a page asks for at once
IN_ONE_GET = 500
FREQUENCIES = ("daily", "weekly", "monthly", "yearly")
WEEKDAYS = ("mo", "tu", "we", "th", "fr", "sa", "su")
STATUSES = ("accepted", "tentative", "declined")
ADDRESS = re.compile(r"^[^@\s<>(),;:\"\[\]\\]+@[^@\s<>(),;:\"\[\]\\]+\.[^@\s<>(),;:\"\[\]\\]+$")
DURATION = re.compile(r"^(-)?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
EVENT_PROPERTIES = ["title", "start", "duration", "timeZone", "showWithoutTime", "baseEventId", "recurrenceId", "calendarIds",
                    "locations", "participants", "organizerCalendarAddress", "color", "recurrenceRule", "recurrenceOverrides",
                    "status", "description", "freeBusyStatus"]


class EventProblem(Exception):
    """An event that can't be: what's wrong, as PrivateEmail says it."""


def _mail():
    return for_mailbox(g.mailbox["email"])


# --- times ---

def parse_duration(text):
    """An ISO 8601 duration (PT1H30M, P1D, P1W) as a timedelta."""
    found = DURATION.match(text or "")
    if not found:
        return datetime.timedelta(0)
    sign, weeks, days, hours, minutes, seconds = found.groups()
    span = datetime.timedelta(weeks=int(weeks or 0), days=int(days or 0), hours=int(hours or 0), minutes=int(minutes or 0),
                              seconds=int(seconds or 0))
    return -span if sign else span


def format_duration(span):
    """A timedelta as an ISO 8601 duration (whole days as P2D, else PT1H30M)."""
    seconds = int(span.total_seconds())
    if seconds <= 0:
        return "PT0S"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    text = "P" + (f"{days}D" if days else "")
    if hours or minutes or seconds:
        text += "T" + (f"{hours}H" if hours else "") + (f"{minutes}M" if minutes else "") + (f"{seconds}S" if seconds else "")
    return text


def _zone_named(name):
    try:
        return zoneinfo.ZoneInfo(name) if name else None
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return None


def _local(moment):
    return moment.replace(tzinfo=None).isoformat(timespec="minutes")


def placed(event, reader):
    """When an event is, in the reader's time zone: (start, end, all day) — naive datetimes; an
    all-day event on its own dates, wherever it's read."""
    start = datetime.datetime.fromisoformat(event["start"])
    span = parse_duration(event.get("duration") or "PT0S")
    if event.get("showWithoutTime"):
        day = start.replace(hour=0, minute=0, second=0)
        return day, day + max(span, datetime.timedelta(days=1)), True
    source = _zone_named(event.get("timeZone")) or reader
    begins = start.replace(tzinfo=source).astimezone(reader)
    return begins.replace(tzinfo=None), (begins + span).replace(tzinfo=None), False


# --- the calendars ---

def calendars(mail):
    """The mailbox's calendars, the default first: [{"id", "name", "color", "visible", "default"}].
    The engine's own first name for one ("Stalwart Calendar (…)") becomes "Calendar"; none, and
    one is made."""
    found = mail.call(("Calendar/get", {}), using=USING)[0]["list"]
    if not found:
        made = mail.call(("Calendar/set", {"create": {"cal": {"name": DEFAULT_CALENDAR, "color": COLORS[0], "isDefault": True}}}),
                         using=USING)[0]
        created = (made.get("created") or {}).get("cal")
        if not created:
            raise MailError(f"Calendar/set: {(made.get('notCreated') or {}).get('cal')}")
        found = [{"id": created["id"], "name": DEFAULT_CALENDAR, "color": COLORS[0], "isDefault": True, "isVisible": True}]
    renames = {one["id"]: {"name": DEFAULT_CALENDAR} for one in found if (one.get("name") or "").startswith("Stalwart Calendar")}
    if renames:
        mail.call(("Calendar/set", {"update": renames}), using=USING)
        for one in found:
            if one["id"] in renames:
                one["name"] = DEFAULT_CALENDAR
    listed = [{"id": one["id"], "name": one.get("name") or DEFAULT_CALENDAR, "color": one.get("color") or COLORS[index % len(COLORS)],
               "visible": one.get("isVisible", True) is not False, "default": bool(one.get("isDefault"))}
              for index, one in enumerate(found)]
    return sorted(listed, key=lambda one: (not one["default"], one["name"].lower()))


# --- the events ---

def _me(event, own):
    """(my participant's key, their status) in an event's participants, or (None, None)."""
    mine = {address.lower() for address in own}
    for key, person in (event.get("participants") or {}).items():
        address = _address_of(person)
        if address and address.lower() in mine:
            return key, person.get("participationStatus") or "needs-action"
    return None, None


def _address_of(person):
    address = person.get("calendarAddress") or person.get("email") or (person.get("sendTo") or {}).get("imip") or ""
    return address[7:] if address.lower().startswith("mailto:") else address


def _organizer(event):
    address = event.get("organizerCalendarAddress") or ""
    if address.lower().startswith("mailto:"):
        return address[7:]
    for person in (event.get("participants") or {}).values():
        if (person.get("roles") or {}).get("owner"):
            return _address_of(person)
    return ""


def shown(event, reader, own, colors):
    """What the page draws of an event (one time of it, for a repeating one)."""
    start, end, all_day = placed(event, reader)
    my_key, my_status = _me(event, own)
    organizer = _organizer(event)
    mine = {address.lower() for address in own}
    has_people = bool(event.get("participants"))
    calendar_id = next(iter(event.get("calendarIds") or {}), None)
    location = next((one.get("name", "") for one in (event.get("locations") or {}).values()), "")
    return {
        "id": event["id"], "base": event.get("baseEventId") or event["id"], "recurrence": event.get("recurrenceId"),
        "repeats": bool(event.get("baseEventId") or event.get("recurrenceRule")),
        "calendar": calendar_id, "color": event.get("color") or colors.get(calendar_id) or COLORS[0],
        "title": event.get("title") or "", "location": location,
        "start": _local(start), "end": _local(end), "all_day": all_day,
        "status": my_status if has_people and organizer.lower() not in mine else None,
        "organizer": organizer, "is_organizer": not has_people or organizer.lower() in mine or not organizer,
        "cancelled": event.get("status") == "cancelled",
    }


def events_between(mail, first_day, last_day, reader, own, colors, visible):
    """The events on the reader's days from first_day to last_day (both), each time a repeating
    one happens, in time order."""
    after = datetime.datetime.combine(first_day - datetime.timedelta(days=1), datetime.time(), reader).astimezone(datetime.timezone.utc)
    before = datetime.datetime.combine(last_day + datetime.timedelta(days=2), datetime.time(), reader).astimezone(datetime.timezone.utc)
    ids = mail.call(("CalendarEvent/query", {"filter": {"after": after.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                         "before": before.strftime("%Y-%m-%dT%H:%M:%SZ")},
                                              "expandRecurrences": True}), using=USING)[0]["ids"]
    found = []
    for start in range(0, len(ids), IN_ONE_GET):
        found += mail.call(("CalendarEvent/get", {"ids": ids[start:start + IN_ONE_GET], "properties": EVENT_PROPERTIES}),
                           using=USING)[0]["list"]
    window_start = datetime.datetime.combine(first_day, datetime.time())
    window_end = datetime.datetime.combine(last_day + datetime.timedelta(days=1), datetime.time())
    listed = []
    for event in found:
        calendar_id = next(iter(event.get("calendarIds") or {}), None)
        if visible is not None and calendar_id not in visible:
            continue
        one = shown(event, reader, own, colors)
        begins, ends = datetime.datetime.fromisoformat(one["start"]), datetime.datetime.fromisoformat(one["end"])
        if ends <= window_start or begins >= window_end:
            if not (begins == ends and window_start <= begins < window_end):
                continue
        listed.append(one)
    listed.sort(key=lambda one: (one["start"], not one["all_day"], one["end"], one["title"].lower()))
    return listed


# --- an event, checked ---

def _date(text, problem):
    try:
        return datetime.date.fromisoformat(str(text or ""))
    except ValueError:
        raise EventProblem(problem)


def _clock(text, problem):
    try:
        return datetime.time.fromisoformat(str(text or ""))
    except ValueError:
        raise EventProblem(problem)


def _repeat(data, starts):
    """The repeat rule ({"frequency", "interval", "days", "month_day", "ordinal", "until", "count"})
    as JSCalendar's, or None for Never."""
    if not data:
        return None
    frequency = data.get("frequency")
    if frequency not in FREQUENCIES:
        raise EventProblem("Choose how the event repeats.")
    rule = {"@type": "RecurrenceRule", "frequency": frequency}
    interval = int(data.get("interval") or 1)
    if not 1 <= interval <= 999:
        raise EventProblem("Repeats every must be between 1 and 999.")
    if interval > 1:
        rule["interval"] = interval
    if frequency == "weekly":
        days = [day for day in WEEKDAYS if day in (data.get("days") or [])] or [WEEKDAYS[starts.weekday()]]
        rule["byDay"] = [{"@type": "NDay", "day": day} for day in days]
    if frequency == "monthly":
        if data.get("ordinal"):
            ordinal = int(data["ordinal"])
            if not 1 <= ordinal <= 5:
                raise EventProblem("Calendar event action is invalid")
            rule["byDay"] = [{"@type": "NDay", "day": WEEKDAYS[starts.weekday()], "nthOfPeriod": ordinal}]
        else:
            rule["byMonthDay"] = [int(data.get("month_day") or starts.day)]
    if data.get("until"):
        until = _date(data["until"], "Event end date is invalid")
        if until < starts:
            raise EventProblem("End date must be on or after event start date")
        rule["until"] = f"{until.isoformat()}T23:59:59"
    elif data.get("count"):
        count = int(data["count"])
        if not 1 <= count <= 999:
            raise EventProblem("After must be between 1 and 999 events.")
        rule["count"] = count
    return rule


def check(data, reader_zone_name):
    """What the form sent, as the event's properties to write: EventProblem when it can't be."""
    title = " ".join(str(data.get("title") or "").split())
    if not title:
        raise EventProblem("A valid event title is required")
    if len(title) > LONGEST_TITLE:
        raise EventProblem("Event title exceeds a 255 limit length.")
    location = " ".join(str(data.get("location") or "").split())
    if len(location) > LONGEST_LOCATION:
        raise EventProblem("Event location exceeds a 255 limit length.")
    description = str(data.get("description") or "").strip()
    if len(description) > LONGEST_DESCRIPTION:
        raise EventProblem("Description is too long. Please shorten it to continue.")
    all_day = bool(data.get("all_day"))
    if not data.get("start_date"):
        raise EventProblem("Event start date is required")
    if not data.get("end_date"):
        raise EventProblem("Event end date is required")
    start_day = _date(data["start_date"], "Event start date is invalid")
    end_day = _date(data["end_date"], "Event end date is invalid")
    if all_day:
        if end_day < start_day:
            raise EventProblem("Event end date must be later than start date")
        starts = datetime.datetime.combine(start_day, datetime.time())
        span = datetime.timedelta(days=(end_day - start_day).days + 1)
    else:
        if not data.get("start_time"):
            raise EventProblem("Event start time is required")
        if not data.get("end_time"):
            raise EventProblem("Event end time is required")
        starts = datetime.datetime.combine(start_day, _clock(data["start_time"], "Event start time is invalid"))
        ends = datetime.datetime.combine(end_day, _clock(data["end_time"], "Event end time is invalid"))
        if ends <= starts:
            raise EventProblem("Event end time must be later than start time" if end_day == start_day
                               else "Event end date must be later than start date")
        span = ends - starts
    people = []
    for address in data.get("participants") or []:
        address = str(address or "").strip()
        if not address:
            continue
        if len(address) > 254 or not ADDRESS.match(address):
            raise EventProblem("One or more of the recipient email addresses is incorrect")
        if address.lower() not in {one.lower() for one in people}:
            people.append(address)
    if len(people) > MOST_PARTICIPANTS:
        raise EventProblem("Participants exceed a 250 limit length.")
    properties = {
        "title": title, "description": description, "showWithoutTime": all_day,
        "start": starts.isoformat(timespec="seconds"), "duration": format_duration(span),
        "timeZone": None if all_day else reader_zone_name,
        "locations": {"l1": {"@type": "Location", "name": location}} if location else None,
        "recurrenceRule": _repeat(data.get("repeat"), start_day),
    }
    return properties, people


def _participants(people, own, name, existing=None):
    """The event's participants: me (the organizer) and the people invited, as they were answered
    so far (existing)."""
    existing = existing or {}
    by_address = {_address_of(person).lower(): (key, person) for key, person in existing.items()}
    made = {}
    me_key, me = by_address.get(own[0].lower(), ("organizer", {}))
    made[me_key] = {**me, "@type": "Participant", "name": name or me.get("name") or own[0], "calendarAddress": f"mailto:{own[0]}",
                    "roles": {"owner": True, "attendee": True, "chair": True}, "participationStatus": "accepted"}
    for index, address in enumerate(people, start=1):
        key, person = by_address.get(address.lower(), (f"p{index}", {}))
        if key == me_key:
            continue
        made[key] = {"@type": "Participant", "calendarAddress": f"mailto:{address}", "roles": {"attendee": True},
                     "participationStatus": person.get("participationStatus") or "needs-action", "expectReply": True,
                     **({"name": person["name"]} if person.get("name") else {})}
    return made


# --- the pages ---

def _reader():
    return zone()


def _reader_zone_name():
    return zone_name()


def _who():
    from .settings import _who as settings_who
    return settings_who() or g.mailbox["email"].partition("@")[0]


def _data():
    return request.get_json(silent=True) or {}


@bp.get("")
@login_required
@reachable
def index():
    mail = _mail()
    listed = calendars(mail)
    view = request.args.get("view") if request.args.get("view") in VIEWS else request.cookies.get("wm_calendar_view", "week")
    view = view if view in VIEWS else "week"
    today = datetime.datetime.now(_reader()).date()
    try:
        chosen = datetime.date.fromisoformat(request.args.get("date", ""))
    except ValueError:
        chosen = today
    name = _who()
    return render_template("webmail-calendar.html", email=g.mailbox["email"], name=name, initial=name[:1].upper(),
                           calendars=listed, view=view, date=chosen.isoformat(), today=today.isoformat(), colors=COLORS,
                           own=_own_addresses(), zone_name=_reader_zone_name())


@bp.get("/events")
@login_required
@reachable
def events():
    """The events from start to end (dates, both in view) as the page draws them."""
    try:
        first_day = datetime.date.fromisoformat(request.args.get("start", ""))
        last_day = datetime.date.fromisoformat(request.args.get("end", ""))
    except ValueError:
        return {"problem": "Choose the dates to show."}, 400
    if last_day < first_day or (last_day - first_day).days > MOST_DAYS:
        return {"problem": "Choose the dates to show."}, 400
    mail = _mail()
    listed = calendars(mail)
    colors = {one["id"]: one["color"] for one in listed}
    visible = {one["id"] for one in listed if one["visible"]}
    return {"events": events_between(mail, first_day, last_day, _reader(), _own_addresses(), colors, visible)}


def _get_event(mail, event_id):
    """One event, or one time of a repeating one (its id from the query: the engine tells which
    series it's of only when asked for baseEventId by name)."""
    found = mail.call(("CalendarEvent/get", {"ids": [event_id], "properties": EVENT_PROPERTIES + ["id"]}), using=USING)[0]["list"]
    return found[0] if found else None


@bp.get("/events/<event_id>")
@login_required
@reachable
def event(event_id):
    """One event (one time of a repeating one), all of it, for the event's own window."""
    mail = _mail()
    found = _get_event(mail, event_id)
    if found is None:
        return {"problem": "Calendar event not found"}, 404
    listed = calendars(mail)
    colors = {one["id"]: one["color"] for one in listed}
    own = _own_addresses()
    one = shown(found, _reader(), own, colors)
    base = found if not found.get("baseEventId") else (_get_event(mail, found["baseEventId"]) or found)
    rule = base.get("recurrenceRule")
    one.update({
        "description": found.get("description") or "",
        "calendar_name": next((calendar["name"] for calendar in listed if calendar["id"] == one["calendar"]), ""),
        "participants": [{"name": person.get("name") or "", "email": _address_of(person),
                          "status": person.get("participationStatus") or "needs-action",
                          "organizer": _address_of(person).lower() == one["organizer"].lower()}
                         for person in (found.get("participants") or {}).values()],
        "rule": _rule_for_form(rule), "base_start": base.get("start"),
    })
    return {"event": one}


def _rule_for_form(rule):
    if not rule:
        return None
    by_day = rule.get("byDay") or []
    return {"frequency": rule.get("frequency"), "interval": rule.get("interval") or 1,
            "days": [one.get("day") for one in by_day if not one.get("nthOfPeriod")],
            "ordinal": next((one.get("nthOfPeriod") for one in by_day if one.get("nthOfPeriod")), None),
            "month_day": (rule.get("byMonthDay") or [None])[0],
            "until": (rule.get("until") or "")[:10] or None, "count": rule.get("count")}


def _calendar_for(mail, wanted):
    listed = calendars(mail)
    return wanted if any(one["id"] == wanted for one in listed) else listed[0]["id"]


def _problem_of(result, key, action):
    error = (result.get(f"not{action}") or {}).get(key) or {}
    if error.get("type") == "forbidden":
        return "Only the organizer can edit this event."
    return {"Created": "Error occurred while creating event", "Updated": "Error occurred while updating event",
            "Destroyed": "Error occurred while deleting event"}[action]


@bp.post("/events")
@login_required
@reachable
def create():
    data = _data()
    try:
        properties, people = check(data, _reader_zone_name())
    except (EventProblem, ValueError) as problem:
        return {"problem": str(problem) if isinstance(problem, EventProblem) else "Calendar event action is invalid"}, 400
    mail = _mail()
    own = _own_addresses()
    event = {"@type": "Event", "calendarIds": {_calendar_for(mail, data.get("calendar")): True},
             **{key: value for key, value in properties.items() if value is not None}}
    if people:
        event["participants"] = _participants(people, own, _who())
        event["organizerCalendarAddress"] = f"mailto:{own[0]}"
    result = mail.call(("CalendarEvent/set", {"create": {"event": event}, "sendSchedulingMessages": bool(people)}), using=USING)[0]
    created = (result.get("created") or {}).get("event")
    if not created:
        return {"problem": _problem_of(result, "event", "Created")}, 502
    return {"message": "Event created", "id": created["id"]}


@bp.post("/events/<event_id>")
@login_required
@reachable
def update(event_id):
    """An event changed: one time of a repeating one ({"scope": "this"}) or all of them ("all")."""
    data = _data()
    mail = _mail()
    found = _get_event(mail, event_id)
    if found is None:
        return {"problem": "Calendar event not found"}, 404
    own = _own_addresses()
    one = shown(found, _reader(), own, {})
    if not one["is_organizer"]:
        return {"problem": "Only the organizer can edit this event."}, 403
    try:
        properties, people = check(data, _reader_zone_name())
    except (EventProblem, ValueError) as problem:
        return {"problem": str(problem) if isinstance(problem, EventProblem) else "Calendar event action is invalid"}, 400
    everything = data.get("scope") == "all" and found.get("baseEventId")
    target = found["baseEventId"] if everything else event_id
    if found.get("baseEventId") and not everything:
        # one time of a repeating event: its own title, time, place and words (the rest is the series')
        patch = {key: properties[key] for key in ("title", "description", "start", "duration", "timeZone", "showWithoutTime",
                                                  "locations")}
    else:
        if everything:   # the whole series moves as this time of it moved (in the reader's time)
            reader = _reader()
            base = _get_event(mail, target)
            moved = datetime.datetime.fromisoformat(properties["start"]) - placed(found, reader)[0]
            properties["start"] = (placed(base, reader)[0] + moved).isoformat(timespec="seconds")
            found = base
        patch = dict(properties)
        patch["calendarIds"] = {_calendar_for(mail, data.get("calendar") or next(iter(found.get("calendarIds") or {}), None)): True}
        if people or found.get("participants"):
            patch["participants"] = _participants(people, own, _who(), found.get("participants")) if people else None
            patch["organizerCalendarAddress"] = f"mailto:{own[0]}" if people else None
    result = mail.call(("CalendarEvent/set", {"update": {target: patch}, "sendSchedulingMessages": bool(people or found.get("participants"))}),
                       using=USING)[0]
    if target not in (result.get("updated") or {}):
        return {"problem": _problem_of(result, target, "Updated")}, 502
    return {"message": "Event updated"}


@bp.post("/events/<event_id>/delete")
@login_required
@reachable
def delete(event_id):
    data = _data()
    mail = _mail()
    found = _get_event(mail, event_id)
    if found is None:
        return {"problem": "Calendar event not found"}, 404
    target = found["baseEventId"] if data.get("scope") == "all" and found.get("baseEventId") else event_id
    result = mail.call(("CalendarEvent/set", {"destroy": [target], "sendSchedulingMessages": bool(found.get("participants"))}),
                       using=USING)[0]
    if target not in (result.get("destroyed") or []):
        return {"problem": _problem_of(result, target, "Destroyed")}, 502
    return {"message": "Event Deleted"}


@bp.post("/events/<event_id>/reply")
@login_required
@reachable
def reply(event_id):
    """An invitation answered: {"status": "accepted" | "tentative" | "declined", "scope"}; the
    organizer is told (iMIP)."""
    data = _data()
    status = data.get("status")
    if status not in STATUSES:
        return {"problem": "Calendar event action is invalid"}, 400
    mail = _mail()
    found = _get_event(mail, event_id)
    if found is None:
        return {"problem": "Calendar event not found"}, 404
    target = found["baseEventId"] if data.get("scope") == "all" and found.get("baseEventId") else event_id
    key, _ = _me(found, _own_addresses())
    if key is None:
        return {"problem": "Calendar event action is invalid"}, 400
    result = mail.call(("CalendarEvent/set", {"update": {target: {f"participants/{key}/participationStatus": status}},
                                               "sendSchedulingMessages": True}), using=USING)[0]
    if target not in (result.get("updated") or {}):
        return {"problem": "The event has changed. Please review the latest version before responding."}, 502
    return {"message": {"accepted": "Event Accepted", "tentative": "Event marked as Maybe", "declined": "Event Declined"}[status]}


@bp.post("/calendars/<calendar_id>")
@login_required
@reachable
def calendar_settings(calendar_id):
    """A calendar shown or hidden ({"visible"}), renamed or coloured ({"name", "color"})."""
    data = _data()
    mail = _mail()
    if not any(one["id"] == calendar_id for one in calendars(mail)):
        return {"problem": "That calendar isn't there any more."}, 404
    patch = {}
    if "visible" in data:
        patch["isVisible"] = bool(data["visible"])
    if "name" in data:
        name = " ".join(str(data["name"] or "").split())
        if not name:
            return {"problem": "A calendar needs a name."}, 400
        if len(name) > 100:
            return {"problem": "A calendar's name must be no more than 100 characters."}, 400
        patch["name"] = name
    if "color" in data:
        if not re.match(r"^#[0-9a-fA-F]{6}$", str(data["color"] or "")):
            return {"problem": "Choose a color."}, 400
        patch["color"] = data["color"].lower()
    if not patch:
        return {"problem": "Nothing to change."}, 400
    result = mail.call(("Calendar/set", {"update": {calendar_id: patch}}), using=USING)[0]
    if calendar_id not in (result.get("updated") or {}):
        return {"problem": "Error occurred while saving calendar settings"}, 502
    return {"message": "Calendar settings saved" if "visible" not in patch else "", "calendars": calendars(mail)}
