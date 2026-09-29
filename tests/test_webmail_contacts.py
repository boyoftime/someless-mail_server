"""Contacts in the webmail (webmail/contacts.py), as PrivateEmail's address book: the list by name,
a page at a time, found as it's searched; a contact made, changed and deleted as a JSContact card
in the engine (RFC 9553); the compose window's suggestions from them. The engine is the made-up
one (jmap_fake.py)."""
import pytest

from someless import mail_password
from someless.webmail import contacts, create_webmail_app
from jmap_fake import FakeJmap
from test_engine_sync import a_mailbox, a_sender, authenticated_domain

PASSWORD = "Mailbox-Pass-1!"


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
    return client


def person(**extra):
    return {"display_name": "Amina Hassan", "first_name": "Amina", "last_name": "Hassan",
            "emails": [{"type": "work", "value": "amina@elsewhere.example"}, {"type": "home", "value": "amina@home.example"}],
            "phones": [{"type": "mobile", "value": "+254 700 000 001"}, {"type": "fax", "value": "+254 20 000 003"}],
            "addresses": [{"type": "work", "street": "Kenyatta Avenue 12", "city": "Nairobi", "state": "", "postcode": "00100",
                           "country": "Kenya"}],
            "job_title": "Head of Sales", "company": "Elsewhere Ltd", "department": "Sales", "birthday": "1990-05-03",
            "notes": "Met at the expo.", "photo": "", **extra}


def listed(mail, **query):
    return mail.get("/contacts", query_string=query, headers={"Accept": "application/json"}).get_json()


# --- the page ---

def test_no_contacts_yet(mail):
    page = mail.get("/contacts").get_data(as_text=True)

    assert "No contacts yet" in page and "Add a contact to view it here." in page
    assert 'placeholder="Search contacts"' in page and "Contact Books" in page


def test_the_engines_first_address_book_is_called_personal(mail, jmap):
    page = mail.get("/contacts").get_data(as_text=True)

    assert jmap.address_books["ab0"]["name"] == "Personal" and ">Personal</span>" in page


def test_an_address_book_is_made_when_there_is_none(mail, jmap):
    jmap.address_books.clear()

    mail.get("/contacts")

    assert [book["name"] for book in jmap.address_books.values()] == ["Personal"]


# --- a contact made ---

def test_a_contact_is_made_as_a_jscontact_card(mail, jmap):
    answer = mail.post("/contacts", json=person())

    assert answer.status_code == 200 and answer.get_json()["message"] == "Contact created"
    card = jmap.cards[answer.get_json()["id"]]
    assert card["name"]["full"] == "Amina Hassan"
    assert card["name"]["components"] == [{"kind": "given", "value": "Amina"}, {"kind": "surname", "value": "Hassan"}]
    assert card["emails"]["e1"] == {"@type": "EmailAddress", "address": "amina@elsewhere.example", "contexts": {"work": True}}
    assert card["emails"]["e2"]["contexts"] == {"private": True}
    assert card["phones"]["p1"]["features"] == {"mobile": True} and card["phones"]["p2"]["features"] == {"fax": True}
    assert {part["kind"]: part["value"] for part in card["addresses"]["a1"]["components"]} == {
        "name": "Kenyatta Avenue 12", "locality": "Nairobi", "postcode": "00100", "country": "Kenya"}
    assert card["organizations"]["o1"] == {"@type": "Organization", "name": "Elsewhere Ltd", "units": [{"@type": "OrgUnit", "name": "Sales"}]}
    assert card["titles"]["t1"]["name"] == "Head of Sales"
    assert card["anniversaries"]["b1"]["date"] == {"@type": "PartialDate", "year": 1990, "month": 5, "day": 3}
    assert card["notes"]["n1"]["note"] == "Met at the expo." and "media" not in card
    assert card["addressBookIds"] == {"ab0": True}


def test_a_contact_comes_back_as_it_was_made(mail):
    made = mail.post("/contacts", json=person()).get_json()["id"]

    contact = mail.get(f"/contacts/{made}").get_json()["contact"]

    for field, value in person().items():
        assert contact[field] == value, field
    assert contact["initials"] == "AH"


