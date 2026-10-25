from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import requests
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from backend.api.admin import admin_bp
from backend.api.auth import auth_bp
from backend.api.credentials import credentials_bp
from backend.api.health import health_bp
from backend.api.orders import orders_bp
from backend.orders.service import OrderQueryService
from backend.api.plans import plans_bp
from backend.api.planning import planning_bp
from backend.ai.planning import PlanningService
from backend.ai.conversation_store import PlanningConversationStore
from backend.ai.queue_graph import QueuePlanningGraph
from backend.ai.intent_planning import IntentPlanningService
from backend.api.availability_simulation import availability_simulation_bp
from backend.api.availability_history import availability_history_bp
from backend.api.availability_live import availability_live_bp
from backend.availability_matching.live import OfficialReadOnlyAvailabilityService
from backend.availability_matching.service import SimulationAvailabilityService
from backend.venue_catalog import VenueCatalogService
from backend.ai.call_guard import AICallGuard
from backend.api.booking_window import booking_window_bp
from backend.api.ai_models import ai_models_bp
from backend.api.booking_execution import booking_execution_bp
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
from backend.execution.settings import ExecutionSettingsService
from backend.credentials.upstream import UpstreamContractAdapter, UpstreamHttpTransport
from backend.execution.engine import BookingExecutionEngine
from backend.execution.protocol import OfficialBookingProtocol
from backend.execution.repository import BookingExecutionRepository
from backend.execution.scheduler import BookingScheduler
from backend.notifications import EmailNotificationService
from backend.db import CURRENT_SCHEMA_VERSION, check_schema_ready
from backend.settings import load_settings
from backend.api.diagnostics import diagnostics_bp
from backend.diagnostics import RuntimeDiagnostics, init_request_diagnostics, report_exception


_SECRET_CONFIG_KEYS = {
    "CSRF_HMAC_SECRET",
    "APP_CREDENTIAL_ENCRYPTION_KEYS",
    "APP_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID",
    "APP_UPSTREAM_FINGERPRINT_KEYS",
    "APP_UPSTREAM_FINGERPRINT_ACTIVE_KEY_ID",
    "LLM_API_KEY",
    "EMAIL_NOTIFICATION_RECIPIENT",
    "EMAIL_NOTIFICATION_WORKER_URL",
    "EMAIL_NOTIFICATION_HMAC_SECRET",
    "EMAIL_NOTIFICATION_OWNER_USERNAME",
    "UPSTREAM_ITEM_AES_KEY_ASCII",
    "UPSTREAM_ITEM_AES_IV_ASCII",
    "AES_KEY_ASCII",
    "AES_IV_ASCII",
}


class DiagnosticFlask(Flask):
    def log_exception(self, exc_info):
        # Flask's default formatter includes uncontrolled exception messages.
        report_exception("api", "api.unhandled", code="internal_error", exception=exc_info[1])


