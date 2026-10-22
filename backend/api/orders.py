from __future__ import annotations

import json

from flask import Blueprint, current_app, g, jsonify, request

from backend.api.auth import require_csrf, require_session
from backend.credentials.types import CredentialOperationError
from backend.execution.protocol import UpstreamCallError
from backend.orders.service import OrderQueryError


orders_bp = Blueprint("orders", __name__, url_prefix="/api/orders")


def _body(required: set[str], optional: set[str] = frozenset()) -> dict:
    if request.mimetype != "application/json" or (request.content_length or 0) > 8192:
        raise OrderQueryError("invalid_order_query")
    try:
        raw = request.stream.read(8193)
        if len(raw) > 8192:
            raise ValueError
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        raise OrderQueryError("invalid_order_query") from None
    if type(value) is not dict or not required <= value.keys() <= required | optional:
        raise OrderQueryError("invalid_order_query")
    return value


@orders_bp.after_request
def _private_response(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@orders_bp.errorhandler(OrderQueryError)
def _query_error(error):
    return jsonify({"error": error.code}), error.status


@orders_bp.errorhandler(CredentialOperationError)
def _credential_error(error):
    return _safe_error(error.code, error.http_status, error.retry_after_seconds)


def _safe_error(code, status, retry_after=None):
    payload = {"error": code}
    if retry_after is not None:
        payload["retry_after_seconds"] = max(1, min(900, retry_after))
    response = jsonify(payload)
    response.status_code = status
    if retry_after is not None:
        response.headers["Retry-After"] = str(payload["retry_after_seconds"])
    return response


@orders_bp.errorhandler(UpstreamCallError)
def _upstream_error(error):
    code = error.safe_code
    if code in {"upstream_read_rate_limited", "validation_rate_limited", "upstream_http_429"}:
        return _safe_error("order_query_rate_limited", 429, error.retry_after_seconds)
    if code in {"upstream_http_401", "upstream_http_403"}:
        return _safe_error("order_upstream_authentication_failed", 422)
    if code in {"credential_not_found", "credential_token_expired", "credential_token_invalid",
                "credential_disabled", "credential_requires_revalidation",
                "credential_account_binding_unresolved", "credential_account_reconfirmation_required"}:
        return _safe_error(code, 404 if code == "credential_not_found" else 422)
    return _safe_error("order_query_failed", 502)


@orders_bp.post("/query")
@require_session
@require_csrf
def query_orders():
    body = _body({"credential_id"}, {"page", "page_size", "status"})
    return jsonify(current_app.extensions["order_query_service"].list(
        g.session_context.user.user_id, g.session_id, body["credential_id"],
        page=body.get("page", 1), page_size=body.get("page_size", 10), status=body.get("status", ""),
    ))


@orders_bp.post("/details")
@require_session
@require_csrf
def order_details():
    body = _body({"credential_id", "reference"})
    return jsonify(current_app.extensions["order_query_service"].detail(
        g.session_context.user.user_id, g.session_id, body["credential_id"], body["reference"],
    ))
