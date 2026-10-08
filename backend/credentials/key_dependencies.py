from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.credentials.keyring import CredentialKeyring
from backend.db import connect_database


class CredentialKeyDependencyError(RuntimeError):
    """A configured keyring is missing a key required by live Credential data."""


def check_credential_key_dependencies(
    database_path: Path,
    busy_timeout_ms: int,
    *,
    encryption_keyring: CredentialKeyring,
    fingerprint_keyring: CredentialKeyring,
) -> None:
    """Read-only check that all key versions referenced by live data are configured."""
    if not isinstance(encryption_keyring, CredentialKeyring):
        raise TypeError("encryption_keyring must be a CredentialKeyring")
    if not isinstance(fingerprint_keyring, CredentialKeyring):
        raise TypeError("fingerprint_keyring must be a CredentialKeyring")
    if not Path(database_path).is_file():
        raise CredentialKeyDependencyError(
            "Credential key dependencies cannot be checked because the database is missing"
        )

    connection = connect_database(Path(database_path), busy_timeout_ms)
    try:
        try:
            encryption_dependencies = {
                row["encryption_key_version"]
                for row in connection.execute(
                    """SELECT DISTINCT encryption_key_version
                       FROM credential_token_revisions
                       WHERE secret_material_active=1"""
                ).fetchall()
            }
            current_token_dependencies = {
                row["token_fingerprint_key_version"]
                for row in connection.execute(
                    """SELECT DISTINCT revision.token_fingerprint_key_version
                       FROM credentials AS credential
                       JOIN credential_token_revisions AS revision
                         ON revision.user_id=credential.user_id
                        AND revision.credential_id=credential.credential_id
                        AND revision.revision_id=credential.current_token_revision_id
                       WHERE credential.deleted_at_utc_ms IS NULL"""
                ).fetchall()
            }
            account_dependencies = {
                row["fingerprint_key_version"]
                for row in connection.execute(
                    """SELECT DISTINCT fingerprint_key_version
                       FROM credentials
                       WHERE deleted_at_utc_ms IS NULL
                         AND account_binding_state IN ('confirmed', 'needs_reconfirmation')
                         AND upstream_account_fingerprint IS NOT NULL"""
                ).fetchall()
            }
        except sqlite3.Error as exc:
            raise CredentialKeyDependencyError(
                "Credential key dependencies cannot be read from the current schema"
            ) from exc
    finally:
        connection.close()

    missing_encryption = encryption_dependencies - set(encryption_keyring.keys)
    missing_fingerprint = (current_token_dependencies | account_dependencies) - set(
        fingerprint_keyring.keys
    )
    if missing_encryption or missing_fingerprint:
        raise CredentialKeyDependencyError(
            "configured Credential keyrings are missing keys referenced by live data"
        )
