from __future__ import annotations

import json

from flask import Blueprint, current_app, g, jsonify, request

from backend.api.auth import require_csrf, require_session
from backend.availability_matching.live import LiveAvailabilityError


availability_live_bp = Blueprint("availability_live", __name__, url_prefix="/api/availability/live")
_MAX_BODY_BYTES = 16 * 1024


def _error(error: LiveAvailabilityError):
    payload = {"error": error.code}
    response = jsonify(payload)
    response.status_code = error.http_status
    if error.retry_after_seconds is not None:
        retry_after = max(1, int(error.retry_after_seconds))
        response.headers["Retry-After"] = str(retry_after)
        response.set_data(json.dumps({"error": error.code, "retry_after_seconds": retry_after}))
        response.content_type = "application/json"
    return response


def _body(expected: set[str]):
    if request.content_length is not None and request.content_length > _MAX_BODY_BYTES:
        return None
    try:
        raw = request.stream.read(_MAX_BODY_BYTES + 1)
        if len(raw) > _MAX_BODY_BYTES:
            return None
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if type(value) is not dict or set(value) != expected:
        return None
    return value


@availability_live_bp.errorhandler(LiveAvailabilityError)
def _handle_live_error(error: LiveAvailabilityError):
    return _error(error)


@availability_live_bp.get("/options")
@require_session
def options():
    return jsonify(current_app.extensions["live_availability_service"].options())


@availability_live_bp.post("/categories")
@require_session
@require_csrf
def categories():
    body = _body({"credential_id"})
    if body is None or type(body.get("credential_id")) is not str or not body["credential_id"]:
        return jsonify({"error": "invalid_request"}), 400
    result = current_app.extensions["live_availability_service"].list_booking_categories(
        user_id=g.session_context.user.user_id,
        session_id=g.session_id,
        credential_id=body["credential_id"],
    )
    return jsonify(result)


@availability_live_bp.post("/grid")
@require_session
@require_csrf
def grid():
    body = _body({"credential_id", "scope_reference", "target_date"})
    if (body is None or any(type(body.get(key)) is not str or not body[key]
                            for key in ("credential_id", "scope_reference", "target_date"))):
        return jsonify({"error": "invalid_request"}), 400
    result = current_app.extensions["live_availability_service"].query_grid(
        user_id=g.session_context.user.user_id,
        session_id=g.session_id,
        credential_id=body["credential_id"],
        scope_reference=body["scope_reference"],
        target_date=body["target_date"],
    )
    return jsonify(result)
