from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from contextlib import closing, contextmanager
from datetime import date, timedelta
from pathlib import Path

from backend.booking_window import BookingWindowPolicy
from backend.db import connect_database
from backend.plans.manual_queue import QUEUE_KIND, parse_queue, automatic_queue_schedule
from backend.plans.models import PlanInterpretationContext, describe_window
from backend.plans.validation import IntentValidationError, parse_manual_intent
from backend.plans.lifecycle import TERMINAL_STATES, queue_lifecycle, lifecycle_sort_key


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
_SCOPE_UNSPECIFIED = object()


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

    def _parse(self, payload, context, now, saved_target=None):
        try:
            today = BookingWindowPolicy(context.timezone_name).business_date_at_utc(now)
            if saved_target and isinstance(payload, dict) and payload.get("target_date") == saved_target:
                today = min(today, date.fromisoformat(saved_target))
            return parse_manual_intent(payload, today_business_date=today, context=context)
        except IntentValidationError as exc:
            raise PlanError("invalid_plan", 400, exc.fields) from exc

    def _owned(self, db, user_id, plan_id):
        row = db.execute(_CURRENT + " AND p.plan_id=?", (user_id, plan_id)).fetchone()
        if row is None:
            raise PlanError("plan_not_found", 404)
        return row

    @staticmethod
    def _credential_scope_tag(user_id, credential_id):
        if not isinstance(credential_id, str) or not credential_id:
            return None
        material = f"yumao:credential-plan-scope:v1\0{user_id}\0{credential_id}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()[:32]

    @staticmethod
    def _stored_scope_tag(plan_id):
        if not isinstance(plan_id, str):
            return None
        parts = plan_id.split(":")
        if len(parts) == 3 and parts[0] in {"agent-v1", "manual-queue-v2"} and re.fullmatch(r"[0-9a-f]{32}", parts[1]):
            return parts[1]
        return None

    @classmethod
    def _matches_scope(cls, user_id, plan_id, credential_id):
        stored = cls._stored_scope_tag(plan_id)
        return stored is None or stored == cls._credential_scope_tag(user_id, credential_id)

    @classmethod
    def _assert_scope(cls, user_id, plan_id, credential_id):
        if not cls._matches_scope(user_id, plan_id, credential_id):
            raise PlanError("plan_not_found", 404)

    def _dto(self, row, now, credential_id=None):
        snapshot = json.loads(row["intent_json"])
        scoped_credential = credential_id if self._stored_scope_tag(row["plan_id"]) == self._credential_scope_tag(row["user_id"], credential_id) else None
        return {
            "plan_id": row["plan_id"], "version": row["version"], "current_revision_id": row["current_revision_id"],
            "created_at_utc_ms": row["created_at_utc_ms"], "updated_at_utc_ms": row["updated_at_utc_ms"],
            "credential_id": scoped_credential,
            "intent_sha256": row["intent_sha256"], **snapshot,
            "can_query_upstream": False, "can_book": False, "can_pay": False, "can_create_job": False,
            "booking_window": describe_window(self.policy, date.fromisoformat(snapshot["intent"]["target_date"]), now, snapshot["context"]["timezone_name"]),
        }

    def create_plan(self, user_id: str, payload: dict, now_utc_ms: int, credential_id=None) -> dict:
        snapshot = self._parse(payload, self.active_context, now_utc_ms)
        scope_tag = self._credential_scope_tag(user_id, credential_id)
        plan_id = f"agent-v1:{scope_tag}:{uuid.uuid4()}" if scope_tag else str(uuid.uuid4())
        revision_id = str(uuid.uuid4())
        with self._transaction() as db:
            db.execute("INSERT INTO booking_plans VALUES (?,?,?,?,?,?)", (plan_id, user_id, revision_id, 1, now_utc_ms, now_utc_ms))
            db.execute("INSERT INTO booking_plan_revisions VALUES (?,?,?,?,?,?,?,?)", (revision_id, plan_id, user_id, 1, snapshot.canonical_json, snapshot.sha256, user_id, now_utc_ms))
            result = self._dto(self._owned(db, user_id, plan_id), now_utc_ms, credential_id)
        return result

    def list_plans(self, user_id: str, now_utc_ms: int | None = None, credential_id=None, *, recent_only=False) -> list[dict]:
        now = now_utc_ms if now_utc_ms is not None else time.time_ns() // 1_000_000
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            query = _CURRENT + " AND json_extract(r.intent_json,'$.kind')!=? AND COALESCE(json_extract(r.intent_json,'$.deleted'),0)=0"
            parameters = [user_id, QUEUE_KIND]
            if recent_only:
                query += " AND json_extract(r.intent_json,'$.intent.target_date')>=?"
                parameters.append((self.policy.business_date_at_utc(now)-timedelta(days=1)).isoformat())
            rows = db.execute(query + " ORDER BY p.updated_at_utc_ms DESC,p.plan_id", parameters)
            return [self._dto(row, now, credential_id) for row in rows
                    if (credential_id is None or self._stored_scope_tag(row["plan_id"]) in
                         (None, self._credential_scope_tag(user_id, credential_id)))]

    def get_plan(self, user_id: str, plan_id: str, now_utc_ms: int | None = None, credential_id=_SCOPE_UNSPECIFIED) -> dict:
        now = now_utc_ms if now_utc_ms is not None else time.time_ns() // 1_000_000
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            if credential_id is not _SCOPE_UNSPECIFIED:
                self._assert_scope(user_id, plan_id, credential_id)
            row = self._owned(db, user_id, plan_id)
            if json.loads(row["intent_json"])["kind"] == QUEUE_KIND or json.loads(row["intent_json"]).get("deleted", False):
                raise PlanError("plan_not_found", 404)
            return self._dto(row, now, None if credential_id is _SCOPE_UNSPECIFIED else credential_id)

    def list_revisions(self, user_id: str, plan_id: str, now_utc_ms: int | None = None, credential_id=None, *, limit=None, before_version=None) -> list[dict]:
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            self._assert_scope(user_id, plan_id, credential_id)
            current = self._owned(db, user_id, plan_id)
            if json.loads(current["intent_json"])["kind"] == QUEUE_KIND:
                raise PlanError("plan_not_found", 404)
            rows = self._revision_rows(db, user_id, plan_id, limit, before_version)
            return [{"revision_id": row["revision_id"], "revision_number": row["revision_number"], "created_at_utc_ms": row["created_at_utc_ms"], "intent_sha256": row["intent_sha256"], **json.loads(row["intent_json"])} for row in rows]

    def update_plan(self, user_id: str, plan_id: str, base_version: int, payload: dict, now_utc_ms: int, credential_id=None) -> dict:
        if type(base_version) is not int or not 1 <= base_version <= 9007199254740991:
            raise PlanError("invalid_plan", 400, {"base_version": "请提供有效的计划版本。"})
        with self._transaction() as db:
            self._assert_scope(user_id, plan_id, credential_id)
            current = self._owned(db, user_id, plan_id)
            if current["version"] != base_version:
                raise PlanError("plan_version_conflict", 409)
            if json.loads(current["intent_json"])["kind"] == QUEUE_KIND or json.loads(current["intent_json"]).get("deleted", False):
                raise PlanError("plan_not_found", 404)
            saved = json.loads(current["intent_json"])["context"]
            context = PlanInterpretationContext(saved["timezone_name"], saved["currency_code"], saved["currency_minor_unit_exponent"])
            snapshot = self._parse(payload, context, now_utc_ms, json.loads(current["intent_json"])["intent"]["target_date"])
            if snapshot.canonical_json == current["intent_json"]:
                return self._dto(current, now_utc_ms, credential_id)
            revision_id = str(uuid.uuid4())
            db.execute("INSERT INTO booking_plan_revisions VALUES (?,?,?,?,?,?,?,?)", (revision_id, plan_id, user_id, base_version + 1, snapshot.canonical_json, snapshot.sha256, user_id, now_utc_ms))
            changed = db.execute("UPDATE booking_plans SET current_revision_id=?, version=version+1,updated_at_utc_ms=? WHERE user_id=? AND plan_id=? AND version=?", (revision_id, now_utc_ms, user_id, plan_id, base_version))
            if changed.rowcount != 1:
                raise PlanError("plan_version_conflict", 409)
            result = self._dto(self._owned(db, user_id, plan_id), now_utc_ms, credential_id)
        return result


    @classmethod
    def _queue_id(cls, user_id, target_date, credential_id=None):
        # Deterministic identity prevents duplicate creations after a lost response.
        if credential_id is None:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, f"yumao:manual-queue:v1:{user_id}:{target_date}"))
        tag = cls._credential_scope_tag(user_id, credential_id)
        stable_id = uuid.uuid5(uuid.NAMESPACE_URL, f"yumao:manual-queue:v2:{user_id}:{credential_id}:{target_date}")
        return f"manual-queue-v2:{tag}:{stable_id}"

    def _queue_dto(self, row, credential_id=None, now_utc_ms=None):
        snapshot = json.loads(row["intent_json"])
        scoped_credential = credential_id if self._stored_scope_tag(row["plan_id"]) == self._credential_scope_tag(row["user_id"], credential_id) else None
        now = time.time_ns() // 1_000_000 if now_utc_ms is None else now_utc_ms
        today = BookingWindowPolicy(snapshot["context"]["timezone_name"]).business_date_at_utc(now)
        within_window = date.fromisoformat(snapshot["target_date"]) in self.policy.queryable_target_dates(now)
        state = ("deleted" if snapshot.get("deleted") else "expired" if snapshot["target_date"] < today.isoformat()
                 else "draft" if within_window else "outside_window")
        return {"plan_id": row["plan_id"], "credential_id": scoped_credential, "version": row["version"],
                "current_revision_id": row["current_revision_id"], "intent_sha256": row["intent_sha256"],
                "updated_at_utc_ms": row["updated_at_utc_ms"], **snapshot,
                "plan_status": state, "execution_state": "not_started",
                "automatic_schedule": automatic_queue_schedule(date.fromisoformat(snapshot["target_date"]), now, snapshot["context"]["timezone_name"]),
                "can_open_selection": (within_window and snapshot["context"]["timezone_name"] == self.policy.timezone_name
                                       and not snapshot.get("deleted", False)),
                "can_query_upstream": False, "can_book": False, "can_pay": False, "can_create_job": False}

    def get_manual_queue(self, user_id, target_date, credential_id=None):
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            row = db.execute(_CURRENT + " AND p.plan_id=?", (user_id, self._queue_id(user_id, target_date, credential_id))).fetchone()
            return self._queue_dto(row, credential_id) if row else None

    def list_manual_queues(self, user_id, credential_id=None, *, recent_only=False, now_utc_ms=None):
        now = time.time_ns()//1_000_000 if now_utc_ms is None else now_utc_ms
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            query = _CURRENT + " AND json_extract(r.intent_json,'$.kind')=? AND COALESCE(json_extract(r.intent_json,'$.deleted'),0)=0"
            parameters = [user_id, QUEUE_KIND]
            if recent_only:
                query += " AND json_extract(r.intent_json,'$.target_date')>=?"
                parameters.append((self.policy.business_date_at_utc(now)-timedelta(days=1)).isoformat())
            rows = db.execute(query + " ORDER BY p.updated_at_utc_ms DESC,p.plan_id", parameters)
            return [self._queue_dto(row, credential_id, now) for row in rows
                    if (credential_id is None or self._stored_scope_tag(row["plan_id"]) in
                         (None, self._credential_scope_tag(user_id, credential_id)))]

    def queue_overview(self, user_id, credential_id, now, *, category="pending", target_date=None, page=1, limit=20):
        """Batch execution summaries; load full candidate payloads for this page only."""
        scope = self._credential_scope_tag(user_id, credential_id)
        terminal = ",".join("?" for _ in TERMINAL_STATES)
        query = f"""
            SELECT p.plan_id, p.current_revision_id AS plan_current_revision_id,
                   p.version AS plan_current_version, r.revision_id, r.revision_number,
                   r.created_at_utc_ms AS revision_created_at_utc_ms,
                   json_extract(r.intent_json,'$.target_date') AS target_date,
                   json_extract(r.intent_json,'$.context.timezone_name') AS timezone_name,
                   json_array_length(r.intent_json,'$.candidates') AS candidate_count,
                   run.run_id, run.state AS run_state, run.completed_at_utc_ms,
                   run.updated_at_utc_ms AS run_updated_at_utc_ms
            FROM booking_plans p JOIN booking_plan_revisions r
              ON r.plan_id=p.plan_id AND r.user_id=p.user_id
            LEFT JOIN booking_execution_runs run
              ON run.user_id=p.user_id AND run.credential_id=?
             AND run.source_plan_id=p.plan_id AND run.source_revision_id=r.revision_id
             AND run.source_version=r.revision_number AND run.source_sha256=r.intent_sha256
             AND run.target_date=json_extract(r.intent_json,'$.target_date')
            WHERE p.user_id=? AND json_extract(r.intent_json,'$.kind')=?
              AND (p.plan_id LIKE ? OR instr(p.plan_id,':')=0)
              AND ((r.revision_id=p.current_revision_id AND COALESCE(json_extract(r.intent_json,'$.deleted'),0)=0
                    AND (json_array_length(r.intent_json,'$.candidates')>0 OR ? IS NOT NULL))
                   OR (r.revision_id!=p.current_revision_id AND run.state IN ({terminal})))
        """
        parameters = [credential_id, user_id, QUEUE_KIND, f"manual-queue-v2:{scope}:%", target_date, *TERMINAL_STATES]
        if target_date:
            query += " AND json_extract(r.intent_json,'$.target_date')=?"
            parameters.append(target_date)
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            # Metadata, counts and immutable page payloads use one consistent read snapshot.
            db.execute("BEGIN")
            items = []
            counts = dict.fromkeys(("pending", "succeeded", "attention", "all"), 0)
            for row in db.execute(query, parameters):
                record = dict(row)
                record["credential_id"] = credential_id if self._stored_scope_tag(row["plan_id"]) == scope else None
                lifecycle = queue_lifecycle(record, now, self.policy.timezone_name)
                item = {"record_id": row["revision_id"], "plan_id": row["plan_id"], "target_date": row["target_date"], "lifecycle": lifecycle}
                counts[lifecycle["category"]] += 1
                counts["all"] += 1
                if category == "all" or category == lifecycle["category"]:
                    items.append(item)
            items.sort(key=lambda item: lifecycle_sort_key(item, category))
            offset = (page - 1) * limit
            selected = items[offset:offset + limit]
            if selected:
                ids = [item["record_id"] for item in selected]
                placeholders = ",".join("?" for _ in ids)
                rows = db.execute(f"""SELECT p.plan_id, p.user_id, r.revision_id AS current_revision_id,
                                      r.revision_number AS version, r.intent_json, r.intent_sha256,
                                      r.created_at_utc_ms AS updated_at_utc_ms
                               FROM booking_plans p JOIN booking_plan_revisions r
                                 ON r.plan_id=p.plan_id AND r.user_id=p.user_id
                               WHERE p.user_id=? AND r.revision_id IN ({placeholders})""", [user_id, *ids])
                queues = {row["current_revision_id"]: self._queue_dto(row, credential_id, now) for row in rows}
                for item in selected:
                    item.update(queues[item["record_id"]])
                    item["execution_state"] = item["lifecycle"]["state"]
                successful_ids = [item["lifecycle"]["run_id"] for item in selected if item["lifecycle"]["state"] == "succeeded"]
                successes = {}
                if successful_ids:
                    marks = ",".join("?" for _ in successful_ids)
                    for run in db.execute(f"""SELECT run.run_id, run.snapshot_json, stage.candidate_index,
                                                    stage.completed_at_utc_ms
                                             FROM booking_execution_runs run JOIN booking_execution_stages stage ON stage.run_id=run.run_id
                                             WHERE run.user_id=? AND run.credential_id=? AND run.run_id IN ({marks})
                                               AND stage.stage_key='payment_verification' AND stage.outcome='success'
                                             ORDER BY stage.completed_at_utc_ms""", [user_id, credential_id, *successful_ids]):
                        candidate = next((candidate for candidate in json.loads(run["snapshot_json"]).get("candidates", [])
                                          if candidate.get("queue_index") == run["candidate_index"]), None)
                        if candidate:
                            successes[run["run_id"]] = {key: candidate.get(key) for key in
                                ("scope_label", "court_preference", "start_time", "end_time", "duration_minutes")}
                            successes[run["run_id"]]["confirmed_at_utc_ms"] = run["completed_at_utc_ms"]
                for item in selected:
                    item["success"] = successes.get(item["lifecycle"]["run_id"])
            return {"queues": selected, "counts": counts, "total": len(items), "page": page,
                    "next_page": page + 1 if offset + limit < len(items) else None,
                    "queried_at_utc_ms": now, "business_timezone_name": self.policy.timezone_name}

    @staticmethod
    def _revision_rows(db, user_id, plan_id, limit, before_version):
        query = "SELECT revision_id,revision_number,intent_json,intent_sha256,created_at_utc_ms FROM booking_plan_revisions WHERE user_id=? AND plan_id=?"
        parameters = [user_id, plan_id]
        if before_version is not None:
            query += " AND revision_number<?"
            parameters.append(before_version)
        query += " ORDER BY revision_number DESC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        return db.execute(query, parameters).fetchall()

    def manual_queue_revisions(self, user_id, target_date, credential_id=None, *, limit=None, before_version=None):
        identifier = self._queue_id(user_id, target_date, credential_id)
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            self._owned(db, user_id, identifier)
            rows = self._revision_rows(db, user_id, identifier, limit, before_version)
            return [{"revision_id": row["revision_id"], "revision_number": row["revision_number"],
                     "created_at_utc_ms": row["created_at_utc_ms"], **json.loads(row["intent_json"])} for row in rows]

    def manual_queue_revision(self, user_id, target_date, credential_id, revision_id):
        identifier = self._queue_id(user_id, target_date, credential_id)
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            row = db.execute(
                """SELECT revision_id,revision_number,intent_json,created_at_utc_ms
                   FROM booking_plan_revisions
                   WHERE user_id=? AND plan_id=? AND revision_id=?""",
                (user_id, identifier, revision_id),
            ).fetchone()
            if row is None:
                return None
            snapshot = json.loads(row["intent_json"])
            if snapshot.get("kind") != QUEUE_KIND or snapshot.get("target_date") != target_date:
                return None
            return {"revision_id": row["revision_id"], "revision_number": row["revision_number"],
                    "created_at_utc_ms": row["created_at_utc_ms"], **snapshot}

    def save_manual_queue(self, user_id, target_date, base_version, entries, now, credential_id=None):
        if type(base_version) is not int or not 0 <= base_version <= 9007199254740991:
            raise PlanError("invalid_plan", 400)
        identifier = self._queue_id(user_id, target_date, credential_id)
        with self._transaction() as db:
            row = db.execute(_CURRENT + " AND p.plan_id=?", (user_id, identifier)).fetchone()
            if (row["version"] if row else 0) != base_version:
                raise PlanError("plan_version_conflict", 409)
            saved = json.loads(row["intent_json"])["context"] if row else self.active_context.to_dict()
            context = PlanInterpretationContext(saved["timezone_name"], saved["currency_code"], saved["currency_minor_unit_exponent"])
            try:
                snapshot = parse_queue({"target_date": target_date, "entries": entries}, context, BookingWindowPolicy(context.timezone_name).business_date_at_utc(now), allow_past=False)
            except IntentValidationError as exc:
                raise PlanError("invalid_plan", 400, exc.fields) from exc
            encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if row and encoded == row["intent_json"]:
                return self._queue_dto(row, credential_id, now)
            revision_id = str(uuid.uuid4())
            if not row:
                db.execute("INSERT INTO booking_plans VALUES (?,?,?,?,?,?)", (identifier, user_id, revision_id, 1, now, now))
            db.execute("INSERT INTO booking_plan_revisions VALUES (?,?,?,?,?,?,?,?)", (revision_id, identifier, user_id, base_version + 1, encoded, hashlib.sha256(encoded.encode()).hexdigest(), user_id, now))
            if row:
                changed = db.execute("UPDATE booking_plans SET current_revision_id=?, version=version+1,updated_at_utc_ms=? WHERE user_id=? AND plan_id=? AND version=?", (revision_id, now, user_id, identifier, base_version))
                if changed.rowcount != 1:
                    raise PlanError("plan_version_conflict", 409)
            return self._queue_dto(self._owned(db, user_id, identifier), credential_id, now)


    def delete_plan(self, user_id, plan_id, base_version, now, credential_id=None):
        if type(base_version) is not int or not 1 <= base_version <= 9007199254740991:
            raise PlanError("invalid_plan", 400)
        with self._transaction() as db:
            self._assert_scope(user_id, plan_id, credential_id)
            row = self._owned(db, user_id, plan_id)
            snapshot = json.loads(row["intent_json"])
            if snapshot["kind"] == QUEUE_KIND or snapshot.get("deleted"):
                raise PlanError("plan_not_found", 404)
            self._delete_snapshot(db, row, snapshot, base_version, now)

    def delete_manual_queue(self, user_id, target_date, base_version, now, credential_id=None):
        if type(base_version) is not int or not 1 <= base_version <= 9007199254740991:
            raise PlanError("invalid_plan", 400)
        with self._transaction() as db:
            self._assert_scope(user_id, self._queue_id(user_id, target_date, credential_id), credential_id)
            row = self._owned(db, user_id, self._queue_id(user_id, target_date, credential_id))
            snapshot = json.loads(row["intent_json"])
            if snapshot.get("deleted") and row["version"] == base_version:
                return self._queue_dto(row, credential_id)
            snapshot["candidates"] = []
            self._delete_snapshot(db, row, snapshot, base_version, now)
            return self._queue_dto(self._owned(db, user_id, row["plan_id"]), credential_id)

    def _delete_snapshot(self, db, row, snapshot, base_version, now):
        if row["version"] != base_version:
            raise PlanError("plan_version_conflict", 409)
        snapshot["deleted"] = True
        snapshot["deleted_at_utc_ms"] = now
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        revision_id = str(uuid.uuid4())
        db.execute("INSERT INTO booking_plan_revisions VALUES (?,?,?,?,?,?,?,?)", (revision_id, row["plan_id"], row["user_id"], base_version + 1, encoded, hashlib.sha256(encoded.encode()).hexdigest(), row["user_id"], now))
        changed = db.execute("UPDATE booking_plans SET current_revision_id=?, version=version+1,updated_at_utc_ms=? WHERE user_id=? AND plan_id=? AND version=?", (revision_id, now, row["user_id"], row["plan_id"], base_version))
        if changed.rowcount != 1:
            raise PlanError("plan_version_conflict", 409)
