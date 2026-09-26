"""Logins for SMTP keys: made from the key's name, so an app's settings say which key it uses
(website-7f3a). Stalwart allows one password per login, so each key has its own."""
import re
import secrets
import unicodedata


def make_login(name, taken):
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    stem = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:20].strip("-") or "key"
    while True:
        login = f"{stem}-{secrets.token_hex(2)}"
        if login not in taken:
            return login
