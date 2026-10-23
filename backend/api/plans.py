from __future__ import annotations

import json
import sqlite3
import time
from flask import Blueprint, current_app, g, jsonify, request

from backend.api.auth import require_csrf, require_session
from backend.plans.service import PlanError

plans_bp = Blueprint("plans", __name__, url_prefix="/api/plans")
MAX_PLAN_BODY_BYTES = 16 * 1024
# A complete legal 1h + 2h grid for ten courts is about 30 KiB. Keep a
# transport bound without reintroducing a candidate-count limit.
MAX_MANUAL_QUEUE_BODY_BYTES = 64 * 1024


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


def _body(required_fields: set[str], optional_fields: set[str] | None = None, *, max_body_bytes=MAX_PLAN_BODY_BYTES) -> dict:
    if request.content_length is not None and request.content_length > max_body_bytes:
        raise PlanError("request_too_large", 413)
    if request.mimetype != "application/json":
        raise PlanError("invalid_request", 400)
    raw = request.stream.read(max_body_bytes + 1)
    if len(raw) > max_body_bytes:
        raise PlanError("request_too_large", 413)
    try:
        body = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise PlanError("invalid_request", 400) from None
    optional_fields = optional_fields or set()
    if (type(body) is not dict or not required_fields.issubset(body)
            or body.keys() - required_fields - optional_fields):
        raise PlanError("invalid_request", 400)
    return body


def _service():
    return current_app.extensions["plan_service"]


def _user_id():
    return g.session_context.user.user_id


def _credential_scope(value):
    if value is None:
        return None
    if type(value) is not str or not value:
        raise PlanError("invalid_request", 400)
    if current_app.extensions["credential_service"].get_for_user(_user_id(), value) is None:
        raise PlanError("credential_not_found", 404)
    return value


def _query_credential_scope(extra_fields=()):
    if set(request.args.keys()) - {"credential_id", *extra_fields} or any(len(request.args.getlist(key)) > 1 for key in request.args):
        raise PlanError("invalid_request", 400)
    return _credential_scope(request.args.get("credential_id"))


def _revision_pagination():
    try:
        limit = int(request.args["limit"]) if "limit" in request.args else None
        before = int(request.args["before_version"]) if "before_version" in request.args else None
        if (limit is not None and not 1 <= limit <= 50) or (before is not None and not 1 <= before <= 9007199254740991):
            raise ValueError
    except ValueError:
        raise PlanError("invalid_request", 400) from None
    return limit, {"limit": limit + 1 if limit is not None else None, "before_version": before}


def _revision_response(rows, limit):
    more = limit is not None and len(rows) > limit
    visible = rows[:limit] if limit is not None else rows
    return jsonify({"revisions": visible, "next_before_version": visible[-1]["revision_number"] if more else None})


@plans_bp.errorhandler(PlanError)
def _plan_error(error):
    return jsonify({"error": error.code, **({"fields": error.fields} if error.fields else {})}), error.status


@plans_bp.errorhandler(sqlite3.Error)
def _storage_error(_error):
    return jsonify({"error": "plan_storage_unavailable"}), 503


@plans_bp.get("")
@require_session
def list_plans():
    credential_id = _query_credential_scope({"view"})
    if request.args.get("view") not in (None, "current"):
        raise PlanError("invalid_request", 400)
    return jsonify({"plans": _service().list_plans(_user_id(), _now_utc_ms(), credential_id, recent_only=request.args.get("view")=="current")})


@plans_bp.get("/options")
@require_session
def options():
    if request.args:
        raise PlanError("invalid_request", 400)
    catalog = current_app.extensions["venue_catalog_service"].public_options()
    # Semantic intent labels; the executor still resolves actual inventory independently.
    return jsonify({**catalog, "context": _service().active_context.to_dict(),
                    "manual_queue_court_labels": [f"{number}号场" for number in range(1, 11)]})


