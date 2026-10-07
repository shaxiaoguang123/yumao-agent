from __future__ import annotations

import hashlib
import importlib
import importlib.util
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path


BUSY_TIMEOUT_MS = 1379
REPO_MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _module(name: str):
    if importlib.util.find_spec(name) is None:
        raise AssertionError(f"{name} must provide the V1 database API")
    return importlib.import_module(name)


def _write_migration(directory: Path, filename: str, sql: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(sql, encoding="utf-8")
    return path


def _copy_identity_migration(directory: Path) -> Path:
    source = REPO_MIGRATIONS / "0001_identity.sql"
    if not source.is_file():
        raise AssertionError("the versioned identity migration must exist")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / source.name
    shutil.copyfile(source, destination)
    return destination


def _insert_user(conn: sqlite3.Connection, user_id: str = "user-a") -> None:
    conn.execute(
        """INSERT INTO users
           (user_id, username, normalized_username, password_hash, role, status,
            created_at_utc_ms, updated_at_utc_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, "Alice", "alice", "synthetic-hash", "user", "active", 1, 1),
    )


def _snapshot(conn: sqlite3.Connection):
    tables = tuple(
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    )
    versions = tuple(
        tuple(row) for row in conn.execute(
            "SELECT version, filename, checksum, applied_at_utc_ms "
            "FROM schema_migrations ORDER BY version"
        )
    ) if "schema_migrations" in tables else ()
    users = tuple(
        tuple(row) for row in conn.execute(
            "SELECT user_id, username, normalized_username FROM users ORDER BY user_id"
        )
    ) if "users" in tables else ()
    return tables, versions, users


class SQLiteConnectionTests(unittest.TestCase):
    def test_each_connection_sets_row_factory_foreign_keys_and_busy_timeout(self) -> None:
        connect_database = _module("backend.db").connect_database
        with tempfile.TemporaryDirectory() as temp_dir:
            conn = connect_database(Path(temp_dir) / "connection.sqlite3", BUSY_TIMEOUT_MS)
            try:
                self.assertIs(conn.row_factory, sqlite3.Row)
                self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], BUSY_TIMEOUT_MS)
            finally:
                conn.close()


class MigrationTests(unittest.TestCase):
    def test_migration_records_checksum_and_is_repeatable(self) -> None:
        db = _module("backend.db")
        migrate_database = _module("backend.migrate").migrate_database
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            migrations = root / "migrations"
            sql = "CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT);\n"
            migration_path = _write_migration(migrations, "0001_sample.sql", sql)
            database_path = root / "sample.sqlite3"

            migrate_database(database_path, BUSY_TIMEOUT_MS, migrations)
            conn = db.connect_database(database_path, BUSY_TIMEOUT_MS)
            try:
                row = conn.execute(
                    "SELECT version, filename, checksum, applied_at_utc_ms FROM schema_migrations"
                ).fetchone()
                self.assertEqual(row["version"], 1)
                self.assertEqual(row["filename"], migration_path.name)
                self.assertEqual(row["checksum"], hashlib.sha256(sql.encode("utf-8")).hexdigest())
                self.assertGreater(row["applied_at_utc_ms"], 0)
                self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                conn.execute("INSERT INTO sample (value) VALUES (?)", ("keep-me",))
                conn.commit()
            finally:
                conn.close()

            migrate_database(database_path, BUSY_TIMEOUT_MS, migrations)
            conn = db.connect_database(database_path, BUSY_TIMEOUT_MS)
            try:
                self.assertEqual(conn.execute("SELECT value FROM sample").fetchone()[0], "keep-me")
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 1)
            finally:
                conn.close()

    def test_second_migration_run_preserves_inserted_user_rows(self) -> None:
        db = _module("backend.db")
        migrate_database = _module("backend.migrate").migrate_database
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            migrations = root / "migrations"
            sql = (
                "CREATE TABLE users (user_id TEXT PRIMARY KEY, username TEXT NOT NULL, "
                "normalized_username TEXT NOT NULL UNIQUE);\n"
            )
            _write_migration(migrations, "0001_users.sql", sql)
            database_path = root / "users.sqlite3"
            migrate_database(database_path, BUSY_TIMEOUT_MS, migrations)

            conn = db.connect_database(database_path, BUSY_TIMEOUT_MS)
            try:
                conn.execute(
                    "INSERT INTO users (user_id, username, normalized_username) VALUES (?, ?, ?)",
                    ("synthetic-user", "Display", "display"),
                )
                conn.commit()
            finally:
                conn.close()

            migrate_database(database_path, BUSY_TIMEOUT_MS, migrations)
            conn = db.connect_database(database_path, BUSY_TIMEOUT_MS)
            try:
                row = conn.execute(
                    "SELECT username FROM users WHERE user_id=?", ("synthetic-user",)
                ).fetchone()
                self.assertEqual(row["username"], "Display")
            finally:
                conn.close()

    def test_failed_migration_rolls_back_schema_and_version_and_preserves_old_data(self) -> None:
        db = _module("backend.db")
        migrate_database = _module("backend.migrate").migrate_database
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            migrations = root / "migrations"
            _write_migration(
                migrations,
                "0001_users.sql",
                "CREATE TABLE users (user_id TEXT PRIMARY KEY, username TEXT NOT NULL);\n",
            )
            database_path = root / "rollback.sqlite3"
            migrate_database(database_path, BUSY_TIMEOUT_MS, migrations)

            conn = db.connect_database(database_path, BUSY_TIMEOUT_MS)
            try:
                conn.execute(
                    "INSERT INTO users (user_id, username) VALUES (?, ?)",
                    ("existing-user", "Existing"),
                )
                conn.commit()
            finally:
                conn.close()

            _write_migration(
                migrations,
                "0002_partial.sql",
                "CREATE TABLE should_rollback (id INTEGER PRIMARY KEY);\n"
                "INSERT INTO table_that_does_not_exist VALUES (1);\n",
            )
            with self.assertRaises(sqlite3.DatabaseError):
                migrate_database(database_path, BUSY_TIMEOUT_MS, migrations)

            conn = db.connect_database(database_path, BUSY_TIMEOUT_MS)
            try:
                table_names = {
                    row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertNotIn("should_rollback", table_names)
                self.assertEqual(
                    [tuple(row) for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()],
                    [(1,)],
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT username FROM users WHERE user_id=?", ("existing-user",)
                    ).fetchone()[0],
                    "Existing",
                )
            finally:
                conn.close()

    def test_statement_parser_handles_semicolons_in_literals_comments_and_triggers(self) -> None:
        db = _module("backend.db")
        migrate_database = _module("backend.migrate").migrate_database
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            migrations = root / "migrations"
            sql = """CREATE TABLE literal_values (value TEXT);
INSERT INTO literal_values VALUES ('left;right'); -- inline comment ; remains a comment
-- standalone comment ; must not split a statement
CREATE TABLE source_values (value TEXT);
CREATE TABLE trigger_events (value TEXT);
CREATE TRIGGER source_insert AFTER INSERT ON source_values
BEGIN
  INSERT INTO trigger_events VALUES ('trigger;first');
  INSERT INTO trigger_events VALUES ('trigger second');
END;
"""
            _write_migration(migrations, "0001_parser.sql", sql)
            database_path = root / "parser.sqlite3"
            migrate_database(database_path, BUSY_TIMEOUT_MS, migrations)

            conn = db.connect_database(database_path, BUSY_TIMEOUT_MS)
            try:
                self.assertEqual(
                    conn.execute("SELECT value FROM literal_values").fetchone()[0],
                    "left;right",
                )
                conn.execute("INSERT INTO source_values VALUES (?)", ("source",))
                conn.commit()
                self.assertEqual(
                    [
                        row[0] for row in conn.execute(
                            "SELECT value FROM trigger_events ORDER BY rowid"
                        )
                    ],
                    ["trigger;first", "trigger second"],
                )
            finally:
                conn.close()

    def test_migration_rejects_top_level_transaction_control_but_allows_trigger_begin_end(self) -> None:
        db = _module("backend.db")
        migrate_database = _module("backend.migrate").migrate_database
        invalid_statements = (
            "BEGIN IMMEDIATE;",
            "COMMIT;",
            "ROLLBACK;",
            "SAVEPOINT nested;",
        )
        for index, transaction_statement in enumerate(invalid_statements):
            with self.subTest(statement=transaction_statement), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                migrations = root / "migrations"
                _write_migration(
                    migrations,
                    "0001_trigger.sql",
                    "CREATE TABLE source (value TEXT);\n"
                    "CREATE TABLE events (value TEXT);\n"
                    "CREATE TRIGGER source_insert AFTER INSERT ON source "
                    "BEGIN INSERT INTO events VALUES (new.value); END;\n",
                )
                database_path = root / f"control-{index}.sqlite3"
                migrate_database(database_path, BUSY_TIMEOUT_MS, migrations)
                _write_migration(migrations, "0002_control.sql", transaction_statement + "\n")

                with self.assertRaises(sqlite3.DatabaseError):
                    migrate_database(database_path, BUSY_TIMEOUT_MS, migrations)

                _write_migration(
                    migrations,
                    "0002_control.sql",
                    "CREATE TABLE recovered_after_rollback (id INTEGER PRIMARY KEY);\n",
                )
                migrate_database(database_path, BUSY_TIMEOUT_MS, migrations)
                conn = db.connect_database(database_path, BUSY_TIMEOUT_MS)
                try:
                    self.assertEqual(
                        [tuple(row) for row in conn.execute(
                            "SELECT version FROM schema_migrations ORDER BY version"
                        ).fetchall()],
                        [(1,), (2,)],
                    )
                finally:
                    conn.close()


class SchemaReadinessTests(unittest.TestCase):
    def _ready_database(self, root: Path) -> tuple[Path, Path]:
        db = _module("backend.db")
        migrate_database = _module("backend.migrate").migrate_database
        migrations = root / "migrations"
        _copy_identity_migration(migrations)
        database_path = root / "identity.sqlite3"
        migrate_database(database_path, BUSY_TIMEOUT_MS, migrations)
        return database_path, migrations

    def test_missing_database_fails_without_creating_it(self) -> None:
        db = _module("backend.db")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "missing.sqlite3"
            with self.assertRaises(db.SchemaNotReadyError):
                db.check_schema_ready(path, BUSY_TIMEOUT_MS, 1, REPO_MIGRATIONS)
            self.assertFalse(path.exists())

    def test_missing_schema_migrations_fails(self) -> None:
        db = _module("backend.db")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "empty.sqlite3"
            conn = db.connect_database(path, BUSY_TIMEOUT_MS)
            conn.close()
            with self.assertRaises(db.SchemaNotReadyError):
                db.check_schema_ready(path, BUSY_TIMEOUT_MS, 1, REPO_MIGRATIONS)

    def test_lower_and_higher_schema_versions_fail_closed(self) -> None:
        db = _module("backend.db")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database_path, migrations = self._ready_database(root)
            with self.assertRaises(db.SchemaNotReadyError):
                db.check_schema_ready(database_path, BUSY_TIMEOUT_MS, 2, migrations)

            conn = db.connect_database(database_path, BUSY_TIMEOUT_MS)
            try:
                conn.execute("UPDATE schema_migrations SET version=2 WHERE version=1")
                conn.commit()
            finally:
                conn.close()
            with self.assertRaises(db.SchemaNotReadyError):
                db.check_schema_ready(database_path, BUSY_TIMEOUT_MS, 1, migrations)

    def test_incompatible_identity_columns_fail_closed(self) -> None:
        db = _module("backend.db")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database_path, migrations = self._ready_database(root)
            conn = db.connect_database(database_path, BUSY_TIMEOUT_MS)
            try:
                conn.execute("DROP TABLE users")
                conn.execute("CREATE TABLE users (user_id TEXT PRIMARY KEY)")
                conn.commit()
            finally:
                conn.close()
            with self.assertRaises(db.SchemaNotReadyError):
                db.check_schema_ready(database_path, BUSY_TIMEOUT_MS, 1, migrations)

    def test_ready_database_matches_schema_and_migration_checksum(self) -> None:
        db = _module("backend.db")
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path, migrations = self._ready_database(Path(temp_dir))
            self.assertIsNone(
                db.check_schema_ready(database_path, BUSY_TIMEOUT_MS, 1, migrations)
            )

    def test_modified_applied_migration_fails_readiness_and_migration_without_changes(self) -> None:
        db = _module("backend.db")
        migrate_database = _module("backend.migrate").migrate_database
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database_path, migrations = self._ready_database(root)
            conn = db.connect_database(database_path, BUSY_TIMEOUT_MS)
            try:
                _insert_user(conn)
                conn.commit()
                before = _snapshot(conn)
            finally:
                conn.close()

            migration = migrations / "0001_identity.sql"
            migration.write_text(migration.read_text(encoding="utf-8") + "\n-- changed after apply\n", encoding="utf-8")
            with self.assertRaises(db.MigrationHistoryMismatch):
                db.check_schema_ready(database_path, BUSY_TIMEOUT_MS, 1, migrations)
            with self.assertRaises(db.MigrationHistoryMismatch):
                migrate_database(database_path, BUSY_TIMEOUT_MS, migrations)

            conn = db.connect_database(database_path, BUSY_TIMEOUT_MS)
            try:
                self.assertEqual(_snapshot(conn), before)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
