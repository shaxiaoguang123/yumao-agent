from __future__ import annotations

import sqlite3
import time
from flask import Blueprint, current_app, g, jsonify

from backend.api.auth import require_csrf, require_session
from backend.api.plans import _body
from backend.ai.service import AIModelError
from backend.plans.service import PlanError

planning_bp = Blueprint("planning", __name__, url_prefix="/api/planning")


@planning_bp.errorhandler(AIModelError)
def _provider_error(exc):
    return jsonify({"error": exc.code}), exc.status


@planning_bp.errorhandler(PlanError)
def _error(exc):
    return jsonify({"error": exc.code, **({"fields": exc.fields} if exc.fields else {})}), exc.status


@planning_bp.errorhandler(sqlite3.Error)
def _storage(_exc):
    return jsonify({"error": "plan_storage_unavailable"}), 503


@planning_bp.post("/proposals")
@require_session
@require_csrf
def proposals():
    body = _body({"message", "plan_id", "base_version"})
    result = current_app.extensions["planning_service"].propose(
        g.session_context.user.user_id, body["message"], body["plan_id"], body["base_version"],
        time.time_ns() // 1_000_000,
    )
    return jsonify(result)
