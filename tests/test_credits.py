"""Credits (pages.py): who made Someless Mail, the thanks, and where to donate. In the side menu,
and in the README too."""
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DONATE = "https://nowpayments.io/donation/someless"


def text(response):
    return html.unescape(response.get_data(as_text=True))


def test_credits_need_login(client):
    assert client.get("/credits").headers["Location"] == "/login"


def test_the_menu_ends_with_credits(client, login):
    login()

    page = text(client.get("/credits"))

    menu = page[page.index('<nav class="side-menu-nav" aria-label="Main">'):]
    menu = menu[:menu.index("</nav>")]
    labels = re.findall(r'<span class="side-menu-label">([^<]+)', menu)
    assert labels[-1] == "Credits"
    assert re.search(r'<a [^>]*href="/credits"[^>]*aria-current="page"', menu)


def test_the_page_thanks_the_makers_and_offers_a_donation(client, login):
    login()

    page = text(client.get("/credits"))

    assert "/static/img/credits/someless-tricks.webp" in page and "/static/img/credits/someless.webp" in page
    words = re.sub(r"<[^>]+>", "", page)
    assert "Someless Tricks" in words and "Stalwart" in words
    donate = re.search(rf'<a [^>]*href="{re.escape(DONATE)}"[^>]*>', page).group(0)
    assert 'target="_blank"' in donate and 'rel="noopener"' in donate


def test_the_credits_say_nothing_of_ai(client, login):
    login()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for words in (re.sub(r"<[^>]+>", "", text(client.get("/credits"))), readme[readme.index("## Credits"):]):
        assert not re.search(r"\bAI\b|artificial intelligence", words, re.I)


def test_the_pictures_are_there(app):
    static = Path(app.static_folder) / "img" / "credits"
    assert (static / "someless-tricks.webp").stat().st_size > 0
    assert (static / "someless.webp").stat().st_size > 0


def test_the_readme_has_the_credits_too():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    credits = readme[readme.index("## Credits"):]
    assert DONATE in credits and "Someless Tricks" in credits and "Stalwart" in credits
    for picture in re.findall(r'<img src="(docs/images/[^"]+)"', credits):
        assert (ROOT / picture).exists(), picture
    assert 'src="docs/images/someless-tricks.png"' in credits and 'src="docs/images/someless.png"' in credits
