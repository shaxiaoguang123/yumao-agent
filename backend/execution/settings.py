from __future__ import annotations

import re
from contextlib import closing
from pathlib import Path

from backend.db import connect_database


_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", re.ASCII)
_DELAY_FIELDS = (
    "booking_node_delay_ms",
    "booking_by_time_delay_ms",
    "get_user_info_delay_ms",
    "get_pay_price_delay_ms",
    "create_booking_delay_ms",
    "open_platform_pay_order_delay_ms",
    "payment_verify_delay_ms",
    "payment_verify_interval_ms",
    "candidate_interval_ms",
)
DEFAULT_SETTINGS = {
    "reconciliation_time": "00:30",
    "clock_calibration_lead_ms": 1000,
    "start_offset_ms": 0,
    **{field: 0 for field in _DELAY_FIELDS},
    "payment_verify_interval_ms": 3000,
}
_MAX_DELAY_MS = 60_000
_MAX_OPEN_PLATFORM_DELAY_MS = 120_000


class ExecutionSettingsError(ValueError):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


def validate_settings(value: object) -> dict:
    if type(value) is not dict or set(value) != set(DEFAULT_SETTINGS):
        raise ExecutionSettingsError("invalid_execution_settings")
    when = value.get("reconciliation_time")
    if type(when) is not str or not _TIME.fullmatch(when) or when >= "07:30":
        raise ExecutionSettingsError("invalid_reconciliation_time")
    result = {"reconciliation_time": when}
    for key, low, high in (
        ("clock_calibration_lead_ms", 0, 30_000),
        ("start_offset_ms", 0, 60_000),
    ):
        number = value.get(key)
        if type(number) is not int or not low <= number <= high:
            raise ExecutionSettingsError("invalid_execution_settings")
        result[key] = number
    for key in _DELAY_FIELDS:
        number = value.get(key)
        maximum = (_MAX_OPEN_PLATFORM_DELAY_MS
                   if key == "open_platform_pay_order_delay_ms" else _MAX_DELAY_MS)
        if type(number) is not int or not 0 <= number <= maximum:
            raise ExecutionSettingsError("invalid_execution_settings")
        result[key] = number
    return result


class ExecutionSettingsService:
    """Tenant-scoped timing controls shared by every credential owned by one user."""

    def __init__(self, database_path: Path, busy_timeout_ms: int, *, worker_enabled: bool = False):
        self.database_path = Path(database_path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.worker_enabled = bool(worker_enabled)

    def assert_credential_owner(self, user_id: str, credential_id: str) -> None:
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            credential = db.execute(
                "SELECT 1 FROM credentials WHERE user_id=? AND credential_id=? AND deleted_at_utc_ms IS NULL",
                (user_id, credential_id),
            ).fetchone()
        if credential is None:
            raise ExecutionSettingsError("credential_not_found", 404)

    def get(self, user_id: str) -> dict:
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            row = db.execute(
                "SELECT version, reconciliation_time, clock_calibration_lead_ms, start_offset_ms, "
                "booking_node_delay_ms, booking_by_time_delay_ms, get_user_info_delay_ms, "
                "get_pay_price_delay_ms, create_booking_delay_ms, "
                "open_platform_pay_order_delay_ms, payment_verify_delay_ms, "
                "payment_verify_interval_ms, candidate_interval_ms "
                "FROM user_booking_execution_settings WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return {
            "version": row["version"] if row else 0,
            "settings": ({key: row[key] for key in DEFAULT_SETTINGS} if row else dict(DEFAULT_SETTINGS)),
            "worker_enabled": self.worker_enabled,
        }

    def save(self, user_id: str, expected_version: object, settings_value: object,
             now_utc_ms: int) -> dict:
        if type(expected_version) is not int or not 0 <= expected_version < 2**53:
            raise ExecutionSettingsError("invalid_execution_settings")
        settings = validate_settings(settings_value)
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                user = db.execute(
                    "SELECT 1 FROM users WHERE user_id=? AND status='active'", (user_id,),
                ).fetchone()
                if user is None:
                    raise ExecutionSettingsError("user_not_found", 404)
                current = db.execute(
                    "SELECT version FROM user_booking_execution_settings WHERE user_id=?",
                    (user_id,),
                ).fetchone()
                current_version = current["version"] if current else 0
                if current_version != expected_version:
                    raise ExecutionSettingsError("execution_settings_version_conflict", 409)
                new_version = current_version + 1
                db.execute(
                    """INSERT INTO user_booking_execution_settings
                       (user_id, version, reconciliation_time,
                        clock_calibration_lead_ms, start_offset_ms, booking_node_delay_ms,
                        booking_by_time_delay_ms, get_user_info_delay_ms,
                        get_pay_price_delay_ms, create_booking_delay_ms,
                        open_platform_pay_order_delay_ms, payment_verify_delay_ms,
                        payment_verify_interval_ms, candidate_interval_ms, updated_at_utc_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(user_id) DO UPDATE SET
                         version=excluded.version,
                         reconciliation_time=excluded.reconciliation_time,
                         clock_calibration_lead_ms=excluded.clock_calibration_lead_ms,
                         start_offset_ms=excluded.start_offset_ms,
                         booking_node_delay_ms=excluded.booking_node_delay_ms,
                         booking_by_time_delay_ms=excluded.booking_by_time_delay_ms,
                         get_user_info_delay_ms=excluded.get_user_info_delay_ms,
                         get_pay_price_delay_ms=excluded.get_pay_price_delay_ms,
                         create_booking_delay_ms=excluded.create_booking_delay_ms,
                         open_platform_pay_order_delay_ms=excluded.open_platform_pay_order_delay_ms,
                         payment_verify_delay_ms=excluded.payment_verify_delay_ms,
                         payment_verify_interval_ms=excluded.payment_verify_interval_ms,
                         candidate_interval_ms=excluded.candidate_interval_ms,
                         updated_at_utc_ms=excluded.updated_at_utc_ms""",
                    (user_id, new_version, settings["reconciliation_time"],
                     settings["clock_calibration_lead_ms"], settings["start_offset_ms"],
                     settings["booking_node_delay_ms"], settings["booking_by_time_delay_ms"],
                     settings["get_user_info_delay_ms"],
                     settings["get_pay_price_delay_ms"], settings["create_booking_delay_ms"],
                     settings["open_platform_pay_order_delay_ms"], settings["payment_verify_delay_ms"],
                     settings["payment_verify_interval_ms"], settings["candidate_interval_ms"],
                     now_utc_ms),
                )
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        return {"version": new_version, "settings": settings, "worker_enabled": self.worker_enabled}

    def list_active_credentials(self) -> list[tuple[str, str]]:
        """Return only owner/credential identifiers; callers revalidate before each run."""
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            rows = db.execute(
                """SELECT credential.user_id, credential.credential_id
                   FROM credentials AS credential
                   JOIN users ON users.user_id=credential.user_id
                   WHERE credential.deleted_at_utc_ms IS NULL
                     AND credential.enabled=1 AND users.status='active'
                   ORDER BY credential.user_id, credential.credential_id"""
            ).fetchall()
        return [(row["user_id"], row["credential_id"]) for row in rows]

