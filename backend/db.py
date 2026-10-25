from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Mapping


CURRENT_SCHEMA_VERSION = 13
_MIGRATION_NAME_RE = re.compile(r"\A(?P<version>[0-9]{4})_[a-z0-9_]+\.sql\Z")

_REQUIRED_COLUMNS: Mapping[str, frozenset[str]] = {
    "schema_migrations": frozenset({"version", "filename", "checksum", "applied_at_utc_ms"}),
    "booking_plans": frozenset({"plan_id", "user_id", "current_revision_id", "version", "created_at_utc_ms", "updated_at_utc_ms"}),
    "booking_plan_revisions": frozenset({"revision_id", "plan_id", "user_id", "revision_number", "intent_json", "intent_sha256", "created_by_user_id", "created_at_utc_ms"}),
    "ai_models": frozenset({"model_id", "user_id", "name", "base_url", "model", "auth_mode", "api_key_ciphertext", "api_key_nonce", "api_key_tag", "encryption_key_id", "key_revision", "version", "created_at_utc_ms", "updated_at_utc_ms"}),
    "ai_model_preferences": frozenset({"user_id", "selected_model_id", "default_model_id", "updated_at_utc_ms"}),
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
    "credentials": frozenset({
        "credential_id", "user_id", "label", "credential_version", "enabled",
        "deleted_at_utc_ms", "current_token_revision_id", "account_binding_state",
        "upstream_account_fingerprint", "fingerprint_key_version",
        "account_identity_contract_version", "account_fingerprint_cleared_at_utc_ms",
        "last_successful_validation_at_utc_ms", "last_confirmed_validation_state",
        "requires_revalidation", "created_at_utc_ms", "updated_at_utc_ms",
    }),
    "credential_token_revisions": frozenset({
        "revision_id", "user_id", "credential_id", "revision_number",
        "token_fingerprint", "token_fingerprint_key_version", "token_expires_at_utc_ms",
        "initial_account_fingerprint_key_version", "initial_account_identity_contract_version",
        "initial_validation_result", "initial_validation_at_utc_ms", "created_by_user_id",
        "secret_material_active", "ciphertext", "nonce", "tag", "encryption_key_version",
        "ciphertext_cleared_at_utc_ms",
    }),
    "credential_payment_secrets": frozenset({
        "user_id", "credential_id", "secret_revision", "ciphertext", "nonce", "tag",
        "encryption_key_version", "updated_at_utc_ms",
    }),
    "booking_execution_settings": frozenset({
        "user_id", "credential_id", "version", "reconciliation_time",
        "clock_calibration_lead_ms", "start_offset_ms", "booking_node_delay_ms",
        "booking_by_time_delay_ms", "get_user_info_delay_ms", "get_children_delay_ms",
        "get_pay_price_delay_ms", "create_booking_delay_ms",
        "open_platform_pay_order_delay_ms", "payment_verify_delay_ms", "updated_at_utc_ms",
    }),
    "user_booking_execution_settings": frozenset({
        "user_id", "version", "reconciliation_time", "clock_calibration_lead_ms",
        "start_offset_ms", "booking_node_delay_ms", "booking_by_time_delay_ms",
        "get_user_info_delay_ms", "get_pay_price_delay_ms", "create_booking_delay_ms",
        "open_platform_pay_order_delay_ms", "payment_verify_delay_ms",
        "payment_verify_interval_ms", "candidate_interval_ms", "updated_at_utc_ms",
    }),
    "user_email_notification_settings": frozenset({
        "user_id", "version", "enabled", "reminder_time", "last_test_sent_at_utc_ms",
        "updated_at_utc_ms",
    }),
    "booking_email_notification_outbox": frozenset({
        "notification_id", "user_id", "credential_id", "target_date", "kind",
        "queue_revision_id", "queue_version", "scheduled_at_utc_ms", "status",
        "attempt_count", "next_attempt_at_utc_ms", "lease_owner_id",
        "lease_expires_at_utc_ms", "provider_message_id", "safe_error_code",
        "created_at_utc_ms", "updated_at_utc_ms", "sent_at_utc_ms",
    }),
    "booking_execution_runs": frozenset({
        "run_id", "user_id", "credential_id", "target_date", "source_plan_id",
        "source_revision_id", "source_version", "source_sha256", "state", "snapshot_json",
        "reconciliation_json", "clock_offset_ms", "clock_uncertainty_ms",
        "created_at_utc_ms", "updated_at_utc_ms", "started_at_utc_ms", "completed_at_utc_ms",
    }),
    "booking_execution_stages": frozenset({
        "stage_id", "run_id", "round_number", "candidate_index", "stage_key",
        "started_at_utc_ms", "completed_at_utc_ms", "elapsed_ms", "outcome", "safe_code",
    }),
    "planning_conversations": frozenset({
        "conversation_id", "conversation_kind", "user_id", "credential_id", "business_date", "state_json",
        "response_history_json", "created_at_utc_ms", "updated_at_utc_ms", "status", "closed_at_utc_ms", "version",
    }),
    "credential_validation_observations": frozenset({
        "validation_attempt_id", "user_id", "credential_id", "operation_kind",
        "credential_version_snapshot", "current_token_revision_snapshot_id", "token_revision_id",
        "started_at_utc_ms", "completed_at_utc_ms", "attempt_result",
        "account_binding_outcome", "http_status_class", "gate_owner_id", "gate_epoch",
        "apply_state",
    }),
    "credential_lifecycle_audits": frozenset({
        "audit_id", "user_id", "credential_id", "revision_id", "actor_user_id",
        "operation_code", "old_key_version", "new_key_version",
        "old_identity_contract_version", "new_identity_contract_version",
        "old_account_binding_state",
        "occurred_at_utc_ms", "outcome",
    }),
    "upstream_request_gate": frozenset({
        "endpoint_key", "lease_owner_id", "lease_epoch", "lease_expires_at_utc_ms",
        "active_started_at_utc_ms",
        "next_validation_attempt_id", "active_validation_attempt_id", "active_user_id",
        "active_credential_id", "active_operation_kind", "active_credential_version_snapshot",
        "active_token_revision_snapshot_id", "next_allowed_at_utc_ms",
        "upstream_backoff_until_utc_ms",
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


def _has_unique_columns(
    connection: sqlite3.Connection,
    table_name: str,
    column_names: tuple[str, ...],
) -> bool:
    for index in connection.execute(f"PRAGMA index_list({table_name})").fetchall():
        if not index["unique"]:
            continue
        indexed_columns = tuple(
            row["name"]
            for row in connection.execute(f"PRAGMA index_info({index['name']})").fetchall()
        )
        if indexed_columns == column_names:
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


def _has_composite_foreign_key(
    connection: sqlite3.Connection,
    table_name: str,
    parent_table: str,
    column_map: tuple[tuple[str, str], ...],
) -> bool:
    rows = connection.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
    grouped: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        if row["table"] == parent_table:
            grouped.setdefault(row["id"], []).append(row)
    wanted = set(column_map)
    return any(
        {(row["from"], row["to"]) for row in group} == wanted
        and len(group) == len(column_map)
        for group in grouped.values()
    )


def _validate_schema_contract(connection: sqlite3.Connection, schema_version: int) -> None:
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    required_contract = {
        name: columns
        for name, columns in _REQUIRED_COLUMNS.items()
        if (schema_version >= 6 or name not in {"ai_models", "ai_model_preferences"})
        and (schema_version >= 5 or name not in {"booking_plans", "booking_plan_revisions"})
        and (schema_version >= 7 or name != "credential_payment_secrets")
        and (schema_version >= 8 or name not in {
            "booking_execution_settings", "booking_execution_runs", "booking_execution_stages",
        })
        and (schema_version >= 12 or name != "user_booking_execution_settings")
        and (schema_version >= 13 or name not in {
            "user_email_notification_settings", "booking_email_notification_outbox",
        })
        and (schema_version >= 9 or name != "planning_conversations")
        and (schema_version >= 2 or name not in {
            "credentials",
            "credential_token_revisions",
            "credential_validation_observations",
            "credential_lifecycle_audits",
            "upstream_request_gate",
        })
    }
    if schema_version == 2:
        required_contract["upstream_request_gate"] = (
            _REQUIRED_COLUMNS["upstream_request_gate"] - {"active_started_at_utc_ms"}
        )
    if 2 <= schema_version < 4:
        required_contract["credential_lifecycle_audits"] = (
            _REQUIRED_COLUMNS["credential_lifecycle_audits"] - {"old_account_binding_state"}
        )
    if 9 <= schema_version < 10:
        required_contract["planning_conversations"] = (
            _REQUIRED_COLUMNS["planning_conversations"] - {"status", "closed_at_utc_ms", "version"}
        )
    elif 10 <= schema_version < 11:
        required_contract["planning_conversations"] = (
            _REQUIRED_COLUMNS["planning_conversations"] - {"version"}
        )
    for table_name, required_columns in required_contract.items():
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

    if schema_version >= 2:
        required_composite_uniques = (
            ("credentials", ("user_id", "credential_id")),
            ("credential_token_revisions", ("user_id", "credential_id", "revision_id")),
            ("credential_token_revisions", ("user_id", "credential_id", "revision_number")),
        )
        if schema_version >= 7:
            required_composite_uniques += (("credential_payment_secrets", ("user_id", "credential_id")),)
        if schema_version >= 8:
            required_composite_uniques += (
                ("booking_execution_settings", ("user_id", "credential_id")),
                ("booking_execution_runs", ("user_id", "credential_id", "target_date", "source_revision_id")),
            )
        for table_name, columns in required_composite_uniques:
            if not _has_unique_columns(connection, table_name, columns):
                raise SchemaNotReadyError(f"required composite uniqueness is missing from {table_name}")

    foreign_keys = (
        ("sessions", "user_id", "users", "user_id"),
        ("invitations", "created_by_user_id", "users", "user_id"),
    )
    if schema_version >= 2:
        foreign_keys += (
            ("credentials", "user_id", "users", "user_id"),
            ("credential_token_revisions", "created_by_user_id", "users", "user_id"),
            ("credential_lifecycle_audits", "actor_user_id", "users", "user_id"),
        )
    if schema_version >= 9:
        foreign_keys += (("planning_conversations", "user_id", "users", "user_id"),)
    for table_name, column_name, parent_table, parent_column in foreign_keys:
        if not _has_foreign_key(connection, table_name, column_name, parent_table, parent_column):
            raise SchemaNotReadyError(f"required foreign key is missing from {table_name}")

    if schema_version >= 2:
        composite_foreign_keys = (
            (
                "credentials",
                "credential_token_revisions",
                (("user_id", "user_id"), ("credential_id", "credential_id"),
                 ("current_token_revision_id", "revision_id")),
            ),
            (
                "credential_token_revisions",
                "credentials",
                (("user_id", "user_id"), ("credential_id", "credential_id")),
            ),
            (
                "credential_validation_observations",
                "credentials",
                (("user_id", "user_id"), ("credential_id", "credential_id")),
            ),
            (
                "credential_validation_observations",
                "credential_token_revisions",
                (("user_id", "user_id"), ("credential_id", "credential_id"),
                 ("token_revision_id", "revision_id")),
            ),
            (
                "credential_lifecycle_audits",
                "credentials",
                (("user_id", "user_id"), ("credential_id", "credential_id")),
            ),
            (
                "credential_lifecycle_audits",
                "credential_token_revisions",
                (("user_id", "user_id"), ("credential_id", "credential_id"),
                 ("revision_id", "revision_id")),
            ),
            (
                "upstream_request_gate",
                "credentials",
                (("active_user_id", "user_id"), ("active_credential_id", "credential_id")),
            ),
        )
        if schema_version >= 7:
            composite_foreign_keys += (
                (
                    "credential_payment_secrets",
                    "credentials",
                    (("user_id", "user_id"), ("credential_id", "credential_id")),
                ),
            )
        if schema_version >= 8:
            composite_foreign_keys += (
                (
                    "booking_execution_settings",
                    "credentials",
                    (("user_id", "user_id"), ("credential_id", "credential_id")),
                ),
                (
                    "booking_execution_runs",
                    "credentials",
                    (("user_id", "user_id"), ("credential_id", "credential_id")),
                ),
                (
                    "booking_execution_runs",
                    "booking_plan_revisions",
                    (("source_revision_id", "revision_id"), ("source_plan_id", "plan_id"),
                     ("user_id", "user_id"), ("source_version", "revision_number")),
                ),
            )
        if schema_version >= 9:
            composite_foreign_keys += (
                (
                    "planning_conversations",
                    "credentials",
                    (("user_id", "user_id"), ("credential_id", "credential_id")),
                ),
            )
        for table_name, parent_table, column_map in composite_foreign_keys:
            if not _has_composite_foreign_key(connection, table_name, parent_table, column_map):
                raise SchemaNotReadyError(f"required tenant-bound foreign key is missing from {table_name}")
    if schema_version >= 2:
        gate_count = connection.execute(
            "SELECT COUNT(*) FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
        ).fetchone()[0]
        if gate_count != 1:
            raise SchemaNotReadyError("the shared getUserInfo request-gate row is missing or duplicated")

    if schema_version >= 5:
        for table, columns in (
            ("booking_plans", ("plan_id", "user_id")),
            ("booking_plan_revisions", ("revision_id", "plan_id", "user_id", "revision_number")),
            ("booking_plan_revisions", ("plan_id", "user_id", "revision_number")),
        ):
            if not _has_unique_columns(connection, table, columns):
                raise SchemaNotReadyError(f"plan uniqueness is missing from {table}")
        for table, parent, columns in (
            ("booking_plans", "booking_plan_revisions", (("current_revision_id", "revision_id"), ("plan_id", "plan_id"), ("user_id", "user_id"), ("version", "revision_number"))),
            ("booking_plan_revisions", "booking_plans", (("plan_id", "plan_id"), ("user_id", "user_id"))),
        ):
            if not _has_composite_foreign_key(connection, table, parent, columns):
                raise SchemaNotReadyError(f"plan ownership/pointer constraint is missing from {table}")
        if not _has_foreign_key(connection, "booking_plans", "user_id", "users", "user_id"):
            raise SchemaNotReadyError("plan owner constraint is missing")
        triggers = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        if not {"booking_plan_revisions_no_update", "booking_plan_revisions_no_delete", "booking_plans_advance_only"} <= triggers:
            raise SchemaNotReadyError("plan immutability guards are missing")

    if schema_version >= 6:
        if not _has_unique_columns(connection, "ai_models", ("user_id", "model_id")):
            raise SchemaNotReadyError("AI model tenant uniqueness is missing")
        if not _has_foreign_key(connection, "ai_models", "user_id", "users", "user_id"):
            raise SchemaNotReadyError("AI model owner constraint is missing")
        if not _has_foreign_key(connection, "ai_model_preferences", "user_id", "users", "user_id"):
            raise SchemaNotReadyError("AI model preference owner constraint is missing")

    if schema_version >= 8:
        if not _has_foreign_key(connection, "booking_execution_stages", "run_id", "booking_execution_runs", "run_id"):
            raise SchemaNotReadyError("execution stage ownership constraint is missing")
        triggers = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        if "booking_execution_runs_owner_immutable" not in triggers:
            raise SchemaNotReadyError("execution queue snapshot immutability guard is missing")

    if schema_version >= 3:
        gate_rows = connection.execute(
            "SELECT lease_owner_id, lease_expires_at_utc_ms, active_started_at_utc_ms, "
            "active_validation_attempt_id, active_user_id, active_credential_id, "
            "active_operation_kind, active_credential_version_snapshot, "
            "active_token_revision_snapshot_id FROM upstream_request_gate "
            "WHERE endpoint_key='getUserInfo'"
        ).fetchall()
        if len(gate_rows) != 1:
            raise SchemaNotReadyError("the shared getUserInfo request-gate row is missing or duplicated")
        row = gate_rows[0]
        active_columns = (
            "lease_expires_at_utc_ms", "active_started_at_utc_ms",
            "active_validation_attempt_id", "active_user_id", "active_credential_id",
            "active_operation_kind", "active_credential_version_snapshot",
            "active_token_revision_snapshot_id",
        )
        if row["lease_owner_id"] is None:
            if any(row[name] is not None for name in active_columns):
                raise SchemaNotReadyError("the shared request-gate lease state is incoherent")
        elif any(row[name] is None for name in (
            "lease_expires_at_utc_ms", "active_started_at_utc_ms",
            "active_validation_attempt_id", "active_user_id", "active_operation_kind",
        )):
            raise SchemaNotReadyError("the shared request-gate lease state is incoherent")
        elif row["active_started_at_utc_ms"] > row["lease_expires_at_utc_ms"]:
            raise SchemaNotReadyError("the shared request-gate lease timestamps are incoherent")


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
        _validate_schema_contract(connection, current_version)
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise SchemaNotReadyError("database contains foreign-key violations")
    except SchemaNotReadyError:
        raise
    except sqlite3.Error as exc:
        raise SchemaNotReadyError("database schema is unreadable or incompatible") from exc
    finally:
        connection.close()
