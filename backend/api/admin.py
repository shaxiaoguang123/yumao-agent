from __future__ import annotations

import time

from flask import Blueprint, current_app, g, jsonify

from backend.api.auth import require_admin, require_csrf, require_session
from backend.auth.invitations import InvitationService
from backend.db import connect_database


admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


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
        return current_app.response_class(status=204)
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
