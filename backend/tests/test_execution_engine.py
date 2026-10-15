from __future__ import annotations

import tempfile
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
        self.get_user_calls = 0
        self.fresh_conflict = False
        self.create_error = None
        self.orders_paid = True

    def _reply(self, envelope, *, date_header=None):
        return ProtocolReply(envelope, 200, date_header, self.now, self.now + 100, 100)

    def read_categories(self, _user_id, _credential_id, _token):
        self.category_calls += 1
        return [{"node_id": f"category-response-{self.category_calls}", "label": "羽毛球"}], self._reply({
            "success": True, "message": "CORE10008", "resultData": [{"id": "category", "nodename": "羽毛球"}],
        })

    def read_grid(self, _user_id, _credential_id, _token, _node_id, _target_date):
        self.grid_calls += 1
        conflicts = ["0-0-1"] if self.fresh_conflict and self.grid_calls > 1 else []
        return self._reply(booking_envelope(conflicts=conflicts))

    def get_user_info(self, _user_id, _credential_id, _token):
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
        if self.create_error:
            raise self.create_error
        return self._reply({"success": True, "message": "CORE10008", "resultData": {"orderno": "order-a"}})

    def pay_order(self, *_args, **_kwargs):
        self.pay_calls += 1
        return self._reply({"success": True, "message": "CORE10008", "resultData": {}})

    def list_orders(self, _token):
        content = [{"orderno": "order-a", "bookingno": "booking-a", "id": "id-a", "status": "1"}]
        return self._reply({"success": True, "message": "CORE10008", "resultData": {"content": content if self.orders_paid else []}})

    def order_details(self, *_args, **_kwargs):
        return self._reply({"success": True, "message": "CORE10008", "resultData": {"status": "1"}})


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
        self.engine = BookingExecutionEngine(
            database_path=self.database, busy_timeout_ms=5000,
            plan_service=self.plan_service, credential_service=self.credentials,
            protocol=self.protocol, timezone_name=ZONE, worker_enabled=True,
            clock_utc_ms=lambda: self.protocol.now, sleep=lambda _seconds: None,
        )

    def _insert_owned_credential(self):
        with closing(connect_database(self.database, 5000)) as db:
            db.execute("BEGIN")
            db.execute(
                """INSERT INTO users
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
                   VALUES (?,?,'A',1,1,'revision-a','confirmed',?,'fp-v1','getuserinfo-idserial-v1',
                           'confirmed_valid',0,?,?)""",
                (CREDENTIAL, USER, "f" * 64, epoch(15, 0, 0), epoch(15, 0, 0)),
            )
            db.execute(
                """INSERT INTO credential_token_revisions
                   (revision_id,user_id,credential_id,revision_number,token_fingerprint,
                    token_fingerprint_key_version,initial_validation_result,initial_validation_at_utc_ms,
                    created_by_user_id,secret_material_active,ciphertext,nonce,tag,encryption_key_version)
                   VALUES ('revision-a',?,?,1,?,'fp-v1','success',?,?,1,?,?,?,'enc-v1')""",
                (USER, CREDENTIAL, "a" * 64, epoch(15, 0, 0), USER,
                 b"cipher", b"n" * 12, b"t" * 16),
            )
            db.commit()

    def _reconcile(self):
        setting_dto = {"version": 0, "settings": dict(DEFAULT_SETTINGS), "worker_enabled": True}
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
        self.assertEqual(self.protocol.grid_calls, 2)  # one preflight, one fresh opening query
        self.assertEqual(self.protocol.quote_calls, 1)
        self.assertEqual(self.protocol.create_calls, 1)
        self.assertEqual(self.protocol.pay_calls, 1)
        self.assertEqual(self.protocol.children_calls, 1)
        self.assertTrue(any(stage["stage_key"] == "payment_verification" for stage in done["stages"]))

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


if __name__ == "__main__":
    unittest.main()
