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


def test_the_mail_engine_is_built_from_our_own_copy_of_its_source():
    """Stalwart's source comes from boyoftime/stalwart, a fork of Stalwart's own with the same
    version tags, so it stays there as long as the image needs it (the AGPL asks for that): the
    build clones it, and the note in the image, and the README, say where it is."""
    build = (ROOT / "stalwart" / "Dockerfile").read_text()
    readme = README.read_text(encoding="utf-8")

    assert 'git clone --depth 1 --branch "${STALWART_VERSION}" https://github.com/boyoftime/stalwart /src' in build
    assert "built from https://github.com/boyoftime/stalwart/tree/%s (commit %s), a copy of https://github.com/stalwartlabs/stalwart" in build
    assert "[boyoftime/stalwart](https://github.com/boyoftime/stalwart)" in readme[readme.index("## Credits"):]


def test_the_image_is_built_again_once_the_mail_engine_is():
    # On the first push both workflows start together, and the image needs the engine's
    # build, which takes far longer: the image waits for it instead of failing.
    workflow = (ROOT / ".github" / "workflows" / "docker.yml").read_text()

    assert 'workflows: ["Build Stalwart (open source)"]' in workflow
    assert "the mail engine isn't built yet" in workflow


def test_mail_comes_in_and_mail_apps_and_the_webmail_are_published():
    compose = COMPOSE.read_text()

    for mapping in ('"25:25"', '"993:17993"', '"995:17995"', '"17090:17090"'):
        assert mapping in compose, mapping
    # the mail engine doesn't run as root, and receiving takes port 25 inside the container too
    assert "net.ipv4.ip_unprivileged_port_start=0" in compose
    expose = next(line for line in DOCKERFILE.read_text().splitlines() if line.startswith("EXPOSE"))
    assert set(expose.split()[1:]) >= {"17080", "17090", "25", "17587", "17465", "17993", "17995", "17081"}


def test_the_health_check_asks_the_panel_and_the_webmail():
    healthcheck = DOCKERFILE.read_text().split("HEALTHCHECK", 1)[1].split("\n\n", 1)[0]

    assert "17080/healthz" in healthcheck and "17090/healthz" in healthcheck


def test_readme_explains_receiving_mail_apps_and_the_webmail():
    readme = README.read_text(encoding="utf-8")

    for words in ("Mailboxes", "993", "995", "17090", "webmail.example.com", "sudo ufw allow 25/tcp"):
        assert words in readme, words
    assert "coming next" not in readme
    assert "net.ipv4.ip_unprivileged_port_start=0" in readme   # the docker run way too


def test_the_readme_has_one_compose_file_for_every_setup():
    """One file to copy, with or without Nginx Proxy Manager: its comments say what to change."""
    readme = README.read_text(encoding="utf-8")

    assert readme.count("services:\n") == 1 and "docker run -d" not in readme
    assert "docker network inspect nginx-proxy >/dev/null 2>&1 || docker network create nginx-proxy" in readme
    compose = COMPOSE.read_text()
    assert "nginx-proxy" in compose and '"17080:17080"' in compose and "put a # at the start" in compose


def test_the_smoke_test_waits_for_the_webmail_as_for_the_panel():
    """The webmail starts beside the panel, a moment after it: the smoke test waits for each before
    looking at it, or a slower start fails the build."""
    workflow = (ROOT / ".github" / "workflows" / "docker.yml").read_text()
    wait = "curl -fsS http://127.0.0.1:17090/healthz && break"
    assert wait in workflow
    assert workflow.index(wait) < workflow.index("curl -fsS http://127.0.0.1:17090/login")
