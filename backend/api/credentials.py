from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone

from flask import Blueprint, current_app, g, jsonify, request

from backend.api.auth import require_csrf, require_session
from backend.credentials.types import CredentialDTO, CredentialOperationError, CredentialOperationResult
from backend.db import connect_database


credentials_bp = Blueprint("credentials", __name__, url_prefix="/api/credentials")
_MAX_JSON_BODY_BYTES = 64 * 1024


def _now_utc_ms() -> int:
    return time.time_ns() // 1_000_000


def _utc_iso8601(value: int | None) -> str | None:
    if value is None:
        return None
    seconds, milliseconds = divmod(value, 1000)
    return (
        datetime.fromtimestamp(seconds, timezone.utc)
        .replace(microsecond=milliseconds * 1000)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _serialize_attempt(value: dict | None) -> dict | None:
    if value is None:
        return None
    return {
        "validation_attempt_id": value["validation_attempt_id"],
        "operation_kind": value["operation_kind"],
        "current_token_revision_snapshot_id": value["current_token_revision_snapshot_id"],
        "token_revision_id": value["token_revision_id"],
        "started_at_utc": _utc_iso8601(value["started_at_utc_ms"]),
        "completed_at_utc": _utc_iso8601(value["completed_at_utc_ms"]),
        "attempt_result": value["attempt_result"],
        "account_binding_outcome": value["account_binding_outcome"],
        "apply_state": value["apply_state"],
    }


def _serialize_credential(value: CredentialDTO) -> dict:
    return {
        "credential_id": value.credential_id,
        "label": value.label,
        "credential_version": value.credential_version,
        "current_token_revision_id": value.current_token_revision_id,
        "enabled": value.enabled,
        "account_binding_state": value.account_binding_state,
        "requires_revalidation": value.requires_revalidation,
        "expiry_state": value.expiry_state,
        "token_expires_at_utc": _utc_iso8601(value.token_expires_at_utc_ms),
        "last_confirmed_validation_state": value.last_confirmed_validation_state,
        "last_successful_validation_at_utc": _utc_iso8601(
            value.last_successful_validation_at_utc_ms
        ),
        "latest_requested_validation_attempt": _serialize_attempt(
            value.latest_requested_validation_attempt
        ),
    }


def _parse_json_body() -> tuple[dict | None, tuple[dict, int] | None]:
    if request.content_length is not None and request.content_length > _MAX_JSON_BODY_BYTES:
        return None, ({"error": "request_too_large"}, 413)
    try:
        raw = request.stream.read(_MAX_JSON_BODY_BYTES + 1)
    except Exception:
        return None, ({"error": "invalid_request"}, 400)
    if len(raw) > _MAX_JSON_BODY_BYTES:
        return None, ({"error": "request_too_large"}, 413)
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, ({"error": "invalid_request"}, 400)
    if not isinstance(value, dict):
        return None, ({"error": "invalid_request"}, 400)
    return value, None


def _validated_body(allowed_fields: set[str], required_fields: set[str]) -> tuple[dict | None, object | None]:
    body, parse_error = _parse_json_body()
    if parse_error is not None:
        payload, status = parse_error
        return None, (jsonify(payload), status)
    assert body is not None
    if not required_fields <= body.keys() or not body.keys() <= allowed_fields:
        return None, (jsonify({"error": "invalid_request"}), 400)
    return body, None


def _current_gate_retry_after(now_utc_ms: int) -> int:
    connection = connect_database(
        current_app.config["DATABASE_PATH"],
        current_app.config["SQLITE_BUSY_TIMEOUT_MS"],
    )
    try:
        row = connection.execute(
            """SELECT lease_expires_at_utc_ms, next_allowed_at_utc_ms,
                      upstream_backoff_until_utc_ms, lease_owner_id
               FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"""
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return 1
    deadline = max(
        row["lease_expires_at_utc_ms"] or 0 if row["lease_owner_id"] is not None else 0,
        row["next_allowed_at_utc_ms"] or 0,
        row["upstream_backoff_until_utc_ms"] or 0,
    )
    remaining_ms = max(0, deadline - now_utc_ms)
    return max(1, math.ceil(remaining_ms / 1000))


def _json_error(
    code: str,
    status: int,
    retry_after_seconds: int | None = None,
    credential: CredentialDTO | None = None,
):
    if status == 401:
        # Upstream status codes never authenticate or invalidate the application Session.
        code = "upstream_validation_unknown"
        status = 502
    if status == 429 and retry_after_seconds is None:
        retry_after_seconds = _current_gate_retry_after(_now_utc_ms())
    payload: dict[str, object] = {"error": code}
    if credential is not None:
        payload["credential"] = _serialize_credential(credential)
    if retry_after_seconds is not None:
        retry_after_seconds = max(1, int(retry_after_seconds))
        payload["retry_after_seconds"] = retry_after_seconds
    response = jsonify(payload)
    response.status_code = status
    if status == 429 and retry_after_seconds is not None:
        response.headers["Retry-After"] = str(retry_after_seconds)
    return response


def _service_error(error: CredentialOperationError):
    return _json_error(error.code, error.http_status, error.retry_after_seconds)


def _operation_response(result: CredentialOperationResult):
    if result.http_status == 401:
        return _json_error("upstream_validation_unknown", 502)
    if not result.succeeded:
        return _json_error(
            result.code,
            result.http_status,
            result.retry_after_seconds,
            result.credential,
        )
    payload: dict[str, object] = {"result": result.code}
    if result.credential is not None:
        payload["credential"] = _serialize_credential(result.credential)
    if result.deleted:
        return current_app.response_class(status=204)
    retry_after = result.retry_after_seconds
    if result.http_status == 429 and retry_after is None:
        retry_after = _current_gate_retry_after(_now_utc_ms())
    if retry_after is not None:
        payload["retry_after_seconds"] = max(1, int(retry_after))
    response = jsonify(payload)
    response.status_code = result.http_status
    if result.http_status == 429 and retry_after is not None:
        response.headers["Retry-After"] = str(max(1, int(retry_after)))
    return response


def _user_id() -> str:
    return g.session_context.user.user_id


@credentials_bp.get("")
@require_session
def list_credentials():
    service = current_app.extensions["credential_service"]
    credentials = service.list_for_user(_user_id())
    return jsonify({"credentials": [_serialize_credential(item) for item in credentials]})


@credentials_bp.post("")
@require_session
@require_csrf
def create_credential():
    body, error = _validated_body({"label", "token"}, {"label", "token"})
    if error is not None:
        return error
    try:
        credential = current_app.extensions["credential_service"].create(
            _user_id(), body["label"], body["token"], _now_utc_ms()
        )
    except CredentialOperationError as exc:
        return _service_error(exc)
    return jsonify({"credential": _serialize_credential(credential)}), 201


@credentials_bp.post("/<credential_id>/validate")
@require_session
@require_csrf
def validate_credential(credential_id: str):
    body, error = _validated_body(
        {"expected_credential_version", "expected_current_token_revision_id"},
        {"expected_credential_version", "expected_current_token_revision_id"},
    )
    if error is not None:
        return error
    try:
        result = current_app.extensions["credential_service"].validate(
            _user_id(),
            credential_id,
            body["expected_credential_version"],
            body["expected_current_token_revision_id"],
            _now_utc_ms(),
        )
    except CredentialOperationError as exc:
        return _service_error(exc)
    return _operation_response(result)


@credentials_bp.post("/<credential_id>/rotate-token")
@require_session
@require_csrf
def rotate_credential_token(credential_id: str):
    body, error = _validated_body(
        {"token", "expected_credential_version", "expected_current_token_revision_id"},
        {"token", "expected_credential_version", "expected_current_token_revision_id"},
    )
    if error is not None:
        return error
    try:
        result = current_app.extensions["credential_service"].rotate_token(
            _user_id(),
            credential_id,
            body["expected_credential_version"],
            body["expected_current_token_revision_id"],
            body["token"],
            _now_utc_ms(),
        )
    except CredentialOperationError as exc:
        return _service_error(exc)
    return _operation_response(result)


@credentials_bp.patch("/<credential_id>")
@require_session
@require_csrf
def update_credential(credential_id: str):
    body, error = _validated_body(
        {"expected_credential_version", "label", "enabled"},
        {"expected_credential_version"},
    )
    if error is not None:
        return error
    if "label" not in body and "enabled" not in body:
        return _json_error("invalid_request", 400)
    service = current_app.extensions["credential_service"]
    current = service.get_for_user(_user_id(), credential_id)
    if current is None:
        return _json_error("credential_not_found", 404)
    enabled = body.get("enabled", current.enabled)
    try:
        result = service.set_enabled(
            _user_id(),
            credential_id,
            body["expected_credential_version"],
            enabled,
            _now_utc_ms(),
            label=body.get("label"),
        )
    except CredentialOperationError as exc:
        return _service_error(exc)
    return _operation_response(result)


@credentials_bp.delete("/<credential_id>")
@require_session
@require_csrf
def delete_credential(credential_id: str):
    body, error = _validated_body(
        {"expected_credential_version"}, {"expected_credential_version"}
    )
    if error is not None:
        return error
    try:
        result = current_app.extensions["credential_service"].soft_delete(
            _user_id(), credential_id, body["expected_credential_version"], _now_utc_ms()
        )
    except CredentialOperationError as exc:
        return _service_error(exc)
    return _operation_response(result)
