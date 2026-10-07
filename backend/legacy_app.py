from __future__ import annotations

import json
import os
import random
import socket
import sys
from collections import deque
from datetime import datetime
from pathlib import Path
import time as _time

from flask import Flask, jsonify, request, send_from_directory

ROOT_DIR = Path(os.environ.get("APP_ROOT_DIR", "").strip()) if os.environ.get("APP_ROOT_DIR", "").strip() else Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.availability import build_availability_payload
from backend.client import ApiClient
from backend.config import BASE_URL, DEFAULT_NODEID, TOKEN
from backend.flow import fetch_booking_by_time, fetch_order_details, fetch_orders, run_plan
from backend.logging_utils import setup_logging, get_api_logger, get_frontend_logger
from backend.plan_validation import PlanValidationError, load_plan_file, normalize_plan_payload
from backend.time_utils import build_timing_payload, today_str
from backend.time_utils import normalize_bool

app = Flask(__name__)
PLAN_PATH = ROOT_DIR / "booking_plan.json"
LOG_DIR = ROOT_DIR / "backend" / "logs"
RUN_LOG_NAME = "run_flow"

setup_logging(RUN_LOG_NAME)
API_LOG = get_api_logger()
FE_LOG = get_frontend_logger()

LOG_SOURCES = {
    "run_flow": RUN_LOG_NAME,
    "http_client": "http_client",
    "api_server": "api_server",
    "frontend": "frontend",
}


@app.before_request
def _log_request_start():
    setattr(request, "_start_time", _time.perf_counter())


@app.after_request
def _log_request(response):
    if request.path in ("/api/logs", "/api/frontend-log"):
        return response
    elapsed = (_time.perf_counter() - getattr(request, "_start_time", _time.perf_counter())) * 1000
    body_summary = ""
    if request.content_type and "json" in request.content_type:
        raw = request.get_data(as_text=True)
        body_summary = (raw[:300] + "...") if len(raw) > 300 else raw
    API_LOG.info(
        "%s %s %s -> %d (%.1fms) body=%s",
        request.method,
        request.path,
        request.query_string.decode("utf-8", errors="replace")[:200],
        response.status_code,
        elapsed,
        body_summary or "-",
    )
    return response


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.get("/api/availability")
def availability():
    if not TOKEN:
        return jsonify({"error": "TOKEN missing in new/.env"}), 400
    date_str = (request.args.get("date") or "").strip()
    nodeid = (request.args.get("nodeid") or DEFAULT_NODEID).strip()
    if not date_str:
        return jsonify({"error": "date is required"}), 400

    client = ApiClient(BASE_URL)
    try:
        resp = fetch_booking_by_time(client, TOKEN, nodeid, date_str)
        payload = build_availability_payload(resp)
        payload["timing"] = build_timing_payload(payload.get("meta") or {}, date_str)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"success": True, "data": payload})


@app.get("/api/plan")
def plan():
    if not PLAN_PATH.exists():
        return jsonify({"success": True, "data": None})
    try:
        data = load_plan_file(PLAN_PATH)
    except PlanValidationError as exc:
        return jsonify({"error": str(exc), "details": exc.details}), 400
    except Exception as exc:
        return jsonify({"error": f"load failed: {exc}"}), 400
    return jsonify({"success": True, "data": data})


@app.post("/api/save_plan")
def save_plan():
    data = request.get_json(silent=True) or {}
    try:
        normalized = normalize_plan_payload(data)
        PLAN_PATH.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except PlanValidationError as exc:
        return jsonify({"error": str(exc), "details": exc.details}), 400
    except Exception as exc:
        return jsonify({"error": f"save failed: {exc}"}), 400
    return jsonify({"success": True, "path": str(PLAN_PATH)})


