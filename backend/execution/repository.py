from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from backend.db import connect_database
from backend.diagnostics import record_event


_STATES = {"ready", "calibrated", "running", "succeeded", "failed", "empty", "stale", "needs_attention"}
_OUTCOMES = {"success", "rejected", "failed", "uncertain", "skipped"}
_SAFE_CODE = re.compile(r"[a-z0-9_]{1,64}\Z", re.ASCII)


class ExecutionRepositoryError(RuntimeError):
    pass


class BookingExecutionRepository:
    def __init__(self, database_path: Path, busy_timeout_ms: int):
        self.database_path = Path(database_path)
        self.busy_timeout_ms = int(busy_timeout_ms)

    @staticmethod
    def _row_dto(row, stages=()):
        snapshot = json.loads(row["snapshot_json"])
        reconciliation = json.loads(row["reconciliation_json"])
        return {
            "run_id": row["run_id"],
            "target_date": row["target_date"],
            "source_version": row["source_version"],
            "source_revision_id": row["source_revision_id"],
            "source_plan_id": row["source_plan_id"],
            "state": row["state"],
            "candidate_count": len(snapshot.get("candidates", [])),
            "candidates": snapshot.get("candidates", []),
            "reconciliation": reconciliation,
            "clock_offset_ms": row["clock_offset_ms"],
            "clock_uncertainty_ms": row["clock_uncertainty_ms"],
            "created_at_utc_ms": row["created_at_utc_ms"],
            "updated_at_utc_ms": row["updated_at_utc_ms"],
            "started_at_utc_ms": row["started_at_utc_ms"],
            "completed_at_utc_ms": row["completed_at_utc_ms"],
            "stages": [dict(stage) for stage in stages],
        }

    def create_run(self, *, user_id: str, credential_id: str, target_date: str, queue: dict,
                   candidates: list[dict], reconciliation: dict, state: str, now_utc_ms: int,
                   stage_events: list[dict] | None = None,
                   clock_offset_ms: int | None = None,
                   clock_uncertainty_ms: int | None = None) -> dict:
        if state not in _STATES or state in {"calibrated", "running", "succeeded", "failed", "stale"}:
            raise ValueError("invalid initial execution state")
        required = (queue.get("plan_id"), queue.get("current_revision_id"), queue.get("intent_sha256"))
        if (any(type(value) is not str or not value for value in required)
                or type(queue.get("version")) is not int):
            raise ValueError("invalid execution queue source")
        snapshot = {
            "snapshot_version": 1,
            "target_date": target_date,
            "source_queue_version": queue["version"],
            "candidates": candidates,
        }
        encoded_snapshot = json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"), allow_nan=False)
        encoded_reconciliation = json.dumps(reconciliation, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":"), allow_nan=False)
        run_id = str(uuid.uuid4())
        completed_at = now_utc_ms if state in {"empty", "needs_attention"} else None
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """INSERT INTO booking_execution_runs
                       (run_id, user_id, credential_id, target_date, source_plan_id,
                        source_revision_id, source_version, source_sha256, state, snapshot_json,
                        reconciliation_json, clock_offset_ms, clock_uncertainty_ms,
                        created_at_utc_ms, updated_at_utc_ms, completed_at_utc_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (run_id, user_id, credential_id, target_date, queue["plan_id"],
                     queue["current_revision_id"], queue["version"], queue["intent_sha256"],
                     state, encoded_snapshot, encoded_reconciliation, clock_offset_ms,
                     clock_uncertainty_ms, now_utc_ms, now_utc_ms,
                     completed_at),
                )
                for event in stage_events or []:
                    self._insert_stage(db, event, run_id)
                row = db.execute("SELECT * FROM booking_execution_runs WHERE run_id=?", (run_id,)).fetchone()
                stages = db.execute(
                    "SELECT round_number,candidate_index,stage_key,started_at_utc_ms,completed_at_utc_ms,elapsed_ms,outcome,safe_code "
                    "FROM booking_execution_stages WHERE run_id=? ORDER BY started_at_utc_ms,stage_id", (run_id,)
                ).fetchall()
                db.execute("COMMIT")
                record_event("execution", "execution.snapshot", run_id=run_id, user_id=user_id,
                             credential_id=credential_id, state=state, before_count=len(queue.get("candidates", [])),
                             after_count=len(candidates), filtered_count=max(0,len(queue.get("candidates", []))-len(candidates)))
                for event in stage_events or []:
                    self._log_stage(run_id, event)
                return self._row_dto(row, stages)
            except sqlite3.IntegrityError as exc:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                if "UNIQUE constraint failed" not in str(exc):
                    raise
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        existing = self.find_source_run(user_id, credential_id, target_date, queue["current_revision_id"])
        if existing is None:
            raise ExecutionRepositoryError("execution_run_write_failed")
        return existing

    @staticmethod
    def _insert_stage(db, event: dict, run_id: str | None = None):
        stage_id = str(uuid.uuid4())
        code = event.get("safe_code")
        if code is not None and (type(code) is not str or not _SAFE_CODE.fullmatch(code)):
            code = "upstream_error"
        outcome = event.get("outcome")
        if outcome not in _OUTCOMES:
            outcome = "failed"
        values = (
            stage_id,
            run_id or event["run_id"],
            int(event.get("round_number", 0)),
            int(event.get("candidate_index", 0)),
            event["stage_key"],
            int(event["started_at_utc_ms"]),
            int(event["completed_at_utc_ms"]),
            max(0, int(event["elapsed_ms"])),
            outcome,
            code,
        )
        if (len(values[4]) > 64 or values[2] < 0 or values[3] < 0
                or values[5] < 0 or values[6] < values[5]):
            raise ValueError("invalid execution stage event")
        db.execute(
            """INSERT INTO booking_execution_stages
               (stage_id,run_id,round_number,candidate_index,stage_key,started_at_utc_ms,
                completed_at_utc_ms,elapsed_ms,outcome,safe_code)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            values,
        )

    def record_stage(self, run_id: str, event: dict) -> None:
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                self._insert_stage(db, event, run_id)
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        self._log_stage(run_id, event)

    @staticmethod
    def _log_stage(run_id, event):
        outcome = event.get("outcome") if event.get("outcome") in _OUTCOMES else "failed"
        code = event.get("safe_code")
        if code is not None and (type(code) is not str or not _SAFE_CODE.fullmatch(code)):
            code = "upstream_error"
        record_event("execution", "execution.stage", run_id=run_id,
                     level="error" if outcome in {"failed","uncertain"} else "warning" if outcome=="rejected" else "info",
                     code=code, stage=event.get("stage_key"), outcome=outcome,
                     round_number=event.get("round_number",0), candidate_index=event.get("candidate_index",0),
                     elapsed_ms=event.get("elapsed_ms",0))

    def find_source_run(self, user_id: str, credential_id: str, target_date: str,
                        source_revision_id: str) -> dict | None:
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            row = db.execute(
                """SELECT * FROM booking_execution_runs
                   WHERE user_id=? AND credential_id=? AND target_date=? AND source_revision_id=?""",
                (user_id, credential_id, target_date, source_revision_id),
            ).fetchone()
            if row is None:
                return None
            stages = db.execute(
                """SELECT round_number,candidate_index,stage_key,started_at_utc_ms,
                          completed_at_utc_ms,elapsed_ms,outcome,safe_code
                   FROM booking_execution_stages WHERE run_id=?
                   ORDER BY started_at_utc_ms,stage_id""",
                (row["run_id"],),
            ).fetchall()
        return self._row_dto(row, stages)

    def latest_run(self, user_id: str, credential_id: str, target_date: str) -> dict | None:
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            row = db.execute(
                """SELECT * FROM booking_execution_runs
                   WHERE user_id=? AND credential_id=? AND target_date=?
                   ORDER BY created_at_utc_ms DESC, run_id DESC LIMIT 1""",
                (user_id, credential_id, target_date),
            ).fetchone()
            if row is None:
                return None
            stages = db.execute(
                """SELECT round_number,candidate_index,stage_key,started_at_utc_ms,
                          completed_at_utc_ms,elapsed_ms,outcome,safe_code
                   FROM booking_execution_stages WHERE run_id=?
                   ORDER BY started_at_utc_ms,stage_id""",
                (row["run_id"],),
            ).fetchall()
        return self._row_dto(row, stages)

    def list_successes(self, user_id: str) -> list[dict]:
        """Return safe, order-query-confirmed booking summaries for one user."""
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            rows = db.execute(
                """SELECT run.*, credential.label AS credential_label,
                          stage.candidate_index AS success_candidate_index,
                          stage.completed_at_utc_ms AS confirmed_at_utc_ms
                   FROM booking_execution_runs AS run
                   JOIN booking_execution_stages AS stage
                     ON stage.run_id=run.run_id
                    AND stage.stage_key='payment_verification'
                    AND stage.outcome='success'
                   JOIN credentials AS credential
                     ON credential.user_id=run.user_id
                    AND credential.credential_id=run.credential_id
                   WHERE run.user_id=? AND run.state='succeeded'
                   ORDER BY stage.completed_at_utc_ms DESC, run.run_id DESC
                   LIMIT 20""",
                (user_id,),
            ).fetchall()
        successes = []
        for row in rows:
            snapshot = json.loads(row["snapshot_json"])
            candidate = next((
                item for item in snapshot.get("candidates", [])
                if item.get("queue_index") == row["success_candidate_index"]
            ), None)
            if candidate is None:
                continue
            successes.append({
                "run_id": row["run_id"],
                "credential_id": row["credential_id"],
                "credential_label": row["credential_label"],
                "target_date": row["target_date"],
                "scope_label": candidate.get("scope_label"),
                "court_preference": candidate.get("court_preference"),
                "start_time": candidate.get("start_time"),
                "end_time": candidate.get("end_time"),
                "duration_minutes": candidate.get("duration_minutes"),
                "confirmed_at_utc_ms": row["confirmed_at_utc_ms"],
                "verification": "order_query",
            })
        return successes

    def run_by_id(self, run_id: str) -> dict | None:
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            row = db.execute("SELECT * FROM booking_execution_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            stages = db.execute(
                """SELECT round_number,candidate_index,stage_key,started_at_utc_ms,
                          completed_at_utc_ms,elapsed_ms,outcome,safe_code
                   FROM booking_execution_stages WHERE run_id=?
                   ORDER BY started_at_utc_ms,stage_id""",
                (run_id,),
            ).fetchall()
        return self._row_dto(row, stages)

    def update_state(self, run_id: str, expected_states: tuple[str, ...], new_state: str,
                     now_utc_ms: int, *, clock_offset_ms: int | None = None,
                     clock_uncertainty_ms: int | None = None, started: bool = False,
                     completed: bool = False) -> bool:
        if new_state not in _STATES or not expected_states or any(state not in _STATES for state in expected_states):
            raise ValueError("invalid execution state transition")
        clauses = ",".join("?" for _ in expected_states)
        fields = ["state=?", "updated_at_utc_ms=?"]
        params: list[object] = [new_state, now_utc_ms]
        if clock_offset_ms is not None:
            fields.append("clock_offset_ms=?")
            params.append(clock_offset_ms)
        if clock_uncertainty_ms is not None:
            fields.append("clock_uncertainty_ms=?")
            params.append(clock_uncertainty_ms)
        if started:
            fields.append("started_at_utc_ms=COALESCE(started_at_utc_ms,?)")
            params.append(now_utc_ms)
        if completed:
            fields.append("completed_at_utc_ms=?")
            params.append(now_utc_ms)
        params.extend((run_id, *expected_states))
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                changed = db.execute(
                    f"UPDATE booking_execution_runs SET {','.join(fields)} WHERE run_id=? AND state IN ({clauses})",
                    params,
                )
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        return changed.rowcount == 1
