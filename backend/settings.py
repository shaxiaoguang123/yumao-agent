from __future__ import annotations

import base64
import binascii
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from backend.credentials.keyring import parse_credential_keyring


_BASE64URL_RE = re.compile(r"\A[A-Za-z0-9_-]+\Z")
_PLACEHOLDER_SECRETS = {"changeme", "change-me", "password", "secret", "default"}


@dataclass(frozen=True, slots=True)
class AppSettings:
    database_path: Path
    app_env: str
    allowed_origins: tuple[str, ...]
    csrf_hmac_secret: bytes = field(repr=False)
    credential_encryption_keys: Mapping[str, bytes] = field(repr=False)
    credential_encryption_active_key_id: str = field(repr=False)
    upstream_fingerprint_keys: Mapping[str, bytes] = field(repr=False)
    upstream_fingerprint_active_key_id: str = field(repr=False)
    upstream_origin: str
    upstream_get_user_info_min_interval_ms: int | None
    upstream_connect_timeout_seconds: float
    upstream_read_timeout_seconds: float
    upstream_total_deadline_seconds: float
    upstream_max_response_bytes: int
    upstream_retry_after_fallback_seconds: int
    max_upstream_backoff_seconds: int
    upstream_lease_safety_margin_seconds: float
    token_expiring_soon_window_seconds: int = 604800
    session_cookie_name: str = "yumao_session"
    session_ttl_seconds: int = 86400
    sqlite_busy_timeout_ms: int = 5000
    login_username_attempt_limit: int = 10
    login_username_window_seconds: int = 900
    login_ip_attempt_limit: int = 60
    login_ip_window_seconds: int = 900
    login_pair_attempt_limit: int = 10
    login_pair_window_seconds: int = 900
    register_ip_attempt_limit: int = 10
    register_ip_window_seconds: int = 3600
    password_change_user_attempt_limit: int = 5
    password_change_user_window_seconds: int = 900
    password_change_ip_attempt_limit: int = 30
    password_change_ip_window_seconds: int = 900


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_float(env: Mapping[str, str], name: str) -> float:
    raw = env.get(name)
    try:
        value = float(raw) if raw is not None else float("nan")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return value


def _optional_positive_int(env: Mapping[str, str], name: str) -> int | None:
    raw = env.get(name)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _https_origin(env: Mapping[str, str]) -> str:
    raw = env.get("UPSTREAM_ORIGIN")
    if not isinstance(raw, str) or not raw or raw != raw.strip():
        raise ValueError("UPSTREAM_ORIGIN must be an allow-listed HTTPS origin")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("UPSTREAM_ORIGIN must be an allow-listed HTTPS origin") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("UPSTREAM_ORIGIN must be an allow-listed HTTPS origin")
    authority = parsed.hostname.lower()
    if port is not None:
        authority = f"{authority}:{port}"
    return f"https://{authority}"


def _decode_csrf_secret(env: Mapping[str, str]) -> bytes:
    encoded = env.get("CSRF_HMAC_SECRET")
    if not isinstance(encoded, str) or not encoded or encoded != encoded.strip():
        raise ValueError("CSRF_HMAC_SECRET is required as canonical unpadded base64url")
    if encoded.lower() in _PLACEHOLDER_SECRETS or not _BASE64URL_RE.fullmatch(encoded):
        raise ValueError("CSRF_HMAC_SECRET must be canonical unpadded base64url")
    try:
        padding = "=" * ((4 - len(encoded) % 4) % 4)
        secret = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("CSRF_HMAC_SECRET must be valid canonical base64url") from exc
    canonical = base64.urlsafe_b64encode(secret).rstrip(b"=").decode("ascii")
    if canonical != encoded:
        raise ValueError("CSRF_HMAC_SECRET must be canonical unpadded base64url")
    if len(secret) < 32:
        raise ValueError("CSRF_HMAC_SECRET must decode to at least 32 bytes")
    if len(set(secret)) < 8 or len(set(encoded)) < 8:
        raise ValueError("CSRF_HMAC_SECRET is a trivial repeated-value placeholder")
    try:
        decoded_text = secret.decode("utf-8")
    except UnicodeDecodeError:
        decoded_text = None
    if decoded_text is not None and decoded_text.isprintable():
        raise ValueError("CSRF_HMAC_SECRET must encode random bytes, not a human-readable string")
    return secret


