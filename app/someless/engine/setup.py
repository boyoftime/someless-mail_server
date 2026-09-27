"""First-time setup of Stalwart, done by the supervisor before the panel starts: it happens
once, and picks up where it left off if interrupted (the engine table's setup_step).
new -> bootstrap mode: Bootstrap/set writes config.json and makes the admin account
bootstrapped -> recovery mode: our listeners
provisioned -> a normal start
Every start also adds any listener an older install lacks, and starts Stalwart again for them.
"""
from pathlib import Path

from . import API_URL, INTERNAL_DOMAIN, client, remember, secret, state
from .client import EngineClient

# Made in recovery mode, so a normal start makes no others. High ports, as Stalwart runs as the
# app's own user, except receiving: other mail servers deliver to port 25 and nowhere else, and
# Stalwart treats local port 25 as the one mail comes in on (no login asked; SPF, DKIM and
# DMARC checked). The container lets its user have that one (Dockerfile).
LISTENERS = [
    {"name": "submission", "protocol": "smtp", "bind": {"[::]:17587": True}},
    {"name": "submissions", "protocol": "smtp", "bind": {"[::]:17465": True}, "tlsImplicit": True},
    {"name": "http", "protocol": "http", "bind": {"127.0.0.1:17880": True}, "useTls": False},
    {"name": "smtp", "protocol": "smtp", "bind": {"[::]:25": True}},                               # receiving
    {"name": "imaps", "protocol": "imap", "bind": {"[::]:17993": True}, "tlsImplicit": True},    # mail apps
    {"name": "pop3s", "protocol": "pop3", "bind": {"[::]:17995": True}, "tlsImplicit": True},    # mail apps
]


def _add_missing_listeners(engine):
    """The listeners Stalwart hasn't got yet, made now; the names of those made."""
    existing = {listener["name"] for listener in engine.get("NetworkListener")}
    made = []
    for listener in LISTENERS:
        if listener["name"] not in existing:
            engine.create("NetworkListener", listener)
            made.append(listener["name"])
    return made


def admin_client():
    """Stalwart's recovery admin, which first-time setup signs in as."""
    return EngineClient(API_URL, basic=("admin", secret("recovery_password")), timeout=20)


def run(stalwart):
    step = state()["setup_step"]
    if step != "new" and not Path(stalwart.config).exists():
        # data/stalwart was deleted (or restored without it): Stalwart would start in bootstrap
        # mode and never answer the panel, so it's set up again, recovery password and all
        step = "new"
    if step == "new":
        stalwart.start("bootstrap", secret("recovery_password"))
        stalwart.wait_until_up()
        made = admin_client().call("x:Bootstrap/set", {"update": {"singleton": {
            "serverHostname": INTERNAL_DOMAIN, "defaultDomain": INTERNAL_DOMAIN,
            "requestTlsCertificate": False, "generateDkimKeys": False,
            "dataStore": {"@type": "RocksDb", "path": str(Path(stalwart.data_dir) / "db")},
        }}})["updated"]["singleton"]   # the admin login Stalwart made, and its password
        remember(admin_login=made["username"], admin_password=made["secret"], setup_step="bootstrapped")
        stalwart.stop()
        step = "bootstrapped"
    if step == "bootstrapped":
        stalwart.start("recovery", secret("recovery_password"))
        stalwart.wait_until_up()
        _add_missing_listeners(admin_client())
        remember(setup_step="provisioned")
        stalwart.stop()
    stalwart.start("normal")
    stalwart.wait_until_up()
    if _add_missing_listeners(client()):   # an older install: new listeners bind when Stalwart starts
        stalwart.stop()
        stalwart.start("normal")
        stalwart.wait_until_up()
    remember(setup_step="ready")
