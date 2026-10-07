from __future__ import annotations

import base64
import binascii
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


_BASE64URL_RE = re.compile(r"\A[A-Za-z0-9_-]+\Z")
_PLACEHOLDER_SECRETS = {"changeme", "change-me", "password", "secret", "default"}


@dataclass(frozen=True, slots=True)
class AppSettings:
    database_path: Path
    app_env: str
    allowed_origins: tuple[str, ...]
    csrf_hmac_secret: bytes = field(repr=False)
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


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


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

    return AppSettings(
        database_path=Path(source.get("DATABASE_PATH", "instance/yumao.sqlite3")),
        app_env=app_env,
        allowed_origins=allowed_origins,
        csrf_hmac_secret=_decode_csrf_secret(source),
        session_cookie_name=source.get("SESSION_COOKIE_NAME", "yumao_session"),
        session_ttl_seconds=_positive_int(source, "SESSION_TTL_SECONDS", 86400),
        sqlite_busy_timeout_ms=_positive_int(source, "SQLITE_BUSY_TIMEOUT_MS", 5000),
        login_username_attempt_limit=_positive_int(source, "LOGIN_USERNAME_ATTEMPT_LIMIT", 10),
        login_username_window_seconds=_positive_int(source, "LOGIN_USERNAME_WINDOW_SECONDS", 900),
        login_ip_attempt_limit=_positive_int(source, "LOGIN_IP_ATTEMPT_LIMIT", 60),
        login_ip_window_seconds=_positive_int(source, "LOGIN_IP_WINDOW_SECONDS", 900),
        login_pair_attempt_limit=_positive_int(source, "LOGIN_PAIR_ATTEMPT_LIMIT", 10),
        login_pair_window_seconds=_positive_int(source, "LOGIN_PAIR_WINDOW_SECONDS", 900),
        register_ip_attempt_limit=_positive_int(source, "REGISTER_IP_ATTEMPT_LIMIT", 10),
        register_ip_window_seconds=_positive_int(source, "REGISTER_IP_WINDOW_SECONDS", 3600),
    )
