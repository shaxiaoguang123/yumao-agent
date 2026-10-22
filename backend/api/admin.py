from __future__ import annotations

import time

from flask import Blueprint, current_app, g, jsonify, request

from backend.api.auth import require_admin, require_csrf, require_session
from backend.auth.invitations import InvitationService
from backend.db import connect_database
from backend.diagnostics import record_event


admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


@admin_bp.get("/users")
@require_session
@require_admin
def list_users():
    query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "all")
    role_filter = request.args.get("role", "all")
    try:
        limit = int(request.args.get("limit", "50"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        return jsonify({"error": "invalid_request"}), 400
    if (
        len(query) > 128
        or status_filter not in {"all", "active", "disabled"}
        or role_filter not in {"all", "admin", "user"}
        or not 1 <= limit <= 100
        or offset < 0
    ):
        return jsonify({"error": "invalid_request"}), 400

    where = []
    params: list[object] = []
    if query:
        where.append("username LIKE ? COLLATE NOCASE")
        params.append(f"%{query}%")
    if status_filter != "all":
        where.append("status=?")
        params.append(status_filter)
    if role_filter != "all":
        where.append("role=?")
        params.append(role_filter)
    predicate = f"WHERE {' AND '.join(where)}" if where else ""

    conn = connect_database(
        current_app.config["DATABASE_PATH"],
        current_app.config["SQLITE_BUSY_TIMEOUT_MS"],
    )
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM users {predicate}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT user_id, username, role, status, created_at_utc_ms
                FROM users {predicate}
                ORDER BY created_at_utc_ms DESC, username COLLATE NOCASE, user_id
                LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()
        counts = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active,
                      SUM(CASE WHEN status='disabled' THEN 1 ELSE 0 END) AS disabled,
                      SUM(CASE WHEN role='admin' THEN 1 ELSE 0 END) AS admins,
                      SUM(CASE WHEN role='admin' AND status='active' THEN 1 ELSE 0 END) AS active_admins
               FROM users"""
        ).fetchone()
        return jsonify({
            "users": [
                {
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "role": row["role"],
                    "status": row["status"],
                    "created_at_utc_ms": row["created_at_utc_ms"],
                }
                for row in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
            "summary": {
                "total": counts["total"],
                "active": counts["active"] or 0,
                "disabled": counts["disabled"] or 0,
                "admins": counts["admins"] or 0,
                "active_admins": counts["active_admins"] or 0,
            },
        })
    finally:
        conn.close()


@admin_bp.post("/invitations")
@require_session
@require_admin
@require_csrf
def create_invitation():
    now_utc_ms = time.time_ns() // 1_000_000
    expires_at_utc_ms = now_utc_ms + 24 * 60 * 60 * 1000
    code = current_app.extensions["invitation_service"].create(
        g.session_context.user.user_id,
        expires_at_utc_ms,
    )
    record_event("admin", "admin.invitation_created")
    return jsonify(
        {
            "invitation_code": code,
            "expires_at_utc_ms": expires_at_utc_ms,
        }
    ), 201


@admin_bp.post("/users/<user_id>/disable")
@require_session
@require_admin
@require_csrf
def disable_user(user_id: str):
    actor_id = g.session_context.user.user_id
    conn = connect_database(
        current_app.config["DATABASE_PATH"],
        current_app.config["SQLITE_BUSY_TIMEOUT_MS"],
    )
    try:
        conn.execute("BEGIN IMMEDIATE")
        actor = conn.execute(
            "SELECT role, status FROM users WHERE user_id=?",
            (actor_id,),
        ).fetchone()
        if actor is None or actor["role"] != "admin" or actor["status"] != "active":
            conn.execute("ROLLBACK")
            return jsonify({"error": "forbidden"}), 403
        if user_id == actor_id:
            conn.execute("ROLLBACK")
            return jsonify({"error": "self_disable_forbidden"}), 409

        target = conn.execute(
            "SELECT role, status FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if target is None:
            conn.execute("ROLLBACK")
            return jsonify({"error": "user_not_found"}), 404
        if target["role"] == "admin" and target["status"] == "active":
            active_admins = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND status='active'"
            ).fetchone()[0]
            if active_admins <= 1:
                conn.execute("ROLLBACK")
                return jsonify({"error": "last_admin_forbidden"}), 409

        now_utc_ms = time.time_ns() // 1_000_000
        conn.execute(
            """UPDATE users SET status='disabled', disabled_at_utc_ms=?,
               updated_at_utc_ms=? WHERE user_id=?""",
            (now_utc_ms, now_utc_ms, user_id),
        )
        conn.execute(
            "UPDATE sessions SET revoked_at_utc_ms=? "
            "WHERE user_id=? AND revoked_at_utc_ms IS NULL",
            (now_utc_ms, user_id),
        )
        conn.execute("COMMIT")
        record_event("admin", "admin.user_disabled", target_user_id=user_id)
        return current_app.response_class(status=204)
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@admin_bp.post("/users/<user_id>/enable")
@require_session
@require_admin
@require_csrf
def enable_user(user_id: str):
    actor_id = g.session_context.user.user_id
    conn = connect_database(
        current_app.config["DATABASE_PATH"],
        current_app.config["SQLITE_BUSY_TIMEOUT_MS"],
    )
    try:
        conn.execute("BEGIN IMMEDIATE")
        actor = conn.execute(
            "SELECT role, status FROM users WHERE user_id=?",
            (actor_id,),
        ).fetchone()
        if actor is None or actor["role"] != "admin" or actor["status"] != "active":
            conn.execute("ROLLBACK")
            return jsonify({"error": "forbidden"}), 403
        target = conn.execute(
            "SELECT status FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if target is None:
            conn.execute("ROLLBACK")
            return jsonify({"error": "user_not_found"}), 404
        now_utc_ms = time.time_ns() // 1_000_000
        conn.execute(
            "UPDATE users SET status='active', disabled_at_utc_ms=NULL, updated_at_utc_ms=? WHERE user_id=?",
            (now_utc_ms, user_id),
        )
        conn.execute("COMMIT")
        record_event("admin", "admin.user_enabled", target_user_id=user_id)
        return current_app.response_class(status=204)
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
