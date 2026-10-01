"""The server at a glance (server_stats.py), on the Dashboard's cake boards: the server's RAM and
disk, how much of its RAM Someless Mail takes, and whether it's healthy; refreshed while the page
is open (/dashboard/stats)."""
import html
import re

import pytest

from someless import server_stats
from someless.db import get_db

GB = 1024 ** 3
MB = 1024 ** 2

MEMINFO = """MemTotal:        8000000 kB
MemFree:          500000 kB
MemAvailable:    5000000 kB
Buffers:          100000 kB
"""


def text(response):
    return html.unescape(response.get_data(as_text=True))


def test_the_servers_ram_is_read_as_the_kernel_says_it():
    total, used = server_stats.parse_meminfo(MEMINFO)

    assert (total, used) == (8000000 * 1024, 3000000 * 1024)   # (used: what isn't available)


def test_the_apps_ram_is_its_container_s_without_cache_it_can_drop(tmp_path):
    (tmp_path / "memory.current").write_text("900000000\n")
    (tmp_path / "memory.stat").write_text("anon 500000000\ninactive_file 200000000\nactive_file 100\n")

    assert server_stats.cgroup_memory(tmp_path) == 700000000


def test_an_older_docker_s_cgroup_is_read_too(tmp_path):
    older = tmp_path / "memory"
    older.mkdir()
    (older / "memory.usage_in_bytes").write_text("600000000\n")
    (older / "memory.stat").write_text("cache 10\ntotal_inactive_file 100000000\n")

    assert server_stats.cgroup_memory(tmp_path) == 500000000
    assert server_stats.cgroup_memory(tmp_path / "nowhere") is None


def test_sizes_read_as_people_say_them():
    assert server_stats.size_text(3 * GB) == "3 GB"
    assert server_stats.size_text(int(7.82 * GB)) == "7.8 GB"
    assert server_stats.size_text(330 * MB) == "330 MB"


# --- health ------------------------------------------------------------------------------------------

def health(app):
    with app.app_context():
        return server_stats.health()


def test_without_a_mail_engine_here_it_says_so(app):
    assert health(app)["state"] == "off" and "No mail engine" in health(app)["title"]


def test_healthy_when_the_mail_engine_answers_and_is_in_line(app, engine):
    with app.app_context():
        from someless.engine import remember
        remember(setup_step="ready", sync_error=None)

    assert health(app) == {"state": "ok", "title": "Healthy", "detail": "Mail engine running, up to date."}


def test_it_says_when_the_engine_isnt_answering_starting_or_catching_up(app, engine):
    from someless.engine import remember
    with app.app_context():
        remember(setup_step="ready", sync_error="Stalwart refused a domain")
    assert health(app)["state"] == "warning" and "Stalwart refused a domain" in health(app)["detail"]

    engine.down = True
    assert health(app)["state"] == "down" and health(app)["title"] == "Mail engine not answering"

    engine.down = False
    with app.app_context():
        remember(setup_step="bootstrapped", sync_error=None)
    assert health(app)["state"] == "warning" and health(app)["title"] == "Starting up"


# --- on the Dashboard -----------------------------------------------------------------------------------

@pytest.fixture
def server(monkeypatch):
    """A made-up server: 8 GB of RAM (3 used), a 100 GB disk (40 used), the app taking 400 MB."""
    monkeypatch.setattr(server_stats, "memory", lambda: (8 * GB, 3 * GB))
    monkeypatch.setattr(server_stats, "disk", lambda: (100 * GB, 40 * GB))
    monkeypatch.setattr(server_stats, "app_memory", lambda: 400 * MB)


def boards(page):
    return re.findall(r'<(?:a|div) class="dash-board is-cake"[^>]*data-key="([a-z-]+)"[^>]*>(.*?)</(?:a|div)>\s*(?=<(?:a|div) class="dash-board|\s*</div>)',
                      page, re.S)


def test_the_dashboard_hangs_four_cake_boards_for_the_server(client, login, server):
    login()

    page = text(client.get("/dashboard"))

    cake = dict(boards(page))
    assert list(cake) == ["ram", "disk", "app-ram", "health"]
    words = {key: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip() for key, value in cake.items()}
    assert words["ram"] == "3 GB RAM used of 8 GB"
    assert words["disk"] == "40 GB Disk used of 100 GB"
    assert words["app-ram"] == "4.9% Someless Mail's RAM: 400 MB"
    assert words["health"].startswith("No mail engine here")
    assert 'style="--used: 37.5%"' in cake["ram"] and 'style="--used: 40.0%"' in cake["disk"]   # (their meters)


def test_a_figure_the_server_cant_tell_says_so(client, login, monkeypatch):
    monkeypatch.setattr(server_stats, "memory", lambda: None)
    monkeypatch.setattr(server_stats, "app_memory", lambda: None)
    login()

    words = re.sub(r"<[^>]+>", " ", text(client.get("/dashboard")))

    assert "Can't tell here" in words


def test_the_figures_refresh_while_the_page_is_open(client, login, server):
    assert client.get("/dashboard/stats").headers["Location"] == "/login"
    login()

    stats = client.get("/dashboard/stats").get_json()

    assert stats["ram"] == {"count": "3 GB", "label": "RAM used of 8 GB", "used": 37.5}
    assert stats["app-ram"]["count"] == "4.9%" and stats["health"]["state"] == "off"


def test_the_boards_are_made_of_cake(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)
    rule = re.search(r"\.dash-board\.is-cake \{[^}]*\}", css).group(0)
    assert 'url("../img/dash/cake-top.png")' in rule and 'url("../img/dash/cake-fill.png")' in rule
    for piece in ("top", "fill"):
        assert client.get(f"/static/img/dash/cake-{piece}.png").status_code == 200
