import hashlib
import os
import secrets
from functools import lru_cache
from pathlib import Path

from flask import Flask
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

VERSION = "1.0.0"

# Mail icons that float behind the login card (static/img/float/<name>.webp).
FLOAT_ICONS = ["gmail-m", "gmail-envelope", "mail-app", "inbox", "paper-plane", "yahoo"]

# Everything the login page loads that the splash doesn't, so the splash can download
# it during its 6 seconds and the login page appears straight away.
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


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATA_DIR=os.environ.get("SOMELESS_DATA_DIR", "/data/someless"),
        SESSION_COOKIE_SAMESITE="Lax",
        SEND_FILE_MAX_AGE_DEFAULT=STATIC_CACHE_SECONDS,
    )
    if test_config:
        app.config.update(test_config)

    data_dir = Path(app.config["DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    app.config["SECRET_KEY"] = _load_secret_key(data_dir)

    # Trust X-Forwarded-* from one reverse proxy (e.g. Nginx Proxy Manager) so HTTPS links stay HTTPS.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    csrf.init_app(app)

    from . import auth, db, pages, settings
    db.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(pages.bp)
    app.register_blueprint(settings.bp)

    @app.url_defaults
    def fingerprint_static_links(endpoint, values):
        # url_for(..., v=None) opts out, for files CSS points at without a fingerprint
        if endpoint != "static" or "filename" not in values or "v" in values:
            return
        path = Path(app.static_folder) / values["filename"]
        if path.is_file():
            values["v"] = _fingerprint(str(path), path.stat().st_mtime_ns)

    @app.context_processor
    def inject_globals():
        return {"version": VERSION, "float_icons": FLOAT_ICONS, "login_page_files": LOGIN_PAGE_FILES}

    return app
