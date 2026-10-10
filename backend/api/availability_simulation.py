import sqlite3
import time
from flask import Blueprint, current_app, g, jsonify

from backend.api.auth import require_session, require_csrf
from backend.api.plans import _body
from backend.availability_matching.models import AvailabilityError
from backend.plans.service import PlanError

availability_simulation_bp = Blueprint('availability_simulation', __name__, url_prefix='/api/availability/simulation')


@availability_simulation_bp.errorhandler(AvailabilityError)
@availability_simulation_bp.errorhandler(PlanError)
def _error(exc):
    return jsonify({'error': exc.code}), exc.status


@availability_simulation_bp.errorhandler(sqlite3.Error)
def _storage(_exc):
    return jsonify({'error': 'plan_storage_unavailable'}), 503


@availability_simulation_bp.get('/options')
@require_session
def options():
    return jsonify(current_app.extensions['availability_simulation_service'].options())


@availability_simulation_bp.post('/plans/<plan_id>')
@require_session
@require_csrf
def simulate(plan_id):
    body = _body({'base_version', 'scenario'})
    return jsonify(current_app.extensions['availability_simulation_service'].simulate(
        g.session_context.user.user_id, plan_id, body['base_version'], body['scenario'], time.time_ns() // 1_000_000))
