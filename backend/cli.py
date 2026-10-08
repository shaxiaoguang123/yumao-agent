from __future__ import annotations

import argparse
import getpass
import sys
import time
import unicodedata
import uuid
from pathlib import Path

from backend.auth.invitations import normalize_username
from backend.auth.passwords import hash_password
from backend.auth.types import UserSummary
from backend.credentials.key_dependencies import CredentialKeyDependencyError
from backend.credentials.keyring import CredentialKeyring
from backend.credentials.maintenance import (
    CredentialMaintenanceError,
    rewrap_credential_tokens,
)
from backend.db import connect_database, check_schema_ready, CURRENT_SCHEMA_VERSION
from backend.settings import load_settings


def create_first_admin(
    database_path: Path,
    busy_timeout_ms: int,
    username: str,
    password_hash: str,
    now_utc_ms: int,
) -> UserSummary:
    if not isinstance(username, str) or any(
        unicodedata.category(character).startswith("C") for character in username
    ):
        raise ValueError("invalid username")
    normalized_username = normalize_username(username)
    if not 3 <= len(normalized_username) <= 64:
        raise ValueError("invalid username")

    conn = connect_database(database_path, busy_timeout_ms)
    try:
        conn.execute("BEGIN IMMEDIATE")
        exists = conn.execute(
            "SELECT 1 FROM users WHERE role='admin' LIMIT 1"
        ).fetchone()
        if exists is not None:
            raise ValueError("an administrator already exists")
        user_id = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO users
               (user_id, username, normalized_username, password_hash, role, status,
                created_at_utc_ms, updated_at_utc_ms, disabled_at_utc_ms)
               VALUES (?, ?, ?, ?, 'admin', 'active', ?, ?, NULL)""",
            (
                user_id,
                username,
                normalized_username,
                password_hash,
                now_utc_ms,
                now_utc_ms,
            ),
        )
        conn.execute("COMMIT")
        return UserSummary(user_id, username, "admin")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Identity and Credential administration tools")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_admin = subparsers.add_parser("create-admin", help="create the first administrator")
    create_admin.add_argument("--username", required=True)
    rewrap = subparsers.add_parser(
        "rewrap-credential-tokens",
        help="rewrap active Credential Token ciphertext with the active encryption key",
    )
    rewrap.add_argument("--actor-user-id", required=True)
    args = parser.parse_args(argv)

    if args.command == "create-admin":
        password = getpass.getpass("Administrator password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            parser.error("passwords do not match")
        password_hash = hash_password(password)
        settings = load_settings()
        migrations_dir = Path(__file__).resolve().parent / "migrations"
        check_schema_ready(
            settings.database_path,
            settings.sqlite_busy_timeout_ms,
            CURRENT_SCHEMA_VERSION,
            migrations_dir,
        )
        user = create_first_admin(
            settings.database_path,
            settings.sqlite_busy_timeout_ms,
            args.username,
            password_hash,
            time.time_ns() // 1_000_000,
        )
        print(f"Created administrator: {user.username}")
        return 0
    if args.command == "rewrap-credential-tokens":
        settings = load_settings()
        migrations_dir = Path(__file__).resolve().parent / "migrations"
        check_schema_ready(
            settings.database_path,
            settings.sqlite_busy_timeout_ms,
            CURRENT_SCHEMA_VERSION,
            migrations_dir,
        )
        encryption_keyring = CredentialKeyring(
            settings.credential_encryption_keys,
            settings.credential_encryption_active_key_id,
        )
        fingerprint_keyring = CredentialKeyring(
            settings.upstream_fingerprint_keys,
            settings.upstream_fingerprint_active_key_id,
        )
        try:
            result = rewrap_credential_tokens(
                settings.database_path,
                settings.sqlite_busy_timeout_ms,
                encryption_keyring=encryption_keyring,
                fingerprint_keyring=fingerprint_keyring,
                actor_user_id=args.actor_user_id,
                now_utc_ms=time.time_ns() // 1_000_000,
            )
        except CredentialMaintenanceError as exc:
            print(f"Credential Token rewrap failed: {exc.code}", file=sys.stderr)
            return 1
        except CredentialKeyDependencyError:
            print("Credential Token rewrap failed: credential_key_dependency_missing", file=sys.stderr)
            return 1
        print(
            f"Rewrapped {result.rewrapped_count} Credential Token envelope(s); "
            f"{result.unchanged_count} already used the active key."
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
