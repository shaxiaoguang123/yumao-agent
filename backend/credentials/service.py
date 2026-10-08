from __future__ import annotations

import hmac
import sqlite3
import time
import unicodedata
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from backend.credentials.contracts import AdapterValidationResult
from backend.credentials.crypto import (
    CredentialTokenCipher,
    EncryptedTokenEnvelope,
    TokenCipherError,
)
from backend.credentials.keyring import CredentialKeyring
from backend.credentials.request_gate import (
    GateAttemptObservation,
    GateDecision,
    GateOperationContext,
    GatePermit,
    GatePreflightDenial,
    UpstreamRequestGate,
)
from backend.credentials.tokens import account_fingerprint, parse_token_exp, token_fingerprint
from backend.credentials.types import (
    CredentialDTO,
    CredentialOperationError,
    CredentialOperationResult,
)
from backend.db import connect_database


_MAX_TOKEN_BYTES = 16_384
_MAX_LABEL_LENGTH = 128
_SAFE_ATTEMPT_RESULTS = {
    "success",
    "explicit_invalid",
    "network_error",
    "rate_limited",
    "contract_drift",
    "validation_unknown",
    "unresolved_identity",
    "internal_error",
}


@dataclass(frozen=True, slots=True)
class _TokenCandidate:
    raw: str = field(repr=False)
    encoded: bytes = field(repr=False)
    expires_at_utc_ms: int | None
    fingerprint: str = field(repr=False)
    fingerprint_key_version: str


