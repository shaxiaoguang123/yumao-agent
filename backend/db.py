from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Mapping


CURRENT_SCHEMA_VERSION = 1
_MIGRATION_NAME_RE = re.compile(r"\A(?P<version>[0-9]{4})_[a-z0-9_]+\.sql\Z")

_REQUIRED_COLUMNS: Mapping[str, frozenset[str]] = {
    "schema_migrations": frozenset({"version", "filename", "checksum", "applied_at_utc_ms"}),
    "users": frozenset({
        "user_id", "username", "normalized_username", "password_hash", "role", "status",
        "created_at_utc_ms", "updated_at_utc_ms", "disabled_at_utc_ms",
    }),
    "sessions": frozenset({
        "session_id_hash", "user_id", "created_at_utc_ms", "expires_at_utc_ms",
        "revoked_at_utc_ms", "csrf_scheme_version",
    }),
    "invitations": frozenset({
        "invitation_code_hash", "created_by_user_id", "created_at_utc_ms",
        "expires_at_utc_ms", "redeemed_at_utc_ms", "revoked_at_utc_ms",
    }),
    "auth_attempts": frozenset({
        "attempt_id", "event_type", "bucket_type", "bucket_key", "attempted_at_utc_ms",
    }),
}


class SchemaNotReadyError(RuntimeError):
    """The database is not compatible with the running application."""


class MigrationHistoryMismatch(SchemaNotReadyError):
    """An applied migration no longer matches the repository history."""


def connect_database(database_path: Path, busy_timeout_ms: int) -> sqlite3.Connection:
    if busy_timeout_ms <= 0:
        raise ValueError("busy_timeout_ms must be positive")
    path = Path(database_path)
    connection = sqlite3.connect(
        str(path),
        timeout=busy_timeout_ms / 1000,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    return connection


def _load_migration_manifest(migrations_dir: Path | None = None) -> dict[int, tuple[str, bytes, str]]:
    directory = (
        Path(migrations_dir)
        if migrations_dir is not None
        else Path(__file__).resolve().parent / "migrations"
    )
    if not directory.is_dir():
        raise MigrationHistoryMismatch("migration directory is missing")

    manifest: dict[int, tuple[str, bytes, str]] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix != ".sql":
            continue
        match = _MIGRATION_NAME_RE.fullmatch(path.name)
        if match is None:
            raise MigrationHistoryMismatch("migration filename is invalid")
        version = int(match.group("version"))
        if version in manifest:
            raise MigrationHistoryMismatch("migration versions are duplicated")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise MigrationHistoryMismatch("migration file cannot be read") from exc
        manifest[version] = (path.name, raw, hashlib.sha256(raw).hexdigest())

    versions = sorted(manifest)
    if versions and versions != list(range(1, versions[-1] + 1)):
        raise MigrationHistoryMismatch("migration versions are not contiguous")
    return manifest


def _column_names(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _has_unique_single_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> bool:
    for index in connection.execute(f"PRAGMA index_list({table_name})").fetchall():
        if not index["unique"]:
            continue
        indexed_columns = tuple(
            row["name"]
            for row in connection.execute(f"PRAGMA index_info({index['name']})").fetchall()
        )
        if indexed_columns == (column_name,):
            return True
    return False


def _has_foreign_key(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    parent_table: str,
    parent_column: str,
) -> bool:
    return any(
        row["from"] == column_name
        and row["table"] == parent_table
        and row["to"] == parent_column
        for row in connection.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
    )


def _validate_schema_contract(connection: sqlite3.Connection) -> None:
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for table_name, required_columns in _REQUIRED_COLUMNS.items():
        if table_name not in tables:
            raise SchemaNotReadyError(f"required table is missing: {table_name}")
        missing = required_columns - _column_names(connection, table_name)
        if missing:
            raise SchemaNotReadyError(f"required columns are missing from {table_name}")

    unique_columns = (
        ("users", "normalized_username"),
        ("sessions", "session_id_hash"),
        ("invitations", "invitation_code_hash"),
    )
    for table_name, column_name in unique_columns:
        if not _has_unique_single_column(connection, table_name, column_name):
            raise SchemaNotReadyError(f"required uniqueness constraint is missing from {table_name}")

    foreign_keys = (
        ("sessions", "user_id", "users", "user_id"),
        ("invitations", "created_by_user_id", "users", "user_id"),
    )
    for table_name, column_name, parent_table, parent_column in foreign_keys:
        if not _has_foreign_key(connection, table_name, column_name, parent_table, parent_column):
            raise SchemaNotReadyError(f"required foreign key is missing from {table_name}")


def _verify_applied_checksums(
    rows: list[sqlite3.Row],
    manifest: dict[int, tuple[str, bytes, str]],
) -> None:
    for row in rows:
        version = row["version"]
        expected = manifest.get(version)
        if expected is None:
            raise MigrationHistoryMismatch("an applied migration file is missing")
        filename, _raw, checksum = expected
        if row["filename"] != filename or row["checksum"] != checksum:
            raise MigrationHistoryMismatch(
                f"applied migration {version:04d} does not match the repository checksum"
            )


def check_schema_ready(
    database_path: Path,
    busy_timeout_ms: int,
    required_version: int,
    migrations_dir: Path | None = None,
) -> None:
    database_path = Path(database_path)
    if not database_path.is_file():
        raise SchemaNotReadyError("database file is missing; run python -m backend.migrate")
    if required_version < 1:
        raise ValueError("required_version must be positive")

    manifest = _load_migration_manifest(migrations_dir)
    connection = connect_database(database_path, busy_timeout_ms)
    try:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "schema_migrations" not in tables:
            raise SchemaNotReadyError("schema_migrations is missing; run python -m backend.migrate")

        missing_metadata_columns = (
            _REQUIRED_COLUMNS["schema_migrations"] - _column_names(connection, "schema_migrations")
        )
        if missing_metadata_columns:
            raise SchemaNotReadyError("schema_migrations has an incompatible structure")

        rows = connection.execute(
            "SELECT version, filename, checksum, applied_at_utc_ms "
            "FROM schema_migrations ORDER BY version"
        ).fetchall()
        versions = [row["version"] for row in rows]
        current_version = versions[-1] if versions else 0
        if current_version < required_version:
            raise SchemaNotReadyError(
                f"database schema is at version {current_version}; run python -m backend.migrate"
            )
        if current_version > required_version:
            raise SchemaNotReadyError("database schema is newer than this application supports")
        if versions != list(range(1, current_version + 1)):
            raise SchemaNotReadyError("schema migration history is not contiguous")

        _verify_applied_checksums(rows, manifest)
        _validate_schema_contract(connection)
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise SchemaNotReadyError("database contains foreign-key violations")
    except SchemaNotReadyError:
        raise
    except sqlite3.Error as exc:
        raise SchemaNotReadyError("database schema is unreadable or incompatible") from exc
    finally:
        connection.close()
