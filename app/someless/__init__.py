import hashlib
import os
import secrets
from functools import lru_cache
from pathlib import Path

from flask import Flask, request
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

VERSION = "1.0.0"

# The admin picks the theme in the side menu (theme.js keeps it in the "someless_theme" cookie).
# Every page is drawn in it from the start, the login page after logging out included.
THEMES = ("dark", "light")
DEFAULT_THEME = "dark"


def picked_theme(cookies):
    """The theme picked, for the panel and the webmail alike: someless_theme, kept for secure and
    plain pages both (the webmail on http://...:17090 beside the panel on https shares its
    cookies, and a secure-only one never reached it: it went back to dark on each refresh), or
    theme, as an older switch kept it; else dark."""
    theme = cookies.get("someless_theme") or cookies.get("theme")
    return theme if theme in THEMES else DEFAULT_THEME

# Mail icons that float behind the login card (static/img/float/<name>.webp).
FLOAT_ICONS = ["gmail-m", "gmail-envelope", "mail-app", "inbox", "paper-plane", "yahoo"]

# Everything the pages after the splash load that the splash itself doesn't, so the
# splash can download it during its 6 seconds and those pages appear straight away.
LOGIN_PAGE_FILES = [
    "img/logo.webp",
    "lottie/contact-mail.json",
    "js/login-card.js",
    "js/password-toggle.js",
    "js/busy-button.js",
    "js/login-submit.js",
    "js/lottie-autoplay.js",
    "js/pixi.min.js",
    "js/login-background.js",
] + [f"img/float/{name}.webp" for name in FLOAT_ICONS]
SIGNED_IN_PAGE_FILES = [
    "js/dashboard.js",   # (the first page after logging in: its hanging boards)
    "lottie/helicopter.json",   # (and the helicopter that flies over them)
    "js/side-menu.js",
    "js/account-panel.js",
    "js/theme.js",
    "js/page-loader.js",
    "js/page-swap.js",
    "js/password-rules.js",
    "js/password-rules-dialog.js",
    "js/two-factor.js",
    "js/copy-button.js",
    "js/tooltip.js",
    "js/local-time.js",
    "js/dropdown.js",
    "js/domains-page.js",
    "js/help-links.js",
    "js/smooth-size.js",
    "js/settings-avatar.js",
    "js/senders-page.js",
    "js/sender-form.js",
    "js/mailboxes-page.js",
    "js/disable-dialog.js",
    "js/smtp-page.js",
    "js/settings-mail-server.js",
    "js/celebrate.js",
    "js/settings-misc.js",
    "js/save-when-changed.js",
    "js/smtp-docs.js",
    "js/api-docs.js",
    "js/api-wires.js",
    "js/page-flip.js",
    "lottie/programming.json",
    "lottie/ai-loading.json",
    "lottie/ai.json",
    "js/collapsible-cards.js",
    "lottie/page-loader.json",
    "lottie/menu-on-dark.json",
    "lottie/menu-on-light.json",
    "lottie/menu-active-on-dark.json",
    "lottie/menu-active-on-light.json",
    "lottie/account-sphere-on-dark.json",
    "lottie/account-sphere-on-light.json",
]
PRELOAD_FILES = LOGIN_PAGE_FILES + SIGNED_IN_PAGE_FILES

# Static links carry a fingerprint of the file (?v=...), so browsers can keep the files
# for a year and still fetch a new copy the moment a file changes.
STATIC_CACHE_SECONDS = 365 * 24 * 60 * 60

csrf = CSRFProtect()


def _load_secret_key(data_dir):
    """Signs session cookies. Created once and kept, so logins survive restarts."""
    path = data_dir / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


@lru_cache(maxsize=512)
def _fingerprint(path, modified):
    """Short hash of a file's contents. `modified` is part of the cache key, so an edited
    file gets a new fingerprint."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:10]


def fingerprint_static_links(app):
    """Static links with the file's fingerprint (the panel's, and the webmail's)."""
    @app.url_defaults
    def add_fingerprint(endpoint, values):
        # url_for(..., v=None) opts out, for files CSS points at without a fingerprint
        if endpoint != "static" or "filename" not in values or "v" in values:
            return
        path = Path(app.static_folder) / values["filename"]
        if path.is_file():
            values["v"] = _fingerprint(str(path), path.stat().st_mtime_ns)


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATA_DIR=os.environ.get("SOMELESS_DATA_DIR", "/data/someless"),
        # a mail engine (Stalwart) runs beside the panel: in the container, not on a dev machine
        ENGINE_ENABLED=os.environ.get("SOMELESS_ENGINE") == "1",
        SESSION_COOKIE_SAMESITE="Lax",
        SEND_FILE_MAX_AGE_DEFAULT=STATIC_CACHE_SECONDS,
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,   # the biggest request: a 5 MB profile picture (avatar.py)
    )
    if test_config:
        app.config.update(test_config)
    app.json.sort_keys = False   # JSON answers keep their fields in order: the API's (api.py) as its guide shows them

    data_dir = Path(app.config["DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    app.config["SECRET_KEY"] = _load_secret_key(data_dir)

    # Trust X-Forwarded-* from one reverse proxy (e.g. Nginx Proxy Manager) so HTTPS links stay HTTPS.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    csrf.init_app(app)

    from . import (api, api_keys, auth, avatar, db, domains, errors, first_password, help_links, mailboxes, pages, senders,
                   settings, smtp, two_factor)
    from .engine import cli as engine_cli
    from .engine import deliveries as engine_deliveries
    db.init_app(app)
    app.cli.add_command(two_factor.cli)
    app.cli.add_command(first_password.show_command)
    app.cli.add_command(first_password.reset_command)
    app.cli.add_command(engine_cli.cli)
    app.register_blueprint(auth.bp)
    app.register_blueprint(pages.bp)
    app.register_blueprint(domains.bp)
    app.register_blueprint(help_links.bp)
    app.register_blueprint(senders.bp)
    app.register_blueprint(mailboxes.bp)
    app.register_blueprint(smtp.bp)
    app.register_blueprint(api_keys.bp)
    # The API: apps call it with an API key in a header, never the login cookie, so no web page
    # can call it for a signed-in admin: no CSRF token to ask for
    app.register_blueprint(api.bp)
    csrf.exempt(api.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(errors.bp)
    # Stalwart's delivery reports: signed with the webhook secret instead of a CSRF token
    app.register_blueprint(engine_deliveries.bp)
    csrf.exempt(engine_deliveries.bp)

    fingerprint_static_links(app)

    @app.context_processor
    def inject_globals():
        return {
            "version": VERSION,
            "theme": picked_theme(request.cookies),
            "float_icons": FLOAT_ICONS,
            "preload_files": PRELOAD_FILES,
            "avatar_url": avatar.url,   # the profile picture, where there is one (shell.html)
        }

    return app
