"""Contacts, as PrivateEmail's address book: the mailbox's contacts, kept in the mail engine (JMAP
for Contacts, RFC 9610: each one a JSContact card, RFC 9553), so mail apps and phones see the same
ones (CardDAV, dav.py). The page lists them by name, a page at a time (10, 25, 50 or 100), found
by what's typed in the search field; a contact opens in Contact details, and is added or changed
in its form: display name, first and last name, email addresses, phone numbers, the job, postal
addresses, a birthday, a note and a photo. The address books are down the side ("Contact Books").

The engine sorts cards only by when they were made, and finds whole words only; so the webmail
reads the names of them all (without photos) and sorts and searches them itself. The compose
window's suggestions use them too (addresses())."""
import datetime
import re

from flask import Blueprint, g, render_template, request

from . import login_required
from .jmap import MailError, for_mailbox
from .mail import reachable

bp = Blueprint("contacts", __name__, url_prefix="/contacts")

USING = ["urn:ietf:params:jmap:contacts"]
PAGE_SIZES = (10, 25, 50, 100)
PAGE_SIZE = 25
IN_ONE_GET = 500
IN_ONE_QUERY = 1000
MOST_ITEMS = 10          # email addresses, phone numbers, postal addresses: each
LONGEST = {"display_name": 255, "first_name": 127, "last_name": 127, "email": 254, "phone": 64, "job_title": 255,
           "company": 255, "department": 255, "street": 255, "city": 127, "state": 127, "postcode": 32, "country": 127,
           "notes": 5000}
BIGGEST_PHOTO = 300_000  # characters of its data: URI (the page makes it 256 pixels square first)
EMAIL_TYPES = ("other", "home", "work")
PHONE_TYPES = ("other", "home", "work", "mobile", "fax", "pager")
ADDRESS_TYPES = ("other", "home", "work")
TYPE_LABELS = {"other": "Other", "home": "Home", "work": "Work", "mobile": "Mobile", "fax": "Fax", "pager": "Pager"}
ADDRESS = re.compile(r"^[^@\s<>(),;:\"\[\]\\]+@[^@\s<>(),;:\"\[\]\\]+\.[^@\s<>(),;:\"\[\]\\]+$")
PHONE = re.compile(r"^[0-9+()#*.,;/\s-]{2,64}$")
LIST_PROPERTIES = ["name", "emails", "phones", "organizations", "titles", "addressBookIds"]
DEFAULT_BOOK = "Personal"


class ContactProblem(Exception):
    """A contact that can't be kept: what's wrong, as PrivateEmail says it."""


def _mail():
    return for_mailbox(g.mailbox["email"])


# --- a card and a contact ---

def _contexts(kind):
    return {"work": {"work": True}, "home": {"private": True}}.get(kind)


def _kind_of(item):
    features = item.get("features") or {}
    for feature in ("mobile", "fax", "pager"):
        if features.get(feature):
            return feature
    contexts = item.get("contexts") or {}
    if contexts.get("work"):
        return "work"
    if contexts.get("private"):
        return "home"
    return "other"


def _ordered(items):
    """A JSContact map ({"e1": {...}}) as a list, in the order it was written (its keys)."""
    return [value for _, value in sorted((items or {}).items(), key=lambda pair: (len(pair[0]), pair[0]))]


def _birthday(anniversaries):
    for anniversary in _ordered(anniversaries):
        if anniversary.get("kind") != "birth":
            continue
        date = anniversary.get("date") or {}
        if date.get("@type") == "Timestamp" or "utc" in date:
            return str(date.get("utc", ""))[:10]
        month, day = date.get("month"), date.get("day")
        if not (month and day):
            continue
        year = date.get("year")
        return f"{year:04d}-{month:02d}-{day:02d}" if year else f"--{month:02d}-{day:02d}"
    return ""


