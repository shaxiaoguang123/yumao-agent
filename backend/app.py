from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import requests
from flask import Flask

from backend.api.admin import admin_bp
from backend.api.auth import auth_bp
from backend.api.credentials import credentials_bp
from backend.api.health import health_bp
from backend.api.plans import plans_bp
from backend.api.planning import planning_bp
from backend.ai.planning import PlanningService
from backend.api.availability_simulation import availability_simulation_bp
from backend.availability_matching.service import SimulationAvailabilityService
from backend.ai.call_guard import AICallGuard
from backend.api.booking_window import booking_window_bp
from backend.api.ai_models import ai_models_bp
from backend.ai.service import AIProviderService
from backend.ai.key_dependencies import check_ai_provider_key_dependencies
from backend.booking_window import BookingWindowPolicy
from backend.plans.service import PlanService
from backend.api.security import init_security
from backend.auth.invitations import InvitationService
from backend.auth.passwords import create_dummy_password_hash
from backend.auth.rate_limit import RateLimitService
from backend.auth.sessions import SessionService
from backend.credentials.key_dependencies import check_credential_key_dependencies
from backend.credentials.keyring import CredentialKeyring
from backend.credentials.request_gate import UpstreamRequestGate
from backend.credentials.service import CredentialService
from backend.credentials.upstream import UpstreamContractAdapter, UpstreamHttpTransport
from backend.db import CURRENT_SCHEMA_VERSION, check_schema_ready
from backend.settings import load_settings


_SECRET_CONFIG_KEYS = {
    "CSRF_HMAC_SECRET",
    "APP_CREDENTIAL_ENCRYPTION_KEYS",
    "APP_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID",
    "APP_UPSTREAM_FINGERPRINT_KEYS",
    "APP_UPSTREAM_FINGERPRINT_ACTIVE_KEY_ID",
    "LLM_API_KEY",
}


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
            if key not in _SECRET_CONFIG_KEYS
        }

    migrations_dir = Path(__file__).resolve().parent / "migrations"
    check_schema_ready(
        settings.database_path,
        settings.sqlite_busy_timeout_ms,
        CURRENT_SCHEMA_VERSION,
        migrations_dir,
    )
    encryption_keyring = CredentialKeyring(
        settings.credential_encryption_keys,
        settings.credential_encryption_active_key_id,
    )
    fingerprint_keyring = CredentialKeyring(
        settings.upstream_fingerprint_keys,
        settings.upstream_fingerprint_active_key_id,
    )
    check_credential_key_dependencies(
        settings.database_path,
        settings.sqlite_busy_timeout_ms,
        encryption_keyring=encryption_keyring,
        fingerprint_keyring=fingerprint_keyring,
    )
    check_ai_provider_key_dependencies(
        settings.database_path,
        settings.sqlite_busy_timeout_ms,
        encryption_keyring,
    )
    gate = UpstreamRequestGate(
        database_path=settings.database_path,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        minimum_interval_ms=settings.upstream_get_user_info_min_interval_ms,
        total_deadline_seconds=settings.upstream_total_deadline_seconds,
        read_timeout_seconds=settings.upstream_read_timeout_seconds,
        lease_safety_margin_seconds=settings.upstream_lease_safety_margin_seconds,
        retry_after_fallback_seconds=settings.upstream_retry_after_fallback_seconds,
        max_upstream_backoff_seconds=settings.max_upstream_backoff_seconds,
    )
    transport = UpstreamHttpTransport(
        session_factory=requests.Session,
        connect_timeout_seconds=settings.upstream_connect_timeout_seconds,
        read_timeout_seconds=settings.upstream_read_timeout_seconds,
        total_deadline_seconds=settings.upstream_total_deadline_seconds,
        max_response_bytes=settings.upstream_max_response_bytes,
    )
    adapter = UpstreamContractAdapter(
        transport=transport,
        upstream_origin=settings.upstream_origin,
        account_continuity_capability=True,
    )
    credential_service = CredentialService(
        database_path=settings.database_path,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        encryption_keyring=encryption_keyring,
        fingerprint_keyring=fingerprint_keyring,
        adapter=adapter,
        gate=gate,
        account_continuity_capability=True,
        token_expiring_soon_window_seconds=settings.token_expiring_soon_window_seconds,
    )
    cipher = credential_service.cipher

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
    app.extensions["ai_call_guard"] = AICallGuard(settings.database_path, app.extensions["rate_limit_service"])
    app.extensions["credential_token_cipher"] = cipher
    app.extensions["credential_upstream_adapter"] = adapter
    app.extensions["upstream_request_gate"] = gate
    app.extensions["credential_service"] = credential_service
    app.extensions["dummy_password_hash"] = create_dummy_password_hash()
    app.extensions["plan_service"] = PlanService(
        settings.database_path, settings.sqlite_busy_timeout_ms,
        BookingWindowPolicy(settings.booking_timezone_name),
        settings.booking_currency_code, settings.booking_currency_minor_unit_exponent,
    )
    app.extensions["ai_provider_service"] = AIProviderService(
        database_path=settings.database_path,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        keyring=encryption_keyring,
        service_default=settings.llm_service_default,
    )
    init_security(app)
    app.extensions["planning_service"] = PlanningService(
        app.extensions["plan_service"], app.extensions["ai_provider_service"],
    )
    app.extensions['availability_simulation_service'] = SimulationAvailabilityService(
        app.extensions['plan_service'], enabled=settings.availability_simulation_enabled)
    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(credentials_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(planning_bp)
    app.register_blueprint(availability_simulation_bp)
    app.register_blueprint(booking_window_bp)
    app.register_blueprint(ai_models_bp)
    return app
