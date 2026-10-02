"""The README (GitHub's front page for Someless Mail): describes the finished mail server as it is,
and every link within it leads to a heading of its own."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def slug(heading):
    """A heading's anchor, as GitHub makes it."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def test_every_link_within_the_readme_leads_to_a_heading():
    anchors = {slug(heading) for heading in re.findall(r"^#{1,6} (.+)$", README, re.M)}

    links = set(re.findall(r"\]\(#([^)]+)\)", README))

    assert links and links <= anchors, sorted(links - anchors)


def test_every_picture_it_shows_is_there():
    pictures = re.findall(r'(?:src|srcset)="(docs/images/[^"]+)"', README)

    assert pictures
    for picture in pictures:
        assert (ROOT / picture).is_file(), picture


def test_it_shows_the_interface():
    """A look inside: the Dashboard in the reader's own GitHub theme (dark or light), then the
    other pages, each with a few words, and the API guide."""
    inside = README[README.index("## A look inside"):]
    inside = inside[:inside.index("\n## ", 1)]
    assert re.search(r'<source media="\(prefers-color-scheme: dark\)" srcset="docs/images/screens/dashboard-dark\.png">\s*'
                     r'<img src="docs/images/screens/dashboard-light\.png" alt="[^"]+"', inside)
    assert re.search(r'<source media="\(prefers-color-scheme: light\)" srcset="docs/images/screens/settings-account-light\.png">\s*'
                     r'<img src="docs/images/screens/settings-account\.png" alt="[^"]+"', inside)
    for screen in ("welcome", "login", "domains", "smtp-ready", "smtp-examples", "senders", "mailboxes",
                   "api-keys", "api-docs", "settings-misc"):
        assert re.search(rf'<img src="docs/images/screens/{screen}\.png" alt="[^"]+"', inside), screen
    assert README.index("## A look inside") < README.index("## How it fits together")


def test_it_says_who_makes_it_and_that_it_is_free():
    """Right at the top, before the first heading: free and open source, by Someless Ado, under the
    GNU AGPL-3.0."""
    top = README[:README.index("\n## ")]
    assert "free and open-source project by **Someless Ado**" in top
    assert re.search(r'<p align="center">.*Free and open source.*Someless Ado.*<a href="LICENSE">GNU AGPL-3\.0</a>.*</p>', top)


def test_the_licence_is_the_agpl_3_0():
    """LICENSE is the licence's own text, word for word (so GitHub recognises it); the copyright and
    what the licence asks of a changed copy are in the README's Licence section."""
    licence = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert licence.split("\n")[:2] == ["                    GNU AFFERO GENERAL PUBLIC LICENSE",
                                       "                       Version 3, 19 November 2007"]
    assert "13. Remote Network Interaction; Use with the GNU General Public License." in licence
    assert licence.rstrip().endswith("<https://www.gnu.org/licenses/>.")
    assert "MIT" not in README[README.index("## Licence"):]
    section = README[README.index("## Licence"):]
    for words in ("[GNU Affero General Public License, version 3](LICENSE)", "Copyright © 2026 Someless Ado",
                  "Stalwart"):
        assert words in section, words


def test_it_tells_of_the_finished_server_and_its_api():
    assert "coming too" not in README and "Coming soon" not in README
    status = re.search(r"^> \*\*Status:\*\*(.+)$", README, re.M).group(1)
    for part in ("webmail", "API", "Dashboard"):
        assert part in status, part
    assert "## The API: domains, senders and mailboxes from your apps" in README
