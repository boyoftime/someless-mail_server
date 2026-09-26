"""First-time setup of Stalwart, done by the supervisor before the panel starts: it happens
once, and picks up where it left off if interrupted (the engine table's setup_step).
new -> bootstrap mode: Bootstrap/set writes config.json and makes the admin account
bootstrapped -> recovery mode: our listeners (high ports, no port 25)
provisioned -> a normal start
"""
from pathlib import Path

from . import API_URL, INTERNAL_DOMAIN, remember, secret, state
from .client import EngineClient

# Nothing below 1024: Stalwart runs as the app's own user, not root. Nothing on port 25:
# receiving mail comes later. Made in recovery mode, so a normal start makes no others.
LISTENERS = [
    {"name": "submission", "protocol": "smtp", "bind": {"[::]:17587": True}},
    {"name": "submissions", "protocol": "smtp", "bind": {"[::]:17465": True}, "tlsImplicit": True},
    {"name": "http", "protocol": "http", "bind": {"127.0.0.1:17880": True}, "useTls": False},
]


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
        client = admin_client()
        existing = {listener["name"] for listener in client.get("NetworkListener")}
        for listener in LISTENERS:
            if listener["name"] not in existing:
                client.create("NetworkListener", listener)
        remember(setup_step="provisioned")
        stalwart.stop()
    stalwart.start("normal")
    stalwart.wait_until_up()
    remember(setup_step="ready")
