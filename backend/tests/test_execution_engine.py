from __future__ import annotations

import tempfile
import threading
import unittest
from contextlib import closing
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.booking_window import BookingWindowPolicy
from backend.credentials.service import BookingCredentialMaterial
from backend.credentials.types import CredentialOperationError
from backend.db import connect_database
from backend.execution.engine import BookingExecutionEngine
from backend.execution.protocol import ProtocolReply, UpstreamCallError
from backend.execution.repository import BookingExecutionRepository
from backend.execution.scheduler import BookingScheduler
from backend.execution.settings import DEFAULT_SETTINGS, ExecutionSettingsService
from backend.migrate import migrate_database
from backend.plans.service import PlanService


ZONE = "Asia/Shanghai"
USER = "user-a"
CREDENTIAL = "credential-a"
TARGET = "2026-10-17"


def epoch(day: int, hour: int, minute: int = 0, second: int = 0) -> int:
    return int(datetime(2026, 10, day, hour, minute, second, tzinfo=ZoneInfo(ZONE)).timestamp() * 1000)


def booking_envelope(*, conflicts=None):
    times = ["09:00", "10:00", "11:00", "12:00"]
    return {
        "success": True,
        "message": "CORE10008",
        "resultData": {
            "stepnumber": len(times),
            "nodeList": [{"nodeid": "fresh-court-id", "sitename": "6号场"}],
            "timeList": [{"time": item, "status": "0"} for item in times],
            "conflictList": conflicts or [],
            "priceList": [],
            "bookingstartdate": "2026-10-16",
            "bookingenddate": TARGET,
            "bookingstarttime": "07:30",
            "bookingendtime": "22:00",
            "isNew": False,
        },
    }


class FakeCredentialService:
    def __init__(self):
        self.material = BookingCredentialMaterial(USER, CREDENTIAL, 1, "revision-a", "test-token", "test-pay-pass")
        self.assertions = 0

    def booking_material(self, _user_id, _credential_id):
        return self.material

    def assert_booking_snapshot(self, _material):
        self.assertions += 1


class FakeProtocol:
    def __init__(self, now):
        self.now = now
        self.grid_calls = 0
        self.category_calls = 0
        self.quote_calls = 0
        self.create_calls = 0
        self.pay_calls = 0
        self.children_calls = 0
        self.created_children_counts = []
        self.get_user_calls = 0
        self.fresh_conflict = False
        self.create_error = None
        self.category_failures_remaining = 0
        self.category_failure_outcome = "uncertain"
        self.orders_paid = True
        self.current_order_no = None
        self.current_order_status = "1"
        self.order_status_hook = None
        self.list_order_calls = 0

    def _reply(self, envelope, *, date_header=None):
        return ProtocolReply(envelope, 200, date_header, self.now, self.now + 100, 100)

    def read_categories(self, _user_id, _credential_id, _token, **_kwargs):
        self.category_calls += 1
        if self.category_failures_remaining:
            self.category_failures_remaining -= 1
            raise UpstreamCallError("upstream_timeout", self.category_failure_outcome)
        return [{"node_id": f"category-response-{self.category_calls}", "label": "羽毛球"}], self._reply({
            "success": True, "message": "CORE10008", "resultData": [{"id": "category", "nodename": "羽毛球"}],
        })

    def read_grid(self, _user_id, _credential_id, _token, _node_id, _target_date, **_kwargs):
        self.grid_calls += 1
        conflicts = ["0-0-1"] if self.fresh_conflict and self.grid_calls > 1 else []
        return self._reply(booking_envelope(conflicts=conflicts))

    def get_user_info(self, _user_id, _credential_id, _token, **_kwargs):
        self.get_user_calls += 1
        server_time = datetime.fromtimestamp(self.now / 1000, timezone.utc).replace(microsecond=0)
        return self._reply({"success": True, "message": "CORE10008", "resultData": {"idserial": "reservation-person"}},
                           date_header=format_datetime(server_time, usegmt=True))

    def get_children(self, _token, _node_id):
        self.children_calls += 1
        return self._reply({"success": True, "message": "CORE10008", "resultData": {"childrennum": "1"}})

    def get_pay_price(self, *_args, **_kwargs):
        self.quote_calls += 1
        return self._reply({"success": True, "message": "CORE10008", "resultData": {"txamt": "20.00"}})

    def create_booking(self, *_args, **_kwargs):
        self.create_calls += 1
        self.created_children_counts.append(_kwargs.get("childrennum"))
        if self.create_error:
            raise self.create_error
        self.current_order_no = f"order-{self.create_calls}"
        return self._reply({"success": True, "message": "CORE10008", "resultData": {"orderno": self.current_order_no}})

    def pay_order(self, *_args, **_kwargs):
        self.pay_calls += 1
        return self._reply({"success": True, "message": "CORE10008", "resultData": {}})

    def list_orders(self, _token, **_kwargs):
        self.list_order_calls += 1
        if self.order_status_hook is not None:
            self.current_order_status = self.order_status_hook(self.create_calls, self.list_order_calls)
        else:
            self.current_order_status = "1" if self.orders_paid else "5"
        content = [{"orderno": self.current_order_no or "order-a", "bookingno": "booking-a",
                    "id": "id-a", "status": self.current_order_status}]
        return self._reply({"success": True, "message": "CORE10008", "resultData": {"content": content}})

    def order_details(self, *_args, **_kwargs):
        detail = {"status": self.current_order_status}
        if self.current_order_status == "5":
            detail["paytime"] = "2026-10-15 07:30:00"
        return self._reply({"success": True, "message": "CORE10008",
                            "resultData": detail})


class ExecutionEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="booking-execution-")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "execution.sqlite3"
        migrate_database(self.database, 5000)
        self._insert_owned_credential()
        self.plan_service = PlanService(self.database, 5000, BookingWindowPolicy(ZONE))
        self.queue = self.plan_service.save_manual_queue(
            USER, TARGET, 0,
            [{"court_preference": "6号场", "scope_label": "羽毛球", "start_time": "09:00",
              "end_time": "10:00", "duration_minutes": 60}],
            epoch(15, 0, 30), CREDENTIAL,
        )
        self.credentials = FakeCredentialService()
        self.protocol = FakeProtocol(epoch(15, 0, 30))
        self.sleeps = []
        self.monotonic_ns_value = 0
        self.engine = BookingExecutionEngine(
            database_path=self.database, busy_timeout_ms=5000,
            plan_service=self.plan_service, credential_service=self.credentials,
            protocol=self.protocol, timezone_name=ZONE, worker_enabled=True,
            clock_utc_ms=lambda: self.protocol.now, monotonic_ns=lambda: self.monotonic_ns_value,
            sleep=self._advance_sleep,
        )

    def _advance_sleep(self, seconds):
        self.sleeps.append(seconds)
        self.monotonic_ns_value += int(seconds * 1_000_000_000)
        self.protocol.now += int(seconds * 1000)

    def _insert_owned_credential(self, credential_id=CREDENTIAL, revision_id="revision-a"):
        with closing(connect_database(self.database, 5000)) as db:
            db.execute("BEGIN")
            db.execute(
                """INSERT OR IGNORE INTO users
                   (user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms)
                   VALUES (?, 'a', 'a', 'hash', 'user', 'active', ?, ?)""",
                (USER, epoch(15, 0, 0), epoch(15, 0, 0)),
            )
            db.execute(
                """INSERT INTO credentials
                   (credential_id,user_id,label,credential_version,enabled,current_token_revision_id,
                    account_binding_state,upstream_account_fingerprint,fingerprint_key_version,
                    account_identity_contract_version,last_confirmed_validation_state,requires_revalidation,
                    created_at_utc_ms,updated_at_utc_ms)
                   VALUES (?,?,'A',1,1,?,'confirmed',?,'fp-v1','getuserinfo-idserial-v1',
                           'confirmed_valid',0,?,?)""",
                (credential_id, USER, revision_id, "f" * 64,
                 epoch(15, 0, 0), epoch(15, 0, 0)),
            )
            db.execute(
                """INSERT INTO credential_token_revisions
                   (revision_id,user_id,credential_id,revision_number,token_fingerprint,
                    token_fingerprint_key_version,initial_validation_result,initial_validation_at_utc_ms,
                    created_by_user_id,secret_material_active,ciphertext,nonce,tag,encryption_key_version)
                   VALUES (?,?,?,1,?,'fp-v1','success',?,?,1,?,?,?,'enc-v1')""",
                (revision_id, USER, credential_id, "a" * 64, epoch(15, 0, 0), USER,
                 b"cipher", b"n" * 12, b"t" * 16),
            )
            db.commit()

    def _reconcile(self, settings=None):
        setting_dto = {"version": 0, "settings": dict(settings or DEFAULT_SETTINGS), "worker_enabled": True}
        return self.engine.reconcile(USER, CREDENTIAL, TARGET, self.queue, setting_dto)

    def _calibrate(self, run):
        self.protocol.now = epoch(15, 7, 29, 59)
        return self.engine.calibrate(run, USER, CREDENTIAL)

    def test_reconciles_then_executes_one_candidate_and_stops_after_payment(self):
        run = self._reconcile()
        self.assertEqual(run["state"], "ready")
        self.assertEqual(run["candidate_count"], 1)
        self.assertEqual(run["candidates"][0]["court_preference"], "6号场")
        calibrated = self._calibrate(run)
        self.assertEqual(calibrated["state"], "calibrated")
        self.protocol.now = epoch(15, 7, 30, 1)
        done = self.engine.execute(run["run_id"], USER, CREDENTIAL)
        self.assertEqual(done["state"], "succeeded")
        successful_run_id = done["run_id"]
        self.assertEqual(self.protocol.grid_calls, 2)  # one preflight, one fresh opening query
        self.assertEqual(self.protocol.quote_calls, 1)
        self.assertEqual(self.protocol.create_calls, 1)
        self.assertEqual(self.protocol.pay_calls, 1)
        self.assertEqual(self.protocol.children_calls, 0)
        self.assertEqual(self.protocol.created_children_counts, ["5"])
        self.assertTrue(any(stage["stage_key"] == "payment_verification" for stage in done["stages"]))
        successes = BookingExecutionRepository(self.database, 5000).list_successes(USER)
        self.assertEqual(len(successes), 1)
        self.assertEqual(
            (successes[0]["credential_id"], successes[0]["court_preference"],
             successes[0]["start_time"], successes[0]["verification"]),
            (CREDENTIAL, "6号场", "09:00", "order_query"),
        )
        self.assertEqual(BookingExecutionRepository(self.database, 5000).list_successes("other-user"), [])
        self.assertFalse({"token", "payment_password", "orderno"} & set(successes[0]))

    def test_configurable_query_candidate_and_verification_intervals_are_applied(self):
        self.queue = self.plan_service.save_manual_queue(
            USER, TARGET, self.queue["version"],
            [
                {"court_preference": "6号场", "scope_label": "羽毛球", "start_time": "09:00",
                 "end_time": "10:00", "duration_minutes": 60},
                {"court_preference": "6号场", "scope_label": "羽毛球", "start_time": "10:00",
                 "end_time": "11:00", "duration_minutes": 60},
            ],
            epoch(15, 0, 31), CREDENTIAL,
        )
        settings = {**DEFAULT_SETTINGS, "booking_by_time_delay_ms": 100,
                    "candidate_interval_ms": 250}
        self.protocol.fresh_conflict = True
        run = self._reconcile(settings)
        self._calibrate(run)
        self.protocol.now = epoch(15, 7, 30, 1)
        done = self.engine.execute(run["run_id"], USER, CREDENTIAL)
        self.assertEqual(done["state"], "succeeded")
        successful_run_id = done["run_id"]
        self.assertEqual(self.sleeps.count(0.1), 3)
        self.assertEqual(self.sleeps.count(0.25), 1)

        self.protocol.orders_paid = False
        self.sleeps.clear()
        next_queue = self.plan_service.save_manual_queue(
            USER, TARGET, self.queue["version"],
            [{"court_preference": "6号场", "scope_label": "羽毛球", "start_time": "11:00",
              "end_time": "12:00", "duration_minutes": 60}],
            epoch(15, 0, 32), CREDENTIAL,
        )
        verify_settings = {**DEFAULT_SETTINGS, "payment_verify_interval_ms": 125}
        run = self.engine.reconcile(
            USER, CREDENTIAL, TARGET, next_queue,
            {"version": 0, "settings": verify_settings, "worker_enabled": True},
        )
        self._calibrate(run)
        self.protocol.now = epoch(15, 7, 30, 2)
        done = self.engine.execute(run["run_id"], USER, CREDENTIAL)
        self.assertEqual(done["state"], "needs_attention")
        self.assertEqual(self.sleeps[:4], [0.125, 0.25, 0.5, 1.0])
        self.assertGreaterEqual(self.protocol.now - epoch(15, 7, 30, 2), 5 * 60 * 1000)
        self.assertEqual(
            [item["run_id"] for item in BookingExecutionRepository(self.database, 5000).list_successes(USER)],
            [successful_run_id],
        )

    def test_fresh_unavailable_candidates_are_rechecked_in_exactly_three_rounds(self):
        self.protocol.fresh_conflict = True
        run = self._reconcile()
        self._calibrate(run)
        self.protocol.now = epoch(15, 7, 30, 1)
        done = self.engine.execute(run["run_id"], USER, CREDENTIAL)
        self.assertEqual(done["state"], "failed")
        self.assertEqual(self.protocol.grid_calls, 4)  # preflight + one fresh query per round
        self.assertEqual(self.protocol.quote_calls, 0)
        self.assertEqual(sorted(stage["round_number"] for stage in done["stages"]
                                if stage["stage_key"] == "booking_by_time"), [1, 2, 3])

    def test_pending_order_with_a_nonempty_detail_paytime_is_never_successful(self):
        self.protocol.orders_paid = False
        run = self._reconcile()
        self._calibrate(run)
        self.protocol.now = epoch(15, 7, 30, 1)
        verification_started = self.protocol.now
        done = self.engine.execute(run["run_id"], USER, CREDENTIAL)
        self.assertEqual(done["state"], "needs_attention")
        self.assertEqual((self.protocol.create_calls, self.protocol.pay_calls), (1, 1))
        self.assertGreaterEqual(self.protocol.now - verification_started, 5 * 60 * 1000)
        self.assertEqual(self.engine.repository.list_successes(USER), [])
        verification = next(item for item in done['stages'] if item['stage_key'] == 'payment_verification')
        self.assertEqual((verification['outcome'], verification['safe_code']), ('uncertain', 'payment_pending'))

    def test_payment_verification_waits_beyond_old_attempt_limit_for_official_confirmation(self):
        run = self._reconcile()
        self._calibrate(run)
        self.protocol.now = epoch(15, 7, 30, 1)
        verification_started = self.protocol.now
        self.protocol.order_status_hook = lambda _created, _listed: (
            "5" if self.protocol.now - verification_started < 60_000 else "1"
        )

        done = self.engine.execute(run["run_id"], USER, CREDENTIAL)

        self.assertEqual(done["state"], "succeeded")
        self.assertGreaterEqual(self.protocol.now - verification_started, 60_000)
        self.assertEqual((self.protocol.create_calls, self.protocol.pay_calls), (1, 1))

    def test_transient_preflight_read_is_retried_and_successful_snapshot_is_saved(self):
        self.protocol.category_failures_remaining = 1

        run = self._reconcile()

        self.assertEqual(run["state"], "ready")
        self.assertEqual(self.protocol.category_calls, 2)
        failures = [stage for stage in run["stages"] if stage["stage_key"] == "reconcile_upstream_read"]
        self.assertEqual([(item["round_number"], item["outcome"]) for item in failures], [(1, "uncertain")])
        self.assertEqual(run["candidate_count"], 1)

    def test_persistent_preflight_read_failure_is_bounded_and_visible(self):
        self.protocol.category_failures_remaining = 3

        run = self._reconcile()

        self.assertEqual(run["state"], "needs_attention")
        self.assertEqual(self.protocol.category_calls, 3)
        failures = [stage for stage in run["stages"] if stage["stage_key"] == "reconcile_upstream_read"]
        self.assertEqual(sorted(item["round_number"] for item in failures), [1, 2, 3])

    def test_definitive_preflight_rejection_is_not_retried(self):
        self.protocol.category_failures_remaining = 1
        self.protocol.category_failure_outcome = "rejected"

        run = self._reconcile()

        self.assertEqual(run["state"], "needs_attention")
        self.assertEqual(self.protocol.category_calls, 1)

    def test_failed_order_list_envelope_cannot_confirm_payment(self):
        self.protocol.list_orders = lambda _token: self.protocol._reply({"success": False, "resultData": {"content": [{"orderno": "order-a", "status": "1"}]}})
        run = self._reconcile()
        self._calibrate(run)
        self.protocol.now = epoch(15, 7, 30, 1)
        done = self.engine.execute(run['run_id'], USER, CREDENTIAL)
        self.assertEqual(done['state'], 'needs_attention')
        self.assertEqual(self.engine.repository.list_successes(USER), [])

    def test_uncertain_order_creation_stops_without_replaying_or_paying(self):
        self.protocol.create_error = UpstreamCallError("upstream_transport_error", "uncertain")
        run = self._reconcile()
        self._calibrate(run)
        self.protocol.now = epoch(15, 7, 30, 1)
        done = self.engine.execute(run["run_id"], USER, CREDENTIAL)
        self.assertEqual(done["state"], "needs_attention")
        self.assertEqual(self.protocol.create_calls, 1)
        self.assertEqual(self.protocol.pay_calls, 0)
        self.assertEqual(self.protocol.grid_calls, 2)

    def test_queue_edit_after_preflight_makes_snapshot_stale(self):
        run = self._reconcile()
        self.plan_service.save_manual_queue(
            USER, TARGET, self.queue["version"],
            [{"court_preference": "6号场", "scope_label": "羽毛球", "start_time": "10:00",
              "end_time": "11:00", "duration_minutes": 60}],
            epoch(15, 1, 0), CREDENTIAL,
        )
        result = self._calibrate(run)
        self.assertEqual(result["state"], "stale")
        self.assertEqual(self.protocol.get_user_calls, 0)

    def test_queue_edit_during_payment_delay_stops_before_payment(self):
        run = self._reconcile({**DEFAULT_SETTINGS, "open_platform_pay_order_delay_ms": 1000})
        self._calibrate(run)
        self.protocol.now = epoch(15, 7, 30, 1)
        original_sleep = self.engine._sleep
        changed = False

        def edit_during_payment_delay(seconds):
            nonlocal changed
            original_sleep(seconds)
            if seconds == 1 and not changed:
                changed = True
                self.plan_service.save_manual_queue(
                    USER, TARGET, self.queue["version"],
                    [{"court_preference": "6号场", "scope_label": "羽毛球", "start_time": "10:00",
                      "end_time": "11:00", "duration_minutes": 60}],
                    epoch(15, 7, 30, 2), CREDENTIAL,
                )

        self.engine._sleep = edit_during_payment_delay
        done = self.engine.execute(run["run_id"], USER, CREDENTIAL)

        self.assertEqual(self.protocol.create_calls, 1)
        self.assertEqual(self.protocol.pay_calls, 0)
        self.assertEqual(done["state"], "needs_attention")
        self.assertTrue(any(stage["safe_code"] == "saved_queue_changed" for stage in done["stages"]))

    def test_queue_edit_during_create_delay_stops_before_order_creation(self):
        run = self._reconcile({**DEFAULT_SETTINGS, "create_booking_delay_ms": 1000})
        self._calibrate(run)
        self.protocol.now = epoch(15, 7, 30, 1)
        original_sleep = self.engine._sleep
        changed = False

        def edit_during_create_delay(seconds):
            nonlocal changed
            original_sleep(seconds)
            if seconds == 1 and not changed:
                changed = True
                self.plan_service.save_manual_queue(
                    USER, TARGET, self.queue["version"],
                    [{"court_preference": "6号场", "scope_label": "羽毛球", "start_time": "10:00",
                      "end_time": "11:00", "duration_minutes": 60}],
                    epoch(15, 7, 30, 2), CREDENTIAL,
                )

        self.engine._sleep = edit_during_create_delay
        done = self.engine.execute(run["run_id"], USER, CREDENTIAL)

        self.assertEqual(self.protocol.create_calls, 0)
        self.assertEqual(self.protocol.pay_calls, 0)
        self.assertEqual(done["state"], "needs_attention")
        self.assertTrue(any(stage["safe_code"] == "saved_queue_changed" for stage in done["stages"]))

    def test_scheduler_selects_only_exact_business_date_plus_two(self):
        settings_service = ExecutionSettingsService(self.database, 5000, worker_enabled=True)
        repository = BookingExecutionRepository(self.database, 5000)
        scheduler = BookingScheduler(
            settings_service=settings_service, engine=self.engine, repository=repository,
            plan_service=self.plan_service, timezone_name=ZONE, worker_enabled=True,
            clock_utc_ms=lambda: epoch(15, 0, 30),
        )
        result = scheduler.tick_once(epoch(15, 0, 30))
        self.assertEqual(result["target_date"], TARGET)
        self.assertEqual(result["reconciled"], 1)
        self.assertEqual(self.protocol.grid_calls, 1)
        self.assertIsNotNone(repository.latest_run(USER, CREDENTIAL, TARGET))

    def test_scheduler_reads_one_shared_profile_once_for_all_user_tokens(self):
        second = "credential-b"
        self._insert_owned_credential(second, "revision-b")
        second_queue = self.plan_service.save_manual_queue(
            USER, TARGET, 0,
            [{"court_preference": "6号场", "scope_label": "羽毛球", "start_time": "10:00",
              "end_time": "11:00", "duration_minutes": 60}],
            epoch(15, 0, 30), second,
        )
        self.assertTrue(second_queue["candidates"])
        settings_service = ExecutionSettingsService(self.database, 5000, worker_enabled=True)
        shared = {**DEFAULT_SETTINGS, "start_offset_ms": 875, "candidate_interval_ms": 250}
        settings_service.save(USER, 0, shared, epoch(15, 0, 0))
        original_get = settings_service.get
        calls = []

        def counted_get(user_id):
            calls.append(user_id)
            return original_get(user_id)

        settings_service.get = counted_get
        repository = BookingExecutionRepository(self.database, 5000)
        scheduler = BookingScheduler(
            settings_service=settings_service, engine=self.engine, repository=repository,
            plan_service=self.plan_service, timezone_name=ZONE, worker_enabled=True,
            clock_utc_ms=lambda: epoch(15, 0, 30),
        )
        result = scheduler.tick_once(epoch(15, 0, 30))
        self.assertEqual((result["reconciled"], calls), (2, [USER]))
        snapshots = [
            repository.latest_run(USER, credential_id, TARGET)["reconciliation"]["execution_settings"]
            for credential_id in (CREDENTIAL, second)
        ]
        self.assertEqual(snapshots, [shared, shared])

    def test_scheduler_dispatches_due_tokens_without_waiting_for_previous_execution(self):
        second = "credential-b"
        self._insert_owned_credential(second, "revision-b")
        second_queue = self.plan_service.save_manual_queue(
            USER, TARGET, 0,
            [{"court_preference": "6号场", "scope_label": "羽毛球", "start_time": "10:00",
              "end_time": "11:00", "duration_minutes": 60}],
            epoch(15, 0, 30), second,
        )
        first_run = self._reconcile()
        second_run = self.engine.reconcile(
            USER, second, TARGET, second_queue,
            {"version": 0, "settings": dict(DEFAULT_SETTINGS), "worker_enabled": True},
        )
        repository = BookingExecutionRepository(self.database, 5000)
        for run in (first_run, second_run):
            repository.update_state(
                run["run_id"], ("ready",), "calibrated", epoch(15, 7, 29),
                clock_offset_ms=0, clock_uncertainty_ms=0,
            )

        barrier = threading.Barrier(2, timeout=2)
        started = []

        def execute(run_id, user_id, credential_id):
            started.append((run_id, user_id, credential_id))
            barrier.wait()

        scheduler = BookingScheduler(
            settings_service=ExecutionSettingsService(self.database, 5000, worker_enabled=True),
            engine=self.engine, repository=repository, plan_service=self.plan_service,
            timezone_name=ZONE, worker_enabled=True,
            clock_utc_ms=lambda: epoch(15, 7, 30, 1),
        )
        original_execute = self.engine.execute
        self.engine.execute = execute
        try:
            result = scheduler.tick_once(epoch(15, 7, 30, 1))
        finally:
            self.engine.execute = original_execute
        self.assertEqual(result["executed"], 2)
        self.assertEqual({item[2] for item in started}, {CREDENTIAL, second})

    def test_scheduler_dispatches_fifty_due_tokens_in_one_bounded_batch(self):
        repository = BookingExecutionRepository(self.database, 5000)
        credentials = []
        for index in range(50):
            credential_id = f"credential-{index:02d}"
            self._insert_owned_credential(credential_id, f"revision-{index:02d}")
            queue = self.plan_service.save_manual_queue(
                USER, TARGET, 0,
                [{"court_preference": "6号场", "scope_label": "羽毛球", "start_time": "10:00",
                  "end_time": "11:00", "duration_minutes": 60}],
                epoch(15, 0, 30), credential_id,
            )
            run = self.engine.reconcile(
                USER, credential_id, TARGET, queue,
                {"version": 0, "settings": dict(DEFAULT_SETTINGS), "worker_enabled": True},
            )
            repository.update_state(
                run["run_id"], ("ready",), "calibrated", epoch(15, 7, 29),
                clock_offset_ms=0, clock_uncertainty_ms=0,
            )
            credentials.append(credential_id)

        barrier = threading.Barrier(50, timeout=5)
        started = []

        def execute(run_id, user_id, credential_id):
            started.append(credential_id)
            barrier.wait()

        scheduler = BookingScheduler(
            settings_service=ExecutionSettingsService(self.database, 5000, worker_enabled=True),
            engine=self.engine, repository=repository, plan_service=self.plan_service,
            timezone_name=ZONE, worker_enabled=True,
            clock_utc_ms=lambda: epoch(15, 7, 30, 1),
        )
        original_execute = self.engine.execute
        self.engine.execute = execute
        try:
            result = scheduler.tick_once(epoch(15, 7, 30, 1))
        finally:
            self.engine.execute = original_execute

        self.assertEqual(result["executed"], 50)
        self.assertEqual(set(started), set(credentials))


if __name__ == "__main__":
    unittest.main()
