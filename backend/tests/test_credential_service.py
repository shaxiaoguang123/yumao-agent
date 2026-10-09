from __future__ import annotations

import base64
from contextlib import closing
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from backend.credentials.keyring import CredentialKeyring
from backend.credentials.request_gate import GateDecision, GateOperationContext, UpstreamRequestGate
from backend.db import connect_database
from backend.migrate import migrate_database


NOW = 1_800_000_000_000
BUSY_TIMEOUT_MS = 5000


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _token(exp_seconds: int = NOW // 1000 + 30 * 86_400, marker: str = "synthetic") -> str:
    header = _b64url(b'{"alg":"none","typ":"JWT"}')
    payload = _b64url(json.dumps({"exp": exp_seconds, "marker": marker}).encode())
    return f"{header}.{payload}.signature"


@dataclass(frozen=True)
class AdapterResult:
    token_outcome: str = "success"
    safe_code: str = "get_user_info_success"
    identity_bytes: bytes | None = b"synthetic-account-id"
    identity_contract_version: str | None = "getuserinfo-idserial-v1"
    http_status_class: str | None = "2xx"
    retry_after_header: str | None = None
    dispatch_state: str = "complete"
    http_status_code: int | None = 200


class FakeAdapter:
    def __init__(self, *results: AdapterResult):
        self.results = list(results)
        self.calls: list[str] = []
        self.after_validate = None

    def validate_token(self, token: str) -> AdapterResult:
        self.calls.append(token)
        if self.after_validate is not None:
            self.after_validate(token)
        if not self.results:
            return AdapterResult()
        return self.results.pop(0)


def _keyring(prefix: bytes, active: str = "v1", include_v2: bool = False) -> CredentialKeyring:
    keys = {"v1": prefix * 32}
    if include_v2:
        keys["v2"] = bytes((value + 1) % 256 for value in prefix * 32)
    return CredentialKeyring(MappingProxyType(keys), active)


class CredentialServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="credential-service-")
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "service.sqlite3"
        migrate_database(self.database_path, BUSY_TIMEOUT_MS)
        self.now = NOW
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            for user_id, username in (("user-a", "a"), ("user-b", "b")):
                connection.execute(
                    """INSERT INTO users
                       (user_id, username, normalized_username, password_hash, role, status,
                        created_at_utc_ms, updated_at_utc_ms)
                       VALUES (?, ?, ?, 'synthetic-hash', 'user', 'active', ?, ?)""",
                    (user_id, username, username, NOW, NOW),
                )

        self.adapter = FakeAdapter()
        self.gate = UpstreamRequestGate(
            database_path=self.database_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            minimum_interval_ms=1,
            total_deadline_seconds=10,
            read_timeout_seconds=5,
            lease_safety_margin_seconds=6,
            retry_after_fallback_seconds=30,
            max_upstream_backoff_seconds=900,
        )
        self.service_module = self._load_module("backend.credentials.service")
        self.service = None
        if self.service_module is not None:
            self.service = self.service_module.CredentialService(
                database_path=self.database_path,
                busy_timeout_ms=BUSY_TIMEOUT_MS,
                encryption_keyring=_keyring(b"e"),
                fingerprint_keyring=_keyring(b"f"),
                adapter=self.adapter,
                gate=self.gate,
                account_continuity_capability=True,
                token_expiring_soon_window_seconds=604800,
                clock_utc_ms=lambda: self.now,
            )

    def _load_module(self, name: str):
        try:
            return __import__(name, fromlist=["*"])
        except ModuleNotFoundError as exc:
            if exc.name == name:
                return None
            raise

    def _require_service(self):
        self.assertIsNotNone(
            self.service,
            "backend.credentials.service must provide CredentialService",
        )
        return self.service

    def _next_time(self) -> int:
        self.now += 1000
        return self.now

    def _create(self, user_id: str = "user-a", token: str | None = None, label: str = "Home"):
        return self._require_service().create(
            user_id, label, token or _token(), self._next_time()
        )

    def _inject_same_user_confirmed_duplicate(self, source) -> None:
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT upstream_account_fingerprint, fingerprint_key_version, "
                "account_identity_contract_version FROM credentials WHERE credential_id=?",
                (source.credential_id,),
            ).fetchone()
            connection.execute(
                """INSERT INTO credentials
                   (credential_id, user_id, label, credential_version, enabled,
                    current_token_revision_id, account_binding_state,
                    upstream_account_fingerprint, fingerprint_key_version,
                    account_identity_contract_version, last_confirmed_validation_state,
                    requires_revalidation, created_at_utc_ms, updated_at_utc_ms)
                   VALUES ('duplicate-credential', 'user-a', 'Duplicate', 1, 1,
                           'duplicate-revision', 'confirmed', ?, ?, ?,
                           'confirmed_valid', 0, ?, ?)""",
                (
                    row["upstream_account_fingerprint"],
                    row["fingerprint_key_version"],
                    row["account_identity_contract_version"],
                    self.now,
                    self.now,
                ),
            )
            connection.execute(
                """INSERT INTO credential_token_revisions
                   (revision_id, user_id, credential_id, revision_number, token_fingerprint,
                    token_fingerprint_key_version, initial_account_fingerprint_key_version,
                    initial_account_identity_contract_version, initial_validation_result,
                    initial_validation_at_utc_ms, created_by_user_id, secret_material_active,
                    ciphertext, nonce, tag, encryption_key_version)
                   VALUES ('duplicate-revision', 'user-a', 'duplicate-credential', 1,
                           ?, 'v1', ?, ?, 'success', ?, 'user-a', 1, ?, ?, ?, 'v1')""",
                (
                    "d" * 64,
                    row["fingerprint_key_version"],
                    row["account_identity_contract_version"],
                    self.now,
                    b"synthetic-ciphertext",
                    b"n" * 12,
                    b"t" * 16,
                ),
            )
            connection.execute("COMMIT")

    def test_create_success_persists_only_encrypted_token_and_safe_identity_fingerprint(self) -> None:
        service = self._require_service()
        token = _token(marker="never-store-plaintext")
        dto = service.create("user-a", "My token", token, self._next_time())

        self.assertEqual(dto.account_binding_state, "confirmed")
        self.assertEqual(dto.last_confirmed_validation_state, "confirmed_valid")
        self.assertEqual(dto.expiry_state, "expiry_ok")
        self.assertNotIn(token, repr(dto))
        self.assertNotIn("synthetic-account-id", repr(dto))
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            credential = connection.execute(
                "SELECT * FROM credentials WHERE user_id='user-a'"
            ).fetchone()
            revision = connection.execute(
                "SELECT * FROM credential_token_revisions WHERE user_id='user-a'"
            ).fetchone()
            self.assertEqual(credential["last_confirmed_validation_state"], "confirmed_valid")
            self.assertEqual(credential["current_token_revision_id"], revision["revision_id"])
            self.assertEqual(revision["secret_material_active"], 1)
            self.assertNotEqual(revision["ciphertext"], token.encode())
            self.assertNotEqual(credential["upstream_account_fingerprint"], b"synthetic-account-id")
        database_bytes = self.database_path.read_bytes()
        self.assertNotIn(token.encode(), database_bytes)
        self.assertNotIn(b"synthetic-account-id", database_bytes)

    def test_one_user_can_store_different_confirmed_upstream_accounts(self) -> None:
        service = self._require_service()
        first = self._create()
        self.adapter.results = [AdapterResult(identity_bytes=b"another-account")]

        second = service.create("user-a", "Different upstream account", _token(marker="different"), self._next_time())

        self.assertNotEqual(first.credential_id, second.credential_id)
        self.assertEqual(len(service.list_for_user("user-a")), 2)

    def test_create_without_identity_is_unresolved_and_later_validation_promotes_binding(self) -> None:
        service = self._require_service()
        self.adapter.results = [AdapterResult(identity_bytes=None)]
        dto = service.create("user-a", "Unresolved", _token(), self._next_time())
        self.assertEqual(dto.account_binding_state, "unresolved")

        self.adapter.results = [AdapterResult(identity_bytes=b"synthetic-account-id")]
        outcome = service.validate(
            "user-a", dto.credential_id, dto.credential_version,
            dto.current_token_revision_id, self._next_time(),
        )
        self.assertEqual(outcome.credential.account_binding_state, "confirmed")

    def test_create_without_identity_conflicts_when_user_already_has_a_credential(self) -> None:
        service = self._require_service()
        first = self._create()
        calls_before = len(self.adapter.calls)
        self.adapter.results = [AdapterResult(identity_bytes=None)]

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.create("user-a", "Second", _token(marker="second"), self._next_time())

        self.assertEqual(raised.exception.code, "credential_account_binding_unresolved")
        self.assertEqual(len(self.adapter.calls), calls_before + 1)
        self.assertEqual(len(service.list_for_user("user-a")), 1)
        self.assertEqual(service.get_for_user("user-a", first.credential_id).account_binding_state, "confirmed")

    def test_disabled_confirmed_duplicate_is_rejected_after_candidate_validation(self) -> None:
        service = self._require_service()
        first = self._create()
        service.set_enabled("user-a", first.credential_id, first.credential_version, False, self._next_time())
        self.adapter.results = [AdapterResult(identity_bytes=b"synthetic-account-id")]

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.create("user-a", "Duplicate", _token(marker="duplicate"), self._next_time())

        self.assertEqual(raised.exception.code, "credential_account_already_configured")
        self.assertEqual(len(service.list_for_user("user-a")), 1)

    def test_unresolved_row_blocks_another_create_before_dispatch(self) -> None:
        service = self._require_service()
        self.adapter.results = [AdapterResult(identity_bytes=None)]
        service.create("user-a", "Unresolved", _token(), self._next_time())
        calls_before = len(self.adapter.calls)

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.create("user-a", "Second", _token(marker="second"), self._next_time())

        self.assertEqual(raised.exception.code, "credential_account_binding_unresolved")
        self.assertEqual(len(self.adapter.calls), calls_before)

    def test_needs_reconfirmation_row_blocks_another_create_before_dispatch(self) -> None:
        service = self._require_service()
        dto = self._create()
        self.adapter.results = [AdapterResult(identity_bytes=b"different-account")]
        mismatch = service.validate(
            "user-a", dto.credential_id, dto.credential_version,
            dto.current_token_revision_id, self._next_time(),
        )
        self.assertEqual(mismatch.credential.account_binding_state, "needs_reconfirmation")
        calls_before = len(self.adapter.calls)

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.create("user-a", "Second", _token(marker="second"), self._next_time())

        self.assertEqual(raised.exception.code, "credential_account_reconfirmation_required")
        self.assertEqual(len(self.adapter.calls), calls_before)

    def test_confirmed_validation_without_identity_preserves_existing_binding(self) -> None:
        service = self._require_service()
        dto = self._create()
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            before = connection.execute(
                "SELECT upstream_account_fingerprint, fingerprint_key_version FROM credentials WHERE credential_id=?",
                (dto.credential_id,),
            ).fetchone()
        self.adapter.results = [AdapterResult(identity_bytes=None)]

        outcome = service.validate(
            "user-a", dto.credential_id, dto.credential_version,
            dto.current_token_revision_id, self._next_time(),
        )

        self.assertEqual(outcome.credential.account_binding_state, "confirmed")
        self.assertEqual(outcome.credential.last_confirmed_validation_state, "confirmed_valid")
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            after = connection.execute(
                "SELECT upstream_account_fingerprint, fingerprint_key_version FROM credentials WHERE credential_id=?",
                (dto.credential_id,),
            ).fetchone()
        self.assertEqual(tuple(after), tuple(before))

    def test_needs_reconfirmation_recovers_only_on_a_matching_current_identity(self) -> None:
        service = self._require_service()
        dto = self._create()
        self.adapter.results = [AdapterResult(identity_bytes=b"different-account")]
        mismatch = service.validate(
            "user-a", dto.credential_id, dto.credential_version,
            dto.current_token_revision_id, self._next_time(),
        )
        self.assertEqual(mismatch.credential.account_binding_state, "needs_reconfirmation")
        self.adapter.results = [AdapterResult(identity_bytes=b"synthetic-account-id")]

        restored = service.validate(
            "user-a", dto.credential_id, mismatch.credential.credential_version,
            dto.current_token_revision_id, self._next_time(),
        )

        self.assertEqual(restored.credential.account_binding_state, "confirmed")

    def test_reconfirmation_does_not_restore_binding_if_another_confirmed_duplicate_exists(self) -> None:
        service = self._require_service()
        dto = self._create()
        self.adapter.results = [AdapterResult(identity_bytes=b"different-account")]
        mismatch = service.validate(
            "user-a", dto.credential_id, dto.credential_version,
            dto.current_token_revision_id, self._next_time(),
        )
        self._inject_same_user_confirmed_duplicate(mismatch.credential)
        self.adapter.results = [AdapterResult(identity_bytes=b"synthetic-account-id")]

        result = service.validate(
            "user-a", dto.credential_id, mismatch.credential.credential_version,
            dto.current_token_revision_id, self._next_time(),
        )

        self.assertEqual(result.code, "credential_account_already_configured")
        self.assertEqual(result.credential.account_binding_state, "needs_reconfirmation")
        self.assertEqual(result.credential.last_confirmed_validation_state, "confirmed_valid")

    def test_lazy_account_fingerprint_rebind_keeps_current_token_fingerprint_key(self) -> None:
        service = self._require_service()
        token = _token()
        dto = self._create(token=token)
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            token_key_before = connection.execute(
                "SELECT token_fingerprint_key_version FROM credential_token_revisions WHERE revision_id=?",
                (dto.current_token_revision_id,),
            ).fetchone()[0]
        service.fingerprint_keyring = CredentialKeyring(
            MappingProxyType({"v1": b"f" * 32, "v2": b"g" * 32}), "v2"
        )
        self.adapter.results = [AdapterResult(identity_bytes=b"synthetic-account-id")]

        result = service.validate(
            "user-a", dto.credential_id, dto.credential_version,
            dto.current_token_revision_id, self._next_time(),
        )

        self.assertEqual(result.credential.account_binding_state, "confirmed")
        calls_before_same_token_rotation = len(self.adapter.calls)
        same_token = service.rotate_token(
            "user-a", dto.credential_id, result.credential.credential_version,
            result.credential.current_token_revision_id, token, self._next_time(),
        )
        self.assertEqual(same_token.code, "token_already_current")
        self.assertEqual(len(self.adapter.calls), calls_before_same_token_rotation)
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            account_key = connection.execute(
                "SELECT fingerprint_key_version FROM credentials WHERE credential_id=?",
                (dto.credential_id,),
            ).fetchone()[0]
            token_key_after = connection.execute(
                "SELECT token_fingerprint_key_version FROM credential_token_revisions WHERE revision_id=?",
                (dto.current_token_revision_id,),
            ).fetchone()[0]
        self.assertEqual(account_key, "v2")
        self.assertEqual(token_key_before, token_key_after)

    def test_same_upstream_account_can_be_bound_by_another_application_user(self) -> None:
        service = self._require_service()
        first = self._create("user-a")
        second = service.create("user-b", "Other user", _token(marker="other-user"), self._next_time())
        self.assertNotEqual(first.credential_id, second.credential_id)
        self.assertEqual(second.account_binding_state, "confirmed")
        self.assertEqual(len(service.list_for_user("user-a")), 1)
        self.assertEqual(len(service.list_for_user("user-b")), 1)

    def test_no_continuity_capability_allows_only_one_unresolved_credential(self) -> None:
        service = self._require_service()
        service.account_continuity_capability = False
        first = self._create()
        self.assertEqual(first.account_binding_state, "unresolved")
        calls_before = len(self.adapter.calls)

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.create("user-a", "Second", _token(marker="second"), self._next_time())

        self.assertEqual(raised.exception.code, "credential_account_binding_unresolved")
        self.assertEqual(len(self.adapter.calls), calls_before)

    def test_transient_validation_failure_does_not_downgrade_confirmed_state(self) -> None:
        service = self._require_service()
        dto = self._create()
        self.adapter.results = [AdapterResult(token_outcome="network_error", safe_code="network_error",
                                               identity_bytes=None, identity_contract_version=None,
                                               http_status_class=None, dispatch_state="uncertain")]

        outcome = service.validate(
            "user-a", dto.credential_id, dto.credential_version,
            dto.current_token_revision_id, self._next_time(),
        )

        self.assertEqual(outcome.credential.account_binding_state, "confirmed")
        self.assertEqual(outcome.credential.last_confirmed_validation_state, "confirmed_valid")
        self.assertEqual(outcome.credential.last_successful_validation_at_utc_ms, dto.last_successful_validation_at_utc_ms)
        self.assertEqual(outcome.credential.latest_requested_validation_attempt["attempt_result"], "network_error")
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            gate_row = connection.execute(
                "SELECT lease_owner_id FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
            ).fetchone()
        self.assertIsNotNone(gate_row["lease_owner_id"])

    def test_uncertain_upstream_rate_limit_extends_gate_and_returns_retry_delay(self) -> None:
        service = self._require_service()
        dto = self._create()
        self.adapter.results = [AdapterResult(
            token_outcome="rate_limited",
            safe_code="upstream_rate_limited",
            identity_bytes=None,
            identity_contract_version=None,
            http_status_class="4xx",
            retry_after_header="120",
            dispatch_state="uncertain",
            http_status_code=429,
        )]

        result = service.validate(
            "user-a", dto.credential_id, dto.credential_version,
            dto.current_token_revision_id, self._next_time(),
        )

        self.assertEqual(result.code, "upstream_rate_limited")
        self.assertEqual(result.http_status, 429)
        self.assertEqual(result.retry_after_seconds, 120)
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            gate = connection.execute(
                "SELECT lease_owner_id, upstream_backoff_until_utc_ms "
                "FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
            ).fetchone()
        self.assertIsNotNone(gate["lease_owner_id"])
        self.assertGreater(gate["upstream_backoff_until_utc_ms"], NOW)

    def test_confirmed_identity_mismatch_preserves_fingerprint_and_requires_reconfirmation(self) -> None:
        service = self._require_service()
        dto = self._create()
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            before = connection.execute(
                "SELECT upstream_account_fingerprint, fingerprint_key_version FROM credentials WHERE credential_id=?",
                (dto.credential_id,),
            ).fetchone()
        self.adapter.results = [AdapterResult(identity_bytes=b"different-account")]

        outcome = service.validate(
            "user-a", dto.credential_id, dto.credential_version,
            dto.current_token_revision_id, self._next_time(),
        )

        self.assertEqual(outcome.credential.account_binding_state, "needs_reconfirmation")
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            after = connection.execute(
                "SELECT upstream_account_fingerprint, fingerprint_key_version FROM credentials WHERE credential_id=?",
                (dto.credential_id,),
            ).fetchone()
        self.assertEqual(tuple(after), tuple(before))

    def test_transient_attempt_does_not_overwrite_a_later_allocated_attempt_projection(self) -> None:
        service = self._require_service()
        dto = self._create()
        self.adapter.results = [AdapterResult()]
        service.validate("user-a", dto.credential_id, dto.credential_version,
                         dto.current_token_revision_id, self._next_time())
        second = service.validate("user-a", dto.credential_id, dto.credential_version,
                                  dto.current_token_revision_id, self._next_time())
        self.assertGreater(
            second.credential.latest_requested_validation_attempt["validation_attempt_id"],
            dto.latest_requested_validation_attempt["validation_attempt_id"],
        )

    def test_disable_and_enable_do_not_change_account_binding(self) -> None:
        service = self._require_service()
        dto = self._create()
        disabled = service.set_enabled("user-a", dto.credential_id, dto.credential_version, False, self._next_time())
        self.assertEqual(disabled.credential.account_binding_state, "confirmed")
        enabled = service.set_enabled("user-a", dto.credential_id, disabled.credential.credential_version, True, self._next_time())
        self.assertEqual(enabled.credential.account_binding_state, "confirmed")
        self.assertTrue(enabled.credential.requires_revalidation)

    def test_same_current_token_rotation_returns_without_dispatch_or_revision(self) -> None:
        service = self._require_service()
        token = _token()
        dto = self._create(token=token)
        before_calls = len(self.adapter.calls)

        outcome = service.rotate_token(
            "user-a", dto.credential_id, dto.credential_version,
            dto.current_token_revision_id, token, self._next_time(),
        )

        self.assertEqual(outcome.code, "token_already_current")
        self.assertEqual(len(self.adapter.calls), before_calls)
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            count = connection.execute(
                "SELECT count(*) FROM credential_token_revisions WHERE credential_id=?",
                (dto.credential_id,),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_rotation_requires_same_confirmed_account_and_clears_previous_ciphertext(self) -> None:
        service = self._require_service()
        original = _token(marker="original")
        dto = self._create(token=original)
        next_token = _token(marker="replacement")
        self.adapter.results = [AdapterResult(identity_bytes=b"synthetic-account-id")]

        outcome = service.rotate_token(
            "user-a", dto.credential_id, dto.credential_version,
            dto.current_token_revision_id, next_token, self._next_time(),
        )

        self.assertEqual(outcome.credential.credential_version, dto.credential_version + 1)
        self.assertNotEqual(outcome.credential.current_token_revision_id, dto.current_token_revision_id)
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            old = connection.execute(
                "SELECT secret_material_active, ciphertext, nonce, tag FROM credential_token_revisions WHERE revision_id=?",
                (dto.current_token_revision_id,),
            ).fetchone()
            current_secret = connection.execute(
                "SELECT secret_material_active, ciphertext FROM credential_token_revisions WHERE revision_id=?",
                (outcome.credential.current_token_revision_id,),
            ).fetchone()
            self.assertEqual(tuple(old), (0, None, None, None))
            self.assertEqual(current_secret["secret_material_active"], 1)
            self.assertIsNotNone(current_secret["ciphertext"])
            credential = connection.execute(
                "SELECT current_token_revision_id, last_confirmed_validation_state, last_successful_validation_at_utc_ms "
                "FROM credentials WHERE credential_id=?",
                (dto.credential_id,),
            ).fetchone()
            self.assertEqual(credential["current_token_revision_id"], outcome.credential.current_token_revision_id)
            self.assertEqual(credential["last_confirmed_validation_state"], "confirmed_valid")
            self.assertEqual(
                credential["last_successful_validation_at_utc_ms"],
                outcome.credential.last_successful_validation_at_utc_ms,
            )

    def test_rotation_identity_mismatch_rejects_candidate_without_changing_current_revision(self) -> None:
        service = self._require_service()
        dto = self._create()
        self.adapter.results = [AdapterResult(identity_bytes=b"other-account")]

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.rotate_token("user-a", dto.credential_id, dto.credential_version,
                                 dto.current_token_revision_id, _token(marker="other"), self._next_time())

        self.assertEqual(raised.exception.code, "credential_account_mismatch")
        current = service.get_for_user("user-a", dto.credential_id)
        self.assertEqual(current.current_token_revision_id, dto.current_token_revision_id)
        self.assertEqual(current.account_binding_state, "confirmed")

    def test_rotation_missing_identity_rejects_candidate_without_changing_current_revision(self) -> None:
        service = self._require_service()
        dto = self._create()
        self.adapter.results = [AdapterResult(identity_bytes=None)]

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.rotate_token(
                "user-a", dto.credential_id, dto.credential_version,
                dto.current_token_revision_id, _token(marker="unresolved"), self._next_time(),
            )

        self.assertEqual(raised.exception.code, "credential_account_binding_unresolved")
        current = service.get_for_user("user-a", dto.credential_id)
        self.assertEqual(current.current_token_revision_id, dto.current_token_revision_id)

    def test_historical_token_reuse_is_allowed_after_a_different_current_token(self) -> None:
        service = self._require_service()
        original = _token(marker="original")
        first = self._create(token=original)
        replacement = _token(marker="replacement")
        self.adapter.results = [AdapterResult()]
        rotated = service.rotate_token(
            "user-a", first.credential_id, first.credential_version,
            first.current_token_revision_id, replacement, self._next_time(),
        )
        self.adapter.results = [AdapterResult()]

        restored = service.rotate_token(
            "user-a", rotated.credential.credential_id,
            rotated.credential.credential_version,
            rotated.credential.current_token_revision_id, original, self._next_time(),
        )

        self.assertEqual(restored.code, "token_rotated")
        self.assertNotEqual(restored.credential.current_token_revision_id, first.current_token_revision_id)

    def test_rotation_result_after_concurrent_disable_cannot_append_revision(self) -> None:
        service = self._require_service()
        dto = self._create()

        def disable_during_network(_token: str) -> None:
            with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE credentials SET enabled=0, credential_version=credential_version+1 "
                    "WHERE user_id='user-a' AND credential_id=?",
                    (dto.credential_id,),
                )
                connection.execute("COMMIT")

        self.adapter.results = [AdapterResult()]
        self.adapter.after_validate = disable_during_network

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.rotate_token(
                "user-a", dto.credential_id, dto.credential_version,
                dto.current_token_revision_id, _token(marker="late-rotation"), self._next_time(),
            )

        self.assertEqual(raised.exception.code, "credential_version_conflict")
        current = service.get_for_user("user-a", dto.credential_id)
        self.assertFalse(current.enabled)
        self.assertEqual(current.current_token_revision_id, dto.current_token_revision_id)

    def test_soft_delete_clears_active_secret_and_account_binding(self) -> None:
        service = self._require_service()
        dto = self._create()

        outcome = service.soft_delete("user-a", dto.credential_id, dto.credential_version, self._next_time())

        self.assertTrue(outcome.deleted)
        self.assertIsNone(service.get_for_user("user-a", dto.credential_id))
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            credential = connection.execute(
                "SELECT account_binding_state, upstream_account_fingerprint FROM credentials WHERE credential_id=?",
                (dto.credential_id,),
            ).fetchone()
            revision = connection.execute(
                "SELECT secret_material_active, ciphertext FROM credential_token_revisions WHERE credential_id=?",
                (dto.credential_id,),
            ).fetchone()
            deleted_audit = connection.execute(
                "SELECT old_account_binding_state FROM credential_lifecycle_audits "
                "WHERE credential_id=? AND operation_code='soft_deleted'",
                (dto.credential_id,),
            ).fetchone()
        self.assertEqual(tuple(credential), ("unresolved", None))
        self.assertEqual(tuple(revision), (0, None))
        self.assertEqual(deleted_audit["old_account_binding_state"], "confirmed")

    def test_all_credential_reads_are_scoped_to_user_id(self) -> None:
        service = self._require_service()
        dto = self._create("user-a")
        self.assertIsNone(service.get_for_user("user-b", dto.credential_id))
        self.assertEqual(service.list_for_user("user-b"), [])

    def test_unconfigured_or_busy_gate_never_persists_candidate_token(self) -> None:
        service = self._require_service()
        active = self.gate.acquire(
            GateOperationContext(user_id="user-b", credential_id=None, operation_kind="create_candidate"),
            self._next_time(),
            lambda _connection, _context: None,
        )
        self.assertTrue(active.allowed)
        token = _token(marker="must-not-persist")

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.create("user-a", "Busy", token, self._next_time())

        self.assertIn(raised.exception.code, {"validation_rate_limited", "validation_not_configured"})
        self.assertEqual(self.adapter.calls, [])
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM credentials").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM credential_token_revisions").fetchone()[0], 0)

    def test_gate_denial_is_latest_requested_without_changing_last_success_time(self) -> None:
        service = self._require_service()
        dto = self._create()
        active = self.gate.acquire(
            GateOperationContext(user_id="user-b", credential_id=None, operation_kind="create_candidate"),
            self._next_time(),
            lambda _connection, _context: None,
        )
        self.assertTrue(active.allowed)

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.validate(
                "user-a", dto.credential_id, dto.credential_version,
                dto.current_token_revision_id, self._next_time(),
            )

        self.assertEqual(raised.exception.code, "validation_rate_limited")
        current = service.get_for_user("user-a", dto.credential_id)
        self.assertEqual(current.latest_requested_validation_attempt["attempt_result"], "rate_limited")
        self.assertEqual(
            current.last_successful_validation_at_utc_ms,
            dto.last_successful_validation_at_utc_ms,
        )

    def test_create_result_after_gate_lease_expiry_is_not_persisted(self) -> None:
        service = self._require_service()
        self.adapter.results = [AdapterResult()]
        self.adapter.after_validate = lambda _token: setattr(self, "now", self.now + 17_000)

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.create("user-a", "Late", _token(), self._next_time())

        self.assertEqual(raised.exception.code, "validation_stale")
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM credentials").fetchone()[0], 0)
            observation = connection.execute(
                "SELECT attempt_result, apply_state, credential_id, token_revision_id "
                "FROM credential_validation_observations"
            ).fetchone()
        self.assertEqual(tuple(observation), ("success", "stale", None, None))

    def test_validation_result_after_disable_race_is_stale(self) -> None:
        service = self._require_service()
        dto = self._create()

        def disable_during_network(_token: str) -> None:
            with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE credentials SET enabled=0, credential_version=credential_version+1 "
                    "WHERE user_id='user-a' AND credential_id=?",
                    (dto.credential_id,),
                )
                connection.execute("COMMIT")

        self.adapter.results = [AdapterResult()]
        self.adapter.after_validate = disable_during_network
        before = service.get_for_user("user-a", dto.credential_id)

        outcome = service.validate(
            "user-a", dto.credential_id, dto.credential_version,
            dto.current_token_revision_id, self._next_time(),
        )

        self.assertEqual(outcome.code, "validation_stale")
        self.assertFalse(outcome.credential.enabled)
        self.assertEqual(
            outcome.credential.last_successful_validation_at_utc_ms,
            before.last_successful_validation_at_utc_ms,
        )

    def test_expired_candidate_token_is_rejected_without_upstream_dispatch(self) -> None:
        service = self._require_service()
        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.create("user-a", "Expired", _token(exp_seconds=NOW // 1000 - 1), self._next_time())
        self.assertEqual(raised.exception.code, "credential_token_expired")
        self.assertEqual(self.adapter.calls, [])

    def test_expired_current_token_is_rejected_without_upstream_dispatch(self) -> None:
        service = self._require_service()
        token = _token(exp_seconds=NOW // 1000 + 3600)
        dto = self._create(token=token)
        calls_before = len(self.adapter.calls)

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.validate(
                "user-a", dto.credential_id, dto.credential_version,
                dto.current_token_revision_id, NOW + 4_000_000,
            )

        self.assertEqual(raised.exception.code, "credential_token_expired")
        self.assertEqual(len(self.adapter.calls), calls_before)

    def test_expired_current_token_can_be_replaced_by_a_valid_token(self) -> None:
        service = self._require_service()
        current_token = _token(exp_seconds=NOW // 1000 + 10, marker="expiring-current")
        dto = self._create(token=current_token)
        self.now = NOW + 20_000
        replacement = _token(exp_seconds=NOW // 1000 + 30 * 86_400, marker="valid-replacement")
        self.adapter.results = [AdapterResult(identity_bytes=b"synthetic-account-id")]

        result = service.rotate_token(
            "user-a",
            dto.credential_id,
            dto.credential_version,
            dto.current_token_revision_id,
            replacement,
            NOW + 21_000,
        )

        self.assertEqual(result.code, "token_rotated")
        self.assertNotEqual(result.credential.current_token_revision_id, dto.current_token_revision_id)
        self.assertEqual(result.credential.expiry_state, "expiry_ok")

    def test_confirmed_invalid_current_token_requires_rotation_instead_of_revalidation(self) -> None:
        service = self._require_service()
        dto = self._create()
        self.adapter.results = [AdapterResult(
            token_outcome="explicit_invalid",
            safe_code="explicit_invalid",
            identity_bytes=None,
            identity_contract_version=None,
            http_status_class="4xx",
            http_status_code=401,
        )]

        invalid = service.validate(
            "user-a", dto.credential_id, dto.credential_version,
            dto.current_token_revision_id, self._next_time(),
        )

        self.assertEqual(invalid.code, "credential_token_invalid")
        self.assertEqual(invalid.credential.last_confirmed_validation_state, "confirmed_invalid")
        self.assertTrue(invalid.credential.requires_revalidation)
        calls_after_invalid = len(self.adapter.calls)
        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.validate(
                "user-a", dto.credential_id, invalid.credential.credential_version,
                dto.current_token_revision_id, self._next_time(),
            )
        self.assertEqual(raised.exception.code, "credential_token_invalid")
        self.assertEqual(len(self.adapter.calls), calls_after_invalid)

        self.adapter.results = [AdapterResult()]
        rotated = service.rotate_token(
            "user-a", dto.credential_id, invalid.credential.credential_version,
            dto.current_token_revision_id, _token(marker="replacement"), self._next_time(),
        )
        self.assertEqual(rotated.code, "token_rotated")
        self.assertEqual(rotated.credential.last_confirmed_validation_state, "confirmed_valid")

    def test_preflight_confirmed_invalid_token_uses_unprocessable_status(self) -> None:
        service = self._require_service()
        denial = GateDecision(1, None, "credential_token_invalid", None)

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service._raise_gate_denial(denial)

        self.assertEqual(raised.exception.http_status, 422)

    def test_invalid_label_and_token_boundaries_are_rejected_before_dispatch(self) -> None:
        service = self._require_service()
        invalid_inputs = (
            ("\n", _token()),
            ("x" * 129, _token()),
            ("valid", "bad\ntoken"),
            ("valid", "x" * 16_385),
        )
        for label, token in invalid_inputs:
            with self.subTest(label_size=len(label), token_size=len(token)):
                with self.assertRaises(self.service_module.CredentialOperationError):
                    service.create("user-a", label, token, self._next_time())
        self.assertEqual(self.adapter.calls, [])

    def test_internal_candidate_repr_does_not_expose_the_token(self) -> None:
        service = self._require_service()
        token = _token(marker="repr-secret")

        candidate = service._token_candidate(token, self._next_time())

        self.assertNotIn(token, repr(candidate))

    def test_unknown_upstream_response_is_observed_without_persisting_candidate(self) -> None:
        service = self._require_service()
        self.adapter.results = [AdapterResult(
            token_outcome="validation_unknown",
            safe_code="upstream_validation_unknown",
            identity_bytes=None,
            identity_contract_version=None,
        )]

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.create("user-a", "Unknown", _token(), self._next_time())

        self.assertEqual(raised.exception.code, "upstream_validation_unknown")
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM credentials").fetchone()[0], 0)
            observation = connection.execute(
                "SELECT attempt_result, apply_state FROM credential_validation_observations"
            ).fetchone()
        self.assertEqual(tuple(observation), ("validation_unknown", "candidate_rejected"))

    def test_success_without_completed_http_dispatch_is_never_accepted(self) -> None:
        service = self._require_service()
        self.adapter.results = [AdapterResult(dispatch_state="not_dispatched")]

        with self.assertRaises(self.service_module.CredentialOperationError) as raised:
            service.create("user-a", "No dispatch", _token(), self._next_time())

        self.assertEqual(raised.exception.code, "upstream_validation_unknown")
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM credentials").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
