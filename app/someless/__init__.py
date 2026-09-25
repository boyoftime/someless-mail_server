import os
import secrets
from pathlib import Path

from flask import Flask
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

VERSION = "1.0.0"

csrf = CSRFProtect()


def _load_secret_key(data_dir):
    """Signs session cookies. Created once and kept, so logins survive restarts."""
    path = data_dir / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATA_DIR=os.environ.get("SOMELESS_DATA_DIR", "/data/someless"),
        SESSION_COOKIE_SAMESITE="Lax",
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

    @app.context_processor
    def inject_version():
        return {"version": VERSION}

    return app
