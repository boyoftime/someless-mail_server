"""Mailbox passwords, kept only as hashes: PBKDF2-SHA256 in the PHC string format
($pbkdf2-sha256$i=…,l=32$salt$hash). The mail engine is given the hash, never the password, and
checks it for the mail apps' logins (IMAP, POP3, SMTP); the webmail checks it here."""
import base64
import hashlib
import hmac
import secrets

ITERATIONS = 210_000


def _b64(raw):
    return base64.b64encode(raw).decode().rstrip("=")


def _unb64(text):
    return base64.b64decode(text + "=" * (-len(text) % 4), validate=True)


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS, 32)
    return f"$pbkdf2-sha256$i={ITERATIONS},l=32${_b64(salt)}${_b64(digest)}"


def password_ok(stored, password):
    try:
        _, scheme, params, salt, digest = stored.split("$")
        if scheme != "pbkdf2-sha256":
            return False
        iterations = int(dict(item.split("=", 1) for item in params.split(","))["i"])
        expected = _unb64(digest)
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt), iterations, len(expected))
    except (ValueError, KeyError, TypeError):
        return False
    return bool(expected) and hmac.compare_digest(got, expected)