def from_card(card):
    """What the page shows of a card."""
    name = card.get("name") or {}
    parts = {part.get("kind"): part.get("value", "") for part in name.get("components") or []}
    first, last = parts.get("given", ""), parts.get("surname", "")
    display = name.get("full") or " ".join(part for part in (first, last) if part)
    organization = next(iter(_ordered(card.get("organizations"))), {})
    title = next((one for one in _ordered(card.get("titles")) if one.get("kind", "title") == "title"), {})
    note = next(iter(_ordered(card.get("notes"))), {})
    photo = next((one.get("uri", "") for one in _ordered(card.get("media")) if one.get("kind") == "photo"), "")
    addresses = []
    for address in _ordered(card.get("addresses")):
        found = {part.get("kind"): part.get("value", "") for part in address.get("components") or []}
        street = found.get("name") or " ".join(value for kind, value in found.items()
                                               if kind in ("number", "block", "building", "floor", "apartment", "room"))
        addresses.append({"type": _kind_of(address), "street": street or (address.get("full") or ""),
                          "city": found.get("locality", ""), "state": found.get("region", ""),
                          "postcode": found.get("postcode", ""), "country": found.get("country", "")})
    return {
        "id": card.get("id"), "book": next(iter(card.get("addressBookIds") or {}), None),
        "display_name": display, "first_name": first, "last_name": last,
        "emails": [{"type": _kind_of(one), "value": one.get("address", "")} for one in _ordered(card.get("emails"))],
        "phones": [{"type": _kind_of(one), "value": one.get("number", "")} for one in _ordered(card.get("phones"))],
        "addresses": addresses,
        "job_title": title.get("name", ""), "company": organization.get("name", ""),
        "department": next((unit.get("name", "") for unit in organization.get("units") or []), ""),
        "birthday": _birthday(card.get("anniversaries")), "notes": note.get("note", ""),
        "photo": photo if photo.startswith("data:image/") else "",
    }


def to_card(contact, book_id):
    """The card for what the form says (every part of it: a change writes them all again)."""
    components = [{"kind": kind, "value": contact[field]} for kind, field in (("given", "first_name"), ("surname", "last_name"))
                  if contact[field]]
    card = {
        "@type": "Card", "version": "1.0", "kind": "individual", "addressBookIds": {book_id: True},
        "name": {"@type": "Name", "full": contact["display_name"], "components": components, "isOrdered": True},
        "emails": {f"e{index}": {"@type": "EmailAddress", "address": one["value"],
                                 **({"contexts": _contexts(one["type"])} if _contexts(one["type"]) else {})}
                   for index, one in enumerate(contact["emails"], start=1)} or None,
        "phones": {f"p{index}": _phone(one) for index, one in enumerate(contact["phones"], start=1)} or None,
        "addresses": {f"a{index}": _address(one) for index, one in enumerate(contact["addresses"], start=1)} or None,
        "organizations": {"o1": _organization(contact)} if contact["company"] or contact["department"] else None,
        "titles": {"t1": {"@type": "Title", "kind": "title", "name": contact["job_title"]}} if contact["job_title"] else None,
        "anniversaries": {"b1": {"@type": "Anniversary", "kind": "birth", "date": _partial_date(contact["birthday"])}}
        if contact["birthday"] else None,
        "notes": {"n1": {"@type": "Note", "note": contact["notes"]}} if contact["notes"] else None,
        "media": {"m1": {"@type": "Media", "kind": "photo", "uri": contact["photo"]}} if contact["photo"] else None,
    }
    return card


def _organization(contact):
    made = {"@type": "Organization"}
    if contact["company"]:
        made["name"] = contact["company"]
    if contact["department"]:
        made["units"] = [{"@type": "OrgUnit", "name": contact["department"]}]
    return made


def _phone(one):
    made = {"@type": "Phone", "number": one["value"]}
    if one["type"] in ("mobile", "fax", "pager"):
        made["features"] = {one["type"]: True}
    elif _contexts(one["type"]):
        made["contexts"] = _contexts(one["type"])
    return made


def _address(one):
    parts = [{"kind": kind, "value": one[field]} for kind, field in (("name", "street"), ("locality", "city"), ("region", "state"),
                                                                     ("postcode", "postcode"), ("country", "country")) if one[field]]
    made = {"@type": "Address", "components": parts, "isOrdered": True}
    if _contexts(one["type"]):
        made["contexts"] = _contexts(one["type"])
    return made


