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
    # The supervisor starts gunicorn, beside the mail engine (engine/supervisor.py).
    from someless.engine import supervisor
    command = " ".join(supervisor.GUNICORN)

    assert "--worker-class gthread" in command
    assert "--threads" in command


def test_the_container_runs_the_supervisor():
    cmd = next(line for line in DOCKERFILE.read_text().splitlines() if line.startswith("CMD"))

    assert cmd == 'CMD ["someless-run"]'
    assert "exec python -m someless.engine.supervisor" in (ROOT / "docker" / "someless-run").read_text()


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


def test_the_image_takes_the_mail_engine_version_from_one_place():
    version = (ROOT / "stalwart" / "VERSION").read_text().strip()
    workflow = (ROOT / ".github" / "workflows" / "docker.yml").read_text()

    assert f"ARG STALWART_IMAGE=ghcr.io/boyoftime/someless-stalwart:{version}" in DOCKERFILE.read_text()
    assert "STALWART_IMAGE=ghcr.io/boyoftime/someless-stalwart:${{ steps.version.outputs.stalwart }}" in workflow


def test_the_image_is_built_again_once_the_mail_engine_is():
    # On the first push both workflows start together, and the image needs the engine's
    # build, which takes far longer: the image waits for it instead of failing.
    workflow = (ROOT / ".github" / "workflows" / "docker.yml").read_text()

    assert 'workflows: ["Build Stalwart (open source)"]' in workflow
    assert "the mail engine isn't built yet" in workflow
