from __future__ import annotations

import tempfile
import unittest
import shutil
from contextlib import closing
from pathlib import Path

from backend.app import create_app
from backend.db import connect_database
from backend.execution.settings import DEFAULT_SETTINGS, ExecutionSettingsService, validate_settings
from backend.migrate import migrate_database
from support import credential_test_settings


NOW = 1_800_000_000_000
ORIGIN = "http://localhost:5173"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


class ExecutionSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="execution-settings-")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "settings.sqlite3"
        migrate_database(self.database, 5000)
        self.app = create_app({**credential_test_settings(self.database), "TESTING": True,
                               "APP_ALLOWED_ORIGINS": ORIGIN})
        self.service = self.app.extensions["execution_settings_service"]
        self._insert_account("user-a", "credential-a")
        self._insert_account("user-a", "credential-b")
        self._insert_account("user-b", "credential-private")

    def _insert_account(self, user_id, credential_id, database=None):
        target = database or self.database
        with closing(connect_database(target, 5000)) as db:
            db.execute("BEGIN")
            db.execute(
                """INSERT OR IGNORE INTO users
                   (user_id, username, normalized_username, password_hash, role, status,
                    created_at_utc_ms, updated_at_utc_ms)
                   VALUES (?, ?, ?, 'synthetic-hash', 'user', 'active', ?, ?)""",
                (user_id, user_id, user_id, NOW, NOW),
            )
            db.execute(
                """INSERT INTO credentials
                   (credential_id, user_id, label, credential_version, enabled,
                    current_token_revision_id, account_binding_state,
                    last_confirmed_validation_state, requires_revalidation,
                    created_at_utc_ms, updated_at_utc_ms)
                   VALUES (?, ?, 'test', 1, 1, ?, 'unresolved', 'never_confirmed', 0, ?, ?)""",
                (credential_id, user_id, f"revision-{credential_id}", NOW, NOW),
            )
            db.execute(
                """INSERT INTO credential_token_revisions
                   (revision_id, user_id, credential_id, revision_number, token_fingerprint,
                    token_fingerprint_key_version, initial_validation_result,
                    initial_validation_at_utc_ms, created_by_user_id, secret_material_active,
                    ciphertext, nonce, tag, encryption_key_version)
                   VALUES (?, ?, ?, 1, ?, 'fp-v1', 'success', ?, ?, 1, ?, ?, ?, 'enc-v1')""",
                (f"revision-{credential_id}", user_id, credential_id, "a" * 64,
                 NOW, user_id, b"cipher", b"n" * 12, b"t" * 16),
            )
            db.commit()

    def test_defaults_and_updates_are_shared_by_tokens_and_isolated_per_user(self):
        initial = self.service.get("user-a")
        self.assertEqual(initial["version"], 0)
        self.assertEqual(initial["settings"], DEFAULT_SETTINGS)
        updated = {**DEFAULT_SETTINGS, "reconciliation_time": "01:15", "start_offset_ms": 875}
        saved = self.service.save("user-a", 0, updated, NOW)
        self.assertEqual(saved["version"], 1)
        self.assertEqual(saved["settings"], updated)
        self.assertEqual(self.service.get("user-a")["settings"], updated)
        self.service.assert_credential_owner("user-a", "credential-a")
        self.service.assert_credential_owner("user-a", "credential-b")
        self.assertEqual(self.service.get("user-b")["settings"], DEFAULT_SETTINGS)

    def test_optimistic_version_rejects_stale_settings_write(self):
        first = self.service.save("user-a", 0, DEFAULT_SETTINGS, NOW)
        with self.assertRaisesRegex(ValueError, "execution_settings_version_conflict"):
            self.service.save("user-a", 0, DEFAULT_SETTINGS, NOW + 1)
        self.assertEqual(first["version"], 1)

    def test_migration_uses_each_users_most_recent_legacy_token_settings(self):
        with tempfile.TemporaryDirectory(prefix="execution-settings-v11-") as temp:
            root = Path(temp)
            legacy_migrations = root / "migrations"
            legacy_migrations.mkdir()
            for source in sorted(MIGRATIONS.glob("*.sql")):
                if source.name < "0012_user_execution_settings.sql":
                    shutil.copyfile(source, legacy_migrations / source.name)
            database = root / "legacy.sqlite3"
            migrate_database(database, 5000, legacy_migrations)
            self._insert_account("legacy-a", "legacy-token-a", database)
            self._insert_account("legacy-a", "legacy-token-b", database)
            self._insert_account("legacy-b", "legacy-token-private", database)
            with closing(connect_database(database, 5000)) as db:
                values = (
                    "reconciliation_time, clock_calibration_lead_ms, start_offset_ms, "
                    "booking_node_delay_ms, booking_by_time_delay_ms, get_user_info_delay_ms, "
                    "get_children_delay_ms, get_pay_price_delay_ms, create_booking_delay_ms, "
                    "open_platform_pay_order_delay_ms, payment_verify_delay_ms, updated_at_utc_ms"
                )
                placeholders = ",".join("?" for _ in range(12))
                for user_id, credential_id, version, offset, updated in (
                    ("legacy-a", "legacy-token-a", 2, 100, NOW),
                    ("legacy-a", "legacy-token-b", 5, 875, NOW + 1),
                    ("legacy-b", "legacy-token-private", 3, 250, NOW + 2),
                ):
                    db.execute(
                        f"INSERT INTO booking_execution_settings "
                        f"(user_id, credential_id, version, {values}) VALUES (?,?,?,{placeholders})",
                        (user_id, credential_id, version, "00:30", 1000, offset,
                         0, 0, 0, 0, 0, 0, 0, 0, updated),
                    )
                db.commit()
            migrate_database(database, 5000, MIGRATIONS)
            service = ExecutionSettingsService(database, 5000)
            self.assertEqual(service.get("legacy-a")["version"], 5)
            self.assertEqual(service.get("legacy-a")["settings"]["start_offset_ms"], 875)
            self.assertEqual(service.get("legacy-b")["settings"]["start_offset_ms"], 250)
            self.assertEqual(service.get("legacy-a")["settings"]["payment_verify_interval_ms"], 3000)

    def test_settings_validate_fixed_preflight_window_and_bounded_delays(self):
        self.assertEqual(validate_settings(DEFAULT_SETTINGS), DEFAULT_SETTINGS)
        self.assertEqual(
            validate_settings({**DEFAULT_SETTINGS, "open_platform_pay_order_delay_ms": 120_000})[
                "open_platform_pay_order_delay_ms"
            ],
            120_000,
        )
        for invalid in (
            {**DEFAULT_SETTINGS, "reconciliation_time": "07:30"},
            {**DEFAULT_SETTINGS, "reconciliation_time": "7:00"},
            {**DEFAULT_SETTINGS, "start_offset_ms": True},
            {**DEFAULT_SETTINGS, "get_pay_price_delay_ms": 60_001},
            {**DEFAULT_SETTINGS, "open_platform_pay_order_delay_ms": 120_001},
            {**DEFAULT_SETTINGS, "unexpected": 1},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_settings(invalid)

    def test_api_requires_session_csrf_and_keeps_owner_scope(self):
        client = self.app.test_client()
        response = client.get("/api/booking-execution/settings")
        self.assertEqual(response.status_code, 401)

        session_id, csrf = self.app.extensions["session_service"].create("user-a", NOW)
        client.set_cookie("yumao_session", session_id)
        url = "/api/booking-execution/settings"
        response = client.get(url, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["settings"], DEFAULT_SETTINGS)
        response = client.put(url, json={"expected_version": 0, "settings": DEFAULT_SETTINGS},
                              headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 403)
        response = client.put(url, json={"expected_version": 0, "settings": DEFAULT_SETTINGS},
                              headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200)

        legacy = "/api/booking-execution/credentials/credential-b/settings"
        response = client.get(legacy, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["settings"], DEFAULT_SETTINGS)
        other = "/api/booking-execution/credentials/credential-private/settings"
        response = client.get(other, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 404)

    def test_execution_snapshot_status_is_owner_scoped_and_read_only(self):
        client = self.app.test_client()
        session_id, _csrf = self.app.extensions["session_service"].create("user-a", NOW)
        client.set_cookie("yumao_session", session_id)
        path = "/api/booking-execution/credentials/credential-a/queues/2026-10-20"
        response = client.get(path, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"run": None, "worker_enabled": False})
        private = "/api/booking-execution/credentials/credential-private/queues/2026-10-20"
        self.assertEqual(client.get(private, headers={"Origin": ORIGIN}).status_code, 404)
        self.assertEqual(client.get(path.replace("2026-10-20", "bad"), headers={"Origin": ORIGIN}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