def create_app(config: Mapping[str, object] | None = None, *, process_role="web") -> Flask:
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
    booking_window_policy = BookingWindowPolicy(settings.booking_timezone_name)
    live_availability_service = OfficialReadOnlyAvailabilityService(
        credential_service=credential_service,
        transport=transport,
        booking_window_policy=booking_window_policy,
        item_aes_key_ascii=settings.upstream_item_aes_key_ascii,
        item_aes_iv_ascii=settings.upstream_item_aes_iv_ascii,
        enabled=(settings.live_availability_enabled or settings.booking_execution_enabled),
        timezone_name=settings.booking_timezone_name,
    )

    app = DiagnosticFlask(__name__)
    if settings.trust_proxy_headers:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
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
    diagnostics = RuntimeDiagnostics(
        settings.database_path, role=process_role,
        enabled=settings.runtime_logs_enabled and (not app.testing or "RUNTIME_LOGS_ENABLED" in flask_overrides),
    )
    app.extensions["runtime_diagnostics"] = diagnostics
    init_request_diagnostics(app, diagnostics)
    diagnostics.emit("system", "service.started", stage=process_role)
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
    app.extensions["upstream_http_transport"] = transport
    app.extensions["credential_service"] = credential_service
    app.extensions["live_availability_service"] = live_availability_service
    app.extensions["execution_settings_service"] = ExecutionSettingsService(
        settings.database_path, settings.sqlite_busy_timeout_ms,
        worker_enabled=settings.booking_execution_enabled,
    )
    app.extensions["dummy_password_hash"] = create_dummy_password_hash()
    app.extensions["plan_service"] = PlanService(
        settings.database_path, settings.sqlite_busy_timeout_ms,
        booking_window_policy,
        settings.booking_currency_code, settings.booking_currency_minor_unit_exponent,
    )
    booking_protocol = OfficialBookingProtocol(
        credential_service=credential_service,
        transport=transport,
        item_aes_key_ascii=settings.upstream_item_aes_key_ascii,
        item_aes_iv_ascii=settings.upstream_item_aes_iv_ascii,
    )
    booking_execution_engine = BookingExecutionEngine(
        database_path=settings.database_path,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        plan_service=app.extensions["plan_service"],
        credential_service=credential_service,
        protocol=booking_protocol,
        timezone_name=settings.booking_timezone_name,
        worker_enabled=settings.booking_execution_enabled,
        diagnostics=diagnostics,
    )
    execution_repository = BookingExecutionRepository(
        settings.database_path, settings.sqlite_busy_timeout_ms,
    )
    email_notification_service = EmailNotificationService(
        settings.database_path, settings.sqlite_busy_timeout_ms,
        timezone_name=settings.booking_timezone_name,
        owner_username=settings.email_notification_owner_username,
        recipient=settings.email_notification_recipient,
        worker_url=settings.email_notification_worker_url,
        hmac_secret=settings.email_notification_hmac_secret,
        default_enabled=settings.email_notification_default_enabled,
        worker_enabled=settings.booking_execution_enabled,
        plan_service=app.extensions["plan_service"],
        execution_settings_service=app.extensions["execution_settings_service"],
    )
    app.extensions["booking_execution_protocol"] = booking_protocol
    app.extensions["order_query_service"] = OrderQueryService(
        credential_service=credential_service, protocol=booking_protocol,
        reference_secret=settings.csrf_hmac_secret,
        enabled=bool(settings.upstream_item_aes_key_ascii and settings.upstream_item_aes_iv_ascii),
    )
    app.extensions["booking_execution_engine"] = booking_execution_engine
    app.extensions["booking_execution_repository"] = execution_repository
    app.extensions["email_notification_service"] = email_notification_service
    app.extensions["booking_scheduler"] = BookingScheduler(
        settings_service=app.extensions["execution_settings_service"],
        engine=booking_execution_engine,
        repository=execution_repository,
        plan_service=app.extensions["plan_service"],
        timezone_name=settings.booking_timezone_name,
        worker_enabled=settings.booking_execution_enabled,
        diagnostics=diagnostics,
        email_notification_service=email_notification_service,
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
    app.extensions["queue_planning_graph"] = QueuePlanningGraph()
    app.extensions["planning_conversation_store"] = PlanningConversationStore(
        settings.database_path, settings.sqlite_busy_timeout_ms,
    )
    app.extensions["intent_planning_service"] = IntentPlanningService(
        app.extensions["plan_service"], app.extensions["ai_provider_service"],
    )
    app.extensions['availability_simulation_service'] = SimulationAvailabilityService(
        app.extensions['plan_service'], enabled=settings.availability_simulation_enabled,
        grid_preview_enabled=settings.app_env == 'development',
        history_preview_enabled=settings.app_env == 'development')
    app.extensions['venue_catalog_service'] = VenueCatalogService()
    app.register_blueprint(health_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(credentials_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(planning_bp)
    app.register_blueprint(availability_simulation_bp)
    app.register_blueprint(availability_history_bp)
    app.register_blueprint(availability_live_bp)
    app.register_blueprint(booking_window_bp)
    app.register_blueprint(ai_models_bp)
    app.register_blueprint(booking_execution_bp)
    app.register_blueprint(diagnostics_bp)
    return app
