from __future__ import annotations

import hashlib
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import MappingProxyType

from backend.credentials.keyring import CredentialKeyring
from backend.db import connect_database
from backend.migrate import migrate_database


BUSY_TIMEOUT_MS = 5000


class CredentialKeyDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="credential-key-deps-")
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "keys.sqlite3"
        migrate_database(self.database_path, BUSY_TIMEOUT_MS)
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            connection.execute(
                """INSERT INTO users
                   (user_id, username, normalized_username, password_hash, role, status,
                    created_at_utc_ms, updated_at_utc_ms)
                   VALUES ('user-a', 'a', 'a', 'synthetic-hash', 'user', 'active', 1, 1)"""
            )
        self.module = self._load_module()

    def _load_module(self):
        try:
            return __import__("backend.credentials.key_dependencies", fromlist=["*"])
        except ModuleNotFoundError as exc:
            if exc.name == "backend.credentials.key_dependencies":
                return None
            raise

    def _require_checker(self):
        self.assertIsNotNone(
            self.module,
            "backend.credentials.key_dependencies must provide the read-only dependency checker",
        )
        return self.module

    def _keyring(self, active: str, keys: dict[str, bytes]):
        return CredentialKeyring(MappingProxyType(keys), active)

    def test_missing_database_is_not_created_by_read_only_dependency_check(self) -> None:
        checker = self._require_checker()
        missing_path = Path(self.temp_dir.name) / "must-stay-missing.sqlite3"

        with self.assertRaises(checker.CredentialKeyDependencyError):
            checker.check_credential_key_dependencies(
                missing_path, BUSY_TIMEOUT_MS,
                encryption_keyring=self._keyring("enc-v1", {"enc-v1": b"e" * 32}),
                fingerprint_keyring=self._keyring("fp-v1", {"fp-v1": b"f" * 32}),
            )

        self.assertFalse(missing_path.exists())

    def _insert_credential(
        self,
        *,
        credential_id: str = "credential-a",
        binding: str = "confirmed",
        enabled: bool = True,
        deleted: bool = False,
        encryption_version: str = "enc-v1",
        token_fingerprint_version: str = "fp-v1",
        account_version: str | None = "fp-v1",
        account_fingerprint: str | None = "a" * 64,
        revision_id: str = "revision-a",
        revision_number: int = 1,
    ) -> None:
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO credentials
                   (credential_id, user_id, label, credential_version, enabled, deleted_at_utc_ms,
                    current_token_revision_id, account_binding_state, upstream_account_fingerprint,
                    fingerprint_key_version, account_identity_contract_version,
                    account_fingerprint_cleared_at_utc_ms, last_successful_validation_at_utc_ms,
                    last_confirmed_validation_state, requires_revalidation, created_at_utc_ms,
                    updated_at_utc_ms)
                   VALUES (?, 'user-a', 'A', 1, ?, ?, ?, ?, ?, ?, ?, ?, 1,
                           'confirmed_valid', 0, 1, 1)""",
                (
                    credential_id,
                    1 if enabled else 0,
                    2 if deleted else None,
                    revision_id,
                    "unresolved" if deleted else binding,
                    None if deleted else account_fingerprint,
                    None if deleted else account_version,
                    None if deleted or account_version is None else "contract-v1",
                    3 if deleted else None,
                ),
            )
            connection.execute(
                """INSERT INTO credential_token_revisions
                   (revision_id, user_id, credential_id, revision_number, token_fingerprint,
                    token_fingerprint_key_version, token_expires_at_utc_ms,
                    initial_account_fingerprint_key_version, initial_account_identity_contract_version,
                    initial_validation_result, initial_validation_at_utc_ms, created_by_user_id,
                    secret_material_active, ciphertext, nonce, tag, encryption_key_version,
                    ciphertext_cleared_at_utc_ms)
                   VALUES (?, 'user-a', ?, ?, ?, ?, NULL, ?, ?, 'success', 1, 'user-a', ?, ?, ?, ?, ?, ?)""",
                (
                    revision_id,
                    credential_id,
                    revision_number,
                    "b" * 64,
                    token_fingerprint_version,
                    None if deleted else account_version,
                    None if deleted or account_version is None else "contract-v1",
                    0 if deleted else 1,
                    None if deleted else b"cipher",
                    None if deleted else b"n" * 12,
                    None if deleted else b"t" * 16,
                    encryption_version,
                    3 if deleted else None,
                ),
            )
            connection.execute("COMMIT")

    def _insert_historical_revision_with_retired_keys(self) -> None:
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO credential_token_revisions
                   (revision_id, user_id, credential_id, revision_number, token_fingerprint,
                    token_fingerprint_key_version, initial_validation_result,
                    initial_validation_at_utc_ms, created_by_user_id, secret_material_active,
                    ciphertext, nonce, tag, encryption_key_version, ciphertext_cleared_at_utc_ms)
                   VALUES ('revision-old', 'user-a', 'credential-a', 2, ?, 'retired-fp',
                           'success', 2, 'user-a', 0, NULL, NULL, NULL, 'retired-enc', 3)""",
                ("c" * 64,),
            )
            connection.execute("COMMIT")

    def test_missing_active_ciphertext_key_fails_read_only(self) -> None:
        self._require_checker()
        self._insert_credential()
        before = hashlib.sha256(self.database_path.read_bytes()).digest()

        with self.assertRaises(self.module.CredentialKeyDependencyError):
            self.module.check_credential_key_dependencies(
                self.database_path,
                BUSY_TIMEOUT_MS,
                encryption_keyring=self._keyring("enc-v2", {"enc-v2": b"x" * 32}),
                fingerprint_keyring=self._keyring("fp-v1", {"fp-v1": b"f" * 32}),
            )

        self.assertEqual(hashlib.sha256(self.database_path.read_bytes()).digest(), before)

    def test_current_token_and_confirmed_account_fingerprint_keys_are_dependencies(self) -> None:
        checker = self._require_checker()
        self._insert_credential(enabled=False, binding="needs_reconfirmation")
        encryption = self._keyring("enc-v1", {"enc-v1": b"e" * 32})

        with self.assertRaises(checker.CredentialKeyDependencyError):
            checker.check_credential_key_dependencies(
                self.database_path, BUSY_TIMEOUT_MS, encryption_keyring=encryption,
                fingerprint_keyring=self._keyring("fp-v2", {"fp-v2": b"g" * 32}),
            )

    def test_current_token_fingerprint_key_is_required_when_binding_is_unresolved(self) -> None:
        checker = self._require_checker()
        self._insert_credential(
            binding="unresolved", account_version=None, account_fingerprint=None,
            token_fingerprint_version="fp-v1",
        )

        with self.assertRaises(checker.CredentialKeyDependencyError):
            checker.check_credential_key_dependencies(
                self.database_path, BUSY_TIMEOUT_MS,
                encryption_keyring=self._keyring("enc-v1", {"enc-v1": b"e" * 32}),
                fingerprint_keyring=self._keyring("fp-v2", {"fp-v2": b"g" * 32}),
            )

    def test_account_fingerprint_key_remains_required_when_token_key_is_present(self) -> None:
        checker = self._require_checker()
        self._insert_credential(account_version="account-v1", token_fingerprint_version="fp-v1")

        with self.assertRaises(checker.CredentialKeyDependencyError):
            checker.check_credential_key_dependencies(
                self.database_path, BUSY_TIMEOUT_MS,
                encryption_keyring=self._keyring("enc-v1", {"enc-v1": b"e" * 32}),
                fingerprint_keyring=self._keyring("fp-v1", {"fp-v1": b"f" * 32}),
            )

    def test_historical_revision_and_soft_deleted_tombstone_keys_are_inert(self) -> None:
        checker = self._require_checker()
        self._insert_credential()
        self._insert_historical_revision_with_retired_keys()

        checker.check_credential_key_dependencies(
            self.database_path,
            BUSY_TIMEOUT_MS,
            encryption_keyring=self._keyring("enc-v1", {"enc-v1": b"e" * 32}),
            fingerprint_keyring=self._keyring("fp-v1", {"fp-v1": b"f" * 32}),
        )

    def test_soft_deleted_tombstone_no_longer_depends_on_cleared_keys(self) -> None:
        checker = self._require_checker()
        self._insert_credential(
            deleted=True, encryption_version="old-enc", token_fingerprint_version="old-fp",
            account_version="old-fp",
        )

        checker.check_credential_key_dependencies(
            self.database_path, BUSY_TIMEOUT_MS,
            encryption_keyring=self._keyring("enc-v1", {"enc-v1": b"e" * 32}),
            fingerprint_keyring=self._keyring("fp-v1", {"fp-v1": b"f" * 32}),
        )

    def test_lazy_account_fingerprint_rebind_requires_matching_identity(self) -> None:
        service_module = None
        try:
            service_module = __import__("backend.credentials.service", fromlist=["*"])
        except ModuleNotFoundError as exc:
            if exc.name != "backend.credentials.service":
                raise
        self.assertIsNotNone(service_module, "CredentialService must implement lazy fingerprint rebind")
        self._insert_credential(account_version="fp-v1")
        # The lifecycle tests exercise v1 -> active-v2 rebind and mismatch preservation in the
        # service; this assertion also pins the old key as a live dependency until the rebind.
        checker = self._require_checker()
        checker.check_credential_key_dependencies(
            self.database_path, BUSY_TIMEOUT_MS,
            encryption_keyring=self._keyring("enc-v1", {"enc-v1": b"e" * 32}),
            fingerprint_keyring=self._keyring(
                "fp-v2", {"fp-v1": b"f" * 32, "fp-v2": b"g" * 32}
            ),
        )


if __name__ == "__main__":
    unittest.main()
