"""The relay's front page (http://mail.example.com/, engine/relay_page.py): whoever opens the mail
server's name sees the proxy host works, "It's all done!" in blocks of the Dashboard's grass, with
Someless Mail as a watermark. Every other address still says whose it is, in a line, for the
proxy host check (checks.relay_answers)."""
import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from someless.engine import checks, relay_page, supervisor


def never(path):
    raise AssertionError(f"asked Stalwart for {path}")


@pytest.fixture
def relay():
    server = ThreadingHTTPServer(("127.0.0.1", 0), supervisor._Relay)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.mark.parametrize("path", ["/", "/?from=browser"])
def test_the_front_page_says_its_all_done(path):
    status, kind, body = supervisor.relay_reply(path, never)

    assert status == 200 and kind == "text/html; charset=utf-8"
    page = body.decode()
    assert "<title>It's all done | Someless Mail</title>" in page
    assert re.search(r'<h1[^>]*>.*It&#39;s all done!.*</h1>', page, re.S) or re.search(r"<h1[^>]*>.*It's all done!.*</h1>", page, re.S)
    assert "Your proxy host works." in page
    assert 'class="watermark" aria-hidden="true">Someless Mail<' in page


def test_the_words_are_built_of_grass_blocks():
    """Each letter a little island: grass on top, earth under it, a rough edge at the bottom."""
    page = relay_page.page().decode()

    blocks = re.findall(r'<i class="(top|fill|bottom)"></i>', page)
    assert len(blocks) > 60 and {"top", "fill", "bottom"} <= set(blocks)
    assert page.count('class="letter') == len("ITSALLDONE") + 2   # and the ' and the !
    for tile in ("top", "fill", "bottom"):
        assert re.search(rf"\.{tile} \{{ background-image: url\(data:image/png;base64,[A-Za-z0-9+/=]+\)", page), tile


def test_a_letters_blocks_follow_its_shape():
    """The T: a bar of grass on top, then the stem's earth, its last block rough at the bottom."""
    assert relay_page.blocks("T") == [["top", "top", "top"],
                                      [None, "fill", None],
                                      [None, "fill", None],
                                      [None, "fill", None],
                                      [None, "bottom", None]]


def test_the_page_needs_nothing_from_elsewhere():
    """Anyone can open it, so it loads nothing and runs nothing: its pictures are in the page."""
    page = relay_page.page().decode()

    assert not re.search(r'(?:src|href)="(?!#)', page)
    assert "<script" not in page and "url(http" not in page and "@import" not in page


def test_it_is_served_as_a_page_that_can_do_nothing(relay):
    with urllib.request.urlopen(relay + "/", timeout=5) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "text/html; charset=utf-8"
        policy = response.headers["Content-Security-Policy"]
        assert "default-src 'none'" in policy and "img-src data:" in policy and "frame-ancestors 'none'" in policy
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert b"It's all done" in response.read()


@pytest.mark.parametrize("path", ["/login", "/favicon.ico", "/.well-known/acme-challenge/someless-check"])
def test_every_other_address_still_says_whose_it_is_in_a_line(path):
    assert supervisor.relay_reply(path, lambda path: (404, b"")) == (404, "text/plain", supervisor.NOT_HERE)


def test_a_real_challenge_is_answered_as_before():
    reply = supervisor.relay_reply("/.well-known/acme-challenge/abc", lambda path: (200, b"token.thumbprint"))

    assert reply == (200, "text/plain", b"token.thumbprint")


def test_the_readme_says_how_to_see_it_works():
    """Step 5 shows the page (in the reader's own GitHub theme), and Troubleshooting sends there too."""
    from pathlib import Path
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    step = readme[readme.index("## Step 5"):readme.index("## Step 6")]
    trouble = readme[readme.index("- **The certificate doesn't arrive.**"):]
    trouble = trouble[:trouble.index("\n")]

    assert "open `http://mail.example.com`" in step and "**It's all done!**" in step
    assert re.search(r'<source media="\(prefers-color-scheme: dark\)" srcset="docs/images/screens/proxy-works-dark\.png">\s*'
                     r'<img src="docs/images/screens/proxy-works-light\.png" alt="[^"]+"', step)
    assert "and nothing else" not in step   # (it has a front page now)
    assert "*It's all done!*" in trouble


def test_the_proxy_host_check_still_finds_the_relay(relay):
    assert checks.relay_answers(relay + "/.well-known/acme-challenge/someless-check")
