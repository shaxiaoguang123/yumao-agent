from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flask import Flask

from backend.api.admin import admin_bp
from backend.api.auth import auth_bp
from backend.api.health import health_bp
from backend.api.security import init_security
from backend.auth.invitations import InvitationService
from backend.auth.passwords import create_dummy_password_hash
from backend.auth.rate_limit import RateLimitService
from backend.auth.sessions import SessionService
from backend.db import CURRENT_SCHEMA_VERSION, check_schema_ready
from backend.settings import load_settings


def create_app(config: Mapping[str, object] | None = None) -> Flask:
    if config is None:
        settings = load_settings()
        flask_overrides: dict[str, Any] = {}
    else:
        settings_env = {str(key): str(value) for key, value in config.items()}
        settings = load_settings(settings_env)
        flask_overrides = {
            key: value
            for key, value in config.items()
            if key not in {"CSRF_HMAC_SECRET"}
        }

    migrations_dir = Path(__file__).resolve().parent / "migrations"
    check_schema_ready(
        settings.database_path,
        settings.sqlite_busy_timeout_ms,
        CURRENT_SCHEMA_VERSION,
        migrations_dir,
    )

    app = Flask(__name__)
    app.config.update(flask_overrides)
    app.config.update(
        DATABASE_PATH=settings.database_path,
        APP_ENV=settings.app_env,
        ALLOWED_ORIGINS=settings.allowed_origins,
        SESSION_COOKIE_NAME=settings.session_cookie_name,
        SESSION_TTL_SECONDS=settings.session_ttl_seconds,
        SQLITE_BUSY_TIMEOUT_MS=settings.sqlite_busy_timeout_ms,
    )
    app.extensions["app_settings"] = settings
    app.extensions["session_service"] = SessionService(
        settings.database_path,
        settings.sqlite_busy_timeout_ms,
        settings.csrf_hmac_secret,
        settings.session_ttl_seconds,
    )
    app.extensions["invitation_service"] = InvitationService(
        settings.database_path,
        settings.sqlite_busy_timeout_ms,
    )
    app.extensions["rate_limit_service"] = RateLimitService(
        settings.database_path,
        settings.sqlite_busy_timeout_ms,
    )
    app.extensions["dummy_password_hash"] = create_dummy_password_hash()
    init_security(app)
    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    return app
