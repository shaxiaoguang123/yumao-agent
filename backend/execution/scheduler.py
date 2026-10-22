from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.execution.engine import BookingExecutionEngine
from backend.execution.repository import BookingExecutionRepository
from backend.execution.settings import DEFAULT_SETTINGS, ExecutionSettingsService
from backend.plans.service import PlanService
from backend.diagnostics import diagnostic_scope, record_event, set_diagnostic_identity


class BookingScheduler:
    """Single-process daily worker for each active user's independent credentials."""

    def __init__(self, *, settings_service: ExecutionSettingsService,
                 engine: BookingExecutionEngine, repository: BookingExecutionRepository,
                 plan_service: PlanService, timezone_name: str,
                 worker_enabled: bool, clock_utc_ms=None, sleep=time.sleep, diagnostics=None):
        self.settings = settings_service
        self.engine = engine
        self.repository = repository
        self.plans = plan_service
        self.timezone_name = timezone_name
        self.zone = ZoneInfo(timezone_name)
        self.worker_enabled = bool(worker_enabled)
        self.diagnostics = diagnostics
        self._clock = clock_utc_ms or (lambda: time.time_ns() // 1_000_000)
        self._sleep = sleep

    def _at_local(self, business_date: date, hour: int, minute: int, second: int = 0) -> int:
        return int(datetime(business_date.year, business_date.month, business_date.day,
                            hour, minute, second, tzinfo=self.zone).timestamp() * 1000)

    @staticmethod
    def _parse_hour_minute(value: str) -> tuple[int, int]:
        hour, minute = value.split(":", 1)
        return int(hour), int(minute)

    def tick_once(self, now_utc_ms: int | None = None) -> dict:
        with diagnostic_scope(self.diagnostics):
            return self._tick_once(now_utc_ms)

    def _tick_once(self, now_utc_ms: int | None = None) -> dict:
        if not self.worker_enabled:
            return {"worker_enabled": False, "reconciled": 0, "executed": 0}
        now = int(self._clock() if now_utc_ms is None else now_utc_ms)
        local_now = datetime.fromtimestamp(now / 1000, self.zone)
        business_date = local_now.date()
        target_date = (business_date + timedelta(days=2)).isoformat()
        opening_at = self._at_local(business_date, 7, 30)
        reconciled = executed = 0
        execution_jobs: list[tuple[str, str, str]] = []
        settings_by_user: dict[str, dict | None] = {}
        for user_id, credential_id in self.settings.list_active_credentials():
            set_diagnostic_identity(user_id=user_id, credential_id=credential_id)
            if user_id not in settings_by_user:
                try:
                    settings_by_user[user_id] = self.settings.get(user_id)
                except Exception as exc:
                    record_event("execution", "scheduler.settings_failed", level="error", code="execution_settings_unavailable", exception=exc)
                    settings_by_user[user_id] = None
            settings_dto = settings_by_user[user_id]
            if settings_dto is None:
                continue
            try:
                setting_values = settings_dto["settings"]
                queue = self.plans.get_manual_queue(user_id, target_date, credential_id)
            except Exception as exc:
                record_event("execution", "scheduler.queue_failed", level="error", code="queue_read_failed", exception=exc)
                continue
            latest = self.repository.latest_run(user_id, credential_id, target_date)
            if not queue or not queue.get("candidates") or queue.get("deleted"):
                if latest and latest["state"] in {"ready", "calibrated"}:
                    self.engine._mark_stale(latest["run_id"])
                continue

            current_run = self.repository.find_source_run(
                user_id, credential_id, target_date, queue.get("current_revision_id", ""),
            )
            if latest and latest["state"] in {"ready", "calibrated"} and latest["source_revision_id"] != queue.get("current_revision_id"):
                self.engine._mark_stale(latest["run_id"])

            reconciliation_hour, reconciliation_minute = self._parse_hour_minute(
                setting_values.get("reconciliation_time", DEFAULT_SETTINGS["reconciliation_time"])
            )
            reconcile_at = self._at_local(business_date, reconciliation_hour, reconciliation_minute)
            if current_run is None and now >= reconcile_at and now < opening_at:
                created = self.engine.reconcile(user_id, credential_id, target_date, queue, settings_dto)
                reconciled += int(created is not None)
                current_run = created
            if not current_run:
                continue

            if current_run["state"] == "ready":
                offset = current_run.get("clock_offset_ms") or 0
                effective_now = now + offset
                calibration_at = self.engine.calibration_due_utc_ms(current_run, {})
                if effective_now >= calibration_at:
                    current_run = self.engine.calibrate(current_run, user_id, credential_id)
                    now = int(self._clock())
                    effective_now = now + (current_run.get("clock_offset_ms") or 0)
            if current_run and current_run["state"] == "calibrated":
                effective_now = int(self._clock()) + (current_run.get("clock_offset_ms") or 0)
                if effective_now >= self.engine.execution_start_utc_ms(current_run, {}):
                    execution_jobs.append((current_run["run_id"], user_id, credential_id))
        if len(execution_jobs) == 1:
            self.engine.execute(*execution_jobs[0])
        elif execution_jobs:
            # shortcut: cap one-process concurrency at eight Tokens until production load is measured.
            with ThreadPoolExecutor(
                max_workers=min(8, len(execution_jobs)),
                thread_name_prefix="booking-token",
            ) as executor:
                futures = [executor.submit(self.engine.execute, *job) for job in execution_jobs]
                for job, future in zip(execution_jobs, futures):
                    try:
                        future.result()
                    except Exception as exc:
                        # Each run owns its durable state; one unexpected Token failure must
                        # not prevent the remaining due Tokens from starting.
                        with diagnostic_scope(self.diagnostics, run_id=job[0], user_id=job[1], credential_id=job[2]):
                            record_event("execution", "scheduler.token_failed", level="error", code="execution_internal_error", exception=exc)
        executed = len(execution_jobs)
        return {"worker_enabled": True, "target_date": target_date,
                "reconciled": reconciled, "executed": executed}

    def next_wait_ms(self, now_utc_ms: int | None = None) -> int:
        now = int(self._clock() if now_utc_ms is None else now_utc_ms)
        local_now = datetime.fromtimestamp(now / 1000, self.zone)
        business_date = local_now.date()
        target_date = (business_date + timedelta(days=2)).isoformat()
        candidates = [now + 30_000]
        opening_at = self._at_local(business_date, 7, 30)
        settings_by_user: dict[str, dict | None] = {}
        for user_id, credential_id in self.settings.list_active_credentials():
            if user_id not in settings_by_user:
                try:
                    settings_by_user[user_id] = self.settings.get(user_id)
                except Exception as exc:
                    with diagnostic_scope(self.diagnostics, user_id=user_id, credential_id=credential_id):
                        record_event("execution", "scheduler.wait_settings_failed", level="error", code="execution_settings_unavailable", exception=exc)
                    settings_by_user[user_id] = None
            settings_dto = settings_by_user[user_id]
            if settings_dto is None:
                continue
            try:
                setting_values = settings_dto["settings"]
                queue = self.plans.get_manual_queue(user_id, target_date, credential_id)
            except Exception as exc:
                with diagnostic_scope(self.diagnostics, user_id=user_id, credential_id=credential_id):
                    record_event("execution", "scheduler.wait_queue_failed", level="error", code="queue_read_failed", exception=exc)
                continue
            if not queue or not queue.get("candidates") or queue.get("deleted"):
                continue
            run = self.repository.find_source_run(
                user_id, credential_id, target_date, queue.get("current_revision_id", ""),
            )
            if run is None:
                hour, minute = self._parse_hour_minute(setting_values.get("reconciliation_time", "00:30"))
                event = self._at_local(business_date, hour, minute)
                if now < event:
                    candidates.append(event)
                elif now < opening_at:
                    return 0
            elif run["state"] == "ready":
                offset = run.get("clock_offset_ms") or 0
                event = self.engine.calibration_due_utc_ms(run, {}) - offset
                if now < event:
                    candidates.append(event)
                else:
                    return 0
            elif run["state"] == "calibrated":
                event = self.engine.execution_start_utc_ms(run, {}) - (run.get("clock_offset_ms") or 0)
                if now < event:
                    candidates.append(event)
                else:
                    return 0
        return max(0, min(30_000, min(candidates) - now))

    def run_forever(self) -> None:
        if not self.worker_enabled:
            raise RuntimeError("booking execution worker is disabled; set BOOKING_EXECUTION_ENABLED=true")
        self.engine.abandon_orphaned_runs(int(self._clock()))
        while True:
            self.tick_once()
            wait_ms = self.next_wait_ms()
            deadline = time.monotonic_ns() + max(0, wait_ms) * 1_000_000
            if wait_ms > 3:
                self._sleep((wait_ms - 2) / 1000)
            # Trim scheduler wake-up drift for millisecond per-token start offsets.
            while time.monotonic_ns() < deadline:
                pass