def test_the_display_name_comes_from_the_first_and_last_name(mail, jmap):
    made = mail.post("/contacts", json={"first_name": " Brian ", "last_name": "Kamau"}).get_json()["id"]

    assert jmap.cards[made]["name"]["full"] == "Brian Kamau"


@pytest.mark.parametrize("change, problem", [
    ({"display_name": "", "first_name": "", "last_name": ""}, "Display name is required"),
    ({"emails": [{"type": "work", "value": "amina-at-elsewhere"}]}, "Enter a valid email address"),
    ({"phones": [{"type": "mobile", "value": "call me"}]}, "Enter a valid phone number"),
    ({"birthday": "1990-13-45"}, "Enter a valid date"),
    ({"notes": "n" * 5001}, "The note must be no more than 5,000 characters."),
    ({"photo": "data:text/html;base64,PGgxPg=="}, "This photo is too large to use, even after resizing. Please choose another one."),
    ({"photo": "data:image/jpeg;base64," + "A" * 300_000}, "This photo is too large to use, even after resizing. Please choose another one."),
    ({"company": "C" * 256}, "Company must be no more than 255 characters."),
])
def test_a_contact_is_checked(mail, change, problem):
    answer = mail.post("/contacts", json=person(**change))

    assert answer.status_code == 400 and answer.get_json()["problem"] == problem


def test_empty_rows_of_the_form_are_left_out(mail, jmap):
    made = mail.post("/contacts", json=person(emails=[{"type": "work", "value": " "}], phones=[], addresses=[{"street": ""}])).get_json()["id"]

    card = jmap.cards[made]
    assert "emails" not in card and "phones" not in card and "addresses" not in card


def test_a_photo_is_kept(mail, jmap):
    photo = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="

    made = mail.post("/contacts", json=person(photo=photo)).get_json()["id"]

    assert jmap.cards[made]["media"]["m1"] == {"@type": "Media", "kind": "photo", "uri": photo}
    assert mail.get(f"/contacts/{made}").get_json()["contact"]["photo"] == photo


# --- a contact changed or deleted ---

def test_a_change_writes_every_part_again(mail, jmap):
    made = mail.post("/contacts", json=person()).get_json()["id"]

    answer = mail.post(f"/contacts/{made}", json={"display_name": "Amina H.", "emails": [{"type": "other", "value": "a@elsewhere.example"}]})

    assert answer.get_json()["message"] == "Contact updated"
    card = jmap.cards[made]
    assert card["name"]["full"] == "Amina H." and card["emails"] == {"e1": {"@type": "EmailAddress", "address": "a@elsewhere.example"}}
    for gone in ("phones", "addresses", "organizations", "titles", "anniversaries", "notes"):
        assert gone not in card, gone
    assert card["addressBookIds"] == {"ab0": True}


def test_a_contact_that_is_gone(mail):
    assert mail.post("/contacts/nope", json=person()).status_code == 404
    assert mail.get("/contacts/nope").status_code == 404


def test_contacts_are_deleted(mail, jmap):
    first = mail.post("/contacts", json=person()).get_json()["id"]
    second = mail.post("/contacts", json=person(display_name="Brian Kamau")).get_json()["id"]

    one = mail.post("/contacts/delete", json={"ids": [first]}).get_json()
    assert one == {"message": "Contact deleted", "deleted": 1} and list(jmap.cards) == [second]
    assert mail.post("/contacts/delete", json={"ids": []}).status_code == 400


def test_every_contact_found_is_deleted_across_the_pages(mail, jmap):
    for number in range(30):
        mail.post("/contacts", json=person(display_name=f"Bulk {number:02d}", emails=[]))
    kept = mail.post("/contacts", json=person(display_name="Keeper")).get_json()["id"]

    answer = mail.post("/contacts/delete", json={"all": True, "q": "bulk", "book": "ab0"})

    assert answer.get_json() == {"message": "Contacts deleted", "deleted": 30}
    assert list(jmap.cards) == [kept]


