from __future__ import annotations

import logging
from urllib.parse import urlsplit

from flask import Flask, current_app, jsonify, request


_ALLOWED_METHODS = "GET, POST, PATCH, DELETE, OPTIONS"
_ALLOWED_HEADERS = "Content-Type, X-CSRF-Token"


def _origin_from(value: str, *, allow_path: bool) -> str | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        if not allow_path and (parsed.path or parsed.query or parsed.fragment):
            return None
        if parsed.fragment:
            return None
        if not allow_path and parsed.query:
            return None
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    except (TypeError, ValueError):
        return None


def _allowed_origins() -> set[str]:
    values = current_app.config.get("ALLOWED_ORIGINS", ())
    origins: set[str] = set()
    for value in values:
        parsed = _origin_from(str(value), allow_path=False)
        if parsed is not None:
            origins.add(parsed)
    return origins


def _request_origins() -> list[str]:
    values: list[str] = []
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    if origin:
        parsed_origin = _origin_from(origin, allow_path=False)
        if parsed_origin is None:
            return [""]
        values.append(parsed_origin)
    if referer:
        parsed_referer = _origin_from(referer, allow_path=True)
        if parsed_referer is None:
            return [""]
        values.append(parsed_referer)
    return values


def request_origin_is_allowed() -> bool:
    origins = _request_origins()
    return bool(origins) and all(origin in _allowed_origins() for origin in origins)


def _origin_for_cors() -> str | None:
    origin = request.headers.get("Origin")
    if not origin:
        return None
    parsed = _origin_from(origin, allow_path=False)
    if parsed is not None and parsed in _allowed_origins():
        return parsed
    return None


def init_security(app: Flask) -> None:
    werkzeug_logger = logging.getLogger("werkzeug")
    if not any(isinstance(item, _RedactWerkzeugRequestLog) for item in werkzeug_logger.filters):
        werkzeug_logger.addFilter(_RedactWerkzeugRequestLog())

    @app.before_request
    def validate_mutation_origin():
        if request.method == "OPTIONS" and request.headers.get("Access-Control-Request-Method"):
            if not request_origin_is_allowed():
                return jsonify({"error": "origin_not_allowed"}), 403
            response = current_app.response_class(status=204)
            response.headers["Access-Control-Allow-Methods"] = _ALLOWED_METHODS
            response.headers["Access-Control-Allow-Headers"] = _ALLOWED_HEADERS
            response.headers["Access-Control-Max-Age"] = "600"
            return response

        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not request_origin_is_allowed():
            return jsonify({"error": "origin_not_allowed"}), 403
        return None

    @app.after_request
    def add_cors_headers(response):
        response.vary.add("Origin")
        allowed_origin = _origin_for_cors()
        if allowed_origin is not None:
            response.headers["Access-Control-Allow-Origin"] = allowed_origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = _ALLOWED_METHODS
            response.headers["Access-Control-Allow-Headers"] = _ALLOWED_HEADERS
        return response


class _RedactWerkzeugRequestLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = "HTTP server event"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True