def _partial_date(text):
    if text.startswith("--"):
        month, day = text[2:].split("-")
        return {"@type": "PartialDate", "month": int(month), "day": int(day)}
    day = datetime.date.fromisoformat(text)
    return {"@type": "PartialDate", "year": day.year, "month": day.month, "day": day.day}


# --- a contact, checked ---

def _text(value, field):
    text = " ".join(str(value or "").split())
    if len(text) > LONGEST[field]:
        raise ContactProblem(f"{field.replace('_', ' ').capitalize()} must be no more than {LONGEST[field]} characters.")
    return text


def check(data):
    """What the form sent, as a contact: ContactProblem when it can't be one."""
    contact = {field: _text(data.get(field), field) for field in ("display_name", "first_name", "last_name", "job_title",
                                                                    "company", "department")}
    if not contact["display_name"]:
        contact["display_name"] = " ".join(part for part in (contact["first_name"], contact["last_name"]) if part)
    if not contact["display_name"]:
        raise ContactProblem("Display name is required")
    emails, phones, addresses = [], [], []
    for one in (data.get("emails") or [])[:MOST_ITEMS]:
        value = str((one or {}).get("value") or "").strip()
        if not value:
            continue
        if len(value) > LONGEST["email"] or not ADDRESS.match(value):
            raise ContactProblem("Enter a valid email address")
        emails.append({"type": one.get("type") if one.get("type") in EMAIL_TYPES else "other", "value": value})
    for one in (data.get("phones") or [])[:MOST_ITEMS]:
        value = " ".join(str((one or {}).get("value") or "").split())
        if not value:
            continue
        if not PHONE.match(value) or not re.search(r"\d", value):
            raise ContactProblem("Enter a valid phone number")
        phones.append({"type": one.get("type") if one.get("type") in PHONE_TYPES else "other", "value": value})
    for one in (data.get("addresses") or [])[:MOST_ITEMS]:
        one = one or {}
        address = {field: _text(one.get(field), field) for field in ("street", "city", "state", "postcode", "country")}
        if not any(address.values()):
            continue
        address["type"] = one.get("type") if one.get("type") in ADDRESS_TYPES else "other"
        addresses.append(address)
    birthday = str(data.get("birthday") or "").strip()
    if birthday:
        try:
            _partial_date(birthday)
        except ValueError:
            raise ContactProblem("Enter a valid date")
    notes = str(data.get("notes") or "").strip()
    if len(notes) > LONGEST["notes"]:
        raise ContactProblem("The note must be no more than 5,000 characters.")
    photo = str(data.get("photo") or "")
    if photo and (not re.match(r"^data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$", photo) or len(photo) > BIGGEST_PHOTO):
        raise ContactProblem("This photo is too large to use, even after resizing. Please choose another one.")
    contact.update(emails=emails, phones=phones, addresses=addresses, birthday=birthday, notes=notes, photo=photo)
    return contact


# --- the address books ---

def books(mail):
    """The mailbox's address books, the default first: [{"id", "name", "default"}]. The engine's own
    first name for one ("Stalwart Address Book (…)") becomes PrivateEmail's "Personal"; none, and
    one is made."""
    found = mail.call(("AddressBook/get", {}), using=USING)[0]["list"]
    if not found:
        made = mail.call(("AddressBook/set", {"create": {"book": {"name": DEFAULT_BOOK, "isDefault": True}}}), using=USING)[0]
        created = (made.get("created") or {}).get("book")
        if not created:
            raise MailError(f"AddressBook/set: {(made.get('notCreated') or {}).get('book')}")
        found = [{"id": created["id"], "name": DEFAULT_BOOK, "isDefault": True}]
    renames = {book["id"]: {"name": DEFAULT_BOOK} for book in found if (book.get("name") or "").startswith("Stalwart Address Book")}
    if renames:
        mail.call(("AddressBook/set", {"update": renames}), using=USING)
        for book in found:
            if book["id"] in renames:
                book["name"] = DEFAULT_BOOK
    listed = [{"id": book["id"], "name": book.get("name") or DEFAULT_BOOK, "default": bool(book.get("isDefault"))} for book in found]
    return sorted(listed, key=lambda book: (not book["default"], book["name"].lower()))