class CredentialService:
    """User-scoped Credential lifecycle with snapshot/network/conditional-write flow."""

    def __init__(
        self,
        *,
        database_path: Path,
        busy_timeout_ms: int,
        encryption_keyring: CredentialKeyring,
        fingerprint_keyring: CredentialKeyring,
        adapter,
        gate: UpstreamRequestGate,
        account_continuity_capability: bool,
        token_expiring_soon_window_seconds: int = 604_800,
        clock_utc_ms: Callable[[], int] | None = None,
    ) -> None:
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        if token_expiring_soon_window_seconds <= 0:
            raise ValueError("token expiry reminder window must be positive")
        if not isinstance(encryption_keyring, CredentialKeyring):
            raise TypeError("encryption_keyring must be a CredentialKeyring")
        if not isinstance(fingerprint_keyring, CredentialKeyring):
            raise TypeError("fingerprint_keyring must be a CredentialKeyring")
        self.database_path = Path(database_path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.encryption_keyring = encryption_keyring
        self.fingerprint_keyring = fingerprint_keyring
        self.cipher = CredentialTokenCipher(encryption_keyring)
        self.adapter = adapter
        self.gate = gate
        self.account_continuity_capability = bool(account_continuity_capability)
        self.token_expiring_soon_window_seconds = int(token_expiring_soon_window_seconds)
        self._clock_utc_ms = clock_utc_ms or (lambda: time.time_ns() // 1_000_000)

    def _now(self, value: int | None = None) -> int:
        now = self._clock_utc_ms() if value is None else value
        if isinstance(now, bool) or not isinstance(now, int) or now < 0:
            raise ValueError("now_utc_ms must be a non-negative integer")
        return now

    @staticmethod
    def _validate_user_id(user_id: str) -> None:
        if not isinstance(user_id, str) or not user_id:
            raise CredentialOperationError("invalid_user", 400)

    @staticmethod
    def _validate_label(label: str) -> str:
        if not isinstance(label, str):
            raise CredentialOperationError("invalid_credential_label", 400)
        normalized = label.strip()
        if (
            not normalized
            or len(normalized) > _MAX_LABEL_LENGTH
            or any(unicodedata.category(character) == "Cc" for character in normalized)
        ):
            raise CredentialOperationError("invalid_credential_label", 400)
        return normalized

    def _token_candidate(self, token: str, now_utc_ms: int) -> _TokenCandidate:
        if not isinstance(token, str) or not token:
            raise CredentialOperationError("invalid_credential_token", 400)
        try:
            encoded = token.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise CredentialOperationError("invalid_credential_token", 400) from exc
        if (
            len(encoded) > _MAX_TOKEN_BYTES
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in token)
        ):
            raise CredentialOperationError("invalid_credential_token", 400)
        expiry = parse_token_exp(
            token,
            now_utc_ms,
            self.token_expiring_soon_window_seconds,
        )
        if expiry.expiry_state == "expired":
            raise CredentialOperationError("credential_token_expired", 422)
        try:
            fingerprint = token_fingerprint(token, self.fingerprint_keyring)
        except ValueError as exc:
            raise CredentialOperationError("invalid_credential_token", 400) from exc
        return _TokenCandidate(
            token,
            encoded,
            expiry.expires_at_utc_ms,
            fingerprint.value,
            fingerprint.key_version,
        )

    @staticmethod
    def _active_rows(connection: sqlite3.Connection, user_id: str) -> list[sqlite3.Row]:
        return connection.execute(
            """SELECT credential_id, account_binding_state
               FROM credentials WHERE user_id=? AND deleted_at_utc_ms IS NULL
               ORDER BY credential_id""",
            (user_id,),
        ).fetchall()

    def _create_preflight(
        self,
        connection: sqlite3.Connection,
        context: GateOperationContext,
    ) -> GatePreflightDenial | None:
        rows = self._active_rows(connection, context.user_id)
        states = {row["account_binding_state"] for row in rows}
        if "needs_reconfirmation" in states:
            return GatePreflightDenial(
                "credential_account_reconfirmation_required",
                "validation_unknown",
                "mismatch",
            )
        if "unresolved" in states:
            return GatePreflightDenial(
                "credential_account_binding_unresolved",
                "validation_unknown",
                "unresolved",
            )
        if rows and not self.account_continuity_capability:
            return GatePreflightDenial(
                "credential_account_binding_unresolved",
                "validation_unknown",
                "unresolved",
            )
        return None

    def _existing_preflight(
        self,
        connection: sqlite3.Connection,
        context: GateOperationContext,
    ) -> GatePreflightDenial | None:
        row = connection.execute(
            """SELECT credential.*, revision.token_expires_at_utc_ms,
                      revision.secret_material_active
               FROM credentials AS credential
               JOIN credential_token_revisions AS revision
                 ON revision.user_id=credential.user_id
                AND revision.credential_id=credential.credential_id
                AND revision.revision_id=credential.current_token_revision_id
               WHERE credential.user_id=? AND credential.credential_id=?""",
            (context.user_id, context.credential_id),
        ).fetchone()
        if row is None or row["deleted_at_utc_ms"] is not None:
            return GatePreflightDenial("credential_not_found")
        if not row["enabled"]:
            return GatePreflightDenial("credential_disabled")
        if (
            row["credential_version"] != context.credential_version_snapshot
            or row["current_token_revision_id"] != context.current_token_revision_snapshot_id
        ):
            return GatePreflightDenial("credential_version_conflict")
        if (
            context.operation_kind == "validate_current"
            and row["last_confirmed_validation_state"] == "confirmed_invalid"
        ):
            return GatePreflightDenial("credential_token_invalid")
        if (
            row["token_expires_at_utc_ms"] is not None
            and row["token_expires_at_utc_ms"] <= self._now()
        ):
            return GatePreflightDenial("credential_token_expired")
        if not row["secret_material_active"]:
            return GatePreflightDenial("credential_token_invalid")
        if context.operation_kind == "token_rotation_candidate":
            if row["account_binding_state"] == "unresolved":
                return GatePreflightDenial(
                    "credential_account_binding_unresolved",
                    account_binding_outcome="unresolved",
                )
            if row["account_binding_state"] == "needs_reconfirmation":
                return GatePreflightDenial(
                    "credential_account_reconfirmation_required",
                    account_binding_outcome="mismatch",
                )
        return None

    @staticmethod
    def _raise_gate_denial(decision: GateDecision) -> None:
        code = decision.denial_code or "validation_unavailable"
        status = 503 if code == "validation_not_configured" else 429 if code == "validation_rate_limited" else 409
        if code in {"credential_token_expired", "credential_token_invalid"}:
            status = 422
        raise CredentialOperationError(code, status, decision.retry_after_seconds)

    def _snapshot(
        self,
        user_id: str,
        credential_id: str,
    ) -> tuple[sqlite3.Row, sqlite3.Row]:
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            row = connection.execute(
                """SELECT credential.*,
                          revision.revision_id AS revision_id,
                          revision.revision_number,
                          revision.token_fingerprint,
                          revision.token_fingerprint_key_version,
                          revision.token_expires_at_utc_ms,
                          revision.secret_material_active,
                          revision.ciphertext,
                          revision.nonce,
                          revision.tag,
                          revision.encryption_key_version
                   FROM credentials AS credential
                   JOIN credential_token_revisions AS revision
                     ON revision.user_id=credential.user_id
                    AND revision.credential_id=credential.credential_id
                    AND revision.revision_id=credential.current_token_revision_id
                   WHERE credential.user_id=? AND credential.credential_id=?
                     AND credential.deleted_at_utc_ms IS NULL""",
                (user_id, credential_id),
            ).fetchone()
            if row is None:
                raise CredentialOperationError("credential_not_found", 404)
            return row, row
        finally:
            connection.close()

    @staticmethod
    def _check_expected(
        row: sqlite3.Row,
        expected_credential_version: int,
        expected_revision_id: str,
    ) -> None:
        if (
            isinstance(expected_credential_version, bool)
            or not isinstance(expected_credential_version, int)
            or expected_credential_version <= 0
            or not isinstance(expected_revision_id, str)
            or not expected_revision_id
        ):
            raise CredentialOperationError("invalid_credential_version", 400)
        if (
            row["credential_version"] != expected_credential_version
            or row["current_token_revision_id"] != expected_revision_id
        ):
            raise CredentialOperationError("credential_version_conflict", 409)

    def _decrypt_snapshot_token(self, row: sqlite3.Row, user_id: str, credential_id: str) -> str:
        if not row["secret_material_active"]:
            raise CredentialOperationError("credential_token_invalid", 409)
        envelope = EncryptedTokenEnvelope(
            ciphertext=row["ciphertext"],
            nonce=row["nonce"],
            tag=row["tag"],
            key_id=row["encryption_key_version"],
        )
        try:
            plaintext = self.cipher.decrypt(
                envelope,
                user_id=user_id,
                credential_id=credential_id,
                revision_id=row["revision_id"],
                key_id=row["encryption_key_version"],
            )
            return plaintext.decode("utf-8", errors="strict")
        except TokenCipherError as exc:
            raise CredentialOperationError("credential_secret_unavailable", 503) from exc
        except UnicodeDecodeError as exc:
            raise CredentialOperationError("credential_secret_unavailable", 503) from exc

    def _identity(self, result: AdapterValidationResult) -> tuple[bytes, str] | None:
        if not self.account_continuity_capability:
            return None
        identity = result.identity_bytes
        contract_version = result.identity_contract_version
        if (
            not isinstance(identity, bytes)
            or not identity
            or not isinstance(contract_version, str)
            or not contract_version
        ):
            return None
        try:
            text = identity.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
        if len(identity) > 512 or any(unicodedata.category(char).startswith("C") for char in text):
            return None
        return identity, contract_version

    def _duplicate_confirmed(
        self,
        connection: sqlite3.Connection,
        user_id: str,
        identity: bytes,
        *,
        exclude_credential_id: str | None = None,
    ) -> bool:
        rows = connection.execute(
            """SELECT credential_id, upstream_account_fingerprint, fingerprint_key_version
               FROM credentials
               WHERE user_id=? AND deleted_at_utc_ms IS NULL
                 AND account_binding_state='confirmed'
                 AND upstream_account_fingerprint IS NOT NULL
                 AND (? IS NULL OR credential_id<>?)""",
            (user_id, exclude_credential_id, exclude_credential_id),
        ).fetchall()
        for row in rows:
            candidate = account_fingerprint(
                identity,
                self.fingerprint_keyring,
                row["fingerprint_key_version"],
            )
            if hmac.compare_digest(candidate.value, row["upstream_account_fingerprint"]):
                return True
        return False

    @staticmethod
    def _account_matches(row: sqlite3.Row, identity: bytes, keyring: CredentialKeyring) -> bool:
        if not row["upstream_account_fingerprint"] or not row["fingerprint_key_version"]:
            return False
        candidate = account_fingerprint(identity, keyring, row["fingerprint_key_version"])
        return hmac.compare_digest(candidate.value, row["upstream_account_fingerprint"])

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        *,
        user_id: str,
        credential_id: str,
        revision_id: str | None,
        operation_code: str,
        now_utc_ms: int,
        outcome: str = "success",
        old_key_version: str | None = None,
        new_key_version: str | None = None,
        old_contract_version: str | None = None,
        new_contract_version: str | None = None,
        old_binding_state: str | None = None,
    ) -> None:
        connection.execute(
            """INSERT INTO credential_lifecycle_audits
               (user_id, credential_id, revision_id, actor_user_id, operation_code,
                old_key_version, new_key_version, old_identity_contract_version,
                new_identity_contract_version, occurred_at_utc_ms, outcome,
                old_account_binding_state)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                credential_id,
                revision_id,
                user_id,
                operation_code,
                old_key_version,
                new_key_version,
                old_contract_version,
                new_contract_version,
                now_utc_ms,
                outcome,
                old_binding_state,
            ),
        )

    @staticmethod
    def _safe_adapter_result(result) -> AdapterValidationResult:
        try:
            dispatch_state = result.dispatch_state
            outcome = result.token_outcome
            status_code = result.http_status_code
            status_class = result.http_status_class
            retry_after = result.retry_after_header
        except Exception:
            return AdapterValidationResult(
                "network_error", "upstream_internal_error", None, None, None, None, "uncertain"
            )
        if dispatch_state not in {"not_dispatched", "complete", "uncertain"}:
            return AdapterValidationResult(
                "network_error", "upstream_internal_error", None, None, None, None, "uncertain"
            )
        if outcome not in {
            "success", "explicit_invalid", "network_error", "rate_limited",
            "contract_drift", "validation_unknown",
        }:
            return AdapterValidationResult(
                "validation_unknown",
                "upstream_validation_unknown",
                None,
                None,
                status_class,
                retry_after,
                dispatch_state,
                status_code,
            )
        if outcome == "success" and dispatch_state != "complete":
            return AdapterValidationResult(
                "validation_unknown",
                "upstream_dispatch_incomplete",
                None,
                None,
                status_class,
                retry_after,
                dispatch_state,
                status_code,
            )
        return result

    @staticmethod
    def _attempt_result(result: AdapterValidationResult) -> str:
        outcome = result.token_outcome
        if outcome not in _SAFE_ATTEMPT_RESULTS:
            return "internal_error"
        return outcome

    @staticmethod
    def _observation(
        permit: GatePermit,
        result: AdapterValidationResult,
        completed_at_utc_ms: int,
        *,
        credential_id: str | None = None,
        token_revision_id: str | None = None,
        attempt_result: str | None = None,
        binding_outcome: str | None = "not_checked",
        apply_state: str = "applied",
    ) -> GateAttemptObservation:
        context = permit.context
        if credential_id is None:
            credential_id = context.credential_id
        if token_revision_id is None and context.operation_kind == "validate_current":
            token_revision_id = context.token_revision_id
        return GateAttemptObservation(
            validation_attempt_id=permit.validation_attempt_id,
            user_id=context.user_id,
            credential_id=credential_id,
            operation_kind=context.operation_kind,
            credential_version_snapshot=context.credential_version_snapshot,
            current_token_revision_snapshot_id=context.current_token_revision_snapshot_id,
            token_revision_id=token_revision_id,
            started_at_utc_ms=permit.started_at_utc_ms,
            completed_at_utc_ms=max(permit.started_at_utc_ms, completed_at_utc_ms),
            attempt_result=attempt_result or CredentialService._attempt_result(result),
            account_binding_outcome=binding_outcome,
            http_status_class=result.http_status_class,
            gate_owner_id=permit.owner_id,
            gate_epoch=permit.epoch,
            apply_state=apply_state,
        )

    @staticmethod
    def _upstream_failure(result: AdapterValidationResult) -> tuple[str, int]:
        if result.token_outcome == "explicit_invalid":
            return "credential_token_invalid", 422
        if result.token_outcome == "rate_limited":
            return "upstream_rate_limited", 429
        if result.token_outcome == "network_error":
            return "upstream_unavailable", 502
        if result.token_outcome == "contract_drift":
            return "upstream_contract_drift", 502
        return "upstream_validation_unknown", 502

    def _dto_from_id(
        self,
        connection: sqlite3.Connection,
        user_id: str,
        credential_id: str,
        now_utc_ms: int,
    ) -> CredentialDTO | None:
        row = connection.execute(
            """SELECT credential.*, revision.token_expires_at_utc_ms
               FROM credentials AS credential
               JOIN credential_token_revisions AS revision
                 ON revision.user_id=credential.user_id
                AND revision.credential_id=credential.credential_id
                AND revision.revision_id=credential.current_token_revision_id
               WHERE credential.user_id=? AND credential.credential_id=?
                 AND credential.deleted_at_utc_ms IS NULL""",
            (user_id, credential_id),
        ).fetchone()
        if row is None:
            return None
        expires_at = row["token_expires_at_utc_ms"]
        if expires_at is None:
            expiry_state = "expiry_unknown"
        elif expires_at <= now_utc_ms:
            expiry_state = "expired"
        elif expires_at <= now_utc_ms + self.token_expiring_soon_window_seconds * 1000:
            expiry_state = "expiring_soon"
        else:
            expiry_state = "expiry_ok"
        latest = connection.execute(
            """SELECT validation_attempt_id, operation_kind,
                      current_token_revision_snapshot_id, token_revision_id,
                      started_at_utc_ms, completed_at_utc_ms, attempt_result,
                      account_binding_outcome, apply_state
               FROM credential_validation_observations
               WHERE user_id=? AND credential_id=?
               ORDER BY validation_attempt_id DESC LIMIT 1""",
            (user_id, credential_id),
        ).fetchone()
        latest_projection = dict(latest) if latest is not None else None
        return CredentialDTO(
            credential_id=row["credential_id"],
            label=row["label"],
            credential_version=row["credential_version"],
            current_token_revision_id=row["current_token_revision_id"],
            enabled=bool(row["enabled"]),
            account_binding_state=row["account_binding_state"],
            requires_revalidation=bool(row["requires_revalidation"]),
            expiry_state=expiry_state,
            token_expires_at_utc_ms=expires_at,
            last_confirmed_validation_state=row["last_confirmed_validation_state"],
            last_successful_validation_at_utc_ms=row["last_successful_validation_at_utc_ms"],
            latest_requested_validation_attempt=latest_projection,
        )

    def get_for_user(self, user_id: str, credential_id: str) -> CredentialDTO | None:
        self._validate_user_id(user_id)
        if not isinstance(credential_id, str) or not credential_id:
            return None
        now = self._now()
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            return self._dto_from_id(connection, user_id, credential_id, now)
        finally:
            connection.close()

    def list_for_user(self, user_id: str) -> list[CredentialDTO]:
        self._validate_user_id(user_id)
        now = self._now()
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            rows = connection.execute(
                """SELECT credential_id FROM credentials
                   WHERE user_id=? AND deleted_at_utc_ms IS NULL
                   ORDER BY created_at_utc_ms, credential_id""",
                (user_id,),
            ).fetchall()
            return [
                dto
                for row in rows
                if (dto := self._dto_from_id(connection, user_id, row["credential_id"], now)) is not None
            ]
        finally:
            connection.close()

    def _write_stale_observation_after_rollback(
        self,
        permit: GatePermit,
        observation: GateAttemptObservation,
        now_utc_ms: int,
    ) -> None:
        if permit.context.operation_kind == "create_candidate":
            observation = replace(
                observation,
                credential_id=None,
                token_revision_id=None,
                apply_state="stale",
            )
        else:
            observation = replace(observation, token_revision_id=None, apply_state="stale")
            if permit.context.operation_kind == "validate_current":
                observation = replace(
                    observation, token_revision_id=permit.context.token_revision_id
                )
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.gate.complete_in_transaction(
                connection,
                permit,
                observation,
                now_utc_ms,
                upstream_status_code=None,
            )
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def create(
        self,
        user_id: str,
        label: str,
        token: str,
        now_utc_ms: int,
    ) -> CredentialDTO:
        self._validate_user_id(user_id)
        clean_label = self._validate_label(label)
        now = self._now(now_utc_ms)
        candidate = self._token_candidate(token, now)
        context = GateOperationContext(
            user_id=user_id,
            credential_id=None,
            operation_kind="create_candidate",
        )
        decision = self.gate.acquire(context, now, self._create_preflight)
        if not decision.allowed or decision.permit is None:
            self._raise_gate_denial(decision)
        permit = decision.permit
        try:
            upstream_result = self.adapter.validate_token(candidate.raw)
        except Exception:
            upstream_result = AdapterValidationResult(
                "network_error", "upstream_internal_error", None, None, None, None, "uncertain"
            )
        upstream_result = self._safe_adapter_result(upstream_result)
        completed_at = self._now()

        if upstream_result.dispatch_state == "uncertain":
            observation = self._observation(permit, upstream_result, completed_at)
            connection = connect_database(self.database_path, self.busy_timeout_ms)
            try:
                connection.execute("BEGIN IMMEDIATE")
                completion = self.gate.mark_uncertain_in_transaction(
                    connection,
                    permit,
                    observation,
                    completed_at,
                    upstream_status_code=upstream_result.http_status_code,
                    retry_after_header=upstream_result.retry_after_header,
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
            if completion.state == "stale":
                raise CredentialOperationError("validation_stale", 409)
            code, status = self._upstream_failure(upstream_result)
            raise CredentialOperationError(code, status, completion.retry_after_seconds)

        if upstream_result.token_outcome != "success":
            observation = self._observation(
                permit,
                upstream_result,
                completed_at,
                apply_state="candidate_rejected",
            )
            connection = connect_database(self.database_path, self.busy_timeout_ms)
            try:
                connection.execute("BEGIN IMMEDIATE")
                completion = self.gate.complete_in_transaction(
                    connection,
                    permit,
                    observation,
                    completed_at,
                    upstream_status_code=upstream_result.http_status_code,
                    retry_after_header=upstream_result.retry_after_header,
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
            if completion.state == "stale":
                raise CredentialOperationError("validation_stale", 409)
            code, status = self._upstream_failure(upstream_result)
            raise CredentialOperationError(code, status)

        identity = self._identity(upstream_result)
        credential_id = uuid.uuid4().hex
        revision_id = uuid.uuid4().hex
        account = account_fingerprint(identity[0], self.fingerprint_keyring) if identity else None
        binding_state = "confirmed" if account is not None else "unresolved"
        conflict: tuple[str, int] | None = None
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = self._active_rows(connection, user_id)
            states = {row["account_binding_state"] for row in rows}
            if "needs_reconfirmation" in states:
                conflict = ("credential_account_reconfirmation_required", 409)
            elif "unresolved" in states or (rows and not self.account_continuity_capability):
                conflict = ("credential_account_binding_unresolved", 409)
            elif account is None and rows:
                conflict = ("credential_account_binding_unresolved", 409)
            elif account is not None and self._duplicate_confirmed(
                connection, user_id, identity[0]
            ):
                conflict = ("credential_account_already_configured", 409)

            if conflict is not None:
                observation = self._observation(
                    permit,
                    upstream_result,
                    completed_at,
                    attempt_result="unresolved_identity" if account is None else "success",
                    binding_outcome=(
                        "duplicate_conflict"
                        if conflict[0] == "credential_account_already_configured"
                        else "unresolved"
                    ),
                    apply_state="candidate_rejected",
                )
                completion = self.gate.complete_in_transaction(
                    connection,
                    permit,
                    observation,
                    completed_at,
                    upstream_status_code=upstream_result.http_status_code,
                    retry_after_header=upstream_result.retry_after_header,
                )
                connection.execute("COMMIT")
                if completion.state == "stale":
                    raise CredentialOperationError("validation_stale", 409)
                raise CredentialOperationError(*conflict)

            envelope = self.cipher.encrypt(
                candidate.encoded,
                user_id=user_id,
                credential_id=credential_id,
                revision_id=revision_id,
                key_id=self.encryption_keyring.active_key_id,
            )
            connection.execute(
                """INSERT INTO credentials
                   (credential_id, user_id, label, credential_version, enabled,
                    deleted_at_utc_ms, current_token_revision_id, account_binding_state,
                    upstream_account_fingerprint, fingerprint_key_version,
                    account_identity_contract_version, account_fingerprint_cleared_at_utc_ms,
                    last_successful_validation_at_utc_ms, last_confirmed_validation_state,
                    requires_revalidation, created_at_utc_ms, updated_at_utc_ms)
                   VALUES (?, ?, ?, 1, 1, NULL, ?, ?, ?, ?, ?, NULL, ?,
                           'confirmed_valid', 0, ?, ?)""",
                (
                    credential_id,
                    user_id,
                    clean_label,
                    revision_id,
                    binding_state,
                    account.value if account else None,
                    account.key_version if account else None,
                    identity[1] if identity else None,
                    completed_at,
                    completed_at,
                    completed_at,
                ),
            )
            connection.execute(
                """INSERT INTO credential_token_revisions
                   (revision_id, user_id, credential_id, revision_number, token_fingerprint,
                    token_fingerprint_key_version, token_expires_at_utc_ms,
                    initial_account_fingerprint_key_version,
                    initial_account_identity_contract_version, initial_validation_result,
                    initial_validation_at_utc_ms, created_by_user_id, secret_material_active,
                    ciphertext, nonce, tag, encryption_key_version, ciphertext_cleared_at_utc_ms)
                   VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, 'success', ?, ?, 1, ?, ?, ?, ?, NULL)""",
                (
                    revision_id,
                    user_id,
                    credential_id,
                    candidate.fingerprint,
                    candidate.fingerprint_key_version,
                    candidate.expires_at_utc_ms,
                    account.key_version if account else None,
                    identity[1] if identity else None,
                    completed_at,
                    user_id,
                    envelope.ciphertext,
                    envelope.nonce,
                    envelope.tag,
                    envelope.key_id,
                ),
            )
            if account is not None:
                self._audit(
                    connection,
                    user_id=user_id,
                    credential_id=credential_id,
                    revision_id=revision_id,
                    operation_code="binding_confirmed",
                    now_utc_ms=completed_at,
                    new_key_version=account.key_version,
                    new_contract_version=identity[1],
                    old_binding_state="unresolved",
                )
            observation = self._observation(
                permit,
                upstream_result,
                completed_at,
                credential_id=credential_id,
                token_revision_id=revision_id,
                attempt_result="success",
                binding_outcome="confirmed" if account else "unresolved",
                apply_state="applied",
            )
            completion = self.gate.complete_in_transaction(
                connection,
                permit,
                observation,
                completed_at,
                upstream_status_code=upstream_result.http_status_code,
                retry_after_header=upstream_result.retry_after_header,
            )
            if completion.state == "stale":
                connection.execute("ROLLBACK")
                self._write_stale_observation_after_rollback(permit, observation, completed_at)
                raise CredentialOperationError("validation_stale", 409)
            dto = self._dto_from_id(connection, user_id, credential_id, completed_at)
            connection.execute("COMMIT")
            if dto is None:
                raise CredentialOperationError("credential_write_failed", 500)
            return dto
        except CredentialOperationError:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        except (sqlite3.Error, ValueError, TokenCipherError) as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise CredentialOperationError("credential_write_failed", 500) from exc
        finally:
            connection.close()

    def validate(
        self,
        user_id: str,
        credential_id: str,
        expected_credential_version: int,
        expected_revision_id: str,
        now_utc_ms: int,
    ) -> CredentialOperationResult:
        self._validate_user_id(user_id)
        now = self._now(now_utc_ms)
        row, _revision = self._snapshot(user_id, credential_id)
        self._check_expected(row, expected_credential_version, expected_revision_id)
        if not row["enabled"]:
            raise CredentialOperationError("credential_disabled", 409)
        if row["last_confirmed_validation_state"] == "confirmed_invalid":
            raise CredentialOperationError("credential_token_invalid", 422)
        if row["token_expires_at_utc_ms"] is not None and row["token_expires_at_utc_ms"] <= now:
            raise CredentialOperationError("credential_token_expired", 422)
        token = self._decrypt_snapshot_token(row, user_id, credential_id)
        context = GateOperationContext(
            user_id=user_id,
            credential_id=credential_id,
            operation_kind="validate_current",
            credential_version_snapshot=row["credential_version"],
            current_token_revision_snapshot_id=row["current_token_revision_id"],
            token_revision_id=row["current_token_revision_id"],
        )
        decision = self.gate.acquire(context, now, self._existing_preflight)
        if not decision.allowed or decision.permit is None:
            self._raise_gate_denial(decision)
        permit = decision.permit
        try:
            upstream_result = self.adapter.validate_token(token)
        except Exception:
            upstream_result = AdapterValidationResult(
                "network_error", "upstream_internal_error", None, None, None, None, "uncertain"
            )
        upstream_result = self._safe_adapter_result(upstream_result)
        completed_at = self._now()
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """SELECT credential.*, revision.token_expires_at_utc_ms
                   FROM credentials AS credential
                   JOIN credential_token_revisions AS revision
                     ON revision.user_id=credential.user_id
                    AND revision.credential_id=credential.credential_id
                    AND revision.revision_id=credential.current_token_revision_id
                   WHERE credential.user_id=? AND credential.credential_id=?""",
                (user_id, credential_id),
            ).fetchone()
            stale_snapshot = (
                current is None
                or current["deleted_at_utc_ms"] is not None
                or not current["enabled"]
                or current["credential_version"] != row["credential_version"]
                or current["current_token_revision_id"] != row["current_token_revision_id"]
                or current["account_binding_state"] != row["account_binding_state"]
                or current["fingerprint_key_version"] != row["fingerprint_key_version"]
                or current["account_identity_contract_version"] != row["account_identity_contract_version"]
            )
            if stale_snapshot:
                observation = self._observation(
                    permit, upstream_result, completed_at, apply_state="stale"
                )
                completion = self.gate.complete_in_transaction(
                    connection,
                    permit,
                    observation,
                    completed_at,
                    upstream_status_code=upstream_result.http_status_code,
                    retry_after_header=upstream_result.retry_after_header,
                )
                dto = self._dto_from_id(connection, user_id, credential_id, completed_at)
                connection.execute("COMMIT")
                return CredentialOperationResult(
                    "validation_stale", 409, dto
                )

            if upstream_result.dispatch_state == "uncertain":
                observation = self._observation(permit, upstream_result, completed_at)
                completion = self.gate.mark_uncertain_in_transaction(
                    connection,
                    permit,
                    observation,
                    completed_at,
                    upstream_status_code=upstream_result.http_status_code,
                    retry_after_header=upstream_result.retry_after_header,
                )
                dto = self._dto_from_id(connection, user_id, credential_id, completed_at)
                connection.execute("COMMIT")
                if completion.state == "stale":
                    return CredentialOperationResult("validation_stale", 409, dto)
                code, status = self._upstream_failure(upstream_result)
                return CredentialOperationResult(
                    code, status, dto, completion.retry_after_seconds
                )

            if upstream_result.token_outcome not in {"success", "explicit_invalid"}:
                code, status = self._upstream_failure(upstream_result)
                observation = self._observation(permit, upstream_result, completed_at)
                completion = self.gate.complete_in_transaction(
                    connection,
                    permit,
                    observation,
                    completed_at,
                    upstream_status_code=upstream_result.http_status_code,
                    retry_after_header=upstream_result.retry_after_header,
                )
                dto = self._dto_from_id(connection, user_id, credential_id, completed_at)
                connection.execute("COMMIT")
                if completion.state == "stale":
                    return CredentialOperationResult("validation_stale", 409, dto)
                return CredentialOperationResult(code, status, dto)

            identity = self._identity(upstream_result) if upstream_result.token_outcome == "success" else None
            next_binding = current["account_binding_state"]
            next_account_fingerprint = current["upstream_account_fingerprint"]
            next_fingerprint_key_version = current["fingerprint_key_version"]
            next_contract_version = current["account_identity_contract_version"]
            binding_outcome = "not_checked"
            binding_audit: tuple[str, str | None, str | None, str | None, str | None] | None = None
            result_code = "validated"
            status = 200

            if upstream_result.token_outcome == "explicit_invalid":
                attempt_result = "explicit_invalid"
                result_code = "credential_token_invalid"
                status = 422
            elif identity is None:
                attempt_result = "unresolved_identity"
                binding_outcome = "unresolved"
            else:
                identity_bytes, identity_contract_version = identity
                if current["account_binding_state"] == "unresolved":
                    if self._duplicate_confirmed(
                        connection, user_id, identity_bytes, exclude_credential_id=credential_id
                    ):
                        binding_outcome = "duplicate_conflict"
                        result_code = "credential_account_already_configured"
                        status = 409
                    else:
                        account = account_fingerprint(identity_bytes, self.fingerprint_keyring)
                        next_binding = "confirmed"
                        next_account_fingerprint = account.value
                        next_fingerprint_key_version = account.key_version
                        next_contract_version = identity_contract_version
                        binding_outcome = "confirmed"
                        binding_audit = (
                            "binding_confirmed", None, account.key_version, None,
                            identity_contract_version,
                        )
                else:
                    matches = self._account_matches(current, identity_bytes, self.fingerprint_keyring)
                    if matches:
                        if (
                            current["account_binding_state"] == "needs_reconfirmation"
                            and self._duplicate_confirmed(
                                connection,
                                user_id,
                                identity_bytes,
                                exclude_credential_id=credential_id,
                            )
                        ):
                            binding_outcome = "duplicate_conflict"
                            result_code = "credential_account_already_configured"
                            status = 409
                        else:
                            account = account_fingerprint(identity_bytes, self.fingerprint_keyring)
                            next_account_fingerprint = account.value
                            next_fingerprint_key_version = account.key_version
                            next_contract_version = identity_contract_version
                            binding_outcome = "confirmed"
                            if current["account_binding_state"] == "needs_reconfirmation":
                                next_binding = "confirmed"
                                binding_audit = (
                                    "binding_reconfirmed", current["fingerprint_key_version"],
                                    account.key_version, current["account_identity_contract_version"],
                                    identity_contract_version,
                                )
                            elif (
                                current["fingerprint_key_version"] != account.key_version
                                or current["account_identity_contract_version"] != identity_contract_version
                            ):
                                binding_audit = (
                                    "fingerprint_rebound", current["fingerprint_key_version"],
                                    account.key_version, current["account_identity_contract_version"],
                                    identity_contract_version,
                                )
                    else:
                        binding_outcome = "mismatch"
                        result_code = "credential_account_mismatch"
                        status = 409
                        if current["account_binding_state"] == "confirmed":
                            next_binding = "needs_reconfirmation"
                            binding_audit = (
                                "binding_needs_reconfirmation", current["fingerprint_key_version"],
                                current["fingerprint_key_version"],
                                current["account_identity_contract_version"],
                                current["account_identity_contract_version"],
                            )
                attempt_result = "success"

            binding_changed = (
                next_binding != current["account_binding_state"]
                or next_account_fingerprint != current["upstream_account_fingerprint"]
                or next_fingerprint_key_version != current["fingerprint_key_version"]
                or next_contract_version != current["account_identity_contract_version"]
            )
            observation = self._observation(
                permit,
                upstream_result,
                completed_at,
                attempt_result=attempt_result,
                binding_outcome=binding_outcome,
                apply_state="applied",
            )
            completion = self.gate.complete_in_transaction(
                connection,
                permit,
                observation,
                completed_at,
                upstream_status_code=upstream_result.http_status_code,
                retry_after_header=upstream_result.retry_after_header,
            )
            if completion.state == "stale":
                dto = self._dto_from_id(connection, user_id, credential_id, completed_at)
                connection.execute("COMMIT")
                return CredentialOperationResult("validation_stale", 409, dto)

            if upstream_result.token_outcome == "success":
                connection.execute(
                    """UPDATE credentials
                       SET account_binding_state=?, upstream_account_fingerprint=?,
                           fingerprint_key_version=?, account_identity_contract_version=?,
                           last_successful_validation_at_utc_ms=?,
                           last_confirmed_validation_state='confirmed_valid',
                           requires_revalidation=0, credential_version=credential_version+?,
                           updated_at_utc_ms=?
                       WHERE user_id=? AND credential_id=? AND credential_version=?
                         AND current_token_revision_id=? AND deleted_at_utc_ms IS NULL""",
                    (
                        next_binding,
                        next_account_fingerprint,
                        next_fingerprint_key_version,
                        next_contract_version,
                        completed_at,
                        1 if binding_changed else 0,
                        completed_at,
                        user_id,
                        credential_id,
                        row["credential_version"],
                        row["current_token_revision_id"],
                    ),
                )
            else:
                connection.execute(
                    """UPDATE credentials
                       SET last_confirmed_validation_state='confirmed_invalid',
                           requires_revalidation=1, updated_at_utc_ms=?
                       WHERE user_id=? AND credential_id=? AND credential_version=?
                         AND current_token_revision_id=? AND deleted_at_utc_ms IS NULL""",
                    (
                        completed_at,
                        user_id,
                        credential_id,
                        row["credential_version"],
                        row["current_token_revision_id"],
                    ),
                )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise CredentialOperationError("validation_stale", 409)
            if binding_audit is not None:
                operation, old_key, new_key, old_contract, new_contract = binding_audit
                self._audit(
                    connection,
                    user_id=user_id,
                    credential_id=credential_id,
                    revision_id=row["current_token_revision_id"],
                    operation_code=operation,
                    now_utc_ms=completed_at,
                    old_key_version=old_key,
                    new_key_version=new_key,
                    old_contract_version=old_contract,
                    new_contract_version=new_contract,
                    old_binding_state=row["account_binding_state"] if binding_changed else None,
                )
            dto = self._dto_from_id(connection, user_id, credential_id, completed_at)
            connection.execute("COMMIT")
            return CredentialOperationResult(result_code, status, dto)
        except CredentialOperationError:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        except (sqlite3.Error, ValueError) as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise CredentialOperationError("credential_validation_write_failed", 500) from exc
        finally:
            connection.close()

    def rotate_token(
        self,
        user_id: str,
        credential_id: str,
        expected_credential_version: int,
        expected_revision_id: str,
        token: str,
        now_utc_ms: int,
    ) -> CredentialOperationResult:
        self._validate_user_id(user_id)
        now = self._now(now_utc_ms)
        candidate = self._token_candidate(token, now)
        check_connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            check_connection.execute("BEGIN IMMEDIATE")
            row = check_connection.execute(
                """SELECT credential.*,
                          revision.revision_id AS revision_id,
                          revision.revision_number,
                          revision.token_fingerprint,
                          revision.token_fingerprint_key_version,
                          revision.token_expires_at_utc_ms,
                          revision.secret_material_active,
                          revision.ciphertext,
                          revision.nonce,
                          revision.tag,
                          revision.encryption_key_version
                   FROM credentials AS credential
                   JOIN credential_token_revisions AS revision
                     ON revision.user_id=credential.user_id
                    AND revision.credential_id=credential.credential_id
                    AND revision.revision_id=credential.current_token_revision_id
                   WHERE credential.user_id=? AND credential.credential_id=?
                     AND credential.deleted_at_utc_ms IS NULL""",
                (user_id, credential_id),
            ).fetchone()
            if row is None:
                raise CredentialOperationError("credential_not_found", 404)
            self._check_expected(row, expected_credential_version, expected_revision_id)
            if not row["enabled"]:
                raise CredentialOperationError("credential_disabled", 409)
            if row["account_binding_state"] == "unresolved":
                raise CredentialOperationError("credential_account_binding_unresolved", 409)
            if row["account_binding_state"] == "needs_reconfirmation":
                raise CredentialOperationError("credential_account_reconfirmation_required", 409)
            if row["account_binding_state"] != "confirmed":
                raise CredentialOperationError("credential_account_binding_unresolved", 409)
            current_fingerprint = token_fingerprint(
                token,
                self.fingerprint_keyring,
                row["token_fingerprint_key_version"],
            )
            if hmac.compare_digest(current_fingerprint.value, row["token_fingerprint"]):
                dto = self._dto_from_id(check_connection, user_id, credential_id, now)
                check_connection.execute("COMMIT")
                return CredentialOperationResult("token_already_current", 200, dto)
            check_connection.execute("COMMIT")
        except CredentialOperationError:
            if check_connection.in_transaction:
                check_connection.execute("ROLLBACK")
            raise
        except ValueError as exc:
            if check_connection.in_transaction:
                check_connection.execute("ROLLBACK")
            raise CredentialOperationError("credential_fingerprint_key_unavailable", 503) from exc
        except sqlite3.Error as exc:
            if check_connection.in_transaction:
                check_connection.execute("ROLLBACK")
            raise CredentialOperationError("credential_snapshot_unavailable", 503) from exc
        finally:
            check_connection.close()

        context = GateOperationContext(
            user_id=user_id,
            credential_id=credential_id,
            operation_kind="token_rotation_candidate",
            credential_version_snapshot=row["credential_version"],
            current_token_revision_snapshot_id=row["current_token_revision_id"],
        )
        decision = self.gate.acquire(context, now, self._existing_preflight)
        if not decision.allowed or decision.permit is None:
            self._raise_gate_denial(decision)
        permit = decision.permit
        try:
            upstream_result = self.adapter.validate_token(candidate.raw)
        except Exception:
            upstream_result = AdapterValidationResult(
                "network_error", "upstream_internal_error", None, None, None, None, "uncertain"
            )
        upstream_result = self._safe_adapter_result(upstream_result)
        completed_at = self._now()
        identity = self._identity(upstream_result) if upstream_result.token_outcome == "success" else None
        failure: tuple[str, int] | None = None
        binding_outcome = "not_checked"
        matches_current_account = False
        if upstream_result.dispatch_state != "uncertain" and upstream_result.token_outcome == "success":
            if identity is None:
                failure = ("credential_account_binding_unresolved", 409)
                binding_outcome = "unresolved"
            else:
                matches_current_account = self._account_matches(row, identity[0], self.fingerprint_keyring)
                if not matches_current_account:
                    failure = ("credential_account_mismatch", 409)
                    binding_outcome = "mismatch"
                else:
                    binding_outcome = "confirmed"
        elif upstream_result.dispatch_state != "uncertain":
            failure = self._upstream_failure(upstream_result)

        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM credentials WHERE user_id=? AND credential_id=?",
                (user_id, credential_id),
            ).fetchone()
            stale_snapshot = (
                current is None
                or current["deleted_at_utc_ms"] is not None
                or not current["enabled"]
                or current["credential_version"] != row["credential_version"]
                or current["current_token_revision_id"] != row["current_token_revision_id"]
                or current["account_binding_state"] != "confirmed"
                or current["fingerprint_key_version"] != row["fingerprint_key_version"]
                or current["account_identity_contract_version"] != row["account_identity_contract_version"]
            )
            if stale_snapshot:
                observation = self._observation(
                    permit, upstream_result, completed_at, apply_state="stale"
                )
                completion = self.gate.complete_in_transaction(
                    connection,
                    permit,
                    observation,
                    completed_at,
                    upstream_status_code=upstream_result.http_status_code,
                    retry_after_header=upstream_result.retry_after_header,
                )
                connection.execute("COMMIT")
                raise CredentialOperationError("credential_version_conflict", 409)

            if upstream_result.dispatch_state == "uncertain":
                observation = self._observation(permit, upstream_result, completed_at)
                completion = self.gate.mark_uncertain_in_transaction(
                    connection,
                    permit,
                    observation,
                    completed_at,
                    upstream_status_code=upstream_result.http_status_code,
                    retry_after_header=upstream_result.retry_after_header,
                )
                connection.execute("COMMIT")
                if completion.state == "stale":
                    raise CredentialOperationError("validation_stale", 409)
                code, status = self._upstream_failure(upstream_result)
                raise CredentialOperationError(code, status, completion.retry_after_seconds)

            if failure is not None:
                observation = self._observation(
                    permit,
                    upstream_result,
                    completed_at,
                    attempt_result=(
                        "unresolved_identity"
                        if failure[0] == "credential_account_binding_unresolved"
                        else self._attempt_result(upstream_result)
                    ),
                    binding_outcome=binding_outcome,
                    apply_state="candidate_rejected",
                )
                completion = self.gate.complete_in_transaction(
                    connection,
                    permit,
                    observation,
                    completed_at,
                    upstream_status_code=upstream_result.http_status_code,
                    retry_after_header=upstream_result.retry_after_header,
                )
                connection.execute("COMMIT")
                if completion.state == "stale":
                    raise CredentialOperationError("validation_stale", 409)
                raise CredentialOperationError(*failure)

            identity_bytes, contract_version = identity
            account = account_fingerprint(identity_bytes, self.fingerprint_keyring)
            if self._duplicate_confirmed(
                connection, user_id, identity_bytes, exclude_credential_id=credential_id
            ):
                observation = self._observation(
                    permit, upstream_result, completed_at,
                    binding_outcome="duplicate_conflict", apply_state="candidate_rejected",
                )
                completion = self.gate.complete_in_transaction(
                    connection, permit, observation, completed_at,
                    upstream_status_code=upstream_result.http_status_code,
                    retry_after_header=upstream_result.retry_after_header,
                )
                connection.execute("COMMIT")
                if completion.state == "stale":
                    raise CredentialOperationError("validation_stale", 409)
                raise CredentialOperationError("credential_account_already_configured", 409)

            revision_id = uuid.uuid4().hex
            revision_number = connection.execute(
                """SELECT coalesce(max(revision_number), 0) + 1
                   FROM credential_token_revisions
                   WHERE user_id=? AND credential_id=?""",
                (user_id, credential_id),
            ).fetchone()[0]
            envelope = self.cipher.encrypt(
                candidate.encoded,
                user_id=user_id,
                credential_id=credential_id,
                revision_id=revision_id,
                key_id=self.encryption_keyring.active_key_id,
            )
            connection.execute(
                """INSERT INTO credential_token_revisions
                   (revision_id, user_id, credential_id, revision_number, token_fingerprint,
                    token_fingerprint_key_version, token_expires_at_utc_ms,
                    initial_account_fingerprint_key_version,
                    initial_account_identity_contract_version, initial_validation_result,
                    initial_validation_at_utc_ms, created_by_user_id, secret_material_active,
                    ciphertext, nonce, tag, encryption_key_version, ciphertext_cleared_at_utc_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'success', ?, ?, 1, ?, ?, ?, ?, NULL)""",
                (
                    revision_id, user_id, credential_id, revision_number,
                    candidate.fingerprint, candidate.fingerprint_key_version,
                    candidate.expires_at_utc_ms, account.key_version, contract_version,
                    completed_at, user_id, envelope.ciphertext, envelope.nonce,
                    envelope.tag, envelope.key_id,
                ),
            )
            observation = self._observation(
                permit, upstream_result, completed_at,
                token_revision_id=revision_id,
                attempt_result="success",
                binding_outcome="confirmed",
                apply_state="applied",
            )
            completion = self.gate.complete_in_transaction(
                connection,
                permit,
                observation,
                completed_at,
                upstream_status_code=upstream_result.http_status_code,
                retry_after_header=upstream_result.retry_after_header,
            )
            if completion.state == "stale":
                connection.execute("ROLLBACK")
                self._write_stale_observation_after_rollback(permit, observation, completed_at)
                raise CredentialOperationError("validation_stale", 409)

            connection.execute(
                """UPDATE credential_token_revisions
                   SET secret_material_active=0, ciphertext=NULL, nonce=NULL, tag=NULL,
                       ciphertext_cleared_at_utc_ms=?
                   WHERE user_id=? AND credential_id=? AND secret_material_active=1
                     AND revision_id<>?""",
                (completed_at, user_id, credential_id, revision_id),
            )
            connection.execute(
                """UPDATE credentials
                   SET current_token_revision_id=?, account_binding_state='confirmed',
                       upstream_account_fingerprint=?, fingerprint_key_version=?,
                       account_identity_contract_version=?, last_successful_validation_at_utc_ms=?,
                       last_confirmed_validation_state='confirmed_valid', requires_revalidation=0,
                       credential_version=credential_version+1, updated_at_utc_ms=?
                   WHERE user_id=? AND credential_id=? AND credential_version=?
                     AND current_token_revision_id=? AND deleted_at_utc_ms IS NULL""",
                (
                    revision_id, account.value, account.key_version, contract_version,
                    completed_at, completed_at, user_id, credential_id,
                    row["credential_version"], row["current_token_revision_id"],
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise CredentialOperationError("credential_version_conflict", 409)
            self._audit(
                connection,
                user_id=user_id,
                credential_id=credential_id,
                revision_id=row["current_token_revision_id"],
                operation_code="ciphertext_cleared",
                now_utc_ms=completed_at,
                old_key_version=row["encryption_key_version"],
            )
            if (
                row["fingerprint_key_version"] != account.key_version
                or row["account_identity_contract_version"] != contract_version
            ):
                self._audit(
                    connection,
                    user_id=user_id,
                    credential_id=credential_id,
                    revision_id=revision_id,
                    operation_code="fingerprint_rebound",
                    now_utc_ms=completed_at,
                    old_key_version=row["fingerprint_key_version"],
                    new_key_version=account.key_version,
                    old_contract_version=row["account_identity_contract_version"],
                    new_contract_version=contract_version,
                    old_binding_state="confirmed",
                )
            dto = self._dto_from_id(connection, user_id, credential_id, completed_at)
            connection.execute("COMMIT")
            if dto is None:
                raise CredentialOperationError("credential_write_failed", 500)
            return CredentialOperationResult("token_rotated", 200, dto)
        except CredentialOperationError:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        except (sqlite3.Error, ValueError, TokenCipherError) as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise CredentialOperationError("credential_rotation_write_failed", 500) from exc
        finally:
            connection.close()

    def set_enabled(
        self,
        user_id: str,
        credential_id: str,
        expected_credential_version: int,
        enabled: bool,
        now_utc_ms: int,
        *,
        label: str | None = None,
    ) -> CredentialOperationResult:
        self._validate_user_id(user_id)
        if type(enabled) is not bool:
            raise CredentialOperationError("invalid_credential_enabled", 400)
        clean_label = None if label is None else self._validate_label(label)
        now = self._now(now_utc_ms)
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT credential.*, revision.revision_id
                   FROM credentials AS credential
                   JOIN credential_token_revisions AS revision
                     ON revision.user_id=credential.user_id
                    AND revision.credential_id=credential.credential_id
                    AND revision.revision_id=credential.current_token_revision_id
                   WHERE credential.user_id=? AND credential.credential_id=?
                     AND credential.deleted_at_utc_ms IS NULL""",
                (user_id, credential_id),
            ).fetchone()
            if row is None:
                raise CredentialOperationError("credential_not_found", 404)
            if (
                isinstance(expected_credential_version, bool)
                or not isinstance(expected_credential_version, int)
                or row["credential_version"] != expected_credential_version
            ):
                raise CredentialOperationError("credential_version_conflict", 409)
            label_changed = clean_label is not None and clean_label != row["label"]
            enabled_changed = bool(row["enabled"]) != enabled
            if label_changed or enabled_changed:
                connection.execute(
                    """UPDATE credentials
                       SET label=?, enabled=?,
                           requires_revalidation=CASE WHEN ?=1 THEN 1 ELSE requires_revalidation END,
                           credential_version=credential_version+1, updated_at_utc_ms=?
                       WHERE user_id=? AND credential_id=? AND credential_version=?
                         AND deleted_at_utc_ms IS NULL""",
                    (
                        clean_label if clean_label is not None else row["label"],
                        1 if enabled else 0,
                        1 if enabled_changed and enabled else 0,
                        now,
                        user_id,
                        credential_id,
                        expected_credential_version,
                    ),
                )
                if enabled_changed:
                    self._audit(
                        connection,
                        user_id=user_id,
                        credential_id=credential_id,
                        revision_id=row["current_token_revision_id"],
                        operation_code="enabled" if enabled else "disabled",
                        now_utc_ms=now,
                        old_binding_state=row["account_binding_state"],
                    )
            dto = self._dto_from_id(connection, user_id, credential_id, now)
            connection.execute("COMMIT")
            return CredentialOperationResult("credential_updated", 200, dto)
        except CredentialOperationError:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise CredentialOperationError("credential_update_failed", 500) from exc
        finally:
            connection.close()

    def soft_delete(
        self,
        user_id: str,
        credential_id: str,
        expected_credential_version: int,
        now_utc_ms: int,
    ) -> CredentialOperationResult:
        self._validate_user_id(user_id)
        now = self._now(now_utc_ms)
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT * FROM credentials
                   WHERE user_id=? AND credential_id=? AND deleted_at_utc_ms IS NULL""",
                (user_id, credential_id),
            ).fetchone()
            if row is None:
                raise CredentialOperationError("credential_not_found", 404)
            if (
                isinstance(expected_credential_version, bool)
                or not isinstance(expected_credential_version, int)
                or row["credential_version"] != expected_credential_version
            ):
                raise CredentialOperationError("credential_version_conflict", 409)
            connection.execute(
                """UPDATE credential_token_revisions
                   SET secret_material_active=0, ciphertext=NULL, nonce=NULL, tag=NULL,
                       ciphertext_cleared_at_utc_ms=?
                   WHERE user_id=? AND credential_id=? AND secret_material_active=1""",
                (now, user_id, credential_id),
            )
            self._audit(
                connection,
                user_id=user_id,
                credential_id=credential_id,
                revision_id=row["current_token_revision_id"],
                operation_code="ciphertext_cleared",
                now_utc_ms=now,
            )
            self._audit(
                connection,
                user_id=user_id,
                credential_id=credential_id,
                revision_id=None,
                operation_code="soft_deleted",
                now_utc_ms=now,
                old_key_version=row["fingerprint_key_version"],
                old_contract_version=row["account_identity_contract_version"],
                old_binding_state=row["account_binding_state"],
            )
            connection.execute(
                """UPDATE credentials
                   SET enabled=0, deleted_at_utc_ms=?, account_binding_state='unresolved',
                       upstream_account_fingerprint=NULL, fingerprint_key_version=NULL,
                       account_identity_contract_version=NULL,
                       account_fingerprint_cleared_at_utc_ms=?, requires_revalidation=1,
                       credential_version=credential_version+1, updated_at_utc_ms=?
                   WHERE user_id=? AND credential_id=? AND credential_version=?
                     AND deleted_at_utc_ms IS NULL""",
                (now, now, now, user_id, credential_id, expected_credential_version),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise CredentialOperationError("credential_version_conflict", 409)
            connection.execute("COMMIT")
            return CredentialOperationResult("credential_deleted", 200, deleted=True)
        except CredentialOperationError:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise CredentialOperationError("credential_delete_failed", 500) from exc
        finally:
            connection.close()
