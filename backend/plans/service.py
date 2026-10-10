from __future__ import annotations

import json
import time
import uuid
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path

from backend.booking_window import BookingWindowPolicy
from backend.db import connect_database
from backend.plans.models import PlanInterpretationContext, describe_window
from backend.plans.validation import IntentValidationError, parse_manual_intent


class PlanError(Exception):
    def __init__(self, code: str, status: int, fields: dict | None = None):
        super().__init__(code)
        self.code, self.status, self.fields = code, status, fields or {}


_CURRENT = """SELECT p.*, r.intent_json, r.intent_sha256, r.revision_number,
                     r.created_at_utc_ms AS revision_created_at_utc_ms
              FROM booking_plans p JOIN booking_plan_revisions r
              ON r.revision_id=p.current_revision_id AND r.plan_id=p.plan_id
                 AND r.user_id=p.user_id AND r.revision_number=p.version
              WHERE p.user_id=?"""


class PlanService:
    """The sole plan persistence boundary; has no transport, credentials or jobs."""

    def __init__(self, database_path: Path, busy_timeout_ms: int, policy: BookingWindowPolicy,
                 currency_code: str | None = None, currency_minor_unit_exponent: int | None = None):
        self.database_path, self.busy_timeout_ms, self.policy = database_path, busy_timeout_ms, policy
        self.active_context = PlanInterpretationContext(policy.timezone_name, currency_code, currency_minor_unit_exponent)

    @contextmanager
    def _transaction(self):
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def _parse(self, payload, context, now):
        try:
            return parse_manual_intent(payload, today_business_date=BookingWindowPolicy(context.timezone_name).business_date_at_utc(now), context=context)
        except IntentValidationError as exc:
            raise PlanError("invalid_plan", 400, exc.fields) from exc

    def _owned(self, db, user_id, plan_id):
        row = db.execute(_CURRENT + " AND p.plan_id=?", (user_id, plan_id)).fetchone()
        if row is None:
            raise PlanError("plan_not_found", 404)
        return row

    def _dto(self, row, now):
        snapshot = json.loads(row["intent_json"])
        return {
            "plan_id": row["plan_id"], "version": row["version"], "current_revision_id": row["current_revision_id"],
            "created_at_utc_ms": row["created_at_utc_ms"], "updated_at_utc_ms": row["updated_at_utc_ms"],
            "intent_sha256": row["intent_sha256"], **snapshot,
            "can_query_upstream": False, "can_book": False, "can_pay": False, "can_create_job": False,
            "booking_window": describe_window(self.policy, date.fromisoformat(snapshot["intent"]["target_date"]), now, snapshot["context"]["timezone_name"]),
        }

    def create_plan(self, user_id: str, payload: dict, now_utc_ms: int) -> dict:
        snapshot = self._parse(payload, self.active_context, now_utc_ms)
        plan_id, revision_id = str(uuid.uuid4()), str(uuid.uuid4())
        with self._transaction() as db:
            db.execute("INSERT INTO booking_plans VALUES (?,?,?,?,?,?)", (plan_id, user_id, revision_id, 1, now_utc_ms, now_utc_ms))
            db.execute("INSERT INTO booking_plan_revisions VALUES (?,?,?,?,?,?,?,?)", (revision_id, plan_id, user_id, 1, snapshot.canonical_json, snapshot.sha256, user_id, now_utc_ms))
            result = self._dto(self._owned(db, user_id, plan_id), now_utc_ms)
        return result

    def list_plans(self, user_id: str, now_utc_ms: int | None = None) -> list[dict]:
        now = now_utc_ms if now_utc_ms is not None else time.time_ns() // 1_000_000
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            return [self._dto(row, now) for row in db.execute(_CURRENT + " ORDER BY p.updated_at_utc_ms DESC,p.plan_id", (user_id,))]

    def get_plan(self, user_id: str, plan_id: str, now_utc_ms: int | None = None) -> dict:
        now = now_utc_ms if now_utc_ms is not None else time.time_ns() // 1_000_000
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            return self._dto(self._owned(db, user_id, plan_id), now)

    def list_revisions(self, user_id: str, plan_id: str, now_utc_ms: int | None = None) -> list[dict]:
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            self._owned(db, user_id, plan_id)
            rows = db.execute("SELECT revision_id, revision_number,intent_json,intent_sha256,created_at_utc_ms FROM booking_plan_revisions WHERE user_id=? AND plan_id=? ORDER BY revision_number DESC", (user_id, plan_id)).fetchall()
            return [{"revision_id": row["revision_id"], "revision_number": row["revision_number"], "created_at_utc_ms": row["created_at_utc_ms"], "intent_sha256": row["intent_sha256"], **json.loads(row["intent_json"])} for row in rows]

    def update_plan(self, user_id: str, plan_id: str, base_version: int, payload: dict, now_utc_ms: int) -> dict:
        if type(base_version) is not int or not 1 <= base_version <= 9007199254740991:
            raise PlanError("invalid_plan", 400, {"base_version": "请提供有效的计划版本。"})
        with self._transaction() as db:
            current = self._owned(db, user_id, plan_id)
            if current["version"] != base_version:
                raise PlanError("plan_version_conflict", 409)
            saved = json.loads(current["intent_json"])["context"]
            context = PlanInterpretationContext(saved["timezone_name"], saved["currency_code"], saved["currency_minor_unit_exponent"])
            snapshot = self._parse(payload, context, now_utc_ms)
            if snapshot.canonical_json == current["intent_json"]:
                return self._dto(current, now_utc_ms)
            revision_id = str(uuid.uuid4())
            db.execute("INSERT INTO booking_plan_revisions VALUES (?,?,?,?,?,?,?,?)", (revision_id, plan_id, user_id, base_version + 1, snapshot.canonical_json, snapshot.sha256, user_id, now_utc_ms))
            changed = db.execute("UPDATE booking_plans SET current_revision_id=?, version=version+1,updated_at_utc_ms=? WHERE user_id=? AND plan_id=? AND version=?", (revision_id, now_utc_ms, user_id, plan_id, base_version))
            if changed.rowcount != 1:
                raise PlanError("plan_version_conflict", 409)
            result = self._dto(self._owned(db, user_id, plan_id), now_utc_ms)
        return result