# --- them all, by name ---

def _all_ids(mail, book_id=None):
    ids, position = [], 0
    while True:
        arguments = {"position": position, "limit": IN_ONE_QUERY, "calculateTotal": True}
        if book_id:
            arguments["filter"] = {"inAddressBook": book_id}
        found = mail.call(("ContactCard/query", arguments), using=USING)[0]
        ids += found["ids"]
        position += len(found["ids"])
        if not found["ids"] or position >= found.get("total", 0):
            return ids


def _get(mail, ids, properties):
    cards = []
    for start in range(0, len(ids), IN_ONE_GET):
        chunk = ids[start:start + IN_ONE_GET]
        cards += mail.call(("ContactCard/get", {"ids": chunk, "properties": properties + ["id"]}), using=USING)[0]["list"]
    return cards


def everyone(mail, book_id=None):
    """The contacts (without photos), by name."""
    if "contacts_all" not in g:
        g.contacts_all = {}
    if book_id not in g.contacts_all:
        people = [from_card(card) for card in _get(mail, _all_ids(mail, book_id), LIST_PROPERTIES)]
        people.sort(key=lambda person: (person["display_name"].casefold(), person["id"]))
        g.contacts_all[book_id] = people
    return g.contacts_all[book_id]


def _digits(text):
    return re.sub(r"\D", "", text)


def matches(person, typed):
    """Whether a contact is one of what's typed: its words in the name, an address, a phone
    number, the job."""
    words = typed.casefold().split()
    haystack = " ".join([person["display_name"], person["first_name"], person["last_name"], person["job_title"],
                         person["company"]] + [one["value"] for one in person["emails"]]).casefold()
    phones = " ".join(_digits(one["value"]) for one in person["phones"])
    return all(word in haystack or (_digits(word) and _digits(word) in phones) for word in words)


def addresses(mail):
    """Everyone's addresses, for the compose window's suggestions: [{"name", "email"}]."""
    return [{"name": person["display_name"], "email": one["value"]} for person in everyone(mail) for one in person["emails"]]


def _photos(mail, people):
    ids = [person["id"] for person in people]
    found = {card["id"]: from_card(card)["photo"] for card in _get(mail, ids, ["media"])} if ids else {}
    for person in people:
        person["photo"] = found.get(person["id"], "")
    return people


def initials(name):
    words = [word for word in re.split(r"[\s._-]+", name or "") if word]
    return ((words[0][:1] + (words[1][:1] if len(words) > 1 else "")) if words else "?").upper()


