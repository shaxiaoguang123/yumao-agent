from __future__ import annotations

import json
import sqlite3
import time
from datetime import date

from flask import Blueprint, current_app, g, jsonify, request

from backend.api.auth import require_csrf, require_session
from backend.execution.settings import ExecutionSettingsError


booking_execution_bp = Blueprint("booking_execution", __name__, url_prefix="/api/booking-execution")
_MAX_BODY_BYTES = 8 * 1024


def _service():
    return current_app.extensions["execution_settings_service"]


@booking_execution_bp.errorhandler(ExecutionSettingsError)
def _settings_error(error: ExecutionSettingsError):
    return jsonify({"error": error.code}), error.status


@booking_execution_bp.errorhandler(sqlite3.Error)
def _storage_error(_error):
    return jsonify({"error": "execution_settings_unavailable"}), 503


def _body():
    if request.mimetype != "application/json" or (
        request.content_length is not None and request.content_length > _MAX_BODY_BYTES
    ):
        raise ExecutionSettingsError("invalid_execution_settings")
    try:
        raw = request.stream.read(_MAX_BODY_BYTES + 1)
        if len(raw) > _MAX_BODY_BYTES:
            raise ExecutionSettingsError("invalid_execution_settings")
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ExecutionSettingsError("invalid_execution_settings") from None
    if type(value) is not dict or set(value) != {"expected_version", "settings"}:
        raise ExecutionSettingsError("invalid_execution_settings")
    return value


@booking_execution_bp.get("/settings")
@require_session
def get_settings():
    return jsonify(_service().get(g.session_context.user.user_id))


@booking_execution_bp.put("/settings")
@require_session
@require_csrf
def update_settings():
    body = _body()
    result = _service().save(
        g.session_context.user.user_id,
        body["expected_version"],
        body["settings"],
        time.time_ns() // 1_000_000,
    )
    return jsonify(result)


@booking_execution_bp.get("/credentials/<credential_id>/settings")
@require_session
def get_legacy_credential_settings(credential_id: str):
    user_id = g.session_context.user.user_id
    _service().assert_credential_owner(user_id, credential_id)
    return jsonify({**_service().get(user_id), "credential_id": credential_id})


@booking_execution_bp.put("/credentials/<credential_id>/settings")
@require_session
@require_csrf
def update_legacy_credential_settings(credential_id: str):
    user_id = g.session_context.user.user_id
    _service().assert_credential_owner(user_id, credential_id)
    body = _body()
    return jsonify({
        **_service().save(
            user_id, body["expected_version"], body["settings"], time.time_ns() // 1_000_000,
        ),
        "credential_id": credential_id,
    })


@booking_execution_bp.get("/credentials/<credential_id>/queues/<target_date>")
@require_session
def get_execution_queue(credential_id: str, target_date: str):
    try:
        parsed = date.fromisoformat(target_date)
    except (TypeError, ValueError):
        raise ExecutionSettingsError("invalid_target_date") from None
    if parsed.isoformat() != target_date:
        raise ExecutionSettingsError("invalid_target_date")
    user_id = g.session_context.user.user_id
    _service().assert_credential_owner(user_id, credential_id)
    run = current_app.extensions["booking_execution_repository"].latest_run(
        user_id, credential_id, target_date,
    )
    return jsonify({"run": run, "worker_enabled": _service().worker_enabled})


@booking_execution_bp.get("/successes")
@require_session
def list_successes():
    return jsonify({
        "successes": current_app.extensions["booking_execution_repository"].list_successes(
            g.session_context.user.user_id,
        ),
        "worker_enabled": _service().worker_enabled,
    })
