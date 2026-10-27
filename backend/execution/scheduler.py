from __future__ import annotations

import time
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.execution.engine import BookingExecutionEngine
from backend.execution.repository import BookingExecutionRepository
from backend.execution.settings import DEFAULT_SETTINGS, ExecutionSettingsService
from backend.plans.service import PlanService
from backend.diagnostics import diagnostic_scope, record_event, set_diagnostic_identity


_MAX_CONCURRENT_TOKEN_EXECUTIONS = 50
_UNEXPECTED_JOB_RETRY_DELAY_MS = 1000


class BookingScheduler:
    """Single-process daily worker for each active user's independent credentials."""

    def __init__(self, *, settings_service: ExecutionSettingsService,
                 engine: BookingExecutionEngine, repository: BookingExecutionRepository,
                 plan_service: PlanService, timezone_name: str,
                 worker_enabled: bool, clock_utc_ms=None, diagnostics=None,
                 email_notification_service=None):
        self.settings = settings_service
        self.engine = engine
        self.repository = repository
        self.plans = plan_service
        self.timezone_name = timezone_name
        self.zone = ZoneInfo(timezone_name)
        self.worker_enabled = bool(worker_enabled)
        self.email_notifications = email_notification_service
        self.diagnostics = diagnostics
        self._clock = clock_utc_ms or (lambda: time.time_ns() // 1_000_000)
        self._jobs = ThreadPoolExecutor(
            max_workers=_MAX_CONCURRENT_TOKEN_EXECUTIONS,
            thread_name_prefix="booking-token",
        )
        self._jobs_lock = threading.Lock()
        self._inflight: dict[tuple[str, str], Future] = {}
        self._retry_after: dict[tuple[str, str], int] = {}
        self._wake_event = threading.Event()
        self._closed = False

    def _at_local(self, business_date: date, hour: int, minute: int, second: int = 0) -> int:
        return int(datetime(business_date.year, business_date.month, business_date.day,
                            hour, minute, second, tzinfo=self.zone).timestamp() * 1000)

    @staticmethod
    def _parse_hour_minute(value: str) -> tuple[int, int]:
        hour, minute = value.split(":", 1)
        return int(hour), int(minute)

    def _is_inflight(self, user_id: str, credential_id: str) -> bool:
        with self._jobs_lock:
            return (user_id, credential_id) in self._inflight

    def _retry_at(self, user_id: str, credential_id: str, now_utc_ms: int) -> int | None:
        key = (user_id, credential_id)
        with self._jobs_lock:
            retry_at = self._retry_after.get(key)
            if retry_at is not None and retry_at <= now_utc_ms:
                del self._retry_after[key]
                return None
            return retry_at

    def _submit(self, stage: str, user_id: str, credential_id: str,
                run_id: str | None, operation) -> bool:
        key = (user_id, credential_id)
        with self._jobs_lock:
            if self._closed or key in self._inflight:
                return False
            try:
                future = self._jobs.submit(self._run_job, operation, run_id, user_id, credential_id)
            except RuntimeError:
                return False
            self._inflight[key] = future

        def completed(done: Future) -> None:
            error = None if done.cancelled() else done.exception()
            with self._jobs_lock:
                if self._inflight.get(key) is done:
                    del self._inflight[key]
                if error is None:
                    self._retry_after.pop(key, None)
                else:
                    self._retry_after[key] = int(self._clock()) + _UNEXPECTED_JOB_RETRY_DELAY_MS
            try:
                if error is not None:
                    with diagnostic_scope(self.diagnostics, run_id=run_id,
                                          user_id=user_id, credential_id=credential_id):
                        record_event(
                            "execution", f"scheduler.{stage}_failed", level="error",
                            code="execution_internal_error", exception=error,
                        )
            finally:
                self._wake_event.set()

        future.add_done_callback(completed)
        return True

    def _run_job(self, operation, run_id: str | None, user_id: str, credential_id: str):
        with diagnostic_scope(self.diagnostics, run_id=run_id,
                              user_id=user_id, credential_id=credential_id):
            return operation()

    def close(self) -> None:
        with self._jobs_lock:
            self._closed = True
        self._jobs.shutdown(wait=True, cancel_futures=False)

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
        settings_by_user: dict[str, dict | None] = {}
        notification_owners: dict[str, bool] = {}
        for user_id, credential_id in self.settings.list_active_credentials():
            if (self._retry_at(user_id, credential_id, now) is not None
                    or self._is_inflight(user_id, credential_id)):
                continue
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
            if self.email_notifications is not None:
                try:
                    if user_id not in notification_owners:
                        notification_owners[user_id] = self.email_notifications.owns_notifications(user_id)
                    if notification_owners[user_id]:
                        notification_queues = {target_date: queue}
                        for offset in (3, 4):
                            notification_date = (business_date + timedelta(days=offset)).isoformat()
                            notification_queues[notification_date] = self.plans.get_manual_queue(
                                user_id, notification_date, credential_id,
                            )
                        self.email_notifications.sync_queue_dates(
                            user_id, credential_id, business_date, notification_queues, now,
                        )
                except Exception as exc:
                    notification_owners[user_id] = False
                    with diagnostic_scope(self.diagnostics, user_id=user_id, credential_id=credential_id):
                        record_event("execution", "notification.schedule_failed", level="error",
                                     code="email_notification_schedule_failed", exception=exc)
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
                if self._submit(
                    "reconcile", user_id, credential_id, None,
                    lambda user_id=user_id, credential_id=credential_id,
                    target_date=target_date, queue=queue, settings_dto=settings_dto:
                        self.engine.reconcile(user_id, credential_id, target_date, queue, settings_dto),
                ):
                    reconciled += 1
                continue
            if not current_run:
                continue

            if current_run["state"] == "ready":
                offset = current_run.get("clock_offset_ms") or 0
                effective_now = now + offset
                calibration_at = self.engine.calibration_due_utc_ms(current_run, {})
                if effective_now >= calibration_at:
                    self._submit(
                        "calibrate", user_id, credential_id, current_run["run_id"],
                        lambda run=current_run, user_id=user_id, credential_id=credential_id:
                            self.engine.calibrate(run, user_id, credential_id),
                    )
                    continue
            if current_run and current_run["state"] == "calibrated":
                effective_now = int(self._clock()) + (current_run.get("clock_offset_ms") or 0)
                if effective_now >= self.engine.execution_start_utc_ms(current_run, {}):
                    run_id = current_run["run_id"]
                    executed += int(self._submit(
                        "token", user_id, credential_id, run_id,
                        lambda run_id=run_id, user_id=user_id, credential_id=credential_id:
                            self.engine.execute(run_id, user_id, credential_id),
                    ))
        if self.email_notifications is not None:
            try:
                self.email_notifications.dispatch_due(int(self._clock()))
            except Exception as exc:
                with diagnostic_scope(self.diagnostics):
                    record_event("execution", "notification.dispatch_failed", level="error",
                                 code="email_notification_dispatch_failed", exception=exc)
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
            retry_at = self._retry_at(user_id, credential_id, now)
            if retry_at is not None:
                candidates.append(retry_at)
                continue
            if self._is_inflight(user_id, credential_id):
                continue
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
        if self.email_notifications is not None:
            email_due = self.email_notifications.next_due_at_utc_ms()
            if email_due is not None:
                candidates.append(email_due)
        return max(0, min(30_000, min(candidates) - now))

    def run_forever(self) -> None:
        if not self.worker_enabled:
            raise RuntimeError("booking execution worker is disabled; set BOOKING_EXECUTION_ENABLED=true")
        self.engine.abandon_orphaned_runs(int(self._clock()))
        while True:
            self._wake_event.clear()
            self.tick_once()
            wait_ms = self.next_wait_ms()
            if wait_ms > 2 and not self._wake_event.wait((wait_ms - 2) / 1000):
                # Keep millisecond start offsets while allowing completed jobs to wake the loop.
                deadline = time.monotonic_ns() + 2_000_000
                while time.monotonic_ns() < deadline and not self._wake_event.is_set():
                    pass

