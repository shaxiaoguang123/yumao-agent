from __future__ import annotations

import argparse
import getpass
import time
import unicodedata
import uuid
from pathlib import Path

from backend.auth.invitations import normalize_username
from backend.auth.passwords import hash_password
from backend.auth.types import UserSummary
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
    parser = argparse.ArgumentParser(description="Identity foundation administration tools")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_admin = subparsers.add_parser("create-admin", help="create the first administrator")
    create_admin.add_argument("--username", required=True)
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
    return 2
