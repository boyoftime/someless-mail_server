"""flask engine status: how far the mail engine's first-time setup got, and its last sync.
The image's smoke test runs it; so can an admin, with docker exec."""
import datetime

import click
from flask.cli import AppGroup

from . import state

cli = AppGroup("engine", help="The mail engine (Stalwart).")


@cli.command("status")
def status():
    """Exits 1 unless the engine is set up and running normally."""
    row = state()
    click.echo(f"setup: {row['setup_step']}")
    synced = datetime.datetime.fromtimestamp(row["synced_at"]).isoformat(" ", "seconds") if row["synced_at"] else "never"
    click.echo(f"synced: {synced}")
    if row["sync_error"]:
        click.echo(f"sync error: {row['sync_error']}")
    raise SystemExit(0 if row["setup_step"] == "ready" else 1)