@plans_bp.post("")
@require_session
@require_csrf
def create_plan():
    body = _body({"intent"}, {"credential_id"})
    credential_id = _credential_scope(body.get("credential_id"))
    return jsonify({"plan": _service().create_plan(_user_id(), body["intent"], _now_utc_ms(), credential_id)}), 201


@plans_bp.get("/<plan_id>")
@require_session
def get_plan(plan_id):
    credential_id = _query_credential_scope()
    return jsonify({"plan": _service().get_plan(_user_id(), plan_id, _now_utc_ms(), credential_id)})


@plans_bp.patch("/<plan_id>")
@require_session
@require_csrf
def update_plan(plan_id):
    body = _body({"base_version", "intent"}, {"credential_id"})
    credential_id = _credential_scope(body.get("credential_id"))
    return jsonify({"plan": _service().update_plan(_user_id(), plan_id, body["base_version"], body["intent"], _now_utc_ms(), credential_id)})


@plans_bp.get("/<plan_id>/revisions")
@require_session
def revisions(plan_id):
    credential_id = _query_credential_scope({"limit", "before_version"})
    limit, page = _revision_pagination()
    return _revision_response(_service().list_revisions(_user_id(), plan_id, _now_utc_ms(), credential_id, **page), limit)


# Dedicated routes keep queue drafts out of the single-intent Matcher / Agent APIs.
def _queue_date(value):
    from backend.plans.validation import parse_target_date, IntentValidationError
    try:
        return parse_target_date(value).isoformat()
    except IntentValidationError as exc:
        raise PlanError("invalid_plan", 400, exc.fields) from exc


@plans_bp.get("/manual-queues")
@require_session
def manual_queues():
    credential_id = _query_credential_scope({"view"})
    if request.args.get("view") not in (None, "current"):
        raise PlanError("invalid_request", 400)
    return jsonify({"queues": _service().list_manual_queues(_user_id(), credential_id,
                    recent_only=request.args.get("view")=="current", now_utc_ms=_now_utc_ms())})


@plans_bp.get("/manual-queues/<target_date>")
@require_session
def manual_queue(target_date):
    credential_id = _query_credential_scope()
    return jsonify({"queue": _service().get_manual_queue(_user_id(), _queue_date(target_date), credential_id)})


@plans_bp.put("/manual-queues/<target_date>")
@require_session
@require_csrf
def save_manual_queue(target_date):
    body = _body(
        {"base_version", "entries"},
        {"credential_id"},
        max_body_bytes=MAX_MANUAL_QUEUE_BODY_BYTES,
    )
    credential_id = _credential_scope(body.get("credential_id"))
    return jsonify({"queue": _service().save_manual_queue(_user_id(), _queue_date(target_date), body["base_version"], body["entries"], _now_utc_ms(), credential_id)})


@plans_bp.get("/manual-queues/<target_date>/revisions")
@require_session
def manual_queue_revisions(target_date):
    credential_id = _query_credential_scope({"limit", "before_version"})
    limit, page = _revision_pagination()
    return _revision_response(_service().manual_queue_revisions(_user_id(), _queue_date(target_date), credential_id, **page), limit)


@plans_bp.delete("/<plan_id>")
@require_session
@require_csrf
def delete_plan(plan_id):
    body = _body({"base_version"}, {"credential_id"})
    credential_id = _credential_scope(body.get("credential_id"))
    _service().delete_plan(_user_id(), plan_id, body["base_version"], _now_utc_ms(), credential_id)
    return jsonify({"deleted": True})


@plans_bp.delete("/manual-queues/<target_date>")
@require_session
@require_csrf
def delete_manual_queue(target_date):
    body = _body({"base_version"}, {"credential_id"})
    credential_id = _credential_scope(body.get("credential_id"))
    return jsonify({"queue": _service().delete_manual_queue(_user_id(), _queue_date(target_date), body["base_version"], _now_utc_ms(), credential_id)})
