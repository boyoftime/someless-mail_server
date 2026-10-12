"""A message's HTML as the reading pane shows it (webmail/content.py): what's inside its <body>, and
whatever a careless mail program put outside it, as a browser (and a phone's mail app) shows it."""
from someless.webmail import content

# As 163.com's mail sends a reply: the new words before <html>, the message replied to in <body>
REPLY_BEFORE_THE_PAGE = (
    "Dear Lazarus:<br/>Indian squid whole round, seafrozen.<br/>Yosha<br/><br/>"
    '<img style="width:1px;height:1px" src="https://count.mail.163.com/beacon/webmail.gif?guid=1">'
    "<html>\n<head>\n<meta http-equiv=\"Content-Type\" content=\"text/html; charset=UTF-8\">\n</head>\n<body>\n"
    '<div class="ntes-mailmaster-quote"><div>---- Replied Message ----</div><p>Dear Yosha:</p></div>\n'
    "</body>\n</html>"
)


def test_words_written_before_the_page_are_shown_first():
    shown = content.from_html(REPLY_BEFORE_THE_PAGE).html

    assert "Dear Lazarus:" in shown and "Indian squid whole round" in shown
    assert shown.index("Dear Lazarus:") < shown.index("---- Replied Message ----") < shown.index("Dear Yosha:")
    assert "<html" not in shown and "<head" not in shown and "<meta" not in shown


def test_words_after_the_page_are_shown_too():
    shown = content.from_html("<html><body><p>Hello</p></body></html>\n<p>Sent from my phone</p>").html

    assert shown.index("Hello") < shown.index("Sent from my phone")


def test_a_proper_page_shows_its_body_as_before():
    page = "<html><head><style>p{color:red}</style><title>x</title></head><body><p>Hello</p></body></html>"

    shown = content.from_html(page).html

    assert "<p>Hello</p>" in shown and "p{color:red}" in shown and ">x<" not in shown
