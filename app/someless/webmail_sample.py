"""Made-up mail for designing the webmail's inbox (webmail-mail.html), shown only where the
webmail runs with SOMELESS_WEBMAIL_PREVIEW=1, until it reads the real mail from the mail engine.
None of it is anyone's real mail: the addresses are at example.com, .org and .net, kept for
examples. There's enough of it to fill the list three times over, 50 at a time (webmail.py),
the newest first, each with what the reading pane shows: its sender's address, when it came,
what it says and its attachments."""
import datetime

# (key, label, icon): the folders every mailbox has in the mail engine
FOLDERS = [("inbox", "Inbox", "inbox"), ("drafts", "Drafts", "drafts"), ("sent", "Sent", "sent"),
           ("archive", "Archive", "archive"), ("spam", "Spam", "spam"), ("trash", "Trash", "trash")]
COUNTS = {"drafts": 2, "spam": 1}   # the inbox counts its unread mail
USED_SHARE = 0.138                  # how full the mailbox looks
TODAY = datetime.date(2026, 9, 28)  # the made-up mail's "today"

_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"]
_ADDRESSES = {"Someless Mail": "hello@someless.example", "Mail Delivery System": "mailer-daemon@mail.example.com",
              "Support Team": "support@example.com", "Newsletter": "news@example.org", "Billing": "billing@example.net"}


def _p(*paragraphs):
    return [("p", text) for text in paragraphs]


