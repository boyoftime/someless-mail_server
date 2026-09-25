from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parent.parent / "Dockerfile"


def test_gunicorn_uses_threads_so_idle_browser_connections_cant_stall_it():
    # Browsers open connections ahead of time and may leave them idle. A plain (sync)
    # worker waits on such a connection until it is killed for taking too long, and the
    # request caught in it gets gunicorn's bare "Internal Server Error" page.
    cmd = next(line for line in DOCKERFILE.read_text().splitlines() if line.startswith("CMD"))

    assert '"--worker-class", "gthread"' in cmd
    assert '"--threads"' in cmd
