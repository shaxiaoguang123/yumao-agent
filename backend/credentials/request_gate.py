from __future__ import annotations

import math
import secrets
import sqlite3
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Literal

from backend.db import connect_database


_OPERATION_KINDS = {
    "create_candidate",
    "validate_current",
    "token_rotation_candidate",
}
_ATTEMPT_RESULTS = {
    "success",
    "explicit_invalid",
    "network_error",
    "rate_limited",
    "contract_drift",
    "validation_unknown",
    "unresolved_identity",
    "internal_error",
}
_BINDING_OUTCOMES = {
    None,
    "not_checked",
    "unresolved",
    "confirmed",
    "mismatch",
    "duplicate_conflict",
}
_APPLY_STATES = {"applied", "candidate_rejected", "not_dispatched", "stale"}
_READ_ONLY_SQLITE_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", -1),
}
_RETRY_AFTER_FALLBACK_STATUSES = {429, 503}
_MAX_RETRY_AFTER_HEADER_CHARS = 256
_MAX_SQLITE_INTEGER = 2**63 - 1
_SAFE_PREFLIGHT_DENIAL_CODES = {
    "credential_not_found",
    "credential_disabled",
    "credential_token_expired",
    "credential_token_invalid",
    "credential_requires_revalidation",
    "credential_account_binding_unresolved",
    "credential_account_reconfirmation_required",
    "credential_account_mismatch",
    "credential_account_already_configured",
    "credential_version_conflict",
    "validation_not_configured",
}


class GateUnavailableError(RuntimeError):
    """The shared upstream gate state is missing or incompatible."""


class GatePreflightReadOnlyError(RuntimeError):
    """A gate preflight attempted to mutate SQLite state."""


@dataclass(frozen=True, slots=True)
class GateOperationContext:
    user_id: str
    credential_id: str | None
    operation_kind: str
    credential_version_snapshot: int | None = None
    current_token_revision_snapshot_id: str | None = None
    token_revision_id: str | None = None


@dataclass(frozen=True, slots=True)
class GatePreflightDenial:
    denial_code: str
    attempt_result: str = "validation_unknown"
    account_binding_outcome: str | None = "not_checked"


@dataclass(frozen=True, slots=True)
class GateAttemptObservation:
    validation_attempt_id: int
    user_id: str
    credential_id: str | None
    operation_kind: str
    credential_version_snapshot: int | None
    current_token_revision_snapshot_id: str | None
    token_revision_id: str | None
    started_at_utc_ms: int
    completed_at_utc_ms: int
    attempt_result: str
    account_binding_outcome: str | None
    http_status_class: str | None
    gate_owner_id: str | None
    gate_epoch: int | None
    apply_state: str


@dataclass(frozen=True, slots=True)
class GatePermit:
    validation_attempt_id: int
    owner_id: str
    epoch: int
    started_at_utc_ms: int
    lease_expires_at_utc_ms: int
    context: GateOperationContext


@dataclass(frozen=True, slots=True)
class GateDecision:
    validation_attempt_id: int
    permit: GatePermit | None
    denial_code: str | None
    retry_after_seconds: int | None

    @property
    def allowed(self) -> bool:
        return self.permit is not None


@dataclass(frozen=True, slots=True)
class GateCompletion:
    state: Literal["completed", "uncertain", "stale"]


def _status_class(status_code: int | None) -> str | None:
    if status_code is None or not 100 <= status_code <= 599:
        return None
    return f"{status_code // 100}xx"


def _retry_seconds_until(deadline_utc_ms: int | None, now_utc_ms: int) -> int:
    if deadline_utc_ms is None or deadline_utc_ms <= now_utc_ms:
        return 0
    return max(1, math.ceil((deadline_utc_ms - now_utc_ms) / 1000))


