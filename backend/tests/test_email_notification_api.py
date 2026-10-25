from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backend.app import create_app
from backend.db import connect_database
from backend.migrate import migrate_database
from support import credential_test_settings


ORIGIN = "http://localhost:5173"


class EmailNotificationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="email-notification-api-")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "email.sqlite3"
        migrate_database(self.database, 5000)
        self.app = create_app({
            **credential_test_settings(self.database), "TESTING": True,
            "APP_ALLOWED_ORIGINS": ORIGIN,
            "EMAIL_NOTIFICATION_OWNER_USERNAME": "notification-owner",
            "EMAIL_NOTIFICATION_RECIPIENT": "notifications@example.test",
            "EMAIL_NOTIFICATION_WORKER_URL": "https://mailer.qq274268.workers.dev/notify",
            "EMAIL_NOTIFICATION_HMAC_SECRET": "ab" * 32,
            "EMAIL_NOTIFICATION_DEFAULT_ENABLED": "true",
        })
        with closing(connect_database(self.database, 5000)) as db:
            db.executemany(
                """INSERT INTO users
                   (user_id,username,normalized_username,password_hash,role,status,
                    created_at_utc_ms,updated_at_utc_ms)
                   VALUES (?,?,?,'test-hash','user','active',1,1)""",
                [("owner", "notification-owner", "notification-owner"), ("other", "other", "other")],
            )

    def client(self, user_id):
        session_id, csrf = self.app.extensions["session_service"].create(user_id, 1_800_000_000_000)
        client = self.app.test_client()
        client.set_cookie("yumao_session", session_id)
        return client, csrf

    def test_owner_can_read_and_update_versioned_settings_only(self):
        owner, csrf = self.client("owner")
        initial = owner.get("/api/booking-execution/email-notifications")
        self.assertEqual(initial.status_code, 200)
        self.assertTrue(initial.get_json()["available"])
        self.assertEqual(initial.get_json()["recipient"], "notifications@example.test")
        self.assertEqual(initial.get_json()["result_time"], "08:00")
        updated = owner.put(
            "/api/booking-execution/email-notifications",
            json={"expected_version": 1, "enabled": True, "reminder_time": "19:45"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["reminder_time"], "19:45")
        conflict = owner.put(
            "/api/booking-execution/email-notifications",
            json={"expected_version": 1, "enabled": False, "reminder_time": "20:00"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        self.assertEqual(conflict.status_code, 409)
        too_early = owner.put(
            "/api/booking-execution/email-notifications",
            json={"expected_version": 2, "enabled": True, "reminder_time": "17:59"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        self.assertEqual(too_early.status_code, 400)

        other, other_csrf = self.client("other")
        self.assertFalse(other.get("/api/booking-execution/email-notifications").get_json()["available"])
        denied = other.put(
            "/api/booking-execution/email-notifications",
            json={"expected_version": 1, "enabled": True, "reminder_time": "20:00"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": other_csrf},
        )
        self.assertEqual(denied.status_code, 404)

    def test_settings_reject_recipient_override_and_require_csrf(self):
        owner, csrf = self.client("owner")
        missing_csrf = owner.put(
            "/api/booking-execution/email-notifications",
            json={"expected_version": 1, "enabled": True, "reminder_time": "20:00"},
            headers={"Origin": ORIGIN},
        )
        self.assertEqual(missing_csrf.status_code, 403)
        override = owner.put(
            "/api/booking-execution/email-notifications",
            json={"expected_version": 1, "enabled": True, "reminder_time": "20:00",
                  "recipient": "other@example.com"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        self.assertEqual(override.status_code, 400)

    def test_test_email_is_owner_only_csrf_protected_and_rate_limited(self):
        owner, csrf = self.client("owner")
        service = self.app.extensions["email_notification_service"]
        sent = []
        service._sender = lambda payload: sent.append(payload) or {
            "accepted": True, "message_id": "synthetic-message-id",
        }
        response = owner.post(
            "/api/booking-execution/email-notifications/test", json={},
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sent[0]["kind"], "test")
        self.assertEqual(response.get_json(), {"accepted": True, "message_id": "synthetic-message-id"})
        limited = owner.post(
            "/api/booking-execution/email-notifications/test", json={},
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        self.assertEqual(limited.status_code, 429)
        other, other_csrf = self.client("other")
        denied = other.post(
            "/api/booking-execution/email-notifications/test", json={},
            headers={"Origin": ORIGIN, "X-CSRF-Token": other_csrf},
        )
        self.assertEqual(denied.status_code, 404)
