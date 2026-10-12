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


# --- a table written in the webmail is sent as it looked there (compose.clean_outgoing) ---

from someless.webmail.compose import clean_outgoing  # noqa: E402

LINE = "border:1px solid #c9ced8"


def test_a_table_written_is_sent_with_the_lines_it_was_written_with():
    written = ('<p>Our needs:</p><table><tbody><tr><th>Product</th><th>Size</th></tr>'
               "<tr><td>Frozen Whole Squid</td><td>100&ndash;300g</td></tr></tbody></table>")

    sent = clean_outgoing(written, [])

    assert 'style="border-collapse:collapse"' in sent.split("<tbody>")[0]
    cells = sent.count("<td") + sent.count("<th")
    assert cells == 4 and sent.count(LINE) == 4 and sent.count("padding:4px 8px") == 4
    assert "Frozen Whole Squid" in sent and "300g" in sent


def test_a_tables_own_lines_or_none_on_purpose_are_kept():
    own = '<table border="0"><tr><td>Layout</td></tr></table><table><tr><td style="border:2px solid red">Mine</td></tr></table>'

    sent = clean_outgoing(own, [])

    assert LINE not in sent.split("</table>")[0]   # (border="0": no lines, on purpose)
    assert "border:2px solid red" in sent and sent.count(LINE) == 0


def test_the_message_replied_to_is_sent_as_it_came():
    reply = ('<p>See below</p><blockquote class="wm-quote"><table><tr><td>Their table</td></tr></table>'
             "<blockquote><table><tr><td>Older</td></tr></table></blockquote></blockquote>"
             "<table><tr><td>After the quote</td></tr></table>")

    sent = clean_outgoing(reply, [])

    assert sent.count(LINE) == 1 and LINE in sent.split("After the quote")[0].rsplit("<table", 1)[1]


def test_a_cells_own_padding_stays():
    sent = clean_outgoing('<table><tr><td style="padding:10px">Wide</td></tr></table>', [])

    assert "padding:10px" in sent and "padding:4px 8px" not in sent and LINE in sent
