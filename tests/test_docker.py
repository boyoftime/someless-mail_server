from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE = ROOT / "docker-compose.yml"
ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"
README = ROOT / "README.md"


def test_gunicorn_uses_threads_so_idle_browser_connections_cant_stall_it():
    # Browsers open connections ahead of time and may leave them idle. A plain (sync)
    # worker waits on such a connection until it is killed for taking too long, and the
    # request caught in it gets gunicorn's bare "Internal Server Error" page.
    cmd = next(line for line in DOCKERFILE.read_text().splitlines() if line.startswith("CMD"))

    assert '"--worker-class", "gthread"' in cmd
    assert '"--threads"' in cmd


def test_data_is_kept_in_a_folder_next_to_docker_compose():
    compose = COMPOSE.read_text()

    assert "- ./data:/data" in compose
    assert "someless-data" not in compose  # no Docker volume hidden away in /var/lib/docker


def test_the_app_takes_over_the_data_folder_docker_makes():
    # Docker creates ./data owned by root, and the app runs as the someless user (2001).
    # The entrypoint hands the folder over first, then starts the server as that user.
    dockerfile = DOCKERFILE.read_text()
    script = ENTRYPOINT.read_text()

    assert 'ENTRYPOINT ["someless-entrypoint"]' in dockerfile
    assert "chown someless:someless" in script
    assert 'exec setpriv --reuid=2001 --regid=2001 --clear-groups "$@"' in script


def test_readme_shows_the_same_compose_file_and_where_the_data_is():
    readme = README.read_text(encoding="utf-8")

    assert COMPOSE.read_text().strip() in readme
    assert "data/someless/someless.db" in readme
