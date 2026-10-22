from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from backend.credentials.service import BookingCredentialMaterial, CredentialService
from backend.credentials.types import CredentialOperationError
from backend.execution.clock import ClockCalibrationError, sample_upstream_clock
from backend.execution.protocol import OfficialBookingProtocol, ProtocolReply, UpstreamCallError
from backend.execution.reconciliation import (
    ReconciliationError,
    candidate_coordinates,
    reconcile_queue,
)
from backend.execution.repository import BookingExecutionRepository
from backend.execution.settings import DEFAULT_SETTINGS
from backend.plans.service import PlanService
from backend.orders.status import order_is_confirmed
from backend.diagnostics import diagnostic_scope, record_event


_MAX_ROUNDS = 3
_VERIFY_ATTEMPTS = 15
_RESERVATION_COUNT = "5"


class BookingExecutionEngine:
    """Reconcile editable intents, then execute a separate queue snapshot."""

    def __init__(self, *, database_path: Path, busy_timeout_ms: int,
                 plan_service: PlanService, credential_service: CredentialService,
                 protocol: OfficialBookingProtocol, timezone_name: str,
                 worker_enabled: bool, clock_utc_ms: Callable[[], int] | None = None,
                 monotonic_ns: Callable[[], int] | None = None,
                 sleep: Callable[[float], None] = time.sleep, diagnostics=None):
        self.database_path = Path(database_path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.plans = plan_service
        self.credentials = credential_service
        self.protocol = protocol
        self.timezone_name = timezone_name
        self.worker_enabled = bool(worker_enabled)
        self.diagnostics = diagnostics
        self.repository = BookingExecutionRepository(database_path, busy_timeout_ms)
        self._clock = clock_utc_ms or (lambda: time.time_ns() // 1_000_000)
        self._monotonic = monotonic_ns or time.monotonic_ns
        self._sleep = sleep
        self._reservation_person: dict[str, str] = {}

    def _now(self) -> int:
        return int(self._clock())

    def _delay(self, settings: dict, key: str) -> None:
        delay = settings.get(key, 0)
        if type(delay) is int and delay > 0:
            self._sleep(delay / 1000)

    @staticmethod
    def _stage_event(stage_key: str, started: int, completed: int, elapsed: int,
                     outcome: str, safe_code: str | None = None, *,
                     round_number: int = 0, candidate_index: int = 0) -> dict:
        return {
            "round_number": round_number,
            "candidate_index": candidate_index,
            "stage_key": stage_key,
            "started_at_utc_ms": max(0, started),
            "completed_at_utc_ms": max(started, completed),
            "elapsed_ms": max(0, elapsed),
            "outcome": outcome,
            "safe_code": safe_code,
        }

    @classmethod
    def _reply_event(cls, stage_key: str, reply: ProtocolReply, *,
                     round_number: int = 0, candidate_index: int = 0) -> dict:
        success = reply.envelope.get("success") is True
        return cls._stage_event(
            stage_key, reply.started_at_utc_ms, reply.completed_at_utc_ms,
            reply.elapsed_ms, "success" if success else "rejected",
            None if success else "upstream_rejected",
            round_number=round_number, candidate_index=candidate_index,
        )

    @classmethod
    def _error_event(cls, stage_key: str, error: UpstreamCallError, *,
                     round_number: int = 0, candidate_index: int = 0) -> dict:
        return cls._stage_event(
            stage_key,
            error.started_at_utc_ms or error.completed_at_utc_ms,
            error.completed_at_utc_ms or error.started_at_utc_ms,
            error.elapsed_ms,
            error.outcome if error.outcome in {"rejected", "uncertain"} else "failed",
            error.safe_code,
            round_number=round_number,
            candidate_index=candidate_index,
        )

    def _source_is_current(self, run: dict, user_id: str, credential_id: str) -> bool:
        queue = self.plans.get_manual_queue(user_id, run["target_date"], credential_id)
        return bool(queue and queue.get("candidates") and not queue.get("deleted")
                    and queue.get("version") == run.get("source_version")
                    and queue.get("current_revision_id") == run.get("source_revision_id"))

    def _mark_stale(self, run_id: str) -> None:
        self.repository.update_state(
            run_id, ("ready", "calibrated"), "stale", self._now(), completed=True,
        )

    def reconcile(self, user_id: str, credential_id: str, target_date: str,
                  queue: dict, execution_settings: dict) -> dict | None:
        """Query each selected real category and persist a filtered execution snapshot."""
        if not self.worker_enabled:
            return None
        if not queue or not queue.get("candidates") or queue.get("deleted"):
            return None
        revision_id = queue.get("current_revision_id")
        existing = self.repository.find_source_run(user_id, credential_id, target_date, revision_id)
        if existing:
            return existing

        settings = (execution_settings.get("settings")
                    or dict(DEFAULT_SETTINGS))
        scope_labels = []
        for candidate in queue["candidates"]:
            label = candidate.get("query_scope_label")
            if type(label) is str and label and label not in scope_labels:
                scope_labels.append(label)
        events: list[dict] = []
        raw_by_scope: dict[str, tuple[dict, int]] = {}
        sample = None
        failure_code = None
        for scope_index, label in enumerate(scope_labels):
            try:
                self._delay(settings, "booking_node_delay_ms")
                categories, category_reply = self.protocol.read_categories(user_id, credential_id, "")
                events.append(self._reply_event("reconcile_booking_node", category_reply,
                                                 candidate_index=scope_index))
                matches = [item for item in categories if item["label"] == label]
                if len(matches) != 1:
                    failure_code = "booking_scope_not_unique"
                    break
                self._delay(settings, "booking_by_time_delay_ms")
                grid_reply = self.protocol.read_grid(
                    user_id, credential_id, "", matches[0]["node_id"], target_date,
                )
                events.append(self._reply_event("reconcile_booking_by_time", grid_reply,
                                                 candidate_index=scope_index))
                if grid_reply.envelope.get("success") is not True:
                    failure_code = "booking_query_rejected"
                    break
                captured_at = grid_reply.completed_at_utc_ms
                raw_by_scope[label] = (grid_reply.envelope, captured_at)
                if grid_reply.server_date_header:
                    try:
                        sample = sample_upstream_clock(
                            grid_reply.server_date_header,
                            grid_reply.started_at_utc_ms,
                            grid_reply.completed_at_utc_ms,
                        )
                    except ClockCalibrationError:
                        sample = None
            except UpstreamCallError as exc:
                events.append(self._error_event(
                    "reconcile_upstream_read", exc, candidate_index=scope_index,
                ))
                failure_code = exc.safe_code
                break
            except CredentialOperationError as exc:
                events.append(self._stage_event(
                    "reconcile_credential_check", self._now(), self._now(), 0,
                    "rejected", exc.code, candidate_index=scope_index,
                ))
                failure_code = exc.code
                break

        result_candidates: list[dict] = []
        if failure_code:
            summary = {
                "input_candidate_count": len(queue["candidates"]),
                "retained_candidate_count": 0,
                "discarded_candidate_counts": {failure_code: len(queue["candidates"])},
                "availability_claim": "none; live preflight failed closed",
                "execution_settings_version": execution_settings.get("version", 0),
                "execution_settings": settings,
            }
            state = "needs_attention"
        else:
            try:
                result_candidates, summary = reconcile_queue(
                    queue["candidates"], raw_by_scope, target_date=target_date,
                    timezone_name=self.timezone_name,
                )
                unbound_or_unqueried = any(
                    reason in summary["discarded_candidate_counts"]
                    for reason in ("scope_unbound", "scope_query_missing")
                )
                state = "needs_attention" if unbound_or_unqueried else "ready" if result_candidates else "empty"
                if state == "needs_attention":
                    result_candidates = []
                summary["execution_settings_version"] = execution_settings.get("version", 0)
                summary["execution_settings"] = settings
            except ReconciliationError as exc:
                summary = {
                    "input_candidate_count": len(queue["candidates"]),
                    "retained_candidate_count": 0,
                    "discarded_candidate_counts": {exc.code: len(queue["candidates"])},
                    "availability_claim": "none; live preflight failed closed",
                    "execution_settings_version": execution_settings.get("version", 0),
                    "execution_settings": settings,
                }
                state = "needs_attention"
                result_candidates = []

        # Fence concurrent edits: a changed saved queue must be reconciled again.
        latest = self.plans.get_manual_queue(user_id, target_date, credential_id)
        if (not latest or latest.get("version") != queue.get("version")
                or latest.get("current_revision_id") != queue.get("current_revision_id")):
            return None
        return self.repository.create_run(
            user_id=user_id, credential_id=credential_id, target_date=target_date,
            queue=queue, candidates=result_candidates, reconciliation=summary,
            state=state, now_utc_ms=self._now(), stage_events=events,
            clock_offset_ms=sample.offset_ms if sample else None,
            clock_uncertainty_ms=sample.uncertainty_ms if sample else None,
        )

    def calibration_due_utc_ms(self, run: dict, execution_settings: dict) -> int:
        target_day = date.fromisoformat(run["target_date"])
        # The execution day is two calendar days before the reservation date.
        execution_day = date.fromordinal(target_day.toordinal() - 2)
        opening = datetime(execution_day.year, execution_day.month, execution_day.day, 7, 30,
                           tzinfo=ZoneInfo(self.timezone_name))
        settings = (execution_settings.get("settings")
                    or run.get("reconciliation", {}).get("execution_settings")
                    or dict(DEFAULT_SETTINGS))
        lead = int(settings.get("clock_calibration_lead_ms", 1000))
        prequery_delay = int(settings.get("get_user_info_delay_ms", 0))
        return int(opening.timestamp() * 1000) - lead - prequery_delay

    def execution_start_utc_ms(self, run: dict, execution_settings: dict) -> int:
        target_day = date.fromisoformat(run["target_date"])
        execution_day = date.fromordinal(target_day.toordinal() - 2)
        opening = datetime(execution_day.year, execution_day.month, execution_day.day, 7, 30,
                           tzinfo=ZoneInfo(self.timezone_name))
        settings = (execution_settings.get("settings")
                    or run.get("reconciliation", {}).get("execution_settings")
                    or dict(DEFAULT_SETTINGS))
        return int(opening.timestamp() * 1000) + int(settings.get("start_offset_ms", 0))

    def calibrate(self, run: dict, user_id: str, credential_id: str) -> dict:
        if run.get("state") != "ready":
            return run
        if not self._source_is_current(run, user_id, credential_id):
            self._mark_stale(run["run_id"])
            return self.repository.run_by_id(run["run_id"])
        settings = run["reconciliation"].get("execution_settings") or dict(DEFAULT_SETTINGS)
        try:
            material = self.credentials.booking_material(user_id, credential_id)
            self._delay(settings, "get_user_info_delay_ms")
            reply = self.protocol.get_user_info(user_id, credential_id, material.token)
            event = self._reply_event("clock_calibration", reply)
            self.repository.record_stage(run["run_id"], event)
            data = reply.envelope.get("resultData")
            reservation_person = str(data.get("idserial") or "") if type(data) is dict else ""
            if reply.envelope.get("success") is not True or not reservation_person:
                raise ClockCalibrationError("reservation_identity_unavailable")
            sample = sample_upstream_clock(
                reply.server_date_header, reply.started_at_utc_ms, reply.completed_at_utc_ms,
            )
            if not self.repository.update_state(
                    run["run_id"], ("ready",), "calibrated", self._now(),
                    clock_offset_ms=sample.offset_ms,
                    clock_uncertainty_ms=sample.uncertainty_ms):
                return self.repository.run_by_id(run["run_id"])
            self._reservation_person[run["run_id"]] = reservation_person
        except ClockCalibrationError as exc:
            self.repository.record_stage(
                run["run_id"], self._stage_event("clock_calibration", self._now(), self._now(), 0,
                                                 "failed", exc.code),
            )
            self.repository.update_state(run["run_id"], ("ready",), "needs_attention", self._now(), completed=True)
        except (CredentialOperationError, UpstreamCallError) as exc:
            self.repository.record_stage(
                run["run_id"], self._stage_event("clock_calibration", self._now(), self._now(), 0,
                                                 "rejected", getattr(exc, "code", getattr(exc, "safe_code", "upstream_read_failed"))),
            )
            self.repository.update_state(run["run_id"], ("ready",), "needs_attention", self._now(), completed=True)
        return self.repository.run_by_id(run["run_id"])

    def _fresh_categories(self, run_id: str, material: BookingCredentialMaterial,
                          settings: dict, round_number: int) -> dict[str, dict]:
        self.credentials.assert_booking_snapshot(material)
        self._delay(settings, "booking_node_delay_ms")
        categories, reply = self.protocol.read_categories(material.user_id, material.credential_id, material.token)
        self.repository.record_stage(
            run_id, self._reply_event("booking_node_list", reply, round_number=round_number),
        )
        return {item["label"]: item for item in categories}

    def _payment_verified(self, run_id: str, material: BookingCredentialMaterial,
                          order_no: str, settings: dict, round_number: int,
                          candidate_index: int) -> tuple[bool, str]:
        started_at = self._now()
        monotonic_start = self._monotonic()
        result = "payment_unverified"
        self._delay(settings, "payment_verify_delay_ms")
        verify_interval_ms = int(settings.get("payment_verify_interval_ms", 3000))
        for attempt in range(_VERIFY_ATTEMPTS):
            self.credentials.assert_booking_snapshot(material)
            try:
                listed = self.protocol.list_orders(material.token)
            except UpstreamCallError as exc:
                result = exc.safe_code
                if attempt + 1 < _VERIFY_ATTEMPTS:
                    self._sleep(verify_interval_ms / 1000)
                continue
            content = ((listed.envelope.get("resultData") or {}).get("content")
                       if listed.envelope.get("success") is True
                       and type(listed.envelope.get("resultData")) is dict else [])
            matching = next((item for item in content if type(item) is dict
                             and str(item.get("orderno") or "") == order_no), None) if type(content) is list else None
            if matching:
                if listed.envelope.get("success") is True and order_is_confirmed(matching):
                    result = "paid"
                    break
                booking_no, order_id = str(matching.get("bookingno") or ""), str(matching.get("id") or "")
                if booking_no and order_id:
                    self.credentials.assert_booking_snapshot(material)
                    try:
                        details = self.protocol.order_details(material.token, booking_no=booking_no, order_id=order_id)
                    except UpstreamCallError:
                        details = None
                    detail = (details.envelope.get("resultData")
                              if details and details.envelope.get("success") is True else None)
                    if order_is_confirmed(detail):
                        result = "paid"
                        break
                    if type(detail) is dict and str(detail.get("status") or "") == "5":
                        result = "payment_pending"
                    elif type(detail) is dict and str(detail.get("status") or "") in {"2", "9"}:
                        result = "order_cancelled" if str(detail["status"]) == "2" else "order_expired"
                        break
            if attempt + 1 < _VERIFY_ATTEMPTS:
                self._sleep(verify_interval_ms / 1000)
        elapsed = max(0, (self._monotonic() - monotonic_start) // 1_000_000)
        self.repository.record_stage(
            run_id,
            self._stage_event("payment_verification", started_at, self._now(), int(elapsed),
                              "success" if result == "paid" else "uncertain",
                              None if result == "paid" else result,
                              round_number=round_number, candidate_index=candidate_index),
        )
        return result == "paid", result

    def execute(self, run_id: str, user_id: str, credential_id: str) -> dict | None:
        with diagnostic_scope(self.diagnostics, run_id=run_id, user_id=user_id, credential_id=credential_id):
            result = self._execute(run_id, user_id, credential_id)
            record_event("execution", "execution.finished", state=result.get("state") if result else "missing")
            return result

    def _execute(self, run_id: str, user_id: str, credential_id: str) -> dict | None:
        run = self.repository.run_by_id(run_id)
        if not run or run.get("state") != "calibrated":
            return run
        if not self._source_is_current(run, user_id, credential_id):
            self._mark_stale(run_id)
            return self.repository.run_by_id(run_id)
        if not self.repository.update_state(run_id, ("calibrated",), "running", self._now(), started=True):
            return self.repository.run_by_id(run_id)
        try:
            material = self.credentials.booking_material(user_id, credential_id)
        except CredentialOperationError as exc:
            self.repository.record_stage(run_id, self._stage_event(
                "credential_preflight", self._now(), self._now(), 0, "rejected", exc.code,
            ))
            self.repository.update_state(run_id, ("running",), "needs_attention", self._now(), completed=True)
            return self.repository.run_by_id(run_id)

        settings = run["reconciliation"].get("execution_settings") or dict(DEFAULT_SETTINGS)
        candidates = run["candidates"]
        candidates = [item for item in candidates if item.get("priority") == "two_hour"] + [
            item for item in candidates if item.get("priority") == "one_hour"
        ]
        reservation_person = self._reservation_person.pop(run_id, "")
        needs_attention = False
        attempt_index = 0
        try:
            if not reservation_person:
                self._delay(settings, "get_user_info_delay_ms")
                user_reply = self.protocol.get_user_info(user_id, credential_id, material.token)
                self.repository.record_stage(run_id, self._reply_event("get_user_info", user_reply))
                user_data = user_reply.envelope.get("resultData")
                reservation_person = str(user_data.get("idserial") or "") if type(user_data) is dict else ""
                if user_reply.envelope.get("success") is not True or not reservation_person:
                    raise UpstreamCallError("reservation_identity_unavailable", "rejected")

            for round_number in range(1, _MAX_ROUNDS + 1):
                if not self._source_is_current(run, user_id, credential_id):
                    self.repository.record_stage(run_id, self._stage_event(
                        "saved_queue_revision_check", self._now(), self._now(), 0,
                        "rejected", "saved_queue_changed", round_number=round_number,
                    ))
                    self.repository.update_state(run_id, ("running",), "needs_attention", self._now(), completed=True)
                    return self.repository.run_by_id(run_id)
                try:
                    categories = self._fresh_categories(run_id, material, settings, round_number)
                except UpstreamCallError as exc:
                    self.repository.record_stage(run_id, self._error_event(
                        "booking_node_list", exc, round_number=round_number,
                    ))
                    continue
                for candidate in candidates:
                    if attempt_index:
                        self._delay(settings, "candidate_interval_ms")
                    attempt_index += 1
                    candidate_index = int(candidate["queue_index"])
                    category = categories.get(candidate["scope_label"])
                    if category is None:
                        self.repository.record_stage(run_id, self._stage_event(
                            "booking_scope", self._now(), self._now(), 0, "rejected",
                            "booking_scope_not_found", round_number=round_number,
                            candidate_index=candidate_index,
                        ))
                        continue
                    self.credentials.assert_booking_snapshot(material)
                    self._delay(settings, "booking_by_time_delay_ms")
                    try:
                        booking = self.protocol.read_grid(
                            user_id, credential_id, material.token, category["node_id"], run["target_date"],
                        )
                    except UpstreamCallError as exc:
                        self.repository.record_stage(run_id, self._error_event(
                            "booking_by_time", exc, round_number=round_number,
                            candidate_index=candidate_index,
                        ))
                        continue
                    self.repository.record_stage(run_id, self._reply_event(
                        "booking_by_time", booking, round_number=round_number,
                        candidate_index=candidate_index,
                    ))
                    if booking.envelope.get("success") is not True:
                        continue
                    corrected_capture = booking.completed_at_utc_ms + int(run["clock_offset_ms"] or 0)
                    coordinates, reason = candidate_coordinates(
                        candidate, booking.envelope, target_date=run["target_date"],
                        timezone_name=self.timezone_name, captured_at_utc_ms=corrected_capture,
                    )
                    if not coordinates:
                        self.repository.record_stage(run_id, self._stage_event(
                            "fresh_availability_check", self._now(), self._now(), 0, "rejected",
                            reason or "candidate_not_selectable", round_number=round_number,
                            candidate_index=candidate_index,
                        ))
                        continue
                    result_data = booking.envelope["resultData"]
                    time_list, node_list = result_data["timeList"], result_data["nodeList"]
                    self.credentials.assert_booking_snapshot(material)
                    self._delay(settings, "get_pay_price_delay_ms")
                    try:
                        quote = self.protocol.get_pay_price(
                            material.token, node_id=category["node_id"], target_date=run["target_date"],
                            coordinates=coordinates, appointment_type="2", reservation_person=reservation_person,
                            time_list=time_list, node_list=node_list,
                        )
                    except UpstreamCallError as exc:
                        self.repository.record_stage(run_id, self._error_event(
                            "get_pay_price", exc, round_number=round_number,
                            candidate_index=candidate_index,
                        ))
                        continue
                    self.repository.record_stage(run_id, self._reply_event(
                        "get_pay_price", quote, round_number=round_number,
                        candidate_index=candidate_index,
                    ))
                    quote_data = quote.envelope.get("resultData")
                    txamt = str(quote_data.get("txamt") or "") if type(quote_data) is dict else ""
                    try:
                        amount = Decimal(txamt)
                        valid_amount = bool(txamt) and len(txamt) <= 32 and amount.is_finite() and amount >= 0
                    except (InvalidOperation, ValueError):
                        valid_amount = False
                    if quote.envelope.get("success") is not True or not valid_amount:
                        continue

                    self.credentials.assert_booking_snapshot(material)
                    self._delay(settings, "create_booking_delay_ms")
                    try:
                        order = self.protocol.create_booking(
                            material.token, node_id=category["node_id"], target_date=run["target_date"],
                            coordinates=coordinates, txamt=txamt, time_list=time_list, node_list=node_list,
                            is_last_day=result_data.get("bookingenddate") == run["target_date"],
                            childrennum=_RESERVATION_COUNT,
                        )
                    except UpstreamCallError as exc:
                        self.repository.record_stage(run_id, self._error_event(
                            "create_booking", exc, round_number=round_number,
                            candidate_index=candidate_index,
                        ))
                        if exc.outcome == "uncertain":
                            needs_attention = True
                            break
                        continue
                    self.repository.record_stage(run_id, self._reply_event(
                        "create_booking", order, round_number=round_number,
                        candidate_index=candidate_index,
                    ))
                    if order.envelope.get("success") is not True:
                        continue
                    order_data = order.envelope.get("resultData")
                    order_no = str(order_data.get("orderno") or "") if type(order_data) is dict else ""
                    if not order_no or len(order_no) > 128:
                        needs_attention = True
                        break

                    if not self._source_is_current(run, user_id, credential_id):
                        self.repository.record_stage(run_id, self._stage_event(
                            "saved_queue_revision_check", self._now(), self._now(), 0,
                            "rejected", "saved_queue_changed", round_number=round_number,
                            candidate_index=candidate_index,
                        ))
                        self.repository.update_state(run_id, ("running",), "needs_attention", self._now(), completed=True)
                        return self.repository.run_by_id(run_id)
                    self.credentials.assert_booking_snapshot(material)
                    self._delay(settings, "open_platform_pay_order_delay_ms")
                    try:
                        payment = self.protocol.pay_order(
                            material.token, order_no=order_no, txamt=txamt,
                            password=material.payment_password,
                        )
                        payment_outcome = "success" if payment.envelope.get("success") is True else "rejected"
                        payment_code = None if payment_outcome == "success" else "payment_rejected"
                        self.repository.record_stage(run_id, self._reply_event(
                            "open_platform_pay_order", payment, round_number=round_number,
                            candidate_index=candidate_index,
                        ))
                    except UpstreamCallError as exc:
                        payment_outcome, payment_code = exc.outcome, exc.safe_code
                        self.repository.record_stage(run_id, self._error_event(
                            "open_platform_pay_order", exc, round_number=round_number,
                            candidate_index=candidate_index,
                        ))

                    paid, verify_result = self._payment_verified(
                        run_id, material, order_no, settings, round_number, candidate_index,
                    )
                    if paid:
                        self.repository.update_state(
                            run_id, ("running",), "succeeded", self._now(), completed=True,
                        )
                        return self.repository.run_by_id(run_id)
                    # The order exists. Retrying a different candidate could create a
                    # second paid reservation after an ambiguous payment response.
                    self.repository.record_stage(run_id, self._stage_event(
                        "payment_outcome", self._now(), self._now(), 0,
                        "uncertain" if payment_outcome == "uncertain" or verify_result in {"payment_unverified", "payment_pending"} else "rejected",
                        payment_code or verify_result,
                        round_number=round_number, candidate_index=candidate_index,
                    ))
                    self.repository.update_state(
                        run_id, ("running",), "needs_attention", self._now(), completed=True,
                    )
                    return self.repository.run_by_id(run_id)
                if needs_attention:
                    break
            terminal = "needs_attention" if needs_attention else "failed"
            self.repository.update_state(run_id, ("running",), terminal, self._now(), completed=True)
        except CredentialOperationError as exc:
            self.repository.record_stage(run_id, self._stage_event(
                "credential_snapshot_check", self._now(), self._now(), 0, "rejected", exc.code,
            ))
            self.repository.update_state(run_id, ("running",), "needs_attention", self._now(), completed=True)
        except Exception as exc:
            record_event("execution", "execution.internal_error", level="error", code="execution_internal_error", exception=exc)
            # Never persist arbitrary exception text or upstream data.
            self.repository.record_stage(run_id, self._stage_event(
                "execution_internal_error", self._now(), self._now(), 0,
                "failed", "execution_internal_error",
            ))
            self.repository.update_state(run_id, ("running",), "needs_attention", self._now(), completed=True)
        return self.repository.run_by_id(run_id)

    def abandon_orphaned_runs(self, now_utc_ms: int, older_than_ms: int = 60_000) -> int:
        """Never replay a process interrupted after its durable execution claim."""
        from contextlib import closing
        from backend.db import connect_database
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            rows = db.execute(
                "SELECT run_id FROM booking_execution_runs WHERE state='running' AND updated_at_utc_ms<=?",
                (now_utc_ms - older_than_ms,),
            ).fetchall()
        changed = 0
        for row in rows:
            changed += int(self.repository.update_state(
                row["run_id"], ("running",), "needs_attention", now_utc_ms, completed=True,
            ))
        return changed

