"""Persist the active, non-secret queue-drafting conversation for refresh recovery."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing

from backend.db import connect_database
from backend.plans.service import PlanError


class PlanningConversationStore:
    def __init__(self, database_path, busy_timeout_ms: int):
        self._database_path = database_path
        self._busy_timeout_ms = busy_timeout_ms

    @staticmethod
    def _encode(value: object) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError, RecursionError):
            raise PlanError("invalid_planning_response", 502) from None

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        return {
            **json.loads(row["state_json"]),
            "conversation_id": row["conversation_id"],
            "conversation_kind": row["conversation_kind"],
            "business_date": row["business_date"],
            "version": row["version"],
            "status": row["status"],
            "closed_at_utc_ms": row["closed_at_utc_ms"],
            "response_history": json.loads(row["response_history_json"]),
        }

    def get(self, conversation_id: str, user_id: str, credential_id: str | None, kind: str = "queue"):
        with closing(connect_database(self._database_path, self._busy_timeout_ms)) as db:
            row = db.execute(
                "SELECT conversation_id, conversation_kind, business_date, version, status, closed_at_utc_ms, state_json, response_history_json "
                "FROM planning_conversations WHERE conversation_id=? AND user_id=? AND credential_id IS ? AND conversation_kind=?",
                (conversation_id, user_id, credential_id, kind),
            ).fetchone()
        return self._decode(row)

    def latest(self, user_id: str, credential_id: str, kind: str = "queue"):
        with closing(connect_database(self._database_path, self._busy_timeout_ms)) as db:
            row = db.execute(
                "SELECT conversation_id, conversation_kind, business_date, version, status, closed_at_utc_ms, state_json, response_history_json "
                "FROM planning_conversations WHERE user_id=? AND credential_id IS ? AND conversation_kind=? "
                "AND status='active' "
                "ORDER BY updated_at_utc_ms DESC, conversation_id DESC LIMIT 1",
                (user_id, credential_id, kind),
            ).fetchone()
        return self._decode(row)

    def list_recent(self, user_id: str, credential_id: str, kind: str = "queue", limit: int = 50) -> list[dict]:
        with closing(connect_database(self._database_path, self._busy_timeout_ms)) as db:
            rows = db.execute(
                "SELECT conversation_id, business_date, version, status, updated_at_utc_ms, state_json, response_history_json "
                "FROM planning_conversations WHERE user_id=? AND credential_id IS ? AND conversation_kind=? "
                "ORDER BY updated_at_utc_ms DESC, conversation_id DESC LIMIT ?",
                (user_id, credential_id, kind, min(max(limit, 1), 100)),
            ).fetchall()
        result = []
        for row in rows:
            state, history = json.loads(row["state_json"]), json.loads(row["response_history_json"])
            latest = history[-1] if history else {}
            slots = {item.get("field"): item for item in (latest.get("conversation") or {}).get("slots", [])}
            target = slots.get("target_date", {}).get("display")
            mode = slots.get("booking_mode", {}).get("display")
            title = " · ".join(value for value in (target, mode) if value)
            if not title:
                title = " ".join(str(state.get("message", "")).split())[:56] or "预约对话"
            workflow_state = latest.get("workflow_state")
            if workflow_state == "saved":
                preview = "队列已保存"
            elif workflow_state == "cancelled":
                preview = "对话已取消"
            else:
                preview = ((latest.get("conversation") or {}).get("contextual_reply")
                           or next(iter(latest.get("questions") or []), "候选队列已整理" if latest.get("status") == "ready" else "继续补充预约信息"))
            result.append({"conversation_id": row["conversation_id"], "business_date": row["business_date"],
                           "version": row["version"], "status": row["status"], "updated_at_utc_ms": row["updated_at_utc_ms"],
                           "title": title, "preview": preview})
        return result

    @staticmethod
    def validate_next(previous: dict, state: dict) -> None:
        old_answers, answers = previous["answers"], state["answers"]
        asked = state.get("asked_fields", [])
        scope_changed = previous.get("scope_label") not in (None, state.get("scope_label"))
        if (previous["message"] != state["message"] or scope_changed
                or any(previous.get(key) != state.get(key) for key in ("plan_id", "base_version", "credential_id"))
                or len(answers) not in (len(old_answers), len(old_answers) + 1)
                or answers[:len(old_answers)] != old_answers):
            raise PlanError("planning_conversation_conflict", 409)
        if previous.get("conversation_kind") == "queue":
            old_kinds = previous.get("turn_kinds") or ["answer"] * (len(old_answers) + 1)
            kinds = state.get("turn_kinds")
            if (type(kinds) is not list or len(kinds) != len(answers) + 1
                    or kinds[:len(old_kinds)] != old_kinds
                    or any(kind not in {"answer", "question", "mixed"} for kind in kinds)):
                raise PlanError("planning_conversation_conflict", 409)
        history = previous["response_history"]
        if "asked_fields" in state:
            expected = [item.get("conversation", {}).get("asking") for item in history[:len(answers)]]
            if asked != expected:
                raise PlanError("planning_conversation_conflict", 409)
        if "follow_up_questions" in state:
            expected = [item.get("questions", []) for item in history[:len(answers)]]
            if state["follow_up_questions"] != expected:
                raise PlanError("planning_conversation_conflict", 409)

    def save(self, conversation_id: str, user_id: str, credential_id: str | None, business_date: str,
             state: dict, response: dict, now_utc_ms: int, kind: str = "queue",
             expected_version: int | None = None) -> int:
        state_json = self._encode(state)

        with closing(connect_database(self._database_path, self._busy_timeout_ms)) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE planning_conversations SET status='closed',closed_at_utc_ms=COALESCE(closed_at_utc_ms,?),version=version+1 "
                "WHERE user_id=? AND credential_id IS ? AND conversation_kind=? AND status='active' AND conversation_id<>?",
                (now_utc_ms, user_id, credential_id, kind, conversation_id),
            )
            row = db.execute(
                "SELECT conversation_kind, user_id, credential_id, business_date, version, state_json, response_history_json "
                "FROM planning_conversations WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            if row is None:
                if expected_version not in (None, 0):
                    raise PlanError("planning_conversation_conflict", 409)
                version = 1
                saved_response = {**response, "conversation_version": version}
                history = [saved_response]
                db.execute(
                    "INSERT INTO planning_conversations "
                    "(conversation_id,conversation_kind,user_id,credential_id,business_date,state_json,response_history_json,created_at_utc_ms,updated_at_utc_ms,status,version) "
                    "VALUES (?,?,?,?,?,?,?,?,?,'active',?)",
                    (conversation_id, kind, user_id, credential_id, business_date, state_json,
                     self._encode(history),
                     now_utc_ms, now_utc_ms, version),
                )
            else:
                if row["conversation_kind"] != kind or row["user_id"] != user_id or row["credential_id"] != credential_id:
                    raise PlanError("planning_conversation_not_found", 404)
                if expected_version is not None and expected_version != row["version"]:
                    raise PlanError("planning_conversation_conflict", 409)
                previous_version = row["version"]
                version = previous_version + 1
                previous = json.loads(row["state_json"])
                history = json.loads(row["response_history_json"])
                previous["response_history"] = history
                previous["conversation_kind"] = row["conversation_kind"]
                self.validate_next(previous, state)
                old_answers, answers = previous["answers"], state["answers"]
                if not history:
                    raise sqlite3.DatabaseError("planning conversation history is empty")
                saved_response = {**response, "conversation_version": version}
                if len(answers) == len(old_answers):
                    history[-1] = saved_response
                else:
                    history.append(saved_response)
                if len(history) > 21:
                    raise PlanError("planning_context_limit", 400)
                cursor = db.execute(
                    "UPDATE planning_conversations SET state_json=?,response_history_json=?,updated_at_utc_ms=?,status='active',closed_at_utc_ms=NULL,version=? "
                    "WHERE conversation_id=? AND user_id=? AND credential_id IS ? AND version=?",
                    (state_json, self._encode(history),
                     now_utc_ms, version, conversation_id, user_id, credential_id, previous_version),
                )
                if cursor.rowcount != 1:
                    raise PlanError("planning_conversation_conflict", 409)
            db.commit()
        return version

    def activate(self, conversation_id: str, user_id: str, credential_id: str, now_utc_ms: int,
                 kind: str = "queue") -> bool:
        with closing(connect_database(self._database_path, self._busy_timeout_ms)) as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute(
                "SELECT 1 FROM planning_conversations WHERE conversation_id=? AND user_id=? "
                "AND credential_id IS ? AND conversation_kind=?",
                (conversation_id, user_id, credential_id, kind),
            ).fetchone()
            if exists is None:
                db.rollback()
                return False
            db.execute(
                "UPDATE planning_conversations SET status='closed',closed_at_utc_ms=COALESCE(closed_at_utc_ms,?),version=version+1 "
                "WHERE user_id=? AND credential_id IS ? AND conversation_kind=? AND status='active' AND conversation_id<>?",
                (now_utc_ms, user_id, credential_id, kind, conversation_id),
            )
            cursor = db.execute(
                "UPDATE planning_conversations SET status='active',closed_at_utc_ms=NULL,updated_at_utc_ms=?,version=version+1 "
                "WHERE conversation_id=? AND user_id=? AND credential_id IS ? AND conversation_kind=?",
                (now_utc_ms, conversation_id, user_id, credential_id, kind),
            )
            db.commit()
        return cursor.rowcount == 1

    def close(self, conversation_id: str, user_id: str, credential_id: str | None, now_utc_ms: int,
              kind: str = "queue", workflow_state: str = "cancelled") -> None:
        with closing(connect_database(self._database_path, self._busy_timeout_ms)) as db:
            if kind == "intent":
                db.execute(
                    "DELETE FROM planning_conversations WHERE conversation_id=? AND user_id=? AND conversation_kind=? AND credential_id IS ?",
                    (conversation_id, user_id, kind, credential_id),
                )
            else:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT status, version, response_history_json FROM planning_conversations "
                    "WHERE conversation_id=? AND user_id=? AND conversation_kind=? AND credential_id IS ?",
                    (conversation_id, user_id, kind, credential_id),
                ).fetchone()
                if row is None:
                    db.rollback()
                    return
                history = json.loads(row["response_history_json"])
                latest = history[-1] if history else {}
                if row["status"] == "closed" and latest.get("workflow_state") == workflow_state:
                    db.rollback()
                    return
                version = row["version"] + 1
                if history:
                    latest["workflow_state"] = workflow_state
                    latest["conversation_version"] = version
                    if isinstance(latest.get("conversation"), dict):
                        latest["conversation"]["workflow_state"] = workflow_state
                db.execute(
                    "UPDATE planning_conversations SET status='closed',closed_at_utc_ms=?,updated_at_utc_ms=?,version=?,response_history_json=? "
                    "WHERE conversation_id=? AND user_id=? AND conversation_kind=? AND credential_id IS ? AND version=?",
                    (now_utc_ms, now_utc_ms, version, self._encode(history), conversation_id,
                     user_id, kind, credential_id, row["version"]),
                )
                db.commit()