@app.post("/api/run")
def run_flow():
    data = request.get_json(silent=True) or {}
    try:
        result = run_plan(PLAN_PATH, auto_run=normalize_bool(data.get("autoRun")))
    except PlanValidationError as exc:
        return jsonify({"success": False, "message": str(exc), "details": exc.details}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": f"run failed: {exc}"}), 400
    if not result.success:
        return jsonify({"success": False, "message": result.message, "details": result.details}), 400
    return jsonify({"success": True, "message": result.message, "details": result.details})


@app.get("/api/orders")
def orders():
    """
    List user's orders (already created/paid appointments).

    Upstream endpoint: /phone/payOrderForPhone
    """
    if not TOKEN:
        return jsonify({"error": "TOKEN missing in new/.env"}), 400

    try:
        page_number = int(request.args.get("pageNumber") or 1)
        page_size = int(request.args.get("pageSize") or 10)
        order_type = int(request.args.get("ordertype") or 1)
    except Exception:
        return jsonify({"error": "invalid pageNumber/pageSize/ordertype"}), 400

    client = ApiClient(BASE_URL)
    try:
        resp = fetch_orders(client, TOKEN, page_number=page_number, page_size=page_size, order_type=order_type)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    if not resp.get("success"):
        return jsonify({"success": False, "message": resp.get("message"), "details": resp}), 400
    return jsonify({"success": True, "data": resp.get("resultData")})


@app.get("/api/order_details")
def order_details():
    """
    Query order details.

    Note: upstream needs bookingno + id (not orderno).
    """
    if not TOKEN:
        return jsonify({"error": "TOKEN missing in new/.env"}), 400

    bookingno = (request.args.get("bookingno") or "").strip()
    order_id = (request.args.get("id") or "").strip()
    if not bookingno or not order_id:
        return jsonify({"error": "bookingno and id are required"}), 400

    client = ApiClient(BASE_URL)
    try:
        resp = fetch_order_details(client, TOKEN, bookingno=bookingno, order_id=order_id)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    if not resp.get("success"):
        return jsonify({"success": False, "message": resp.get("message"), "details": resp}), 400
    return jsonify({"success": True, "data": resp.get("resultData")})


def _tail_lines(path: Path, limit: int) -> list[str]:
    if limit <= 0:
        return []
    lines: deque[str] = deque(maxlen=limit)
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            lines.append(line.rstrip("\n"))
    return list(lines)


@app.get("/api/logs")
def logs():
    date_str = (request.args.get("date") or "").strip()
    try:
        limit = int(request.args.get("limit") or 200)
    except (ValueError, TypeError):
        return jsonify({"error": "limit must be an integer"}), 400
    limit = max(1, min(limit, 2000))
    source = (request.args.get("source") or "run_flow").strip()
    if source not in LOG_SOURCES:
        return jsonify({"error": f"invalid source, allowed: {', '.join(LOG_SOURCES)}"}), 400
    log_name = LOG_SOURCES[source]

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    base_log = LOG_DIR / f"{log_name}.log"
    if date_str:
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "invalid date format, expected YYYY-MM-DD"}), 400
        current_date = today_str()
        if date_str == current_date:
            target = base_log
        else:
            target = LOG_DIR / f"{log_name}.log.{date_str}"
    else:
        target = base_log

    if not target.exists():
        return jsonify({"success": True, "data": {"date": date_str or today_str(), "lines": []}})

    try:
        lines = _tail_lines(target, limit)
    except Exception as exc:
        return jsonify({"error": f"read logs failed: {exc}"}), 400

    return jsonify({"success": True, "data": {"date": date_str or today_str(), "lines": lines}})


@app.delete("/api/logs")
def clear_logs():
    date_str = (request.args.get("date") or "").strip()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    source = (request.args.get("source") or "run_flow").strip()
    if source not in LOG_SOURCES:
        return jsonify({"success": False, "message": f"invalid source, allowed: {', '.join(LOG_SOURCES)}"}), 400
    log_name = LOG_SOURCES[source]
    base_log = LOG_DIR / f"{log_name}.log"

    if date_str:
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"success": False, "message": "invalid date format, expected YYYY-MM-DD"}), 400
        current_date = today_str()
        if date_str == current_date:
            target = base_log
        else:
            target = LOG_DIR / f"{log_name}.log.{date_str}"
    else:
        target = base_log

    if not target.exists():
        return jsonify({"success": True, "message": "log file not found, nothing to clear"})

    try:
        with target.open("w", encoding="utf-8") as f:
            f.truncate(0)
    except Exception as exc:
        return jsonify({"success": False, "message": f"clear logs failed: {exc}"}), 500

    return jsonify({"success": True, "message": f"cleared {target.name}"})


def _sanitize_log_field(value: str, max_len: int = 500) -> str:
    """Remove control chars that could forge log lines; cap length."""
    return value.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")[:max_len]


@app.post("/api/frontend-log")
def frontend_log():
    data = request.get_json(silent=True) or {}
    level = str(data.get("level") or "info").lower()
    action = _sanitize_log_field(str(data.get("action") or "unknown"), 100)
    detail = _sanitize_log_field(str(data.get("detail") or ""), 500)
    ts = _sanitize_log_field(str(data.get("ts") or ""), 40)
    msg = "[frontend] action=%s ts=%s detail=%s"
    args = (action, ts, detail or "-")
    if level == "error":
        FE_LOG.error(msg, *args)
    elif level == "warn":
        FE_LOG.warning(msg, *args)
    else:
        FE_LOG.info(msg, *args)
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Static file serving (for EXE mode: Flask serves the Vue dist/ folder)
# ---------------------------------------------------------------------------

DIST_DIR = ROOT_DIR / "frontend" / "dist"


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    """Serve the Vue SPA from frontend/dist/.

    API routes are registered before this catch-all, so they take priority.
    """
    if path and (DIST_DIR / path).is_file():
        return send_from_directory(str(DIST_DIR), path)
    return send_from_directory(str(DIST_DIR), "index.html")


# ---------------------------------------------------------------------------
# Port selection helpers
# ---------------------------------------------------------------------------

# Uncommon ports unlikely to conflict with well-known services
_PORT_POOL = [
    18930, 19847, 21073, 23156, 24891, 26743, 28517, 29634,
    31247, 32891, 34567, 36219, 37843, 39471, 41023, 42657,
]


def _is_port_free(port: int) -> bool:
    """Return True if *port* on 127.0.0.1 is available."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def find_free_port(preferred: int | None = None) -> int:
    """Pick an available port.

    1. Try *preferred* first (if given).
    2. Shuffle the pool and try each.
    3. Fall back to OS-assigned port (bind to 0).
    """
    if preferred and _is_port_free(preferred):
        return preferred
    pool = list(_PORT_POOL)
    random.shuffle(pool)
    for port in pool:
        if _is_port_free(port):
            return port
    # Ultimate fallback: let the OS pick
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5175, debug=True)
