from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from backend.credentials.crypto import (
    CredentialTokenCipher,
    EncryptedTokenEnvelope,
    TokenCipherError,
)
from backend.credentials.key_dependencies import (
    CredentialKeyDependencyError,
    check_credential_key_dependencies,
)
from backend.credentials.keyring import CredentialKeyring
from backend.db import connect_database


class CredentialMaintenanceError(RuntimeError):
    """Safe error code for explicit Credential key maintenance."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CredentialRewrapResult:
    rewrapped_count: int
    unchanged_count: int


def rewrap_credential_tokens(
    database_path: Path,
    busy_timeout_ms: int,
    *,
    encryption_keyring: CredentialKeyring,
    fingerprint_keyring: CredentialKeyring,
    actor_user_id: str,
    now_utc_ms: int,
) -> CredentialRewrapResult:
    """Authenticate and rewrap every live Token envelope in one SQLite transaction."""
    if not isinstance(actor_user_id, str) or not actor_user_id:
        raise CredentialMaintenanceError("maintenance_admin_required")
    if isinstance(now_utc_ms, bool) or not isinstance(now_utc_ms, int) or now_utc_ms < 0:
        raise CredentialMaintenanceError("invalid_maintenance_time")
    try:
        check_credential_key_dependencies(
            database_path,
            busy_timeout_ms,
            encryption_keyring=encryption_keyring,
            fingerprint_keyring=fingerprint_keyring,
        )
    except CredentialKeyDependencyError as exc:
        raise CredentialMaintenanceError("credential_key_dependency_missing") from exc

    cipher = CredentialTokenCipher(encryption_keyring)
    connection = connect_database(Path(database_path), busy_timeout_ms)
    rewrapped_count = 0
    unchanged_count = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        actor = connection.execute(
            "SELECT role, status FROM users WHERE user_id=?",
            (actor_user_id,),
        ).fetchone()
        if actor is None or actor["role"] != "admin" or actor["status"] != "active":
            raise CredentialMaintenanceError("maintenance_admin_required")

        revisions = connection.execute(
            """SELECT revision.revision_id, revision.user_id, revision.credential_id,
                      revision.ciphertext, revision.nonce, revision.tag,
                      revision.encryption_key_version
               FROM credential_token_revisions AS revision
               WHERE revision.secret_material_active=1
               ORDER BY revision.user_id, revision.credential_id, revision.revision_number"""
        ).fetchall()
        active_key_id = encryption_keyring.active_key_id
        for row in revisions:
            envelope = EncryptedTokenEnvelope(
                ciphertext=row["ciphertext"],
                nonce=row["nonce"],
                tag=row["tag"],
                key_id=row["encryption_key_version"],
            )
            try:
                plaintext = cipher.decrypt(
                    envelope,
                    user_id=row["user_id"],
                    credential_id=row["credential_id"],
                    revision_id=row["revision_id"],
                    key_id=row["encryption_key_version"],
                )
            except (TokenCipherError, TypeError, ValueError) as exc:
                raise CredentialMaintenanceError("credential_rewrap_failed") from exc

            if row["encryption_key_version"] == active_key_id:
                unchanged_count += 1
                continue

            try:
                new_envelope = cipher.encrypt(
                    plaintext,
                    user_id=row["user_id"],
                    credential_id=row["credential_id"],
                    revision_id=row["revision_id"],
                    key_id=active_key_id,
                )
            except (TokenCipherError, TypeError, ValueError) as exc:
                raise CredentialMaintenanceError("credential_rewrap_failed") from exc
            cursor = connection.execute(
                """UPDATE credential_token_revisions
                   SET ciphertext=?, nonce=?, tag=?, encryption_key_version=?
                   WHERE user_id=? AND credential_id=? AND revision_id=?
                     AND secret_material_active=1 AND encryption_key_version=?""",
                (
                    new_envelope.ciphertext,
                    new_envelope.nonce,
                    new_envelope.tag,
                    new_envelope.key_id,
                    row["user_id"],
                    row["credential_id"],
                    row["revision_id"],
                    row["encryption_key_version"],
                ),
            )
            if cursor.rowcount != 1:
                raise CredentialMaintenanceError("credential_rewrap_stale")
            connection.execute(
                """INSERT INTO credential_lifecycle_audits
                   (user_id, credential_id, revision_id, actor_user_id, operation_code,
                    old_key_version, new_key_version, occurred_at_utc_ms, outcome)
                   VALUES (?, ?, ?, ?, 'key_rewrapped', ?, ?, ?, 'success')""",
                (
                    row["user_id"],
                    row["credential_id"],
                    row["revision_id"],
                    actor_user_id,
                    row["encryption_key_version"],
                    new_envelope.key_id,
                    now_utc_ms,
                ),
            )
            rewrapped_count += 1
        connection.execute("COMMIT")
        return CredentialRewrapResult(rewrapped_count, unchanged_count)
    except CredentialMaintenanceError:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise CredentialMaintenanceError("credential_rewrap_failed") from exc
    finally:
        connection.close()
