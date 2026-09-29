"""What a message says, made safe to show: the webmail puts it in a sandboxed frame where no
script runs and nothing loads from other sites but pictures (webmail-body.html), and before that
its HTML is cleaned here: only formatting stays (no scripts, forms, frames or redirects), links
lose their tracking codes (PrivateEmail's "Links cleaned from tracking", counted on the shield),
and pictures sent with the message (cid:) come from the webmail itself."""
import html
import re
import urllib.parse

import nh3

TAGS = {
    "a", "abbr", "address", "b", "bdi", "bdo", "big", "blockquote", "br", "caption", "center", "cite", "code", "col",
    "colgroup", "dd", "del", "details", "dfn", "div", "dl", "dt", "em", "figcaption", "figure", "font", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "i", "img", "ins", "kbd", "li", "mark", "ol", "p", "pre", "q", "s", "samp", "small", "span",
    "strike", "strong", "style", "sub", "summary", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "time", "tr",
    "tt", "u", "ul", "var", "wbr",
}
ATTRIBUTES = {
    "*": {"style", "class", "align", "valign", "width", "height", "bgcolor", "color", "dir", "lang", "title", "border",
          "background", "face", "size"},
    "a": {"href", "name", "target"},
    "img": {"src", "alt", "hspace", "vspace"},
    "table": {"cellpadding", "cellspacing", "frame", "rules", "summary"},
    "td": {"colspan", "rowspan", "nowrap", "abbr", "scope"},
    "th": {"colspan", "rowspan", "nowrap", "abbr", "scope"},
    "col": {"span"},
    "colgroup": {"span"},
    "ol": {"start", "type", "reversed"},
    "ul": {"type"},
    "li": {"value", "type"},
    "blockquote": {"cite"},
    "q": {"cite"},
    "time": {"datetime"},
    "details": {"open"},
}
LINK_SCHEMES = ("http:", "https:", "mailto:", "tel:")
# Query parameters that only follow the reader around (analytics and ad click ids): taken off links
TRACKING = {
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "yclid", "twclid", "ttclid", "li_fat_id", "igshid",
    "mc_cid", "mc_eid", "_hsenc", "_hsmi", "__hssc", "__hstc", "__hsfp", "hsctatracking", "mkt_tok", "vero_id",
    "vero_conv", "oly_anon_id", "oly_enc_id", "_openstat", "rb_clickid", "s_cid", "ncid", "sr_share", "trk", "trkcampaign",
    "ml_subscriber", "ml_subscriber_hash", "ck_subscriber_id", "wickedid", "srsltid", "ss_email_id", "ss_campaign_id",
}
URL = re.compile(r"""\bhttps?://[^\s<>"']+""", re.IGNORECASE)


def clean_link(url):
    """The address without its tracking codes (utm_*, fbclid...), and the codes taken off
    ("key=value"s: none when it had none)."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return url, []
    if parts.scheme.lower() not in ("http", "https") or not parts.query:
        return url, []
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    kept = [(key, value) for key, value in pairs if not (key.lower().startswith("utm_") or key.lower() in TRACKING)]
    if len(kept) == len(pairs):
        return url, []
    removed = [f"{key}={value}" for key, value in pairs if (key, value) not in kept]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(kept, doseq=True))), removed


class Shown:
    """What a message says, ready for its frame: its HTML, and the links cleaned of tracking
    (what each was, what it became and what came off it: the shield's "See details")."""
    def __init__(self):
        self.html = ""
        self.cleaned = []   # (was, now, [removed])


def from_html(source, picture_url=lambda cid: None):
    """The message's own HTML, cleaned. picture_url: where a picture sent with it (cid:) comes from."""
    shown = Shown()

    def attribute(tag, name, value):
        if name == "href" and tag == "a":
            value = value.strip()
            if value.startswith("#"):
                return value
            if not value.lower().startswith(LINK_SCHEMES):
                return None
            clean, removed = clean_link(value)
            if removed:
                shown.cleaned.append((value, clean, removed))
            return clean
        if name == "target":
            return "_blank"
        if name == "src" and tag == "img":
            value = value.strip()
            if value.lower().startswith("cid:"):
                return picture_url(urllib.parse.unquote(value[4:]).strip("<>"))
            if value.lower().startswith(("http:", "https:")) or re.match(r"data:image/(png|gif|jpe?g|webp|bmp);", value, re.I):
                return value
            return None
        if name == "background":   # a table's picture: from the web, or not at all
            return value if value.lower().startswith(("http:", "https:")) else None
        return value

    body = _body_of(source)
    shown.html = nh3.clean(body, tags=TAGS, clean_content_tags={"script", "noscript", "title"}, attributes=ATTRIBUTES,
                           attribute_filter=attribute, url_schemes={"http", "https", "mailto", "tel", "cid", "data"},
                           link_rel="noopener noreferrer", strip_comments=True)
    return shown


def from_text(text):
    """A message in plain text: its words as they are, its web addresses as links (cleaned)."""
    shown = Shown()
    out, last = [], 0
    for match in URL.finditer(text or ""):
        address = match.group(0).rstrip(".,;:!?)]}'\"")
        end = match.start() + len(address)
        out.append(html.escape(text[last:match.start()]))
        clean, removed = clean_link(address)
        if removed:
            shown.cleaned.append((address, clean, removed))
        out.append(f'<a href="{html.escape(clean)}" target="_blank" rel="noopener noreferrer">{html.escape(clean)}</a>')
        last = end
    out.append(html.escape((text or "")[last:]))
    shown.html = '<div class="is-text">' + "".join(out) + "</div>"
    return shown


def _body_of(source):
    """What's inside the <body> (with the <style>s of its <head>), since the frame has its own page."""
    head = re.split(r"<body\b", source, maxsplit=1, flags=re.I)
    head_styles = "".join(re.findall(r"<style\b[^>]*>.*?</style>", head[0], re.I | re.S)) if len(head) > 1 else ""
    match = re.search(r"<body\b[^>]*>(.*)</body>", source, re.I | re.S)
    if not match:
        match = re.search(r"<body\b[^>]*>(.*)", source, re.I | re.S)
    return head_styles + (match.group(1) if match else source)
