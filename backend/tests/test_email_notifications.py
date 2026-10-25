from __future__ import annotations

import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from backend.booking_window import BookingWindowPolicy
from backend.db import connect_database
from backend.execution.repository import BookingExecutionRepository
from backend.execution.scheduler import BookingScheduler
from backend.execution.settings import ExecutionSettingsService
from backend.migrate import migrate_database
from backend.notifications import EmailNotificationService, NotificationSendError
from backend.plans.service import PlanService


ZONE = "Asia/Shanghai"
RECIPIENT = "notifications@example.test"


def epoch(day: int, hour: int = 0, minute: int = 0, second: int = 0) -> int:
    return int(datetime(2026, 10, day, hour, minute, second,
                        tzinfo=ZoneInfo(ZONE)).timestamp() * 1000)


def entry(court="2号场"):
    return {"court_preference": court, "scope_label": "羽毛球", "start_time": "16:00",
            "end_time": "18:00", "duration_minutes": 120}


class EmailNotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="yumao-email-notifications-")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "notifications.sqlite3"
        migrate_database(self.database, 5000)
        self._insert_user_and_credential("owner", "notification-owner", "credential-a")
        self._insert_user_and_credential("other", "other", "credential-b")
        self.plans = PlanService(self.database, 5000, BookingWindowPolicy(ZONE))
        self.queue = self.plans.save_manual_queue(
            "owner", "2026-10-26", 0, [entry()], epoch(10), "credential-a",
        )
        self.deliveries = []
        self.service = self._service(self._capture, default_enabled=True)

    def _capture(self, payload):
        self.deliveries.append(payload)
        return {"accepted": True, "message_id": f"message-{len(self.deliveries)}"}

    def _insert_user_and_credential(self, user_id, username, credential_id):
        with closing(connect_database(self.database, 5000)) as db:
            db.execute("BEGIN")
            db.execute(
                """INSERT INTO users
                   (user_id,username,normalized_username,password_hash,role,status,
                    created_at_utc_ms,updated_at_utc_ms)
                   VALUES (?,?,?,'test-hash','user','active',1,1)""",
                (user_id, username, username),
            )
            revision = f"revision-{credential_id}"
            db.execute(
                """INSERT INTO credentials
                   (credential_id,user_id,label,credential_version,enabled,current_token_revision_id,
                    account_binding_state,upstream_account_fingerprint,fingerprint_key_version,
                    account_identity_contract_version,last_confirmed_validation_state,
                    requires_revalidation,created_at_utc_ms,updated_at_utc_ms)
                   VALUES (?,?,?,1,1,?,'unresolved',NULL,NULL,NULL,'never_confirmed',0,1,1)""",
                (credential_id, user_id, credential_id, revision),
            )
            db.execute(
                """INSERT INTO credential_token_revisions
                   (revision_id,user_id,credential_id,revision_number,token_fingerprint,
                    token_fingerprint_key_version,initial_validation_result,initial_validation_at_utc_ms,
                    created_by_user_id,secret_material_active,ciphertext,nonce,tag,encryption_key_version)
                   VALUES (?,?,?,1,?,'fp-v1','success',1,?,1,?,?,?,'enc-v1')""",
                (revision, user_id, credential_id, "a" * 64, user_id,
                 b"cipher", b"n" * 12, b"t" * 16),
            )
            db.commit()

    def _service(self, sender, *, default_enabled=False):
        return EmailNotificationService(
            self.database, 5000, timezone_name=ZONE, owner_username="notification-owner",
            recipient=RECIPIENT, worker_url="https://mailer.qq274268.workers.dev/notify",
            hmac_secret="ab" * 32, default_enabled=default_enabled,
            worker_enabled=True, plan_service=self.plans,
            clock_utc_ms=lambda: epoch(23, 19), sender=sender,
        )

    def _outbox(self, kind):
        with closing(connect_database(self.database, 5000)) as db:
            row = db.execute(
                "SELECT * FROM booking_email_notification_outbox WHERE user_id='owner' AND kind=?",
                (kind,),
            ).fetchone()
        return dict(row) if row else None

    def test_reminder_and_result_dates_follow_target_minus_two_days(self):
        self.service.sync_queue("owner", "credential-a", "2026-10-26", self.queue, epoch(23, 19))
        reminder, result = self._outbox("reminder"), self._outbox("result")
        self.assertEqual(reminder["scheduled_at_utc_ms"], epoch(23, 20))
        self.assertEqual(result["scheduled_at_utc_ms"], epoch(24, 8))
        self.assertEqual(reminder["queue_revision_id"], self.queue["current_revision_id"])

    def test_repeated_scheduler_ticks_create_one_outbox_record_per_event(self):
        for now in (epoch(23, 19), epoch(23, 19, 30), epoch(23, 19, 59)):
            self.service.sync_queue("owner", "credential-a", "2026-10-26", self.queue, now)
        with closing(connect_database(self.database, 5000)) as db:
            count = db.execute(
                "SELECT count(*) FROM booking_email_notification_outbox WHERE user_id='owner'",
            ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_concurrent_dispatchers_claim_one_reminder_once(self):
        self.service.sync_queue("owner", "credential-a", "2026-10-26", self.queue, epoch(23, 19))
        with ThreadPoolExecutor(max_workers=2) as executor:
            counts=list(executor.map(lambda _index:self.service.dispatch_due(epoch(23,20)), range(2)))
        self.assertEqual(sum(counts),1)
        self.assertEqual(len(self.deliveries),1)
        self.assertEqual(self._outbox("reminder")["status"],"sent")

    def test_queue_edit_updates_only_pending_reminder_snapshot(self):
        self.service.sync_queue("owner", "credential-a", "2026-10-26", self.queue, epoch(23, 19))
        reminder = self._outbox("reminder")
        updated = self.plans.save_manual_queue(
            "owner", "2026-10-26", self.queue["version"], [entry("4号场")], epoch(23, 19, 30),
            "credential-a",
        )
        self.service.sync_queue("owner", "credential-a", "2026-10-26", updated, epoch(23, 19, 31))
        outbox = self._outbox("reminder")
        self.assertEqual(outbox["notification_id"], reminder["notification_id"])
        self.assertEqual(outbox["queue_version"], updated["version"])
        self.assertEqual(self.service._reminder_payload(outbox)["candidates"][0]["courts"], ["4号场"])

    def test_live_scheduler_queues_t_minus_one_reminder_and_eight_am_report(self):
        scheduler = BookingScheduler(
            settings_service=ExecutionSettingsService(self.database, 5000, worker_enabled=True),
            engine=None, repository=BookingExecutionRepository(self.database, 5000),
            plan_service=self.plans, timezone_name=ZONE, worker_enabled=True,
            clock_utc_ms=lambda: epoch(23, 19, 59, 59), email_notification_service=self.service,
        )
        result = scheduler.tick_once(epoch(23, 19, 59, 59))
        self.assertEqual(result["target_date"], "2026-10-25")
        self.assertEqual(result["reconciled"], 0)
        self.assertEqual(self._outbox("reminder")["scheduled_at_utc_ms"], epoch(23, 20))
        self.assertEqual(self._outbox("result")["scheduled_at_utc_ms"], epoch(24, 8))
        self.assertEqual(self.service.next_due_at_utc_ms(), epoch(23, 20))
        self.assertEqual(scheduler.next_wait_ms(epoch(23, 19, 59, 59)), 1000)

    def test_scheduler_skips_extra_notification_queue_reads_for_nonowners(self):
        scheduler = BookingScheduler(
            settings_service=ExecutionSettingsService(self.database, 5000, worker_enabled=True),
            engine=None, repository=BookingExecutionRepository(self.database, 5000),
            plan_service=self.plans, timezone_name=ZONE, worker_enabled=True,
            clock_utc_ms=lambda: epoch(23, 19, 59, 59), email_notification_service=self.service,
        )
        original = self.plans.get_manual_queue
        reads = []

        def track_read(user_id, target_date, credential_id=None):
            reads.append((user_id, target_date))
            return original(user_id, target_date, credential_id)

        with patch.object(self.plans, "get_manual_queue", side_effect=track_read):
            scheduler.tick_once(epoch(23, 19, 59, 59))

        self.assertEqual([target for user, target in reads if user == "other"], ["2026-10-25"])
        self.assertEqual(len([target for user, target in reads if user == "owner"]), 3)

    def test_notification_owner_lookup_failure_does_not_stop_scheduler(self):
        self.service.owns_notifications = Mock(side_effect=RuntimeError("private storage error"))
        scheduler = BookingScheduler(
            settings_service=ExecutionSettingsService(self.database, 5000, worker_enabled=True),
            engine=None, repository=BookingExecutionRepository(self.database, 5000),
            plan_service=self.plans, timezone_name=ZONE, worker_enabled=True,
            clock_utc_ms=lambda: epoch(23, 19, 59, 59), email_notification_service=self.service,
        )

        result = scheduler.tick_once(epoch(23, 19, 59, 59))

        self.assertEqual(result["target_date"], "2026-10-25")

    def test_reminder_describes_saved_preferences_and_result_uses_verified_actual_candidate(self):
        self.service.sync_queue("owner", "credential-a", "2026-10-26", self.queue, epoch(23, 19))
        self.assertEqual(self.service.dispatch_due(epoch(23, 20)), 1)
        self.assertEqual(self.deliveries[0]["kind"], "reminder")
        self.assertEqual(self.deliveries[0]["candidates"][0]["courts"], ["2号场"])

        repository = BookingExecutionRepository(self.database, 5000)
        run = repository.create_run(
            user_id="owner", credential_id="credential-a", target_date="2026-10-26",
            queue=self.queue, candidates=[{**entry(), "queue_index": 0}],
            reconciliation={"retained_candidate_count": 1}, state="ready", now_utc_ms=epoch(24, 7, 30),
        )
        repository.update_state(run["run_id"], ("ready",), "running", epoch(24, 7, 31), started=True)
        repository.record_stage(run["run_id"], {
            "round_number": 1, "candidate_index": 0, "stage_key": "payment_verification",
            "started_at_utc_ms": epoch(24, 7, 32), "completed_at_utc_ms": epoch(24, 7, 33),
            "elapsed_ms": 1000, "outcome": "success", "safe_code": None,
        })
        repository.update_state(run["run_id"], ("running",), "succeeded", epoch(24, 7, 33), completed=True)
        self.assertEqual(self.service.dispatch_due(epoch(24, 8)), 1)
        result = self.deliveries[1]
        self.assertEqual(result["outcome"], "succeeded")
        self.assertEqual((result["court"], result["start_time"], result["end_time"]),
                         ("2号场", "16:00", "18:00"))
        self.assertEqual(self.service.dispatch_due(epoch(24, 8, 30)), 0)
        self.assertEqual(self._outbox("result")["status"], "sent")

    def test_only_the_configured_owner_can_read_settings_or_schedule_email(self):
        self.assertTrue(self.service.get_settings("owner")["available"])
        self.assertFalse(self.service.get_settings("other")["available"])
        other_queue = self.plans.save_manual_queue(
            "other", "2026-10-26", 0, [entry("3号场")], epoch(10), "credential-b",
        )
        self.service.sync_queue("other", "credential-b", "2026-10-26", other_queue, epoch(23, 19))
        with closing(connect_database(self.database, 5000)) as db:
            count = db.execute(
                "SELECT count(*) FROM booking_email_notification_outbox WHERE user_id='other'",
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_reminder_and_result_settings_use_version_checks_and_disable_pending_events(self):
        initial = self.service.get_settings("owner")
        self.assertTrue(initial["enabled"])
        saved = self.service.save_settings("owner", initial["version"], False, "19:30", epoch(23, 19))
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["reminder_time"], "19:30")
        with self.assertRaisesRegex(ValueError, "email_notification_version_conflict"):
            self.service.save_settings("owner", initial["version"], True, "20:00", epoch(23, 19))
        self.service.sync_queue("owner", "credential-a", "2026-10-26", self.queue, epoch(23, 19))
        self.assertIsNone(self._outbox("reminder"))

    def test_notification_failures_never_change_booking_state_and_ambiguous_send_is_not_retried(self):
        self.service.sync_queue("owner", "credential-a", "2026-10-26", self.queue, epoch(23, 19))
        retrying = self._service(lambda _payload: (_ for _ in ()).throw(
            NotificationSendError("provider_retryable", retryable=True)), default_enabled=True)
        self.assertEqual(retrying.dispatch_due(epoch(23, 20)), 0)
        reminder = self._outbox("reminder")
        self.assertEqual(reminder["status"], "pending")
        self.assertEqual(reminder["next_attempt_at_utc_ms"], epoch(23, 20) + 30_000)
        uncertain = self._service(lambda _payload: (_ for _ in ()).throw(
            NotificationSendError("provider_timeout", uncertain=True)), default_enabled=True)
        self.assertEqual(uncertain.dispatch_due(reminder["next_attempt_at_utc_ms"]), 0)
        self.assertEqual(self._outbox("reminder")["status"], "uncertain")
        self.assertEqual(self.plans.get_manual_queue("owner", "2026-10-26", "credential-a")["version"],
                         self.queue["version"])

    def test_result_mail_distinguishes_exhausted_candidates_from_an_empty_preflight(self):
        repository = BookingExecutionRepository(self.database, 5000)
        failed = repository.create_run(
            user_id="owner", credential_id="credential-a", target_date="2026-10-26",
            queue=self.queue, candidates=[{**entry(), "queue_index": 0}],
            reconciliation={"retained_candidate_count": 1}, state="ready", now_utc_ms=epoch(24, 7, 30),
        )
        repository.update_state(failed["run_id"], ("ready",), "running", epoch(24, 7, 31), started=True)
        repository.update_state(failed["run_id"], ("running",), "failed", epoch(24, 7, 34), completed=True)
        failed_payload=self.service._result_payload({"user_id":"owner","credential_id":"credential-a",
            "target_date":"2026-10-26","queue_revision_id":self.queue["current_revision_id"],
            "notification_id":"failed-id"})
        self.assertEqual(failed_payload["outcome"], "failed")
        self.assertIn("未抢到", failed_payload["status_label"])

        empty_queue=self.plans.save_manual_queue("owner","2026-10-27",0,[entry()],epoch(10),"credential-a")
        repository.create_run(user_id="owner",credential_id="credential-a",target_date="2026-10-27",
            queue=empty_queue,candidates=[],reconciliation={"retained_candidate_count":0},
            state="empty",now_utc_ms=epoch(25,0,30))
        empty_payload=self.service._result_payload({"user_id":"owner","credential_id":"credential-a",
            "target_date":"2026-10-27","queue_revision_id":empty_queue["current_revision_id"],
            "notification_id":"empty-id"})
        self.assertEqual(empty_payload["outcome"], "empty")
        self.assertIn("没有可执行", empty_payload["status_label"])

    def test_cloudflare_request_is_signed_and_redirects_are_not_followed(self):
        self.service._clock=lambda:epoch(23,19)
        response=Mock(status_code=200)
        response.iter_content.return_value=[b'{"accepted":true,"message_id":"message-a"}']
        payload={"notification_id":"event-a","kind":"test","outcome":"test",
                 "status_label":"发信测试"}
        with patch('backend.notifications.requests.post',return_value=response) as post:
            result=self.service._send(payload)
        self.assertEqual(result,{"accepted":True,"message_id":"message-a"})
        args,kwargs=post.call_args
        body=kwargs["data"]
        expected=__import__('hmac').new(b'\xab'*32,str(epoch(23,19)//1000).encode()+b'\n'+body,__import__('hashlib').sha256).hexdigest()
        self.assertEqual(kwargs["headers"]["X-Yumao-Signature"],expected)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertIn("/notify",args[0])

    def test_cloudflare_unknown_outcome_is_never_retried(self):
        response = Mock(status_code=409)
        response.iter_content.return_value = [b'{"error":"provider_outcome_unknown","provider_code":"E_INTERNAL_SERVER_ERROR"}']
        with patch('backend.notifications.requests.post', return_value=response):
            with self.assertRaises(NotificationSendError) as caught:
                self.service._send({"notification_id":"event-a","kind":"test",
                                    "outcome":"test","status_label":"test"})
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(caught.exception.code,"cloudflare_e_internal_server_error")

    def test_cloudflare_explicit_rate_limit_is_retryable(self):
        response = Mock(status_code=429)
        response.iter_content.return_value = [b'{"error":"provider_retryable","provider_code":"E_RATE_LIMIT_EXCEEDED"}']
        with patch('backend.notifications.requests.post', return_value=response):
            with self.assertRaises(NotificationSendError) as caught:
                self.service._send({"notification_id":"event-a","kind":"test",
                                    "outcome":"test","status_label":"test"})
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.code,"cloudflare_e_rate_limit_exceeded")

    def test_invalid_provider_code_is_not_persisted(self):
        response = Mock(status_code=409)
        response.iter_content.return_value = [b'{"error":"provider_outcome_unknown","provider_code":"SECRET\\nVALUE"}']
        with patch('backend.notifications.requests.post', return_value=response):
            with self.assertRaises(NotificationSendError) as caught:
                self.service._send({"notification_id":"event-a","kind":"test",
                                    "outcome":"test","status_label":"test"})
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(caught.exception.code,"provider_outcome_unknown")


if __name__ == "__main__":
    unittest.main()
