"""Mailbox passwords, kept only as hashes the mail engine checks too (mail_password.py)."""
import re

from someless import mail_password


def test_a_password_is_kept_as_a_pbkdf2_hash():
    stored = mail_password.hash_password("Mailbox-Pass-123!")

    assert re.fullmatch(r"\$pbkdf2-sha256\$i=\d+,l=32\$[A-Za-z0-9+/]+\$[A-Za-z0-9+/]+", stored)
    assert "Mailbox-Pass-123!" not in stored
    assert stored != mail_password.hash_password("Mailbox-Pass-123!")   # salted: never the same twice


def test_the_right_password_matches_and_no_other():
    stored = mail_password.hash_password("Mailbox-Pass-123!")

    assert mail_password.password_ok(stored, "Mailbox-Pass-123!")
    assert not mail_password.password_ok(stored, "mailbox-pass-123!")
    assert not mail_password.password_ok(stored, "")


def test_something_that_isnt_a_hash_matches_nothing():
    for stored in ("", "plain", "$pbkdf2-sha256$broken", "$argon2id$v=19$m=1,t=1,p=1$c2FsdA$aGFzaA"):
        assert not mail_password.password_ok(stored, "plain")
