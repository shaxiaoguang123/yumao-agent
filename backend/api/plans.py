from __future__ import annotations

import json
import sqlite3
import time
from flask import Blueprint, current_app, g, jsonify, request

from backend.api.auth import require_csrf, require_session
from backend.plans.service import PlanError

plans_bp = Blueprint("plans", __name__, url_prefix="/api/plans")
MAX_PLAN_BODY_BYTES = 16 * 1024


def _now_utc_ms():
    return time.time_ns() // 1_000_000


def _reject_constant(_value):
    raise ValueError("nonstandard JSON")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _body(required_fields: set[str]) -> dict:
    if request.content_length is not None and request.content_length > MAX_PLAN_BODY_BYTES:
        raise PlanError("request_too_large", 413)
    if request.mimetype != "application/json":
        raise PlanError("invalid_request", 400)
    raw = request.stream.read(MAX_PLAN_BODY_BYTES + 1)
    if len(raw) > MAX_PLAN_BODY_BYTES:
        raise PlanError("request_too_large", 413)
    try:
        body = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise PlanError("invalid_request", 400) from None
    if type(body) is not dict or body.keys() != required_fields:
        raise PlanError("invalid_request", 400)
    return body


def _service():
    return current_app.extensions["plan_service"]


def _user_id():
    return g.session_context.user.user_id


@plans_bp.errorhandler(PlanError)
def _plan_error(error):
    return jsonify({"error": error.code, **({"fields": error.fields} if error.fields else {})}), error.status


@plans_bp.errorhandler(sqlite3.Error)
def _storage_error(_error):
    return jsonify({"error": "plan_storage_unavailable"}), 503


@plans_bp.get("")
@require_session
def list_plans():
    return jsonify({"plans": _service().list_plans(_user_id(), _now_utc_ms())})


@plans_bp.get("/options")
@require_session
def options():
    if request.args:
        raise PlanError("invalid_request", 400)
    return jsonify({"catalog_status": "not_configured", "venues": [], "context": _service().active_context.to_dict()})


@plans_bp.post("")
@require_session
@require_csrf
def create_plan():
    body = _body({"intent"})
    return jsonify({"plan": _service().create_plan(_user_id(), body["intent"], _now_utc_ms())}), 201


@plans_bp.get("/<plan_id>")
@require_session
def get_plan(plan_id):
    return jsonify({"plan": _service().get_plan(_user_id(), plan_id, _now_utc_ms())})


@plans_bp.patch("/<plan_id>")
@require_session
@require_csrf
def update_plan(plan_id):
    body = _body({"base_version", "intent"})
    return jsonify({"plan": _service().update_plan(_user_id(), plan_id, body["base_version"], body["intent"], _now_utc_ms())})


@plans_bp.get("/<plan_id>/revisions")
@require_session
def revisions(plan_id):
    return jsonify({"revisions": _service().list_revisions(_user_id(), plan_id, _now_utc_ms())})