def _parse_http_date(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


class UpstreamRequestGate:
    """One SQLite-persisted request interval, backoff, and lease for getUserInfo."""

    def __init__(
        self,
        *,
        database_path: Path,
        busy_timeout_ms: int,
        minimum_interval_ms: int | None,
        total_deadline_seconds: float,
        read_timeout_seconds: float,
        lease_safety_margin_seconds: float,
        retry_after_fallback_seconds: int,
        max_upstream_backoff_seconds: int,
        allow_http_date: bool = False,
    ):
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        if minimum_interval_ms is not None and minimum_interval_ms <= 0:
            raise ValueError("minimum_interval_ms must be positive or None")
        if total_deadline_seconds <= 0 or read_timeout_seconds <= 0:
            raise ValueError("upstream deadlines must be positive")
        if read_timeout_seconds >= total_deadline_seconds:
            raise ValueError("read timeout must be less than total deadline")
        if lease_safety_margin_seconds < read_timeout_seconds:
            raise ValueError("lease safety margin must cover one read timeout")
        if retry_after_fallback_seconds <= 0 or max_upstream_backoff_seconds <= 0:
            raise ValueError("upstream backoff values must be positive")
        if retry_after_fallback_seconds > max_upstream_backoff_seconds:
            raise ValueError("retry-after fallback must not exceed maximum backoff")

        self.database_path = Path(database_path)
        self.busy_timeout_ms = busy_timeout_ms
        self.minimum_interval_ms = minimum_interval_ms
        self.total_deadline_seconds = float(total_deadline_seconds)
        self.read_timeout_seconds = float(read_timeout_seconds)
        self.lease_safety_margin_seconds = float(lease_safety_margin_seconds)
        self.retry_after_fallback_seconds = retry_after_fallback_seconds
        self.max_upstream_backoff_seconds = max_upstream_backoff_seconds
        self.allow_http_date = allow_http_date

    @staticmethod
    def _context_is_valid(context: GateOperationContext) -> bool:
        if (
            not isinstance(context, GateOperationContext)
            or not isinstance(context.user_id, str)
            or not context.user_id
            or context.operation_kind not in _OPERATION_KINDS
        ):
            return False
        if context.credential_id is not None and (
            not isinstance(context.credential_id, str) or not context.credential_id
        ):
            return False
        if context.credential_version_snapshot is not None and (
            isinstance(context.credential_version_snapshot, bool)
            or not isinstance(context.credential_version_snapshot, int)
            or context.credential_version_snapshot <= 0
        ):
            return False
        if context.current_token_revision_snapshot_id is not None and (
            not isinstance(context.current_token_revision_snapshot_id, str)
            or not context.current_token_revision_snapshot_id
        ):
            return False
        if context.token_revision_id is not None and (
            not isinstance(context.token_revision_id, str) or not context.token_revision_id
        ):
            return False
        if context.operation_kind == "create_candidate":
            return (
                context.credential_id is None
                and context.credential_version_snapshot is None
                and context.current_token_revision_snapshot_id is None
                and context.token_revision_id is None
            )
        valid_existing = (
            context.credential_id is not None
            and context.credential_version_snapshot is not None
            and isinstance(context.current_token_revision_snapshot_id, str)
            and bool(context.current_token_revision_snapshot_id)
        )
        if not valid_existing:
            return False
        if context.operation_kind == "validate_current":
            return context.token_revision_id == context.current_token_revision_snapshot_id
        return context.operation_kind == "token_rotation_candidate" and context.token_revision_id is None

    @staticmethod
    def _insert_observation(connection: sqlite3.Connection, observation: GateAttemptObservation) -> bool:
        if (
            isinstance(observation.validation_attempt_id, bool)
            or not isinstance(observation.validation_attempt_id, int)
            or observation.validation_attempt_id <= 0
            or isinstance(observation.started_at_utc_ms, bool)
            or not isinstance(observation.started_at_utc_ms, int)
            or isinstance(observation.completed_at_utc_ms, bool)
            or not isinstance(observation.completed_at_utc_ms, int)
            or observation.started_at_utc_ms < 0
            or observation.completed_at_utc_ms < observation.started_at_utc_ms
        ):
            raise ValueError("invalid validation observation ordering or ID")
        if (observation.gate_owner_id is None) != (observation.gate_epoch is None):
            raise ValueError("gate observation owner and epoch must be paired")
        if observation.attempt_result not in _ATTEMPT_RESULTS:
            raise ValueError("unknown safe gate attempt result")
        if observation.account_binding_outcome not in _BINDING_OUTCOMES:
            raise ValueError("unknown safe gate account-binding outcome")
        if observation.apply_state not in _APPLY_STATES:
            raise ValueError("unknown safe gate apply state")
        if observation.http_status_class not in {None, "1xx", "2xx", "3xx", "4xx", "5xx"}:
            raise ValueError("unknown safe HTTP status class")
        cursor = connection.execute(
            """INSERT INTO credential_validation_observations
               (validation_attempt_id, user_id, credential_id, operation_kind,
                credential_version_snapshot, current_token_revision_snapshot_id, token_revision_id,
                started_at_utc_ms, completed_at_utc_ms, attempt_result, account_binding_outcome,
                http_status_class, gate_owner_id, gate_epoch, apply_state)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(validation_attempt_id) DO NOTHING""",
            (
                observation.validation_attempt_id,
                observation.user_id,
                observation.credential_id,
                observation.operation_kind,
                observation.credential_version_snapshot,
                observation.current_token_revision_snapshot_id,
                observation.token_revision_id,
                observation.started_at_utc_ms,
                observation.completed_at_utc_ms,
                observation.attempt_result,
                observation.account_binding_outcome,
                observation.http_status_class,
                observation.gate_owner_id,
                observation.gate_epoch,
                observation.apply_state,
            ),
        )
        return cursor.rowcount == 1

    @staticmethod
    def _read_only_authorizer(action, _arg1, _arg2, _database, _trigger):
        return (
            sqlite3.SQLITE_OK
            if action in _READ_ONLY_SQLITE_ACTIONS
            else sqlite3.SQLITE_DENY
        )

    def _run_preflight(
        self,
        connection: sqlite3.Connection,
        context: GateOperationContext,
        preflight_check: Callable[
            [sqlite3.Connection, GateOperationContext], GatePreflightDenial | None
        ],
    ) -> GatePreflightDenial | None:
        connection.set_authorizer(self._read_only_authorizer)
        try:
            result = preflight_check(connection, context)
        except sqlite3.DatabaseError as exc:
            raise GatePreflightReadOnlyError("gate preflight must be read-only") from exc
        finally:
            connection.set_authorizer(None)
        if result is not None and not isinstance(result, GatePreflightDenial):
            raise TypeError("preflight_check must return GatePreflightDenial or None")
        if result is not None:
            if result.denial_code not in _SAFE_PREFLIGHT_DENIAL_CODES:
                raise ValueError("unknown safe gate preflight denial code")
            if result.attempt_result not in _ATTEMPT_RESULTS:
                raise ValueError("unknown safe preflight attempt result")
            if result.account_binding_outcome not in _BINDING_OUTCOMES:
                raise ValueError("unknown safe preflight account-binding outcome")
        return result

    def _attempt_observation(
        self,
        attempt_id: int,
        context: GateOperationContext,
        now_utc_ms: int,
        *,
        result: str,
        apply_state: str,
        account_binding_outcome: str | None = "not_checked",
        owner_id: str | None = None,
        epoch: int | None = None,
    ) -> GateAttemptObservation:
        return GateAttemptObservation(
            validation_attempt_id=attempt_id,
            user_id=context.user_id,
            credential_id=context.credential_id,
            operation_kind=context.operation_kind,
            credential_version_snapshot=context.credential_version_snapshot,
            current_token_revision_snapshot_id=context.current_token_revision_snapshot_id,
            token_revision_id=context.token_revision_id,
            started_at_utc_ms=now_utc_ms,
            completed_at_utc_ms=now_utc_ms,
            attempt_result=result,
            account_binding_outcome=account_binding_outcome,
            http_status_class=None,
            gate_owner_id=owner_id,
            gate_epoch=epoch,
            apply_state=apply_state,
        )

    @staticmethod
    def _reclaimed_observation(row: sqlite3.Row, now_utc_ms: int) -> GateAttemptObservation:
        return GateAttemptObservation(
            validation_attempt_id=row["active_validation_attempt_id"],
            user_id=row["active_user_id"],
            credential_id=row["active_credential_id"],
            operation_kind=row["active_operation_kind"],
            credential_version_snapshot=row["active_credential_version_snapshot"],
            current_token_revision_snapshot_id=row["active_token_revision_snapshot_id"],
            token_revision_id=(
                row["active_token_revision_snapshot_id"]
                if row["active_operation_kind"] == "validate_current"
                else None
            ),
            started_at_utc_ms=row["active_started_at_utc_ms"],
            completed_at_utc_ms=now_utc_ms,
            attempt_result="network_error",
            account_binding_outcome="not_checked",
            http_status_class=None,
            gate_owner_id=row["lease_owner_id"],
            gate_epoch=row["lease_epoch"],
            apply_state="stale",
        )

    def _retry_after_delay_ms(
        self,
        retry_after_header: str | None,
        status_code: int | None,
        now_utc_ms: int,
    ) -> int | None:
        if status_code not in _RETRY_AFTER_FALLBACK_STATUSES and retry_after_header is None:
            return None

        delay_seconds: int | None = None
        value = retry_after_header.strip() if isinstance(retry_after_header, str) else ""
        if value and len(value) <= _MAX_RETRY_AFTER_HEADER_CHARS:
            if value.isascii() and value.isdecimal():
                parsed_seconds = int(value)
                if parsed_seconds <= sys.maxsize:
                    delay_seconds = min(parsed_seconds, self.max_upstream_backoff_seconds)
            elif self.allow_http_date:
                parsed_date = _parse_http_date(value)
                if parsed_date is not None:
                    try:
                        target_ms = int(parsed_date.timestamp() * 1000)
                    except (OSError, OverflowError, ValueError):
                        target_ms = None
                    if target_ms is not None:
                        delay_seconds = max(0, math.ceil((target_ms - now_utc_ms) / 1000))

        if delay_seconds is None:
            delay_seconds = self.retry_after_fallback_seconds
        delay_seconds = min(delay_seconds, self.max_upstream_backoff_seconds)
        return delay_seconds * 1000

    @staticmethod
    def _extend_backoff_in_transaction(
        connection: sqlite3.Connection,
        now_utc_ms: int,
        retry_after_delay_ms: int | None,
    ) -> None:
        if retry_after_delay_ms is None:
            return
        proposed_deadline = min(now_utc_ms + retry_after_delay_ms, _MAX_SQLITE_INTEGER)
        connection.execute(
            """UPDATE upstream_request_gate
               SET upstream_backoff_until_utc_ms =
                   max(coalesce(upstream_backoff_until_utc_ms, 0), ?)
               WHERE endpoint_key='getUserInfo'""",
            (proposed_deadline,),
        )

    def acquire(
        self,
        context: GateOperationContext,
        now_utc_ms: int,
        preflight_check: Callable[
            [sqlite3.Connection, GateOperationContext], GatePreflightDenial | None
        ],
    ) -> GateDecision:
        if not self._context_is_valid(context):
            raise ValueError("invalid upstream gate operation context")
        if (
            isinstance(now_utc_ms, bool)
            or not isinstance(now_utc_ms, int)
            or not 0 <= now_utc_ms <= _MAX_SQLITE_INTEGER
        ):
            raise ValueError("now_utc_ms must be a non-negative integer")

        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
            ).fetchone()
            if row is None:
                raise GateUnavailableError("the shared getUserInfo request-gate row is missing")
            next_attempt_id = row["next_validation_attempt_id"]
            if next_attempt_id >= 2**63 - 1:
                raise GateUnavailableError("the validation attempt sequence is exhausted")
            connection.execute(
                "UPDATE upstream_request_gate SET next_validation_attempt_id=? WHERE endpoint_key='getUserInfo'",
                (next_attempt_id + 1,),
            )

            preflight_denial = self._run_preflight(connection, context, preflight_check)
            if preflight_denial is not None:
                self._insert_observation(
                    connection,
                    self._attempt_observation(
                        next_attempt_id,
                        context,
                        now_utc_ms,
                        result=preflight_denial.attempt_result,
                        apply_state="not_dispatched",
                        account_binding_outcome=preflight_denial.account_binding_outcome,
                    ),
                )
                connection.execute("COMMIT")
                return GateDecision(next_attempt_id, None, preflight_denial.denial_code, None)

            if self.minimum_interval_ms is None:
                self._insert_observation(
                    connection,
                    self._attempt_observation(
                        next_attempt_id,
                        context,
                        now_utc_ms,
                        result="validation_unknown",
                        apply_state="not_dispatched",
                    ),
                )
                connection.execute("COMMIT")
                return GateDecision(next_attempt_id, None, "validation_not_configured", None)

            row = connection.execute(
                "SELECT * FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
            ).fetchone()
            epoch = row["lease_epoch"]
            reclaimed = False
            if row["lease_owner_id"] is not None:
                if row["lease_expires_at_utc_ms"] > now_utc_ms:
                    self._insert_observation(
                        connection,
                        self._attempt_observation(
                            next_attempt_id,
                            context,
                            now_utc_ms,
                            result="rate_limited",
                            apply_state="not_dispatched",
                        ),
                    )
                    retry_at = max(
                        row["lease_expires_at_utc_ms"],
                        row["next_allowed_at_utc_ms"] or 0,
                        row["upstream_backoff_until_utc_ms"] or 0,
                    )
                    retry_after = _retry_seconds_until(retry_at, now_utc_ms)
                    connection.execute("COMMIT")
                    return GateDecision(next_attempt_id, None, "validation_rate_limited", retry_after)

                if row["active_started_at_utc_ms"] is None:
                    raise GateUnavailableError("expired gate lease has no persisted start time")
                self._insert_observation(connection, self._reclaimed_observation(row, now_utc_ms))
                epoch += 1
                connection.execute(
                    """UPDATE upstream_request_gate SET lease_owner_id=NULL,
                       lease_expires_at_utc_ms=NULL, active_validation_attempt_id=NULL,
                       active_started_at_utc_ms=NULL, active_user_id=NULL, active_credential_id=NULL,
                       active_operation_kind=NULL, active_credential_version_snapshot=NULL,
                       active_token_revision_snapshot_id=NULL, lease_epoch=?
                       WHERE endpoint_key='getUserInfo'""",
                    (epoch,),
                )
                reclaimed = True

            retry_at = max(
                row["next_allowed_at_utc_ms"] or 0,
                row["upstream_backoff_until_utc_ms"] or 0,
            )
            if retry_at > now_utc_ms:
                self._insert_observation(
                    connection,
                    self._attempt_observation(
                        next_attempt_id,
                        context,
                        now_utc_ms,
                        result="rate_limited",
                        apply_state="not_dispatched",
                    ),
                )
                retry_after = _retry_seconds_until(retry_at, now_utc_ms)
                connection.execute("COMMIT")
                return GateDecision(next_attempt_id, None, "validation_rate_limited", retry_after)

            owner_id = secrets.token_urlsafe(24)
            if not reclaimed:
                epoch += 1
            lease_duration_ms = math.ceil(
                (self.total_deadline_seconds + self.lease_safety_margin_seconds) * 1000
            )
            if lease_duration_ms > _MAX_SQLITE_INTEGER - now_utc_ms:
                raise GateUnavailableError("configured gate lease exceeds the SQLite timestamp range")
            lease_expires = now_utc_ms + lease_duration_ms
            if self.minimum_interval_ms > _MAX_SQLITE_INTEGER - now_utc_ms:
                raise GateUnavailableError("configured request interval exceeds the SQLite timestamp range")
            next_allowed = max(
                row["next_allowed_at_utc_ms"] or 0,
                now_utc_ms + self.minimum_interval_ms,
            )
            connection.execute(
                """UPDATE upstream_request_gate SET lease_owner_id=?, lease_epoch=?,
                   lease_expires_at_utc_ms=?, active_validation_attempt_id=?,
                   active_started_at_utc_ms=?, active_user_id=?, active_credential_id=?,
                   active_operation_kind=?, active_credential_version_snapshot=?,
                   active_token_revision_snapshot_id=?, next_allowed_at_utc_ms=?
                   WHERE endpoint_key='getUserInfo'""",
                (
                    owner_id,
                    epoch,
                    lease_expires,
                    next_attempt_id,
                    now_utc_ms,
                    context.user_id,
                    context.credential_id,
                    context.operation_kind,
                    context.credential_version_snapshot,
                    context.current_token_revision_snapshot_id,
                    next_allowed,
                ),
            )
            connection.execute("COMMIT")
            permit = GatePermit(
                validation_attempt_id=next_attempt_id,
                owner_id=owner_id,
                epoch=epoch,
                started_at_utc_ms=now_utc_ms,
                lease_expires_at_utc_ms=lease_expires,
                context=context,
            )
            return GateDecision(next_attempt_id, permit, None, None)
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _lease_matches(
        self,
        row: sqlite3.Row | None,
        permit: GatePermit,
        now_utc_ms: int,
    ) -> bool:
        return bool(
            row is not None
            and row["lease_owner_id"] == permit.owner_id
            and row["lease_epoch"] == permit.epoch
            and row["active_validation_attempt_id"] == permit.validation_attempt_id
            and row["active_started_at_utc_ms"] == permit.started_at_utc_ms
            and row["lease_expires_at_utc_ms"] > now_utc_ms
        )

    @staticmethod
    def _validate_permit_observation(
        permit: GatePermit,
        observation: GateAttemptObservation,
    ) -> None:
        context = permit.context
        if (
            observation.validation_attempt_id != permit.validation_attempt_id
            or observation.user_id != context.user_id
            or observation.operation_kind != context.operation_kind
            or observation.credential_version_snapshot != context.credential_version_snapshot
            or observation.current_token_revision_snapshot_id
            != context.current_token_revision_snapshot_id
            or observation.started_at_utc_ms != permit.started_at_utc_ms
            or observation.gate_owner_id != permit.owner_id
            or observation.gate_epoch != permit.epoch
        ):
            raise ValueError("gate observation does not match its permit")
        if context.operation_kind != "create_candidate" and (
            observation.credential_id != context.credential_id
        ):
            raise ValueError("gate observation does not match its credential")
        if context.operation_kind == "validate_current":
            if observation.token_revision_id != context.token_revision_id:
                raise ValueError("validation observation does not match its Token revision")
        elif observation.token_revision_id is not None and (
            observation.attempt_result != "success"
            or observation.apply_state != "applied"
        ):
            raise ValueError("candidate revision may be recorded only after successful persistence")

    def complete_in_transaction(
        self,
        connection: sqlite3.Connection,
        permit: GatePermit,
        safe_observation: GateAttemptObservation,
        now_utc_ms: int,
        *,
        upstream_status_code: int | None,
        retry_after_header: str | None = None,
    ) -> GateCompletion:
        if not connection.in_transaction:
            raise ValueError("complete_in_transaction requires an active transaction")
        self._validate_permit_observation(permit, safe_observation)
        row = connection.execute(
            "SELECT * FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
        ).fetchone()
        if not self._lease_matches(row, permit, now_utc_ms):
            self._insert_observation(
                connection,
                replace(safe_observation, apply_state="stale"),
            )
            return GateCompletion("stale")

        self._insert_observation(connection, safe_observation)
        delay_ms = self._retry_after_delay_ms(
            retry_after_header,
            upstream_status_code,
            now_utc_ms,
        )
        self._extend_backoff_in_transaction(connection, now_utc_ms, delay_ms)
        connection.execute(
            """UPDATE upstream_request_gate SET lease_owner_id=NULL, lease_expires_at_utc_ms=NULL,
               active_validation_attempt_id=NULL, active_started_at_utc_ms=NULL,
               active_user_id=NULL, active_credential_id=NULL, active_operation_kind=NULL,
               active_credential_version_snapshot=NULL, active_token_revision_snapshot_id=NULL
               WHERE endpoint_key='getUserInfo' AND lease_owner_id=? AND lease_epoch=?""",
            (permit.owner_id, permit.epoch),
        )
        return GateCompletion("completed")

    def mark_uncertain_in_transaction(
        self,
        connection: sqlite3.Connection,
        permit: GatePermit,
        safe_observation: GateAttemptObservation,
        now_utc_ms: int,
    ) -> GateCompletion:
        if not connection.in_transaction:
            raise ValueError("mark_uncertain_in_transaction requires an active transaction")
        self._validate_permit_observation(permit, safe_observation)
        row = connection.execute(
            "SELECT * FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
        ).fetchone()
        if not self._lease_matches(row, permit, now_utc_ms):
            self._insert_observation(connection, replace(safe_observation, apply_state="stale"))
            return GateCompletion("stale")
        self._insert_observation(connection, safe_observation)
        return GateCompletion("uncertain")
