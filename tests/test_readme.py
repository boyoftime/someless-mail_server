"""The README (GitHub's front page for Someless Mail): describes the finished mail server as it is,
and every link within it leads to a heading of its own."""
import re
from pathlib import Path

README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")


def slug(heading):
    """A heading's anchor, as GitHub makes it."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def test_every_link_within_the_readme_leads_to_a_heading():
    anchors = {slug(heading) for heading in re.findall(r"^#{1,6} (.+)$", README, re.M)}

    links = set(re.findall(r"\]\(#([^)]+)\)", README))

    assert links and links <= anchors, sorted(links - anchors)


def test_it_tells_of_the_finished_server_and_its_api():
    assert "coming too" not in README and "Coming soon" not in README
    status = re.search(r"^> \*\*Status:\*\*(.+)$", README, re.M).group(1)
    for part in ("webmail", "API", "Dashboard"):
        assert part in status, part
    assert "## The API: domains, senders and mailboxes from your apps" in README
