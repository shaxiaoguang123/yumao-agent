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
    def _decode(row):
        if row is None:
            return None
        return {
            "conversation_id": row["conversation_id"],
            "conversation_kind": row["conversation_kind"],
            "business_date": row["business_date"],
            **json.loads(row["state_json"]),
            "response_history": json.loads(row["response_history_json"]),
        }

    def get(self, conversation_id: str, user_id: str, credential_id: str | None, kind: str = "queue"):
        with closing(connect_database(self._database_path, self._busy_timeout_ms)) as db:
            row = db.execute(
                "SELECT conversation_id, conversation_kind, business_date, state_json, response_history_json "
                "FROM planning_conversations WHERE conversation_id=? AND user_id=? AND credential_id IS ? AND conversation_kind=?",
                (conversation_id, user_id, credential_id, kind),
            ).fetchone()
        return self._decode(row)

    def latest(self, user_id: str, credential_id: str, kind: str = "queue"):
        with closing(connect_database(self._database_path, self._busy_timeout_ms)) as db:
            row = db.execute(
                "SELECT conversation_id, conversation_kind, business_date, state_json, response_history_json "
                "FROM planning_conversations WHERE user_id=? AND credential_id IS ? AND conversation_kind=? "
                "ORDER BY updated_at_utc_ms DESC, conversation_id DESC LIMIT 1",
                (user_id, credential_id, kind),
            ).fetchone()
        return self._decode(row)

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
             state: dict, response: dict, now_utc_ms: int, kind: str = "queue") -> None:
        try:
            state_json = json.dumps(state, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            response_json = json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError, RecursionError):
            raise PlanError("invalid_planning_response", 502) from None

        with closing(connect_database(self._database_path, self._busy_timeout_ms)) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT conversation_kind, user_id, credential_id, business_date, state_json, response_history_json "
                "FROM planning_conversations WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            if row is None:
                history = [response]
                db.execute(
                    "INSERT INTO planning_conversations "
                    "(conversation_id,conversation_kind,user_id,credential_id,business_date,state_json,response_history_json,created_at_utc_ms,updated_at_utc_ms) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (conversation_id, kind, user_id, credential_id, business_date, state_json,
                     json.dumps(history, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
                     now_utc_ms, now_utc_ms),
                )
            else:
                if row["conversation_kind"] != kind or row["user_id"] != user_id or row["credential_id"] != credential_id:
                    raise PlanError("planning_conversation_not_found", 404)
                previous = json.loads(row["state_json"])
                history = json.loads(row["response_history_json"])
                previous["response_history"] = history
                self.validate_next(previous, state)
                old_answers, answers = previous["answers"], state["answers"]
                if not history:
                    raise sqlite3.DatabaseError("planning conversation history is empty")
                if len(answers) == len(old_answers):
                    history[-1] = response
                else:
                    history.append(response)
                if len(history) > 21:
                    raise PlanError("planning_context_limit", 400)
                db.execute(
                    "UPDATE planning_conversations SET state_json=?,response_history_json=?,updated_at_utc_ms=? "
                    "WHERE conversation_id=? AND user_id=? AND credential_id IS ?",
                    (state_json, json.dumps(history, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
                     now_utc_ms, conversation_id, user_id, credential_id),
                )
            db.commit()

    def close(self, conversation_id: str, user_id: str, credential_id: str | None, kind: str = "queue") -> None:
        with closing(connect_database(self._database_path, self._busy_timeout_ms)) as db:
            db.execute(
                "DELETE FROM planning_conversations WHERE conversation_id=? AND user_id=? "
                "AND conversation_kind=? AND (credential_id IS ? OR ? IS NULL)",
                (conversation_id, user_id, kind, credential_id, credential_id),
            )
