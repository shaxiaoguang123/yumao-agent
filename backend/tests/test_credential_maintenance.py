from __future__ import annotations

import base64
import contextlib
import io
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from backend.credentials.crypto import CredentialTokenCipher
from backend.credentials.keyring import CredentialKeyring
from backend.credentials.key_dependencies import (
    CredentialKeyDependencyError,
    check_credential_key_dependencies,
)
from backend.credentials.tokens import token_fingerprint
from backend.db import connect_database
from backend.migrate import migrate_database
from backend.settings import load_settings
from support import credential_test_settings


BUSY_TIMEOUT_MS = 5000
NOW = 1_800_000_000_000
OLD_ENCRYPTION_KEY = b"\xa1" * 32
NEW_ENCRYPTION_KEY = b"\xb2" * 32
FINGERPRINT_KEY = bytes(range(64, 96))
SYNTHETIC_TOKEN_A = "synthetic.jwt.token-a"
SYNTHETIC_TOKEN_B = "synthetic.jwt.token-b"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class CredentialMaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="credential-maintenance-")
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "maintenance.sqlite3"
        migrate_database(self.database_path, BUSY_TIMEOUT_MS)
        self.encryption_keys = MappingProxyType({
            "enc-v1": OLD_ENCRYPTION_KEY,
            "enc-v2": NEW_ENCRYPTION_KEY,
        })
        self.old_encryption_keyring = CredentialKeyring(self.encryption_keys, "enc-v1")
        self.active_encryption_keyring = CredentialKeyring(self.encryption_keys, "enc-v2")
        self.fingerprint_keyring = CredentialKeyring(
            MappingProxyType({"fp-v1": FINGERPRINT_KEY}), "fp-v1"
        )
        self._insert_user("admin-a", "Admin", "admin")
        self._insert_user("user-a", "Alice", "user")
        self.module = self._load_maintenance_module()

    def _load_maintenance_module(self):
        try:
            return __import__("backend.credentials.maintenance", fromlist=["*"])
        except ModuleNotFoundError as exc:
            if exc.name == "backend.credentials.maintenance":
                return None
            raise

    def _require_maintenance(self):
        self.assertIsNotNone(
            self.module,
            "backend.credentials.maintenance must provide explicit token envelope rewrap",
        )
        return self.module

    def _insert_user(self, user_id: str, username: str, role: str) -> None:
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            connection.execute(
                """INSERT INTO users
                   (user_id, username, normalized_username, password_hash, role, status,
                    created_at_utc_ms, updated_at_utc_ms)
                   VALUES (?, ?, ?, 'synthetic-password-hash', ?, 'active', ?, ?)""",
                (user_id, username, username.casefold(), role, NOW, NOW),
            )

    def _insert_active_credential(
        self,
        credential_id: str,
        revision_id: str,
        token: str,
        *,
        encryption_keyring: CredentialKeyring | None = None,
    ) -> None:
        keyring = encryption_keyring or self.old_encryption_keyring
        cipher = CredentialTokenCipher(keyring)
        envelope = cipher.encrypt(
            token.encode("utf-8"),
            user_id="user-a",
            credential_id=credential_id,
            revision_id=revision_id,
            key_id="enc-v1",
        )
        fingerprint = token_fingerprint(token, self.fingerprint_keyring)
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO credentials
                   (credential_id, user_id, label, credential_version, enabled,
                    current_token_revision_id, account_binding_state,
                    last_confirmed_validation_state, requires_revalidation,
                    created_at_utc_ms, updated_at_utc_ms)
                   VALUES (?, 'user-a', ?, 1, 1, ?, 'unresolved', 'confirmed_valid', 0, ?, ?)""",
                (credential_id, credential_id, revision_id, NOW, NOW),
            )
            connection.execute(
                """INSERT INTO credential_token_revisions
                   (revision_id, user_id, credential_id, revision_number, token_fingerprint,
                    token_fingerprint_key_version, token_expires_at_utc_ms,
                    initial_validation_result, initial_validation_at_utc_ms,
                    created_by_user_id, secret_material_active, ciphertext, nonce, tag,
                    encryption_key_version)
                   VALUES (?, 'user-a', ?, 1, ?, 'fp-v1', NULL, 'success', ?,
                           'user-a', 1, ?, ?, ?, 'enc-v1')""",
                (
                    revision_id,
                    credential_id,
                    fingerprint.value,
                    NOW,
                    envelope.ciphertext,
                    envelope.nonce,
                    envelope.tag,
                ),
            )
            connection.execute("COMMIT")

    def _insert_inactive_historical_revision(self, credential_id: str) -> None:
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            connection.execute(
                """INSERT INTO credential_token_revisions
                   (revision_id, user_id, credential_id, revision_number, token_fingerprint,
                    token_fingerprint_key_version, initial_validation_result,
                    initial_validation_at_utc_ms, created_by_user_id, secret_material_active,
                    ciphertext, nonce, tag, encryption_key_version, ciphertext_cleared_at_utc_ms)
                   VALUES ('historical-revision', 'user-a', ?, 2, ?, 'retired-fp', 'success',
                           ?, 'user-a', 0, NULL, NULL, NULL, 'retired-enc', ?)""",
                (credential_id, "h" * 64, NOW - 1, NOW),
            )

    def _revision_snapshot(self, revision_id: str):
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            return dict(connection.execute(
                "SELECT * FROM credential_token_revisions WHERE revision_id=?",
                (revision_id,),
            ).fetchone())

    def test_rewrap_authenticates_and_changes_only_encryption_envelope_fields(self) -> None:
        maintenance = self._require_maintenance()
        self._insert_active_credential("credential-a", "revision-a", SYNTHETIC_TOKEN_A)
        before = self._revision_snapshot("revision-a")

        result = maintenance.rewrap_credential_tokens(
            self.database_path,
            BUSY_TIMEOUT_MS,
            encryption_keyring=self.active_encryption_keyring,
            fingerprint_keyring=self.fingerprint_keyring,
            actor_user_id="admin-a",
            now_utc_ms=NOW + 1,
        )

        after = self._revision_snapshot("revision-a")
        self.assertEqual(result.rewrapped_count, 1)
        self.assertEqual(result.unchanged_count, 0)
        self.assertEqual(after["encryption_key_version"], "enc-v2")
        for field in (
            "revision_id", "user_id", "credential_id", "revision_number", "token_fingerprint",
            "token_fingerprint_key_version", "token_expires_at_utc_ms",
            "initial_account_fingerprint_key_version", "initial_account_identity_contract_version",
            "initial_validation_result", "initial_validation_at_utc_ms", "created_by_user_id",
            "secret_material_active", "ciphertext_cleared_at_utc_ms",
        ):
            self.assertEqual(after[field], before[field], field)
        self.assertNotEqual(after["ciphertext"], before["ciphertext"])
        cipher = CredentialTokenCipher(self.active_encryption_keyring)
        plaintext = cipher.decrypt(
            __import__("backend.credentials.crypto", fromlist=["EncryptedTokenEnvelope"]).EncryptedTokenEnvelope(
                after["ciphertext"], after["nonce"], after["tag"], after["encryption_key_version"]
            ),
            user_id="user-a",
            credential_id="credential-a",
            revision_id="revision-a",
            key_id="enc-v2",
        )
        self.assertEqual(plaintext.decode("utf-8"), SYNTHETIC_TOKEN_A)
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            audit = connection.execute(
                """SELECT operation_code, old_key_version, new_key_version, actor_user_id
                   FROM credential_lifecycle_audits WHERE revision_id='revision-a'"""
            ).fetchone()
        self.assertEqual(tuple(audit), ("key_rewrapped", "enc-v1", "enc-v2", "admin-a"))
        self.assertNotIn(SYNTHETIC_TOKEN_A, repr(result))

    def test_wrong_old_key_fails_authentication_without_database_changes(self) -> None:
        maintenance = self._require_maintenance()
        self._insert_active_credential("credential-a", "revision-a", SYNTHETIC_TOKEN_A)
        before = self._revision_snapshot("revision-a")
        wrong_ring = CredentialKeyring(
            MappingProxyType({"enc-v1": b"x" * 32, "enc-v2": NEW_ENCRYPTION_KEY}),
            "enc-v2",
        )

        with self.assertRaises(maintenance.CredentialMaintenanceError) as raised:
            maintenance.rewrap_credential_tokens(
                self.database_path,
                BUSY_TIMEOUT_MS,
                encryption_keyring=wrong_ring,
                fingerprint_keyring=self.fingerprint_keyring,
                actor_user_id="admin-a",
                now_utc_ms=NOW + 1,
            )

        self.assertEqual(raised.exception.code, "credential_rewrap_failed")
        after = self._revision_snapshot("revision-a")
        self.assertEqual(after, before)
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM credential_lifecycle_audits").fetchone()[0], 0)

    def test_partial_rewrap_failure_rolls_back_all_envelopes_and_audits(self) -> None:
        maintenance = self._require_maintenance()
        self._insert_active_credential("credential-a", "revision-a", SYNTHETIC_TOKEN_A)
        self._insert_active_credential("credential-b", "revision-b", SYNTHETIC_TOKEN_B)
        before_a = self._revision_snapshot("revision-a")
        before_b = self._revision_snapshot("revision-b")
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            connection.execute(
                "UPDATE credential_token_revisions SET tag=? WHERE revision_id='revision-b'",
                (b"!" * 16,),
            )
        before_b_tampered = self._revision_snapshot("revision-b")

        with self.assertRaises(maintenance.CredentialMaintenanceError):
            maintenance.rewrap_credential_tokens(
                self.database_path,
                BUSY_TIMEOUT_MS,
                encryption_keyring=self.active_encryption_keyring,
                fingerprint_keyring=self.fingerprint_keyring,
                actor_user_id="admin-a",
                now_utc_ms=NOW + 1,
            )

        self.assertEqual(self._revision_snapshot("revision-a"), before_a)
        self.assertEqual(self._revision_snapshot("revision-b"), before_b_tampered)
        self.assertNotEqual(before_b_tampered, before_b)
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM credential_lifecycle_audits").fetchone()[0], 0)

    def test_key_dependencies_retain_old_cipher_key_until_rewrap_and_ignore_inert_history(self) -> None:
        maintenance = self._require_maintenance()
        self._insert_active_credential("credential-a", "revision-a", SYNTHETIC_TOKEN_A)
        self._insert_inactive_historical_revision("credential-a")
        old_ring = CredentialKeyring(
            MappingProxyType({"enc-v1": OLD_ENCRYPTION_KEY, "enc-v2": NEW_ENCRYPTION_KEY}),
            "enc-v1",
        )
        active_only_ring = CredentialKeyring(
            MappingProxyType({"enc-v2": NEW_ENCRYPTION_KEY}), "enc-v2"
        )
        check_credential_key_dependencies(
            self.database_path,
            BUSY_TIMEOUT_MS,
            encryption_keyring=old_ring,
            fingerprint_keyring=self.fingerprint_keyring,
        )
        with self.assertRaises(CredentialKeyDependencyError):
            check_credential_key_dependencies(
                self.database_path,
                BUSY_TIMEOUT_MS,
                encryption_keyring=active_only_ring,
                fingerprint_keyring=self.fingerprint_keyring,
            )

        maintenance.rewrap_credential_tokens(
            self.database_path,
            BUSY_TIMEOUT_MS,
            encryption_keyring=self.active_encryption_keyring,
            fingerprint_keyring=self.fingerprint_keyring,
            actor_user_id="admin-a",
            now_utc_ms=NOW + 1,
        )
        check_credential_key_dependencies(
            self.database_path,
            BUSY_TIMEOUT_MS,
            encryption_keyring=active_only_ring,
            fingerprint_keyring=self.fingerprint_keyring,
        )
        with self.assertRaises(CredentialKeyDependencyError):
            check_credential_key_dependencies(
                self.database_path,
                BUSY_TIMEOUT_MS,
                encryption_keyring=active_only_ring,
                fingerprint_keyring=CredentialKeyring(
                    MappingProxyType({"fp-v2": b"f" * 32}), "fp-v2"
                ),
            )

    def test_cli_rewrap_prints_only_safe_counts_and_requires_active_admin_actor(self) -> None:
        self._require_maintenance()
        self._insert_active_credential("credential-a", "revision-a", SYNTHETIC_TOKEN_A)
        base = credential_test_settings(self.database_path)
        base["APP_CREDENTIAL_ENCRYPTION_KEYS"] = json.dumps({
            "enc-v1": _b64url(OLD_ENCRYPTION_KEY),
            "enc-v2": _b64url(NEW_ENCRYPTION_KEY),
        })
        base["APP_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID"] = "enc-v2"
        settings = load_settings(base)
        encoded_keys = list(json.loads(base["APP_CREDENTIAL_ENCRYPTION_KEYS"]).values())
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch("backend.cli.load_settings", return_value=settings), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = __import__("backend.cli", fromlist=["*"]).main([
                "rewrap-credential-tokens", "--actor-user-id", "admin-a"
            ])

        self.assertEqual(exit_code, 0)
        self.assertIn("Rewrapped 1", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(SYNTHETIC_TOKEN_A, stdout.getvalue())
        self.assertTrue(all(value not in stdout.getvalue() for value in encoded_keys))
        self.assertNotIn(SYNTHETIC_TOKEN_A, repr(settings))
        self.assertTrue(all(value not in repr(settings) for value in encoded_keys))
        self.assertNotIn(base["CSRF_HMAC_SECRET"], repr(settings))
        self.assertNotIn(SYNTHETIC_TOKEN_A, stderr.getvalue())

    def test_maintenance_requires_an_active_admin_actor(self) -> None:
        maintenance = self._require_maintenance()
        self._insert_active_credential("credential-a", "revision-a", SYNTHETIC_TOKEN_A)

        with self.assertRaises(maintenance.CredentialMaintenanceError) as raised:
            maintenance.rewrap_credential_tokens(
                self.database_path,
                BUSY_TIMEOUT_MS,
                encryption_keyring=self.active_encryption_keyring,
                fingerprint_keyring=self.fingerprint_keyring,
                actor_user_id="user-a",
                now_utc_ms=NOW + 1,
            )

        self.assertEqual(raised.exception.code, "maintenance_admin_required")
        self.assertEqual(self._revision_snapshot("revision-a")["encryption_key_version"], "enc-v1")


if __name__ == "__main__":
    unittest.main()