# Today's and the last few days' mail: (when, message)
_RECENT = [
    (datetime.datetime(2026, 9, 28, 18, 51), {
        "sender": "Someless Mail", "subject": "Welcome to your new mailbox", "unread": True,
        "preview": "Your mailbox is ready. Read, write and send your mail right here, or in any mail app.",
        "body": _p("Welcome to your new mailbox!",
                   "Your mailbox is ready. Read, write and send your mail right here, or in any mail app: Outlook, "
                   "Apple Mail, Thunderbird, or the one on your phone.")
        + [("ul", ["Your Inbox holds the mail sent to you.", "Sent keeps a copy of everything you send.",
                   "Spam catches mail that looks unwanted."])]
        + _p("Happy mailing,\nThe Someless Mail team")}),
    (datetime.datetime(2026, 9, 28, 16, 19), {
        "sender": "Amina Hassan", "subject": "Re: Partnership proposal", "unread": True,
        "preview": "Hi, thanks for the details. We've gone through the proposal and would like to meet next week.",
        "body": _p("Hi,",
                   "Thanks for the details. We've gone through the proposal and would like to meet next week to "
                   "talk about the next steps.",
                   "Before the meeting, could you confirm the following:")
        + [("ol", ["the expected start date;", "the budget for the first phase;",
                   "who will lead the project on your side."])]
        + _p("I've attached our notes, the updated budget and our logo for the slides.",
             "Kind regards,\nAmina Hassan"),
        "attachments": [("Partnership-notes.docx", "35.4 KB"), ("Budget-2027.xlsx", "48.2 KB"),
                        ("logo.png", "12.6 KB")]}),
    (datetime.datetime(2026, 9, 28, 13, 11), {
        "sender": "Mail Delivery System", "subject": "Undelivered Mail Returned to Sender",
        "preview": "This is the mail system at host mail.example.com. I'm sorry to have to inform you that your message",
        "body": _p("This is the mail system at host mail.example.com.",
                   "I'm sorry to have to inform you that your message could not be delivered to one or more "
                   "recipients.",
                   "<nobody@example.org>: host mx.example.org said: 550 5.1.1 The email account that you tried to "
                   "reach does not exist.")}),
    (datetime.datetime(2026, 9, 28, 13, 10), {
        "sender": "David Mwangi", "subject": "Invoice #1043 for September", "unread": True,
        "preview": "Please find the invoice for September attached. Payment is due within 14 days.",
        "body": _p("Hello,", "Please find the invoice for September attached. Payment is due within 14 days.")
        + [("ul", ["Invoice number: 1043", "Amount: TZS 2,450,000", "Due date: October 12, 2026"])]
        + _p("Thank you for your business.\nDavid Mwangi\nAccounts"),
        "attachments": [("Invoice-1043.pdf", "184.6 KB")]}),
    (datetime.datetime(2026, 9, 28, 12, 44), {
        "sender": "Grace Kimaro", "subject": "Team meeting moved to Thursday", "forwarded": True,
        "preview": "Quick heads-up: this week's meeting is on Thursday at 10:00 instead, same room.",
        "body": _p("Hi all,", "Quick heads-up: this week's meeting is on Thursday at 10:00 instead, same room.",
                   "The agenda stays the same. If you can't make it, let me know by Wednesday.", "Thanks,\nGrace")}),
    (datetime.datetime(2026, 9, 28, 12, 37), {
        "sender": "Support Team", "subject": "Your request #5821 is resolved",
        "preview": "We've closed your request. If anything else comes up, just reply to this message.",
        "body": _p("Hello,",
                   "We've closed your request #5821: the new mailboxes are ready, and the old addresses forward to "
                   "them.",
                   "If anything else comes up, just reply to this message.", "Best,\nThe Support Team")}),
    (datetime.datetime(2026, 9, 27, 17, 2), {
        "sender": "Neema Juma", "subject": "Photos from the launch",
        "preview": "Here are the photos from Friday's launch. The team did a great job, thank you all!",
        "body": _p("Hi everyone,", "Here are the photos from Friday's launch. The team did a great job, thank you all!",
                   "Feel free to use them on the website and in the newsletter.", "Neema"),
        "attachments": [("Launch-01.jpg", "1.2 MB"), ("Launch-02.jpg", "980 KB"), ("Launch-03.jpg", "1.1 MB")]}),
    (datetime.datetime(2026, 9, 26, 10, 15), {
        "sender": "Peter Otieno", "subject": "Quarterly report draft", "forwarded": True,
        "preview": "I've added the numbers for July and August. Could you look over the summary before Monday?",
        "body": _p("Hi,", "I've added the numbers for July and August. Could you look over the summary before Monday?",
                   "Two things I'm not sure about:")
        + [("ul", ["whether to show the figures per month or per quarter;",
                   "if the chart on page 3 needs last year's numbers too."])]
        + _p("Thanks,\nPeter")}),
    (datetime.datetime(2026, 9, 25, 8, 30), {
        "sender": "Newsletter", "subject": "This week in email: keeping your domain trusted",
        "preview": "Five simple habits that keep your mail out of spam folders, and your domain's reputation high.",
        "body": _p("Five simple habits that keep your mail out of spam folders, and your domain's reputation high:")
        + [("ol", ["Send from an authenticated domain.", "Only send to people who asked for your mail.",
                   "Remove addresses that bounce.", "Make it easy to unsubscribe.",
                   "Grow the amount you send slowly."])]
        + _p("See you next week!")}),
]

# The older mail, made from these, a message or two a day going back
_SENDERS = ["Amina Hassan", "David Mwangi", "Grace Kimaro", "Neema Juma", "Peter Otieno", "Support Team",
            "Joseph Ndege", "Fatma Ali", "Billing", "Samuel Kariuki", "Lucy Wanjiru", "Newsletter", "Hassan Omari"]
