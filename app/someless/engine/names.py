"""The server's name: what it greets other servers with, its certificate is for, apps connect
to, and its reverse DNS should say. One of the authenticated domains' mail names."""
from ..db import get_db
from ..domain_records import HOST_CHOICES
from . import state


def server_names():
    return [f"{row['mail_host'] or HOST_CHOICES[0]}.{row['name']}" for row in get_db().execute(
        "SELECT domains.name, domain_keys.mail_host FROM domains JOIN domain_keys ON domain_keys.domain_id = domains.id"
        " WHERE domains.authenticated = 1 ORDER BY domains.name")]


def server_name():
    names = server_names()
    chosen = state()["server_name"]
    return chosen if chosen in names else (names[0] if names else None)