def page_of(mail, book_id, typed, page, size):
    """One page of the contacts: (people on it, how many in all, the page, the pages)."""
    people = [person for person in everyone(mail, book_id) if not typed or matches(person, typed)]
    pages = max(1, -(-len(people) // size))
    page = min(max(1, page), pages)
    shown = [dict(person) for person in people[(page - 1) * size:page * size]]
    return _photos(mail, shown), len(people), page, pages


# --- the pages ---

def _who():
    from .settings import _who as settings_who
    name = settings_who() or g.mailbox["email"].partition("@")[0]
    return name


def _size():
    """Items per page: as chosen (the page keeps it in a cookie)."""
    size = request.args.get("size", type=int) or request.cookies.get("wm_contacts_size", type=int)
    return size if size in PAGE_SIZES else PAGE_SIZE


@bp.get("")
@login_required
@reachable
def index():
    mail = _mail()
    address_books = books(mail)
    book = request.args.get("book") or ""
    book_id = book if any(one["id"] == book for one in address_books) else address_books[0]["id"]
    typed = request.args.get("q", "").strip()[:200]
    size = _size()
    people, total, page, pages = page_of(mail, book_id, typed, request.args.get("page", 1, type=int), size)
    for person in people:
        person["initials"] = initials(person["display_name"])
    name = _who()
    if _wants_json():
        return {"html": render_template("webmail-contacts-rows.html", people=people, type_labels=TYPE_LABELS),
                "total": total, "page": page, "pages": pages, "size": size}
    return render_template("webmail-contacts.html", email=g.mailbox["email"], name=name, initial=name[:1].upper(),
                           books=address_books, book=book_id, people=people, total=total, page=page, pages=pages,
                           size=size, sizes=PAGE_SIZES, query=typed, type_labels=TYPE_LABELS, email_types=EMAIL_TYPES,
                           phone_types=PHONE_TYPES, address_types=ADDRESS_TYPES)


def _wants_json():
    return request.accept_mimetypes.best == "application/json"


@bp.get("/<contact_id>")
@login_required
@reachable
def details(contact_id):
    found = _mail().call(("ContactCard/get", {"ids": [contact_id]}), using=USING)[0]["list"]
    if not found:
        return {"problem": "That contact isn't there any more."}, 404
    contact = from_card(found[0])
    contact["initials"] = initials(contact["display_name"])
    return {"contact": contact}


def _data():
    return request.get_json(silent=True) or {}


@bp.post("")
@login_required
@reachable
def create():
    try:
        contact = check(_data())
    except ContactProblem as problem:
        return {"problem": str(problem)}, 400
    mail = _mail()
    address_books = books(mail)
    wanted = _data().get("book")
    book_id = wanted if any(one["id"] == wanted for one in address_books) else address_books[0]["id"]
    card = {key: value for key, value in to_card(contact, book_id).items() if value is not None}
    made = mail.call(("ContactCard/set", {"create": {"contact": card}}), using=USING)[0]
    created = (made.get("created") or {}).get("contact")
    if not created:
        return {"problem": "Something went wrong. Please try again."}, 502
    return {"message": "Contact created", "id": created["id"]}


@bp.post("/<contact_id>")
@login_required
@reachable
def update(contact_id):
    try:
        contact = check(_data())
    except ContactProblem as problem:
        return {"problem": str(problem)}, 400
    mail = _mail()
    found = mail.call(("ContactCard/get", {"ids": [contact_id], "properties": ["addressBookIds"]}), using=USING)[0]["list"]
    if not found:
        return {"problem": "That contact isn't there any more."}, 404
    book_id = next(iter(found[0].get("addressBookIds") or {}), None) or books(mail)[0]["id"]
    card = to_card(contact, book_id)
    patch = {key: value for key, value in card.items() if key not in ("@type", "version", "kind", "addressBookIds")}
    done = mail.call(("ContactCard/set", {"update": {contact_id: patch}}), using=USING)[0]
    if contact_id not in (done.get("updated") or {}):
        return {"problem": "Something went wrong. Please try again."}, 502
    return {"message": "Contact updated"}


@bp.post("/delete")
@login_required
@reachable
def delete():
    """Contacts deleted: those ticked ({"ids"}), or every one found ({"all": true, "q", "book"})."""
    data = _data()
    mail = _mail()
    if data.get("all"):
        book = data.get("book") or None
        typed = str(data.get("q") or "").strip()
        ids = [person["id"] for person in everyone(mail, book) if not typed or matches(person, typed)]
    else:
        ids = [str(one) for one in data.get("ids") or [] if one]
    if not ids:
        return {"problem": "Choose a contact first."}, 400
    destroyed = []
    for start in range(0, len(ids), IN_ONE_GET):
        done = mail.call(("ContactCard/set", {"destroy": ids[start:start + IN_ONE_GET]}), using=USING)[0]
        destroyed += done.get("destroyed") or []
    if len(destroyed) < len(ids):
        return {"problem": "Some contacts could not be deleted" if len(ids) > 1 else "Contact could not be deleted",
                "deleted": len(destroyed)}, 502
    return {"message": "Contact deleted" if len(ids) == 1 else "Contacts deleted", "deleted": len(destroyed)}
