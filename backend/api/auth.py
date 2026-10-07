from __future__ import annotations

import functools
import time
import unicodedata
from typing import Callable

from flask import Blueprint, current_app, g, jsonify, request

from backend.auth.invitations import InvitationService, normalize_username
from backend.auth.passwords import hash_password, verify_password
from backend.auth.rate_limit import RateLimitBucket
from backend.auth.sessions import SessionCredentialChangedError
from backend.db import connect_database


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _now_utc_ms() -> int:
    return time.time_ns() // 1_000_000


def _json_body() -> dict:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def _error(code: str, status: int):
    return jsonify({"error": code}), status


def require_session(view: Callable):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        session_id = request.cookies.get(current_app.config["SESSION_COOKIE_NAME"])
        context = current_app.extensions["session_service"].resolve(session_id, _now_utc_ms())
        if context is None:
            return _error("session_invalid", 401)
        g.session_id = session_id
        g.session_context = context
        return view(*args, **kwargs)

    return wrapped


def require_csrf(view: Callable):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        session_id = getattr(g, "session_id", None)
        csrf_token = request.headers.get("X-CSRF-Token", "")
        if not current_app.extensions["session_service"].verify_csrf(session_id, csrf_token):
            return _error("csrf_invalid", 403)
        return view(*args, **kwargs)

    return wrapped


def require_admin(view: Callable):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        context = getattr(g, "session_context", None)
        if context is None or context.user.role != "admin":
            return _error("forbidden", 403)
        return view(*args, **kwargs)

    return wrapped


def _set_session_cookie(response, session_id: str, *, clear: bool = False):
    ttl = int(current_app.config["SESSION_TTL_SECONDS"])
    response.set_cookie(
        current_app.config["SESSION_COOKIE_NAME"],
        "" if clear else session_id,
        max_age=0 if clear else ttl,
        expires=0 if clear else None,
        httponly=True,
        secure=current_app.config["APP_ENV"] == "production",
        samesite="Lax",
        path="/",
    )
    return response


def _login_buckets(event_type: str, username_key: str, source_ip: str) -> list[RateLimitBucket]:
    settings = current_app.extensions["app_settings"]
    buckets = [
        RateLimitBucket(
            event_type,
            "normalized_username",
            username_key,
            settings.login_username_attempt_limit,
            settings.login_username_window_seconds,
        ),
        RateLimitBucket(
            event_type,
            "source_ip",
            source_ip,
            settings.login_ip_attempt_limit,
            settings.login_ip_window_seconds,
        ),
    ]
    if settings.login_pair_attempt_limit > 0:
        buckets.append(
            RateLimitBucket(
                event_type,
                "username_source_ip",
                f"{username_key}\x00{source_ip}",
                settings.login_pair_attempt_limit,
                settings.login_pair_window_seconds,
            )
        )
    return buckets


def _limited_response(retry_after_seconds: int):
    response = jsonify({"error": "rate_limited"})
    response.status_code = 429
    response.headers["Retry-After"] = str(max(1, retry_after_seconds))
    return response


@auth_bp.get("/session")
def session_status():
    session_id = request.cookies.get(current_app.config["SESSION_COOKIE_NAME"])
    context = current_app.extensions["session_service"].resolve(session_id, _now_utc_ms())
    if context is None:
        return jsonify({"authenticated": False})
    csrf_token = current_app.extensions["session_service"].csrf_token_for(
        session_id, context.csrf_scheme_version
    )
    return jsonify(
        {
            "authenticated": True,
            "user": {
                "user_id": context.user.user_id,
                "username": context.user.username,
                "role": context.user.role,
            },
            "csrf_token": csrf_token,
        }
    )


@auth_bp.post("/register")
def register():
    body = _json_body()
    source_ip = request.remote_addr or "unknown"
    settings = current_app.extensions["app_settings"]
    decision = current_app.extensions["rate_limit_service"].check_and_record(
        "register",
        [
            RateLimitBucket(
                "register",
                "source_ip",
                source_ip,
                settings.register_ip_attempt_limit,
                settings.register_ip_window_seconds,
            )
        ],
        _now_utc_ms(),
    )
    if not decision.allowed:
        return _limited_response(decision.retry_after_seconds)

    username = body.get("username")
    password = body.get("password")
    invitation_code = body.get("invitation_code")
    if not isinstance(username, str) or not isinstance(password, str):
        return _error("invalid_registration", 400)
    if any(unicodedata.category(character).startswith("C") for character in username):
        return _error("invalid_registration", 400)
    try:
        normalized = normalize_username(username)
        if not 3 <= len(normalized) <= 64:
            return _error("invalid_registration", 400)
        password_hash = hash_password(password)
        created = current_app.extensions["invitation_service"].redeem(
            invitation_code,
            username,
            password_hash,
            _now_utc_ms(),
        )
    except ValueError as exc:
        if str(exc) == "username is already registered":
            return _error("username_unavailable", 409)
        return _error("invalid_invitation", 400)
    return jsonify({"user_id": created.user_id, "username": created.username}), 201


