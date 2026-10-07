from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path

from backend.db import (
    MigrationHistoryMismatch,
    _load_migration_manifest,
    connect_database,
)
from backend.settings import load_settings


def _only_sql_comments_or_whitespace(source: str) -> bool:
    index = 0
    length = len(source)
    while index < length:
        if source[index].isspace():
            index += 1
            continue
        if source.startswith("--", index):
            newline = source.find("\n", index + 2)
            if newline < 0:
                return True
            index = newline + 1
            continue
        if source.startswith("/*", index):
            closing = source.find("*/", index + 2)
            if closing < 0:
                return False
            index = closing + 2
            continue
        return False
    return True


def _migration_statements(script: str):
    buffer: list[str] = []
    for character in script:
        buffer.append(character)
        if character != ";":
            continue
        candidate = "".join(buffer)
        if sqlite3.complete_statement(candidate):
            statement = candidate.strip()
            if statement and not _only_sql_comments_or_whitespace(statement):
                yield statement
            buffer.clear()

    remainder = "".join(buffer)
    if _only_sql_comments_or_whitespace(remainder):
        return
    if not sqlite3.complete_statement(remainder):
        raise sqlite3.OperationalError("migration contains an unterminated SQL statement")
    yield remainder.strip()


def _migration_files(migrations_dir: Path | None):
    manifest = _load_migration_manifest(migrations_dir)
    migrations = []
    for version, (filename, raw, checksum) in sorted(manifest.items()):
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MigrationHistoryMismatch("migration file must be UTF-8") from exc
        migrations.append((version, filename, checksum, source))
    if not migrations:
        raise MigrationHistoryMismatch("no versioned migration files are available")
    return migrations


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _validate_existing_history(
    connection: sqlite3.Connection,
    migrations_dir: Path | None,
    migrations: list[tuple[int, str, str, str]],
) -> set[int]:
    tables = _table_names(connection)
    if "schema_migrations" not in tables:
        existing_user_tables = tables - {"sqlite_sequence"}
        if existing_user_tables:
            raise MigrationHistoryMismatch(
                "non-empty database has no schema_migrations history"
            )
        return set()

    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(schema_migrations)").fetchall()
    }
    required = {"version", "filename", "checksum", "applied_at_utc_ms"}
    if not required <= columns:
        raise MigrationHistoryMismatch("schema_migrations has an incompatible structure")

    rows = connection.execute(
        "SELECT version, filename, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    versions = [row["version"] for row in rows]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationHistoryMismatch("applied migration history is not contiguous")

    manifest = _load_migration_manifest(migrations_dir)
    for row in rows:
        expected = manifest.get(row["version"])
        if expected is None:
            raise MigrationHistoryMismatch("an applied migration file is missing")
        filename, _raw, checksum = expected
        if row["filename"] != filename or row["checksum"] != checksum:
            raise MigrationHistoryMismatch(
                f"applied migration {row['version']:04d} does not match the repository checksum"
            )

    if not rows:
        existing_domain_tables = tables - {"schema_migrations", "sqlite_sequence"}
        if existing_domain_tables:
            raise MigrationHistoryMismatch(
                "database has schema objects but no applied migration history"
            )
    return set(versions)


def _bootstrap_metadata(connection: sqlite3.Connection) -> None:
    if "schema_migrations" in _table_names(connection):
        return
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            """CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY CHECK (version > 0),
                filename TEXT NOT NULL UNIQUE,
                checksum TEXT NOT NULL CHECK (length(checksum) = 64),
                applied_at_utc_ms INTEGER NOT NULL
            )"""
        )
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def _deny_transaction_control(action, _arg1, _arg2, _database, _trigger):
    denied_actions = {sqlite3.SQLITE_TRANSACTION}
    savepoint_action = getattr(sqlite3, "SQLITE_SAVEPOINT", None)
    if savepoint_action is not None:
        denied_actions.add(savepoint_action)
    return sqlite3.SQLITE_DENY if action in denied_actions else sqlite3.SQLITE_OK


def migrate_database(
    database_path: Path,
    busy_timeout_ms: int,
    migrations_dir: Path | None = None,
) -> None:
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    migrations = _migration_files(migrations_dir)

    connection = connect_database(database_path, busy_timeout_ms)
    try:
        applied_versions = _validate_existing_history(connection, migrations_dir, migrations)

        # History is verified before this persistent database setting changes.
        journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(journal_mode).lower() != "wal":
            raise sqlite3.OperationalError("SQLite WAL mode could not be enabled")

        _bootstrap_metadata(connection)
        for version, filename, checksum, source in migrations:
            if version in applied_versions:
                continue
            if version != len(applied_versions) + 1:
                raise MigrationHistoryMismatch("pending migration versions are not contiguous")

            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.set_authorizer(_deny_transaction_control)
                for statement in _migration_statements(source):
                    connection.execute(statement)
                connection.set_authorizer(None)
                connection.execute(
                    """INSERT INTO schema_migrations
                       (version, filename, checksum, applied_at_utc_ms)
                       VALUES (?, ?, ?, ?)""",
                    (version, filename, checksum, time.time_ns() // 1_000_000),
                )
                connection.execute("COMMIT")
                applied_versions.add(version)
            except BaseException:
                connection.set_authorizer(None)
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply explicit SQLite schema migrations.")
    parser.parse_args()
    settings = load_settings()
    migrate_database(settings.database_path, settings.sqlite_busy_timeout_ms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
