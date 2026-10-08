from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from backend.credentials.request_gate import (
    GateAttemptObservation,
    GateOperationContext,
    GatePreflightDenial,
    UpstreamRequestGate,
)
from backend.db import connect_database
from backend.migrate import migrate_database


BUSY_TIMEOUT_MS = 5000


def _context(user_id: str = "user-a", credential_id: str | None = None):
    return GateOperationContext(
        user_id=user_id,
        credential_id=credential_id,
        operation_kind="create_candidate" if credential_id is None else "validate_current",
        credential_version_snapshot=None if credential_id is None else 1,
        current_token_revision_snapshot_id=None if credential_id is None else "revision-1",
        token_revision_id=None if credential_id is None else "revision-1",
    )


def _allow(_connection, _context):
    return None


def _observation(permit, now_utc_ms, result="success", apply_state="applied", status="2xx"):
    context = permit.context
    return GateAttemptObservation(
        validation_attempt_id=permit.validation_attempt_id,
        user_id=context.user_id,
        credential_id=context.credential_id,
        operation_kind=context.operation_kind,
        credential_version_snapshot=context.credential_version_snapshot,
        current_token_revision_snapshot_id=context.current_token_revision_snapshot_id,
        token_revision_id=context.token_revision_id,
        started_at_utc_ms=permit.started_at_utc_ms,
        completed_at_utc_ms=now_utc_ms,
        attempt_result=result,
        account_binding_outcome="not_checked",
        http_status_class=status,
        gate_owner_id=permit.owner_id,
        gate_epoch=permit.epoch,
        apply_state=apply_state,
    )


class UpstreamRequestGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="credential-gate-")
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "gate.sqlite3"
        migrate_database(self.database_path, BUSY_TIMEOUT_MS)
        self.gate = UpstreamRequestGate(
            database_path=self.database_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            minimum_interval_ms=1000,
            total_deadline_seconds=10,
            read_timeout_seconds=5,
            lease_safety_margin_seconds=6,
            retry_after_fallback_seconds=7,
            max_upstream_backoff_seconds=60,
        )

    def _complete(self, permit, now_utc_ms, *, status=200, result="success", retry_after=None):
        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            conn.execute("BEGIN IMMEDIATE")
            decision = self.gate.complete_in_transaction(
                conn,
                permit,
                _observation(
                    permit,
                    now_utc_ms,
                    result=result,
                    status="2xx" if status < 300 else f"{status // 100}xx",
                ),
                now_utc_ms,
                upstream_status_code=status,
                retry_after_header=retry_after,
            )
            conn.execute("COMMIT")
            return decision
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def test_attempt_ids_are_allocated_in_request_order_for_permit_and_denial(self) -> None:
        first = self.gate.acquire(_context("user-a"), 10_000, _allow)
        second = self.gate.acquire(_context("user-b"), 10_001, _allow)

        self.assertTrue(first.allowed)
        self.assertEqual(first.validation_attempt_id, 1)
        self.assertFalse(second.allowed)
        self.assertEqual(second.validation_attempt_id, 2)
        self.assertEqual(second.denial_code, "validation_rate_limited")
        self.assertEqual(second.retry_after_seconds, 16)

        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            observation = conn.execute(
                "SELECT attempt_result, apply_state FROM credential_validation_observations "
                "WHERE validation_attempt_id=2"
            ).fetchone()
            self.assertEqual(tuple(observation), ("rate_limited", "not_dispatched"))
            state = conn.execute(
                "SELECT next_validation_attempt_id, lease_owner_id FROM upstream_request_gate "
                "WHERE endpoint_key='getUserInfo'"
            ).fetchone()
            self.assertEqual(state["next_validation_attempt_id"], 3)
            self.assertEqual(state["lease_owner_id"], first.permit.owner_id)
        finally:
            conn.close()

    def test_preflight_denial_is_observed_without_creating_a_lease(self) -> None:
        denial = GatePreflightDenial(
            denial_code="credential_token_expired",
            attempt_result="validation_unknown",
            account_binding_outcome="not_checked",
        )
        result = self.gate.acquire(_context(), 20_000, lambda _conn, _ctx: denial)

        self.assertFalse(result.allowed)
        self.assertEqual(result.denial_code, "credential_token_expired")
        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            row = conn.execute(
                "SELECT started_at_utc_ms, completed_at_utc_ms, attempt_result, apply_state "
                "FROM credential_validation_observations WHERE validation_attempt_id=1"
            ).fetchone()
            self.assertEqual(tuple(row), (20_000, 20_000, "validation_unknown", "not_dispatched"))
            state = conn.execute(
                "SELECT lease_owner_id FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
            ).fetchone()
            self.assertIsNone(state["lease_owner_id"])
        finally:
            conn.close()

    def test_unconfigured_endpoint_gate_denies_without_creating_a_lease(self) -> None:
        gate = UpstreamRequestGate(
            database_path=self.database_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            minimum_interval_ms=None,
            total_deadline_seconds=10,
            read_timeout_seconds=5,
            lease_safety_margin_seconds=6,
            retry_after_fallback_seconds=7,
            max_upstream_backoff_seconds=60,
        )

        result = gate.acquire(_context(), 25_000, _allow)

        self.assertFalse(result.allowed)
        self.assertEqual(result.denial_code, "validation_not_configured")
        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM credential_validation_observations").fetchone()[0],
                1,
            )
            self.assertIsNone(
                conn.execute(
                    "SELECT lease_owner_id FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
                ).fetchone()[0]
            )
        finally:
            conn.close()

    def test_preflight_callback_runs_in_acquire_transaction_and_cannot_write(self) -> None:
        observed = []

        def read_only_preflight(connection, _operation):
            observed.append(connection.in_transaction)
            connection.execute("SELECT endpoint_key FROM upstream_request_gate").fetchone()
            return None

        decision = self.gate.acquire(_context(), 30_000, read_only_preflight)

        self.assertTrue(decision.allowed)
        self.assertEqual(observed, [True])
        from backend.credentials.request_gate import GatePreflightReadOnlyError

        with self.assertRaises(GatePreflightReadOnlyError):
            self.gate.acquire(
                _context(),
                30_001,
                lambda connection, _operation: connection.execute(
                    "UPDATE upstream_request_gate SET lease_epoch=lease_epoch WHERE endpoint_key='getUserInfo'"
                ),
            )

    def test_expired_lease_reclaim_uses_persisted_original_start_time(self) -> None:
        first = self.gate.acquire(_context("user-a"), 40_000, _allow)
        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE upstream_request_gate SET lease_expires_at_utc_ms=? WHERE endpoint_key='getUserInfo'",
                (first.permit.lease_expires_at_utc_ms,),
            )
            conn.execute("COMMIT")
        finally:
            conn.close()

        second = self.gate.acquire(_context("user-b"), first.permit.lease_expires_at_utc_ms, _allow)

        self.assertTrue(second.allowed)
        self.assertEqual(second.validation_attempt_id, 2)
        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            stale = conn.execute(
                "SELECT started_at_utc_ms, completed_at_utc_ms, attempt_result, apply_state, gate_epoch "
                "FROM credential_validation_observations WHERE validation_attempt_id=1"
            ).fetchone()
            self.assertEqual(stale["started_at_utc_ms"], 40_000)
            self.assertEqual(stale["completed_at_utc_ms"], first.permit.lease_expires_at_utc_ms)
            self.assertEqual(stale["attempt_result"], "network_error")
            self.assertEqual(stale["apply_state"], "stale")
            state = conn.execute(
                "SELECT lease_epoch, lease_owner_id, active_started_at_utc_ms "
                "FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
            ).fetchone()
            self.assertEqual(state["lease_epoch"], second.permit.epoch)
            self.assertEqual(state["lease_owner_id"], second.permit.owner_id)
            self.assertEqual(state["active_started_at_utc_ms"], second.permit.started_at_utc_ms)
        finally:
            conn.close()

    def test_completion_persists_observation_and_releases_matching_live_lease(self) -> None:
        permit = self.gate.acquire(_context(), 50_000, _allow).permit
        result = self._complete(permit, 50_250)

        self.assertEqual(result.state, "completed")
        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            state = conn.execute(
                "SELECT lease_owner_id, active_started_at_utc_ms, next_allowed_at_utc_ms "
                "FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
            ).fetchone()
            self.assertIsNone(state["lease_owner_id"])
            self.assertIsNone(state["active_started_at_utc_ms"])
            self.assertEqual(state["next_allowed_at_utc_ms"], 51_000)
            observation = conn.execute(
                "SELECT attempt_result, apply_state, started_at_utc_ms, completed_at_utc_ms "
                "FROM credential_validation_observations WHERE validation_attempt_id=1"
            ).fetchone()
            self.assertEqual(tuple(observation), ("success", "applied", 50_000, 50_250))
        finally:
            conn.close()

    def test_configured_minimum_interval_applies_after_a_lease_completes(self) -> None:
        first = self.gate.acquire(_context(), 55_000, _allow).permit
        self._complete(first, 55_000)

        too_early = self.gate.acquire(_context("user-b"), 55_500, _allow)
        on_time = self.gate.acquire(_context("user-c"), 56_000, _allow)

        self.assertFalse(too_early.allowed)
        self.assertEqual(too_early.retry_after_seconds, 1)
        self.assertTrue(on_time.allowed)

    def test_late_owner_completion_cannot_release_a_reclaimed_newer_lease(self) -> None:
        first = self.gate.acquire(_context("user-a"), 57_000, _allow).permit
        second = self.gate.acquire(
            _context("user-b"), first.lease_expires_at_utc_ms, _allow
        ).permit
        self.assertGreater(second.epoch, first.epoch)

        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            conn.execute("BEGIN IMMEDIATE")
            result = self.gate.complete_in_transaction(
                conn,
                first,
                _observation(first, second.started_at_utc_ms + 1),
                second.started_at_utc_ms + 1,
                upstream_status_code=200,
            )
            conn.execute("COMMIT")
        finally:
            conn.close()

        self.assertEqual(result.state, "stale")
        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            state = conn.execute(
                "SELECT lease_owner_id, lease_epoch FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
            ).fetchone()
            self.assertEqual(state["lease_owner_id"], second.owner_id)
            self.assertEqual(state["lease_epoch"], second.epoch)
        finally:
            conn.close()

    def test_uncertain_result_is_recorded_without_releasing_the_lease(self) -> None:
        permit = self.gate.acquire(_context(), 60_000, _allow).permit
        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            conn.execute("BEGIN IMMEDIATE")
            result = self.gate.mark_uncertain_in_transaction(
                conn,
                permit,
                _observation(permit, 60_100, result="network_error", apply_state="applied", status=None),
                60_100,
            )
            conn.execute("COMMIT")
            self.assertEqual(result.state, "uncertain")
        finally:
            conn.close()

        blocked = self.gate.acquire(_context("user-b"), 60_200, _allow)
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.retry_after_seconds, 16)

    def test_retry_after_delta_seconds_and_missing_header_backoff_are_shared(self) -> None:
        permit = self.gate.acquire(_context(), 70_000, _allow).permit
        self._complete(permit, 70_010, status=429, result="rate_limited", retry_after="17")
        denied = self.gate.acquire(_context("user-b"), 71_000, _allow)

        self.assertFalse(denied.allowed)
        self.assertEqual(denied.retry_after_seconds, 17)
        self.assertEqual(denied.denial_code, "validation_rate_limited")

    def test_bad_negative_overflow_and_unsupported_http_date_use_bounded_fallback(self) -> None:
        bad_values = ("not-a-delay", "-3", "9223372036854775808", "Wed, 21 Oct 2030 07:28:00 GMT")
        for index, header in enumerate(bad_values):
            with self.subTest(header_kind=index):
                with tempfile.TemporaryDirectory() as temp_dir:
                    path = Path(temp_dir) / "gate.sqlite3"
                    migrate_database(path, BUSY_TIMEOUT_MS)
                    gate = UpstreamRequestGate(
                        database_path=path,
                        busy_timeout_ms=BUSY_TIMEOUT_MS,
                        minimum_interval_ms=1,
                        total_deadline_seconds=10,
                        read_timeout_seconds=5,
                        lease_safety_margin_seconds=6,
                        retry_after_fallback_seconds=7,
                        max_upstream_backoff_seconds=60,
                        allow_http_date=False,
                    )
                    permit = gate.acquire(_context(), 80_000, _allow).permit
                    conn = connect_database(path, BUSY_TIMEOUT_MS)
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        gate.complete_in_transaction(
                            conn,
                            permit,
                            _observation(permit, 80_010, result="rate_limited", status="4xx"),
                            80_010,
                            upstream_status_code=429,
                            retry_after_header=header,
                        )
                        conn.execute("COMMIT")
                    finally:
                        conn.close()
                    denied = gate.acquire(_context("user-b"), 80_011, _allow)
                    self.assertFalse(denied.allowed)
                    self.assertEqual(denied.retry_after_seconds, 7)

    def test_retry_after_delay_clamps_to_configured_maximum(self) -> None:
        permit = self.gate.acquire(_context(), 90_000, _allow).permit
        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            conn.execute("BEGIN IMMEDIATE")
            self.gate.complete_in_transaction(
                conn,
                permit,
                _observation(permit, 90_010, result="network_error", status="5xx"),
                90_010,
                upstream_status_code=503,
                retry_after_header="120",
            )
            conn.execute("COMMIT")
        finally:
            conn.close()

        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            until = conn.execute(
                "SELECT upstream_backoff_until_utc_ms FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
            ).fetchone()[0]
            self.assertEqual(until, 150_010)
        finally:
            conn.close()

    def test_retry_after_response_never_shortens_an_existing_deadline(self) -> None:
        permit = self.gate.acquire(_context(), 90_000, _allow).permit
        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE upstream_request_gate SET upstream_backoff_until_utc_ms=? "
                "WHERE endpoint_key='getUserInfo'",
                (200_000,),
            )
            self.gate.complete_in_transaction(
                conn,
                permit,
                _observation(permit, 90_010, result="network_error", status="5xx"),
                90_010,
                upstream_status_code=503,
                retry_after_header="1",
            )
            conn.execute("COMMIT")
        finally:
            conn.close()

        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            until = conn.execute(
                "SELECT upstream_backoff_until_utc_ms FROM upstream_request_gate WHERE endpoint_key='getUserInfo'"
            ).fetchone()[0]
            self.assertEqual(until, 200_000)
        finally:
            conn.close()

    def test_parallel_users_share_one_global_permit(self) -> None:
        barrier = Barrier(8)

        def acquire(index: int):
            barrier.wait()
            return self.gate.acquire(_context(f"user-{index}"), 100_000, _allow)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(acquire, range(8)))

        self.assertEqual(sum(item.allowed for item in results), 1)
        self.assertEqual(sorted(item.validation_attempt_id for item in results), list(range(1, 9)))
        self.assertEqual(sum(item.permit is not None for item in results), 1)


if __name__ == "__main__":
    unittest.main()
