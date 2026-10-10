from __future__ import annotations

import json
import sqlite3

from flask import Blueprint, current_app, g, jsonify

from backend.ai.service import AIModelError
from backend.api.auth import require_csrf, require_session


ai_models_bp = Blueprint("ai_models", __name__, url_prefix="/api/ai/models")
MAX_BODY = 16 * 1024


def _body(required: set[str], allowed: set[str]):
    from flask import request
    if request.content_length is not None and request.content_length > MAX_BODY:
        raise AIModelError("request_too_large", 413)
    if request.mimetype != "application/json":
        raise AIModelError("invalid_request", 400)
    raw = request.stream.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY: raise AIModelError("request_too_large", 413)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise AIModelError("invalid_request", 400) from None
    if type(value) is not dict or not required <= value.keys() or not value.keys() <= allowed:
        raise AIModelError("invalid_request", 400)
    return value


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("invalid JSON constant")


def _service(): return current_app.extensions["ai_provider_service"]
def _user_id(): return g.session_context.user.user_id


@ai_models_bp.errorhandler(AIModelError)
def _error(error): return jsonify({"error": error.code}), error.status


@ai_models_bp.errorhandler(sqlite3.Error)
def _storage_error(_error):
    return jsonify({"error": "provider_storage_unavailable"}), 503


@ai_models_bp.get("")
@require_session
def list_models():
    return jsonify(_service().list_models(_user_id()))


@ai_models_bp.post("")
@require_session
@require_csrf
def create_model():
    body = _body({"name", "base_url", "model", "auth_mode"}, {"name", "base_url", "model", "auth_mode", "api_key"})
    result = _service().create(_user_id(), body["name"], body["base_url"], body["model"], body["auth_mode"], body.get("api_key"))
    return jsonify({"model": result}), 201


@ai_models_bp.patch("/<model_id>")
@require_session
@require_csrf
def update_model(model_id):
    body = _body({"base_version", "name", "base_url", "model", "auth_mode"},
                 {"base_version", "name", "base_url", "model", "auth_mode", "api_key", "delete_api_key"})
    result = _service().update(_user_id(), model_id, body)
    return jsonify({"model": result})


@ai_models_bp.delete("/<model_id>")
@require_session
@require_csrf
def delete_model(model_id):
    body = _body({"base_version"}, {"base_version"})
    _service().delete(_user_id(), model_id, body["base_version"])
    return current_app.response_class(status=204)


@ai_models_bp.patch("/preferences")
@require_session
@require_csrf
def set_preferences():
    body = _body({"selected_model_id", "default_model_id"}, {"selected_model_id", "default_model_id"})
    if any(value is not None and not isinstance(value, str) for value in body.values()):
        raise AIModelError("invalid_request", 400)
    _service().set_preferences(_user_id(), body["selected_model_id"], body["default_model_id"])
    return jsonify(_service().list_models(_user_id()))


@ai_models_bp.post("/<model_id>/test")
@require_session
@require_csrf
def test_model(model_id):
    _body(set(), set())
    return jsonify(_service().test(_user_id(), model_id))
