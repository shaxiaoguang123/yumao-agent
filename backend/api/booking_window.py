from flask import Blueprint, current_app, jsonify, request

from backend.api.auth import require_session
from backend.api.plans import _now_utc_ms
from backend.plans.models import describe_window
from backend.plans.validation import IntentValidationError, parse_target_date

booking_window_bp = Blueprint("booking_window", __name__)


@booking_window_bp.get("/api/booking-window")
@require_session
def booking_window():
    if set(request.args) - {"target_date"} or len(request.args.getlist("target_date")) > 1:
        return jsonify({"error": "invalid_request"}), 400
    policy = current_app.extensions["plan_service"].policy
    now = _now_utc_ms()
    try:
        target = parse_target_date(request.args["target_date"]) if "target_date" in request.args else policy.queryable_target_dates(now)[2]
        result = describe_window(policy, target, now)
    except (IntentValidationError, ValueError, OverflowError):
        return jsonify({"error": "invalid_target_date"}), 400
    return jsonify(result)
