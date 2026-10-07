from __future__ import annotations

import base64
import hashlib
import importlib
import importlib.util
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


BUSY_TIMEOUT_MS = 5000
CSRF_SECRET = bytes(range(32))


def _module(name: str):
    try:
        spec = importlib.util.find_spec(name)
    except ModuleNotFoundError:
        spec = None
    if spec is None:
        raise AssertionError(f"{name} must provide the V1 auth service")
    return importlib.import_module(name)


def _new_database(testcase: unittest.TestCase) -> Path:
    migrate_database = _module("backend.migrate").migrate_database
    temp_dir = tempfile.TemporaryDirectory(prefix="yumao-auth-service-")
    testcase.addCleanup(temp_dir.cleanup)
    database_path = Path(temp_dir.name) / "identity.sqlite3"
    migrate_database(database_path, BUSY_TIMEOUT_MS)
    return database_path


def _insert_user(database_path: Path, user_id: str, username: str, role: str = "user") -> None:
    connect_database = _module("backend.db").connect_database
    conn = connect_database(database_path, BUSY_TIMEOUT_MS)
    try:
        conn.execute(
            """INSERT INTO users
               (user_id, username, normalized_username, password_hash, role, status,
                created_at_utc_ms, updated_at_utc_ms)
               VALUES (?, ?, ?, ?, ?, 'active', 1, 1)""",
            (user_id, username, username.casefold(), "synthetic-password-hash", role),
        )
    finally:
        conn.close()


class PasswordServiceTests(unittest.TestCase):
    def test_hashes_are_salted_versioned_and_verify_correct_and_wrong_passwords(self) -> None:
        passwords = _module("backend.auth.passwords")
        password = "correct synthetic password"
        first_hash = passwords.hash_password(password)
        second_hash = passwords.hash_password(password)
        self.assertNotEqual(first_hash, second_hash)
        self.assertTrue(first_hash.startswith("scrypt$v1$"))
        self.assertTrue(passwords.verify_password(password, first_hash))
        self.assertFalse(passwords.verify_password("incorrect password", first_hash))

    def test_malformed_and_unknown_hash_versions_are_rejected_safely(self) -> None:
        verify_password = _module("backend.auth.passwords").verify_password
        self.assertFalse(verify_password("any password", ""))
        self.assertFalse(verify_password("any password", "scrypt$v99$broken"))

    def test_password_length_boundaries_are_enforced_without_weak_fallback(self) -> None:
        passwords = _module("backend.auth.passwords")
        with self.assertRaises(ValueError):
            passwords.hash_password("short")
        with self.assertRaises(ValueError):
            passwords.hash_password("x" * 1025)
        stored_hash = passwords.hash_password("x" * 12)
        self.assertTrue(passwords.verify_password("x" * 12, stored_hash))


class UsernameTests(unittest.TestCase):
    def test_nfkc_trim_casefold_normalizes_comparison_without_changing_display_value(self) -> None:
        normalize_username = _module("backend.auth.invitations").normalize_username
        self.assertEqual(normalize_username("  Ａlice  "), "alice")
        self.assertEqual(normalize_username("Straße"), "strasse")


class SessionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = _new_database(self)
        _insert_user(self.database_path, "user-a", "Alice")
        _insert_user(self.database_path, "user-b", "Bob")
        self.service = _module("backend.auth.sessions").SessionService(
            self.database_path,
            BUSY_TIMEOUT_MS,
            CSRF_SECRET,
            session_ttl_seconds=100,
        )

    def test_only_session_id_hash_and_csrf_scheme_are_persisted(self) -> None:
        connect_database = _module("backend.db").connect_database
        session_id, csrf_token = self.service.create("user-a", now_utc_ms=1_000)
        expected_hash = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            row = conn.execute(
                "SELECT session_id_hash, csrf_scheme_version FROM sessions"
            ).fetchone()
            self.assertEqual(row["session_id_hash"], expected_hash)
            self.assertEqual(row["csrf_scheme_version"], 1)
            stored = repr(tuple(row))
            self.assertNotIn(session_id, stored)
            self.assertNotIn(csrf_token, stored)
        finally:
            conn.close()

    def test_expired_and_revoked_sessions_do_not_resolve(self) -> None:
        session_id, _csrf = self.service.create("user-a", now_utc_ms=1_000)
        self.assertIsNotNone(self.service.resolve(session_id, now_utc_ms=100_999))
        self.assertIsNone(self.service.resolve(session_id, now_utc_ms=101_000))

        active_id, _csrf = self.service.create("user-a", now_utc_ms=2_000)
        self.assertTrue(self.service.revoke(active_id, now_utc_ms=2_001))
        self.assertIsNone(self.service.resolve(active_id, now_utc_ms=2_001))

    def test_same_user_rotation_revokes_old_session_and_binds_csrf_to_each_id(self) -> None:
        old_id, old_csrf = self.service.create("user-a", now_utc_ms=1_000)
        new_id, new_csrf = self.service.rotate(old_id, "user-a", now_utc_ms=1_001)

        self.assertIsNone(self.service.resolve(old_id, now_utc_ms=1_001))
        self.assertIsNotNone(self.service.resolve(new_id, now_utc_ms=1_001))
        self.assertNotEqual(old_id, new_id)
        self.assertNotEqual(old_csrf, new_csrf)
        self.assertTrue(self.service.verify_csrf(new_id, new_csrf))
        self.assertFalse(self.service.verify_csrf(old_id, new_csrf))
        self.assertFalse(self.service.verify_csrf(new_id, old_csrf))

    def test_cross_user_login_rotation_does_not_revoke_previous_users_session(self) -> None:
        user_a_session, _user_a_csrf = self.service.create("user-a", now_utc_ms=1_000)
        user_b_session, _user_b_csrf = self.service.rotate(
            user_a_session, "user-b", now_utc_ms=1_001
        )

        user_a_context = self.service.resolve(user_a_session, now_utc_ms=1_001)
        user_b_context = self.service.resolve(user_b_session, now_utc_ms=1_001)
        self.assertIsNotNone(user_a_context)
        self.assertEqual(user_a_context.user.user_id, "user-a")
        self.assertIsNotNone(user_b_context)
        self.assertEqual(user_b_context.user.user_id, "user-b")

    def test_missing_or_expired_old_session_still_creates_new_session(self) -> None:
        new_id, _csrf = self.service.rotate("not-a-valid-session", "user-a", now_utc_ms=1_000)
        self.assertIsNotNone(self.service.resolve(new_id, now_utc_ms=1_000))
        old_id, _old_csrf = self.service.create("user-a", now_utc_ms=2_000)
        rotated_id, _rotated_csrf = self.service.rotate(old_id, "user-a", now_utc_ms=102_000)
        self.assertIsNone(self.service.resolve(old_id, now_utc_ms=102_000))
        self.assertIsNotNone(self.service.resolve(rotated_id, now_utc_ms=102_000))


class InvitationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = _new_database(self)
        _insert_user(self.database_path, "admin-a", "Admin", role="admin")
        self.service = _module("backend.auth.invitations").InvitationService(
            self.database_path,
            BUSY_TIMEOUT_MS,
        )

    def _future_expiry(self) -> int:
        import time
        return time.time_ns() // 1_000_000 + 60_000

    def test_invitation_is_single_use_and_display_username_is_preserved(self) -> None:
        connect_database = _module("backend.db").connect_database
        code = self.service.create("admin-a", self._future_expiry())
        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            stored_code_hash = conn.execute(
                "SELECT invitation_code_hash FROM invitations"
            ).fetchone()[0]
            self.assertEqual(stored_code_hash, hashlib.sha256(code.encode("utf-8")).hexdigest())
            self.assertNotIn(code, stored_code_hash)
        finally:
            conn.close()
        created = self.service.redeem(code, "  Ａlice  ", "synthetic-hash", now_utc_ms=2_000)
        self.assertEqual(created.username, "  Ａlice  ")
        with self.assertRaises(ValueError):
            self.service.redeem(code, "another-user", "synthetic-hash", now_utc_ms=2_001)

        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            row = conn.execute(
                "SELECT username, normalized_username FROM users WHERE user_id=?",
                (created.user_id,),
            ).fetchone()
            self.assertEqual(tuple(row), ("  Ａlice  ", "alice"))
        finally:
            conn.close()

    def test_expired_invitation_is_rejected(self) -> None:
        connect_database = _module("backend.db").connect_database
        code = self.service.create("admin-a", self._future_expiry())
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            conn.execute(
                "UPDATE invitations SET expires_at_utc_ms=? WHERE invitation_code_hash=?",
                (1_000, code_hash),
            )
        finally:
            conn.close()
        with self.assertRaises(ValueError):
            self.service.redeem(code, "Alice", "synthetic-hash", now_utc_ms=1_001)

    def test_concurrent_redemption_of_one_code_creates_one_user(self) -> None:
        connect_database = _module("backend.db").connect_database
        code = self.service.create("admin-a", self._future_expiry())

        def redeem():
            try:
                return self.service.redeem(
                    code, "Concurrent User", "synthetic-hash", now_utc_ms=3_000
                )
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: redeem(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)

        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM users WHERE normalized_username='concurrent user'"
                ).fetchone()[0],
                1,
            )
        finally:
            conn.close()

    def test_normalized_duplicate_username_is_rejected(self) -> None:
        code_a = self.service.create("admin-a", self._future_expiry())
        code_b = self.service.create("admin-a", self._future_expiry())
        self.service.redeem(code_a, "Straße", "synthetic-hash", now_utc_ms=4_000)
        with self.assertRaises(ValueError):
            self.service.redeem(code_b, "STRASSE", "synthetic-hash", now_utc_ms=4_001)


class RateLimitServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = _new_database(self)
        self.service = _module("backend.auth.rate_limit").RateLimitService(
            self.database_path,
            BUSY_TIMEOUT_MS,
        )
        self.bucket_type = _module("backend.auth.rate_limit").RateLimitBucket

    def _bucket(self, kind: str, key: str, limit: int, window: int):
        return self.bucket_type("login", kind, key, limit, window)

    def test_bucket_event_type_is_explicit_and_must_match_request(self) -> None:
        try:
            bucket = self.bucket_type(
                event_type="login",
                bucket_type="username",
                bucket_key="alice",
                limit=2,
                window_seconds=60,
            )
        except TypeError as exc:
            self.fail(f"RateLimitBucket must include its event_type: {exc}")
        with self.assertRaises(ValueError):
            self.service.check_and_record("register", [bucket], now_utc_ms=1_000)

    def _count(self, bucket_type: str, key: str) -> int:
        conn = _module("backend.db").connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM auth_attempts "
                "WHERE event_type='login' AND bucket_type=? AND bucket_key=?",
                (bucket_type, key),
            ).fetchone()[0]
        finally:
            conn.close()

    def test_rolling_window_includes_exact_boundary_and_expires_after_it(self) -> None:
        bucket = self._bucket("username", "alice", 1, 10)
        first = self.service.check_and_record("login", [bucket], now_utc_ms=100_000)
        at_boundary = self.service.check_and_record("login", [bucket], now_utc_ms=110_000)
        after_boundary = self.service.check_and_record("login", [bucket], now_utc_ms=110_001)

        self.assertTrue(first.allowed)
        self.assertFalse(at_boundary.allowed)
        self.assertEqual(at_boundary.retry_after_seconds, 1)
        self.assertTrue(after_boundary.allowed)

    def test_all_buckets_are_recorded_or_none_when_one_is_limited(self) -> None:
        username = self._bucket("username", "alice", 2, 10)
        source_ip = self._bucket("source_ip", "192.0.2.7", 2, 10)
        self.assertTrue(
            self.service.check_and_record("login", [username, source_ip], now_utc_ms=100_000).allowed
        )
        self.assertTrue(
            self.service.check_and_record("login", [source_ip], now_utc_ms=101_000).allowed
        )

        denied = self.service.check_and_record(
            "login", [username, source_ip], now_utc_ms=102_000
        )
        self.assertFalse(denied.allowed)
        self.assertEqual(self._count("username", "alice"), 1)
        self.assertEqual(self._count("source_ip", "192.0.2.7"), 2)

        allowed_username_only = self.service.check_and_record(
            "login", [username], now_utc_ms=102_000
        )
        self.assertTrue(allowed_username_only.allowed)
        self.assertEqual(self._count("username", "alice"), 2)

    def test_retry_after_uses_longest_blocked_bucket_from_same_window_snapshot(self) -> None:
        soon = self._bucket("username", "alice", 1, 10)
        later = self._bucket("source_ip", "192.0.2.9", 1, 10)
        self.assertTrue(self.service.check_and_record("login", [soon], now_utc_ms=95_000).allowed)
        self.assertTrue(self.service.check_and_record("login", [later], now_utc_ms=99_000).allowed)

        denied = self.service.check_and_record(
            "login", [soon, later], now_utc_ms=100_000
        )
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.retry_after_seconds, 10)

    def test_concurrent_attempts_cannot_exceed_bucket_limit(self) -> None:
        bucket = self._bucket("username", "parallel-user", 3, 60)

        def attempt(_index: int) -> bool:
            return self.service.check_and_record(
                "login", [bucket], now_utc_ms=200_000
            ).allowed

        with ThreadPoolExecutor(max_workers=8) as executor:
            decisions = list(executor.map(attempt, range(12)))
        self.assertEqual(sum(decisions), 3)
        self.assertEqual(self._count("username", "parallel-user"), 3)


if __name__ == "__main__":
    unittest.main()