@auth_bp.post("/login")
def login():
    body = _json_body()
    username = body.get("username")
    password = body.get("password")
    normalized = normalize_username(username) if isinstance(username, str) else ""
    username_bucket = normalized or "<invalid-username>"
    source_ip = request.remote_addr or "unknown"
    now_utc_ms = _now_utc_ms()
    decision = current_app.extensions["rate_limit_service"].check_and_record(
        "login", _login_buckets("login", username_bucket, source_ip), now_utc_ms
    )
    if not decision.allowed:
        return _limited_response(decision.retry_after_seconds)

    user = None
    if normalized:
        conn = connect_database(
            current_app.config["DATABASE_PATH"],
            current_app.config["SQLITE_BUSY_TIMEOUT_MS"],
        )
        try:
            user = conn.execute(
                """SELECT user_id, username, normalized_username, password_hash, role
                   FROM users WHERE normalized_username=? AND status='active'""",
                (normalized,),
            ).fetchone()
        finally:
            conn.close()

    candidate_password = password if isinstance(password, str) else ""
    stored_hash = (
        user["password_hash"]
        if user is not None
        else current_app.extensions["dummy_password_hash"]
    )
    password_matches = verify_password(candidate_password, stored_hash)
    if user is None or not password_matches:
        return _error("invalid_credentials", 401)

    try:
        session_id, csrf_token = current_app.extensions["session_service"].rotate(
            request.cookies.get(current_app.config["SESSION_COOKIE_NAME"]),
            user["user_id"],
            now_utc_ms,
            expected_password_hash=user["password_hash"],
        )
    except SessionCredentialChangedError:
        return _error("invalid_credentials", 401)
    response = jsonify(
        {
            "authenticated": True,
            "user": {
                "user_id": user["user_id"],
                "username": user["username"],
                "role": user["role"],
            },
            "csrf_token": csrf_token,
        }
    )
    return _set_session_cookie(response, session_id)


@auth_bp.post("/logout")
@require_session
@require_csrf
def logout():
    revoked = current_app.extensions["session_service"].revoke(
        g.session_id, _now_utc_ms()
    )
    if not revoked:
        response = jsonify({"error": "session_revoked"})
        response.status_code = 401
        return _set_session_cookie(response, "", clear=True)
    response = current_app.response_class(status=204)
    return _set_session_cookie(response, "", clear=True)


@auth_bp.post("/change-password")
@require_session
@require_csrf
def change_password():
    body = _json_body()
    current_password = body.get("current_password")
    new_password = body.get("new_password")
    if not isinstance(current_password, str) or not isinstance(new_password, str):
        return _error("invalid_password", 400)

    database_path = current_app.config["DATABASE_PATH"]
    busy_timeout_ms = current_app.config["SQLITE_BUSY_TIMEOUT_MS"]
    user_id = g.session_context.user.user_id
    conn = connect_database(database_path, busy_timeout_ms)
    try:
        row = conn.execute(
            "SELECT password_hash, status FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or row["status"] != "active" or not verify_password(
        current_password, row["password_hash"]
    ):
        return _error("current_password_invalid", 400)

    try:
        new_hash = hash_password(new_password)
    except ValueError:
        return _error("invalid_password", 400)

    conn = connect_database(database_path, busy_timeout_ms)
    try:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT password_hash, status FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if (
            current is None
            or current["status"] != "active"
            or current["password_hash"] != row["password_hash"]
        ):
            conn.execute("ROLLBACK")
            return _error("session_invalid", 401)
        now_utc_ms = _now_utc_ms()
        conn.execute(
            "UPDATE users SET password_hash=?, updated_at_utc_ms=? WHERE user_id=?",
            (new_hash, now_utc_ms, user_id),
        )
        conn.execute(
            "UPDATE sessions SET revoked_at_utc_ms=? "
            "WHERE user_id=? AND revoked_at_utc_ms IS NULL",
            (now_utc_ms, user_id),
        )
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    response = current_app.response_class(status=204)
    return _set_session_cookie(response, "", clear=True)
