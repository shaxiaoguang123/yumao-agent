from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from flask import Blueprint, current_app, g, jsonify, request

from backend.api.auth import require_admin, require_session
from backend.diagnostics import DiagnosticsUnavailable, LEVELS, MODULES, record_event, valid_code, valid_identifier
from backend.metrics import overview
from backend.db import connect_database


diagnostics_bp = Blueprint("diagnostics",__name__)


@diagnostics_bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@diagnostics_bp.errorhandler(DiagnosticsUnavailable)
def logs_unavailable(_error):
    return jsonify({"error":"runtime_logs_unavailable","collection":current_app.extensions["runtime_diagnostics"].status()}),503


@diagnostics_bp.errorhandler(sqlite3.Error)
def metrics_unavailable(_error):
    return jsonify({"error":"metrics_unavailable"}),503


@diagnostics_bp.get("/api/metrics/overview")
@require_session
def personal_metrics():
    return jsonify(overview(current_app.extensions["app_settings"],time.time_ns()//1_000_000,
                            user_id=g.session_context.user.user_id))


@diagnostics_bp.get("/api/admin/metrics")
@require_session
@require_admin
def system_metrics():
    record_event("admin","admin.metrics_read")
    return jsonify(overview(current_app.extensions["app_settings"],time.time_ns()//1_000_000,
                            diagnostics=current_app.extensions["runtime_diagnostics"]))


@diagnostics_bp.get("/api/admin/logs")
@require_session
@require_admin
def logs():
    now = time.time_ns()//1_000_000
    allowed = {"hours","since","until","limit","before","level","module","user_id","code","request_id","conversation_id","run_id"}
    if not request.args.keys() <= allowed or any(len(request.args.getlist(key))!=1 for key in request.args):
        return jsonify({"error":"invalid_log_query"}),400
    try:
        hours = int(request.args.get("hours",24))
        if hours not in {1,24,168,336}:
            raise ValueError
        since,until = int(request.args.get("since",now-hours*3600000)),int(request.args.get("until",now))
        limit = int(request.args.get("limit",50))
        before = int(request.args["before"]) if "before" in request.args else None
        if not 1<=limit<=100 or not 0<=since<=until<=now+60000 or until-since>14*86400000 or (before is not None and not 0<before<2**63):
            raise ValueError
    except ValueError:
        return jsonify({"error":"invalid_log_query"}),400
    filters = {key:request.args[key] for key in allowed-{"hours","since","until","limit","before"} if request.args.get(key)}
    for key,value in filters.items():
        if ((key=="level" and value not in LEVELS) or (key=="module" and value not in MODULES)
                or (key=="code" and not valid_code(value))
                or (key not in {"level","module","code"} and not valid_identifier(value))):
            return jsonify({"error":"invalid_log_query"}),400
    result = current_app.extensions["runtime_diagnostics"].query(filters,since=since,until=until,limit=limit,before=before)
    record_event("admin","admin.logs_read",candidate_count=len(result["events"]))
    return jsonify({**result,"queried_at_utc_ms":now,"window":{"since":since,"until":until}})


@diagnostics_bp.get("/api/admin/logs/<int:event_id>")
@require_session
@require_admin
def log_detail(event_id):
    if not 0<event_id<2**63:
        return jsonify({"error":"invalid_log_query"}),400
    result = current_app.extensions["runtime_diagnostics"].detail(event_id)
    if result is None:
        return jsonify({"error":"runtime_event_not_found"}),404
    run_id = result["event"].get("run_id")
    if run_id:
        with closing(connect_database(current_app.config["DATABASE_PATH"],current_app.config["SQLITE_BUSY_TIMEOUT_MS"])) as db:
            run = db.execute("SELECT target_date,state,clock_offset_ms,clock_uncertainty_ms FROM booking_execution_runs WHERE run_id=?",(run_id,)).fetchone()
            if run:
                rows = db.execute("""SELECT stage_key,round_number,candidate_index,started_at_utc_ms,
                    completed_at_utc_ms,elapsed_ms,outcome,safe_code FROM booking_execution_stages
                    WHERE run_id=? ORDER BY started_at_utc_ms DESC,stage_id DESC LIMIT 501""",(run_id,)).fetchall()
                result["execution"] = {**dict(run),"stages":[dict(row) for row in reversed(rows[:500])],"truncated":len(rows)>500}
    record_event("admin","admin.log_detail_read")
    return jsonify(result)