def load_settings(env: Mapping[str, str] | None = None) -> AppSettings:
    source: Mapping[str, str] = os.environ if env is None else env
    app_env = source.get("APP_ENV", "development").strip().lower()
    if not app_env:
        raise ValueError("APP_ENV must not be empty")

    raw_origins = source.get("APP_ALLOWED_ORIGINS", "")
    allowed_origins = tuple(origin.strip().rstrip("/") for origin in raw_origins.split(",") if origin.strip())
    if app_env == "production" and not allowed_origins:
        raise ValueError("APP_ALLOWED_ORIGINS is required in production")
    if not allowed_origins and app_env != "production":
        allowed_origins = ("http://localhost:5173",)

    csrf_hmac_secret = _decode_csrf_secret(source)
    encryption_keyring = parse_credential_keyring(
        source.get("APP_CREDENTIAL_ENCRYPTION_KEYS"),
        source.get("APP_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID"),
    )
    fingerprint_keyring = parse_credential_keyring(
        source.get("APP_UPSTREAM_FINGERPRINT_KEYS"),
        source.get("APP_UPSTREAM_FINGERPRINT_ACTIVE_KEY_ID"),
    )
    encryption_material = set(encryption_keyring.keys.values())
    fingerprint_material = set(fingerprint_keyring.keys.values())
    if encryption_material & fingerprint_material:
        raise ValueError("encryption and fingerprint key material must be independent")
    if csrf_hmac_secret in encryption_material or csrf_hmac_secret in fingerprint_material:
        raise ValueError("CSRF and Credential key material must be independent")

    connect_timeout = _positive_float(source, "UPSTREAM_CONNECT_TIMEOUT_SECONDS")
    read_timeout = _positive_float(source, "UPSTREAM_READ_TIMEOUT_SECONDS")
    total_deadline = _positive_float(source, "UPSTREAM_TOTAL_DEADLINE_SECONDS")
    max_response_bytes = _positive_int(source, "UPSTREAM_MAX_RESPONSE_BYTES", 0)
    retry_after_fallback = _positive_int(source, "UPSTREAM_RETRY_AFTER_FALLBACK_SECONDS", 0)
    max_backoff = _positive_int(source, "MAX_UPSTREAM_BACKOFF_SECONDS", 0)
    lease_safety_margin = _positive_float(source, "UPSTREAM_LEASE_SAFETY_MARGIN_SECONDS")
    if connect_timeout >= total_deadline or read_timeout >= total_deadline:
        raise ValueError("upstream connect/read timeouts must be less than the total deadline")
    if retry_after_fallback > max_backoff:
        raise ValueError("UPSTREAM_RETRY_AFTER_FALLBACK_SECONDS must not exceed MAX_UPSTREAM_BACKOFF_SECONDS")
    if lease_safety_margin < read_timeout:
        raise ValueError("UPSTREAM_LEASE_SAFETY_MARGIN_SECONDS must cover one read timeout")

    return AppSettings(
        database_path=Path(source.get("DATABASE_PATH", "instance/yumao.sqlite3")),
        app_env=app_env,
        allowed_origins=allowed_origins,
        csrf_hmac_secret=csrf_hmac_secret,
        credential_encryption_keys=encryption_keyring.keys,
        credential_encryption_active_key_id=encryption_keyring.active_key_id,
        upstream_fingerprint_keys=fingerprint_keyring.keys,
        upstream_fingerprint_active_key_id=fingerprint_keyring.active_key_id,
        upstream_origin=_https_origin(source),
        upstream_get_user_info_min_interval_ms=_optional_positive_int(
            source, "UPSTREAM_GET_USER_INFO_MIN_INTERVAL_MS"
        ),
        upstream_connect_timeout_seconds=connect_timeout,
        upstream_read_timeout_seconds=read_timeout,
        upstream_total_deadline_seconds=total_deadline,
        upstream_max_response_bytes=max_response_bytes,
        upstream_retry_after_fallback_seconds=retry_after_fallback,
        max_upstream_backoff_seconds=max_backoff,
        upstream_lease_safety_margin_seconds=lease_safety_margin,
        token_expiring_soon_window_seconds=_positive_int(
            source, "TOKEN_EXPIRING_SOON_WINDOW_SECONDS", 604800
        ),
        session_cookie_name=source.get("SESSION_COOKIE_NAME", "yumao_session"),
        session_ttl_seconds=_positive_int(source, "SESSION_TTL_SECONDS", 86400),
        sqlite_busy_timeout_ms=_positive_int(source, "SQLITE_BUSY_TIMEOUT_MS", 5000),
        login_username_attempt_limit=_positive_int(source, "LOGIN_USERNAME_ATTEMPT_LIMIT", 10),
        login_username_window_seconds=_positive_int(source, "LOGIN_USERNAME_WINDOW_SECONDS", 900),
        login_ip_attempt_limit=_positive_int(source, "LOGIN_IP_ATTEMPT_LIMIT", 60),
        login_ip_window_seconds=_positive_int(source, "LOGIN_IP_WINDOW_SECONDS", 900),
        login_pair_attempt_limit=_nonnegative_int(source, "LOGIN_PAIR_ATTEMPT_LIMIT", 10),
        login_pair_window_seconds=_positive_int(source, "LOGIN_PAIR_WINDOW_SECONDS", 900),
        register_ip_attempt_limit=_positive_int(source, "REGISTER_IP_ATTEMPT_LIMIT", 10),
        register_ip_window_seconds=_positive_int(source, "REGISTER_IP_WINDOW_SECONDS", 3600),
        password_change_user_attempt_limit=_positive_int(
            source, "PASSWORD_CHANGE_USER_ATTEMPT_LIMIT", 5
        ),
        password_change_user_window_seconds=_positive_int(
            source, "PASSWORD_CHANGE_USER_WINDOW_SECONDS", 900
        ),
        password_change_ip_attempt_limit=_positive_int(
            source, "PASSWORD_CHANGE_IP_ATTEMPT_LIMIT", 30
        ),
        password_change_ip_window_seconds=_positive_int(
            source, "PASSWORD_CHANGE_IP_WINDOW_SECONDS", 900
        ),
    )