# --- the list ---

def test_the_list_is_by_name_whatever_the_case(mail, jmap):
    for name in ("zawadi Ochieng", "Amina Hassan", "brian Kamau"):
        jmap.add_card(name={"full": name})

    page = listed(mail)

    assert page["total"] == 3
    names = [line.strip() for line in page["html"].split('class="wm-contact-name">')[1:]]
    assert [name.split("<")[0] for name in names] == ["Amina Hassan", "brian Kamau", "zawadi Ochieng"]


@pytest.mark.parametrize("typed, found", [
    ("ami", ["Amina Hassan"]), ("hassan amina", ["Amina Hassan"]), ("logistics", ["Brian Kamau"]),
    ("722111", ["Brian Kamau"]), ("sales", ["Amina Hassan"]), ("nobody", []),
])
def test_contacts_are_found_as_they_are_typed(mail, jmap, typed, found):
    jmap.add_card(name={"full": "Amina Hassan"}, titles={"t1": {"name": "Head of Sales"}})
    jmap.add_card(name={"full": "Brian Kamau"}, emails={"e1": {"address": "brian@logistics.example"}},
                  phones={"p1": {"number": "+254 722 111 222"}})

    page = listed(mail, q=typed)

    assert [line.split("<")[0] for line in page["html"].split('class="wm-contact-name">')[1:]] == found
    assert page["total"] == len(found)


def test_the_list_comes_a_page_at_a_time(mail, jmap):
    for number in range(27):
        jmap.add_card(name={"full": f"Person {number:02d}"})

    first = listed(mail, size=10)
    last = listed(mail, size=10, page=9)

    assert (first["total"], first["page"], first["pages"], first["size"]) == (27, 1, 3, 10)
    assert first["html"].count('class="wm-contact"') == 10
    assert (last["page"], last["html"].count('class="wm-contact"')) == (3, 7)   # (past the end: the last page)
    assert listed(mail, size=7)["size"] == 25   # (only 10, 25, 50 or 100)
    mail.set_cookie("wm_contacts_size", "50")
    assert listed(mail)["size"] == 50


def test_a_contact_from_elsewhere_is_shown_as_well_as_it_can_be(mail, jmap):
    """A card made by a phone (CardDAV): no full name, an address as one line, a birthday without a year."""
    card_id = jmap.add_card(name={"components": [{"kind": "given", "value": "Lucy"}, {"kind": "surname", "value": "Achieng"}]},
                            addresses={"a": {"full": "12 School Lane, Kisumu"}},
                            anniversaries={"b": {"kind": "birth", "date": {"@type": "PartialDate", "month": 5, "day": 3}}},
                            media={"m": {"kind": "photo", "uri": "https://tracker.example/pixel.png"}})

    contact = mail.get(f"/contacts/{card_id}").get_json()["contact"]

    assert contact["display_name"] == "Lucy Achieng"
    assert contact["addresses"][0]["street"] == "12 School Lane, Kisumu"
    assert contact["birthday"] == "--05-03"
    assert contact["photo"] == ""   # (a picture from elsewhere isn't fetched: it could tell them it was seen)


def test_a_birthday_without_a_year_is_kept_so(mail, jmap):
    made = mail.post("/contacts", json=person(birthday="--05-03")).get_json()["id"]

    assert jmap.cards[made]["anniversaries"]["b1"]["date"] == {"@type": "PartialDate", "month": 5, "day": 3}


# --- the compose window's suggestions ---

def test_contacts_are_suggested_when_writing(mail, jmap):
    jmap.add_card(name={"full": "Grace Wanjiru"}, emails={"e1": {"address": "grace@studio.example"}})

    people = mail.get("/compose/suggest", query_string={"q": "gra"}).get_json()["people"]

    assert {"name": "Grace Wanjiru", "email": "grace@studio.example"} in people


def test_initials():
    assert contacts.initials("amina hassan") == "AH"
    assert contacts.initials("grace") == "G"
    assert contacts.initials("") == "?"
