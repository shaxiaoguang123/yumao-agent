from flask import Blueprint, current_app, jsonify

from backend.api.auth import require_csrf, require_session
from backend.api.plans import _body
from backend.availability_matching.models import AvailabilityError
from backend.plans.service import PlanError


availability_history_bp = Blueprint("availability_history", __name__, url_prefix="/api/availability/history")


@availability_history_bp.errorhandler(AvailabilityError)
@availability_history_bp.errorhandler(PlanError)
def _error(exc):
    return jsonify({"error": exc.code}), exc.status


@availability_history_bp.post("/preview")
@require_session
@require_csrf
def preview():
    body = _body({"response"}, max_body_bytes=128 * 1024)
    # The adapter returns display-only fields; the submitted capture is not persisted
    # or logged and its upstream identifiers/prices are never returned.
    return jsonify(current_app.extensions["availability_simulation_service"].preview_history(body["response"]))