_TOPICS = [
    ("Monthly statement is ready", "Your statement for the month is ready to view. Nothing needs doing on your side."),
    ("Re: Delivery schedule", "The next delivery leaves the warehouse on Tuesday morning, as planned."),
    ("Welcome aboard, new team member", "Please join us in welcoming our newest colleague to the team this week."),
    ("Contract renewal reminder", "Your contract comes up for renewal next month. Let us know if anything should change."),
    ("Re: Website update", "The new pages are live. Could you check the contact form works from your side too?"),
    ("Payment received, thank you", "We've received your payment. A receipt is attached for your records."),
    ("Workshop slides", "As promised, here are the slides from yesterday's workshop, with the extra examples."),
    ("Re: Office move", "The movers arrive at 8:00 on Saturday. Please pack your desk by Friday afternoon."),
    ("Your weekly summary", "You sent 42 messages and received 118 this week. Your busiest day was Wednesday."),
    ("Re: Price list for next year", "Thanks for sending it over. Two of the items look higher than we expected."),
    ("Training day on Friday", "Friday's training starts at 9:30 in the main room. Lunch is provided."),
    ("Re: Logo options", "We like the second option best. Could you try it in a darker blue?"),
    ("Holiday opening hours", "Over the holidays the office opens from 9:00 to 13:00, and closes on public holidays."),
    ("Re: Supplier meeting notes", "Here are my notes from the meeting. The main points are at the top."),
    ("New login to your account", "Your account was just signed in to from a new device. If this was you, all is well."),
]
_FOLLOW_UPS = ["Let me know if you have any questions.", "Thanks for your help with this.",
               "Talk soon, and have a good week.", "Happy to go through it on a call if that's easier."]
_FILES = [("Statement.pdf", "212 KB"), ("Slides.pptx", "1.4 MB"), ("Photo.jpg", "860 KB"), ("Notes.docx", "28.9 KB"),
          ("Receipt.pdf", "96.3 KB")]


def _older(count=126, newest=datetime.date(2026, 9, 24)):
    mail = []
    for number in range(count):
        subject, preview = _TOPICS[(number * 7) % len(_TOPICS)]
        sender = _SENDERS[number % len(_SENDERS)]
        day = newest - datetime.timedelta(days=number * 3 // 4)
        minutes = 8 * 60 + (number * 97) % (10 * 60)
        when = datetime.datetime(day.year, day.month, day.day, minutes // 60, minutes % 60)
        mail.append((when, {
            "sender": sender, "subject": subject, "preview": preview, "unread": number % 17 == 3,
            "forwarded": number % 11 == 6,
            "body": _p("Hi,", preview, _FOLLOW_UPS[number % len(_FOLLOW_UPS)], f"Best regards,\n{sender}"),
            "attachments": [_FILES[number % len(_FILES)]] if number % 5 == 2 else []}))
    return mail


def _address(sender):
    return _ADDRESSES.get(sender) or sender.lower().replace(" ", ".") + "@example.com"


def _list_time(when):
    """As the list shows it: the time today, Yesterday, then the day."""
    if when.date() == TODAY:
        return f"{(when.hour - 1) % 12 + 1:02d}:{when.minute:02d} {'PM' if when.hour >= 12 else 'AM'}"
    if when.date() == TODAY - datetime.timedelta(days=1):
        return "Yesterday"
    return f"{_MONTHS[when.month - 1][:3]} {when.day}"


def _full_time(when):
    """As the reading pane shows it: September 18, 5:34 PM."""
    return (f"{_MONTHS[when.month - 1]} {when.day}, {(when.hour - 1) % 12 + 1}:{when.minute:02d} "
            f"{'PM' if when.hour >= 12 else 'AM'}")


def _file(name, size):
    base, dot, extension = name.rpartition(".")
    return {"name": name, "base": base if dot else name, "extension": dot + extension if dot else "", "size": size}


# The whole inbox, newest first, each message with its id (as the mail engine gives them: text)
MESSAGES = [{"id": str(number), "unread": False, "forwarded": False, **message,
             "address": _address(message["sender"]), "time": _list_time(when), "date": _full_time(when),
             "attachments": [_file(*attachment) for attachment in message.get("attachments", [])],
             "attachment": bool(message.get("attachments"))}
            for number, (when, message) in enumerate(sorted(_RECENT + _older(), key=lambda mail: mail[0], reverse=True),
                                                     start=1)]
BY_ID = {message["id"]: message for message in MESSAGES}
