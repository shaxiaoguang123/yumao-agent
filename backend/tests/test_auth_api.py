from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.util
import io
import logging
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from support import credential_test_settings


BUSY_TIMEOUT_MS = 5000
ORIGIN = "http://localhost:5173"


def _module(name: str):
    try:
        spec = importlib.util.find_spec(name)
    except ModuleNotFoundError:
        spec = None
    if spec is None:
        raise AssertionError(f"{name} must provide the V1 authentication API")
    return importlib.import_module(name)


class AuthApiTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory(prefix="yumao-auth-api-")
        self.addCleanup(temp_dir.cleanup)
        self.database_path = Path(temp_dir.name) / "identity.sqlite3"
        _module("backend.migrate").migrate_database(self.database_path, BUSY_TIMEOUT_MS)
        self.config = {
            **credential_test_settings(self.database_path),
            "TESTING": True,
            "APP_ALLOWED_ORIGINS": ORIGIN,
            "SESSION_TTL_SECONDS": 3600,
        }
        self.app = _module("backend.app").create_app(self.config)
        self.client = self.app.test_client()
        self.db = _module("backend.db")
        self.passwords = _module("backend.auth.passwords")
        self.sessions = self.app.extensions.get("session_service")
        self.invitations = _module("backend.auth.invitations").InvitationService(
            self.database_path, BUSY_TIMEOUT_MS
        )

    def _insert_user(self, user_id: str, username: str, password: str, role: str = "user") -> None:
        conn = self.db.connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            conn.execute(
                """INSERT INTO users
                   (user_id, username, normalized_username, password_hash, role, status,
                    created_at_utc_ms, updated_at_utc_ms)
                   VALUES (?, ?, ?, ?, ?, 'active', 1, 1)""",
                (
                    user_id,
                    username,
                    _module("backend.auth.invitations").normalize_username(username),
                    self.passwords.hash_password(password),
                    role,
                ),
            )
        finally:
            conn.close()

    def _origin_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        return {"Origin": ORIGIN, **(extra or {})}

    @staticmethod
    def _now_ms() -> int:
        return time.time_ns() // 1_000_000

    def _login(self, username: str, password: str, client=None):
        return (client or self.client).post(
            "/api/auth/login",
            json={"username": username, "password": password},
            headers=self._origin_headers(),
        )

    def _login_user(
        self,
        user_id: str,
        username: str,
        password: str,
        client=None,
        role: str = "user",
    ):
        self._insert_user(user_id, username, password, role=role)
        response = self._login(username, password, client)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["csrf_token"]

    def _post_with_csrf(self, client, path: str, csrf: str, **kwargs):
        headers = self._origin_headers({"X-CSRF-Token": csrf})
        return client.post(path, headers=headers, **kwargs)

    def _invitation(self, creator_id: str = "admin-1") -> str:
        self._insert_user(creator_id, "Admin", "admin password for tests", role="admin")
        return self.invitations.create(creator_id, 4_000_000_000_000)

    def _user_status(self, user_id: str) -> tuple[str, str]:
        conn = self.db.connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            row = conn.execute(
                "SELECT status, role FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
            return row["status"], row["role"]
        finally:
            conn.close()

    def _session_count(self, user_id: str) -> int:
        conn = self.db.connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE user_id=? AND revoked_at_utc_ms IS NULL",
                (user_id,),
            ).fetchone()[0]
        finally:
            conn.close()

    def test_session_endpoint_is_anonymous_until_login_and_returns_minimal_user(self) -> None:
        self._insert_user("user-1", "Alice", "alice correct test password")
        response = self.client.get("/api/auth/session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"authenticated": False})

        login = self._login("Alice", "alice correct test password")
        self.assertEqual(
            set(login.get_json()), {"authenticated", "user", "csrf_token"}
        )
        self.assertEqual(login.get_json()["user"], {
            "user_id": "user-1", "username": "Alice", "role": "user"
        })
        self.assertNotIn("session_id", login.get_json())
        self.assertNotIn("password_hash", login.get_json())
        self.assertEqual(self.client.get("/api/auth/session").get_json()["authenticated"], True)

    def test_login_sets_http_only_same_site_cookie_and_absolute_max_age(self) -> None:
        self._insert_user("user-1", "Alice", "alice correct test password")
        response = self._login("Alice", "alice correct test password")
        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn("yumao_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Max-Age=3600", cookie)
        self.assertNotIn("Secure", cookie)

    def test_production_session_cookie_is_secure(self) -> None:
        self._insert_user("user-1", "Alice", "alice correct test password")
        prod_app = _module("backend.app").create_app({
            **self.config,
            "APP_ENV": "production",
            "APP_ALLOWED_ORIGINS": ORIGIN,
        })
        response = prod_app.test_client().post(
            "/api/auth/login",
            json={"username": "Alice", "password": "alice correct test password"},
            headers=self._origin_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers["Set-Cookie"])

    def test_registration_requires_body_invite_and_never_accepts_client_role(self) -> None:
        invitation = self._invitation()
        query_only = self.client.post(
            f"/api/auth/register?invitation_code={invitation}",
            json={"username": "New User", "password": "new user strong password"},
            headers=self._origin_headers(),
        )
        self.assertEqual(query_only.status_code, 400)
        path_only = self.client.post(
            f"/api/auth/register/{invitation}",
            json={"username": "Path User", "password": "path user strong password"},
            headers=self._origin_headers(),
        )
        self.assertEqual(path_only.status_code, 404)

        response = self.client.post(
            "/api/auth/register",
            json={
                "invitation_code": invitation,
                "username": "  Ｎew User  ",
                "password": "new user strong password",
                "role": "admin",
                "is_admin": True,
            },
            headers=self._origin_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json(), {"user_id": response.get_json()["user_id"], "username": "  Ｎew User  "})
        self.assertEqual(self._user_status(response.get_json()["user_id"]), ("active", "user"))

        duplicate_invite = self.invitations.create("admin-1", 4_000_000_000_000)
        duplicate = self.client.post(
            "/api/auth/register",
            json={
                "invitation_code": duplicate_invite,
                "username": "new user",
                "password": "another strong test password",
            },
            headers=self._origin_headers(),
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertNotIn("admin", duplicate.get_data(as_text=True).lower())

    def test_invalid_invitation_is_generic_and_single_use(self) -> None:
        self._invitation()
        invalid = self.client.post(
            "/api/auth/register",
            json={"invitation_code": "wrong", "username": "New User", "password": "new user strong password"},
            headers=self._origin_headers(),
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.get_json()["error"], "invalid_invitation")

    def test_login_failure_is_generic_and_unknown_user_runs_dummy_verify(self) -> None:
        unknown = self.client.post(
            "/api/auth/login",
            json={"username": "Missing User", "password": "some strong test password"},
            headers=self._origin_headers(),
        )
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(unknown.get_json()["error"], "invalid_credentials")

        self._insert_user("user-1", "Alice", "alice correct test password")
        wrong = self._login("Alice", "incorrect strong test password")
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.get_json(), unknown.get_json())

    def test_auth_json_body_limit_rejects_oversized_login_before_parsing(self) -> None:
        response = self.client.post(
            "/api/auth/login",
            data='{"username":"' + ("x" * 17_000) + '","password":"some strong test password"}',
            content_type="application/json",
            headers=self._origin_headers(),
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json(), {"error": "request_too_large"})

    def test_auth_json_rejects_non_object_body(self) -> None:
        response = self.client.post(
            "/api/auth/login",
            data="[]",
            content_type="application/json",
            headers=self._origin_headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "invalid_request"})

    def test_auth_json_reports_parser_limit_errors_as_invalid_request(self) -> None:
        oversized_integer = '{"username":"Alice","password":"some strong test password","value":' + ("9" * 5000) + "}"
        deeply_nested = '{"username":"Alice","password":"some strong test password","value":' + ("{" * 1400) + '"end":true' + ("}" * 1400) + "}"

        for body in (oversized_integer, deeply_nested):
            with self.subTest(body_bytes=len(body)):
                response = self.client.post(
                    "/api/auth/login",
                    data=body,
                    content_type="application/json",
                    headers=self._origin_headers(),
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {"error": "invalid_request"})

    def test_unknown_user_uses_one_versioned_dummy_hash_verification(self) -> None:
        with patch("backend.api.auth.verify_password", return_value=False) as verify:
            response = self.client.post(
                "/api/auth/login",
                json={"username": "Missing User", "password": "some strong test password"},
                headers=self._origin_headers(),
            )
        self.assertEqual(response.status_code, 401)
        verify.assert_called_once()
        dummy_hash = verify.call_args.args[1]
        self.assertTrue(dummy_hash.startswith("scrypt$v1$n=32768$r=8$p=1$"))

    def test_login_is_rate_limited_by_username_across_ip_addresses_before_scrypt(self) -> None:
        self._insert_user("user-1", "Alice", "alice correct test password")
        app = _module("backend.app").create_app({
            **self.config,
            "LOGIN_USERNAME_ATTEMPT_LIMIT": 1,
            "LOGIN_IP_ATTEMPT_LIMIT": 20,
        })
        client = app.test_client()
        with patch("backend.api.auth.verify_password", return_value=False) as verify:
            first = client.post(
                "/api/auth/login",
                json={"username": "Alice", "password": "incorrect strong test password"},
                headers=self._origin_headers(),
                environ_base={"REMOTE_ADDR": "192.0.2.1"},
            )
            self.assertEqual(first.status_code, 401)
            self.assertEqual(verify.call_count, 1)
            second = client.post(
                "/api/auth/login",
                json={"username": "Alice", "password": "incorrect strong test password"},
                headers=self._origin_headers(),
                environ_base={"REMOTE_ADDR": "192.0.2.2"},
            )
            self.assertEqual(second.status_code, 429)
            self.assertIn("Retry-After", second.headers)
            self.assertEqual(verify.call_count, 1)

    def test_login_rechecks_password_hash_before_issuing_session(self) -> None:
        self._insert_user("user-1", "Alice", "alice correct test password")
        replacement_hash = self.passwords.hash_password("alice newer correct password")
        real_verify = self.passwords.verify_password
        changed = False

        def verify_then_change_password(password: str, stored_hash: str) -> bool:
            nonlocal changed
            verified = real_verify(password, stored_hash)
            if verified and not changed:
                changed = True
                conn = self.db.connect_database(self.database_path, BUSY_TIMEOUT_MS)
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "UPDATE users SET password_hash=?, updated_at_utc_ms=2 WHERE user_id=?",
                        (replacement_hash, "user-1"),
                    )
                    conn.execute(
                        "UPDATE sessions SET revoked_at_utc_ms=2 "
                        "WHERE user_id=? AND revoked_at_utc_ms IS NULL",
                        ("user-1",),
                    )
                    conn.execute("COMMIT")
                finally:
                    conn.close()
            return verified

        with patch("backend.api.auth.verify_password", side_effect=verify_then_change_password):
            response = self._login("Alice", "alice correct test password")

        self.assertTrue(changed)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"error": "invalid_credentials"})
        self.assertIsNone(self.client.get_cookie("yumao_session"))
        self.assertEqual(self._session_count("user-1"), 0)

    def test_login_is_rate_limited_by_source_ip_across_usernames(self) -> None:
        app = _module("backend.app").create_app({
            **self.config,
            "LOGIN_USERNAME_ATTEMPT_LIMIT": 20,
            "LOGIN_IP_ATTEMPT_LIMIT": 1,
        })
        client = app.test_client()
        for username in ("Alice", "Bob"):
            response = client.post(
                "/api/auth/login",
                json={"username": username, "password": "incorrect strong test password"},
                headers=self._origin_headers({"X-Forwarded-For": f"198.51.100.{len(username)}"}),
                environ_base={"REMOTE_ADDR": "192.0.2.7"},
            )
        self.assertEqual(response.status_code, 429)
        self.assertGreaterEqual(int(response.headers["Retry-After"]), 1)

    def test_optional_pair_limit_can_be_disabled_without_disabling_username_or_ip_limits(self) -> None:
        app = _module("backend.app").create_app({
            **self.config,
            "LOGIN_PAIR_ATTEMPT_LIMIT": 0,
            "LOGIN_USERNAME_ATTEMPT_LIMIT": 20,
            "LOGIN_IP_ATTEMPT_LIMIT": 20,
        })
        self.assertEqual(app.extensions["app_settings"].login_pair_attempt_limit, 0)

    def test_registration_is_rate_limited_by_source_ip_before_invitation_validation(self) -> None:
        self._invitation()
        app = _module("backend.app").create_app({
            **self.config,
            "REGISTER_IP_ATTEMPT_LIMIT": 1,
        })
        client = app.test_client()
        first = client.post(
            "/api/auth/register",
            json={"invitation_code": "invalid", "username": "First User", "password": "first strong password"},
            headers=self._origin_headers(),
            environ_base={"REMOTE_ADDR": "192.0.2.10"},
        )
        self.assertEqual(first.status_code, 400)
        second = client.post(
            "/api/auth/register",
            json={"invitation_code": "invalid", "username": "Second User", "password": "second strong password"},
            headers=self._origin_headers(),
            environ_base={"REMOTE_ADDR": "192.0.2.10"},
        )
        self.assertEqual(second.status_code, 429)
        self.assertIn("Retry-After", second.headers)

    def test_mutations_require_an_allowed_origin_or_referer(self) -> None:
        no_origin = self.client.post(
            "/api/auth/login", json={"username": "Alice", "password": "password"}
        )
        bad_origin = self.client.post(
            "/api/auth/login",
            json={"username": "Alice", "password": "password"},
            headers={"Origin": "https://attacker.invalid"},
        )
        referer = self.client.post(
            "/api/auth/login",
            json={"username": "Alice", "password": "password"},
            headers={"Referer": f"{ORIGIN}/login"},
        )
        self.assertEqual(no_origin.status_code, 403)
        self.assertEqual(bad_origin.status_code, 403)
        self.assertIn(referer.status_code, (200, 401))

    def test_registration_and_protected_mutations_reject_untrusted_origins(self) -> None:
        invite = self._invitation()
        invalid_registration = self.client.post(
            "/api/auth/register",
            json={"invitation_code": invite, "username": "New User", "password": "new user strong password"},
            headers={"Origin": "https://attacker.invalid"},
        )
        self.assertEqual(invalid_registration.status_code, 403)
        allowed_registration = self.client.post(
            "/api/auth/register",
            json={"invitation_code": invite, "username": "New User", "password": "new user strong password"},
            headers=self._origin_headers(),
        )
        self.assertEqual(allowed_registration.status_code, 201)

        admin_login = self._login("Admin", "admin password for tests")
        conflicting_headers = {
            "Origin": ORIGIN,
            "Referer": "https://attacker.invalid/login",
            "X-CSRF-Token": admin_login.get_json()["csrf_token"],
        }
        protected = self.client.post(
            "/api/admin/invitations", json={}, headers=conflicting_headers
        )
        self.assertEqual(protected.status_code, 403)

    def test_allowed_referer_with_query_is_accepted(self) -> None:
        response = self.client.post(
            "/api/auth/login",
            json={"username": "Missing User", "password": "some strong test password"},
            headers={"Referer": f"{ORIGIN}/login?next=%2Faccount"},
        )
        self.assertEqual(response.status_code, 401)

    def test_werkzeug_access_logs_do_not_expose_source_ip_or_request_target(self) -> None:
        logger = logging.getLogger("werkzeug")
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        try:
            logger.info(
                '"%s" %s',
                "192.0.2.99 - GET /api/auth/register?invite=synthetic-secret HTTP/1.1",
                400,
            )
        finally:
            logger.removeHandler(handler)
            handler.close()
            logger.setLevel(previous_level)
        message = stream.getvalue()
        self.assertNotIn("192.0.2.99", message)
        self.assertNotIn("synthetic-secret", message)
        self.assertNotIn("/api/auth/register", message)

    def test_protected_mutations_reject_missing_and_invalid_csrf_without_side_effect(self) -> None:
        self._login_user("admin-1", "Admin", "admin password for tests", role="admin")
        missing = self.client.post(
            "/api/admin/invitations", json={}, headers={"Origin": ORIGIN}
        )
        invalid = self.client.post(
            "/api/admin/invitations",
            json={},
            headers=self._origin_headers({"X-CSRF-Token": "invalid-csrf"}),
        )
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(invalid.status_code, 403)
        self.assertEqual(missing.get_json()["error"], "csrf_invalid")
        self.assertEqual(invalid.get_json()["error"], "csrf_invalid")
        self.assertEqual(self.invitations_count(), 0)

    def invitations_count(self) -> int:
        conn = self.db.connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            return conn.execute("SELECT COUNT(*) FROM invitations").fetchone()[0]
        finally:
            conn.close()

    def test_allowed_origin_cors_preflight_allows_credentials_and_csrf_header(self) -> None:
        response = self.client.options(
            "/api/auth/login",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-csrf-token",
            },
        )
        self.assertIn(response.status_code, (200, 204))
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), ORIGIN)
        self.assertEqual(response.headers.get("Access-Control-Allow-Credentials"), "true")
        self.assertIn("X-CSRF-Token", response.headers.get("Access-Control-Allow-Headers", ""))

    def test_same_user_login_rotation_invalidates_old_session_and_both_cross_pairs(self) -> None:
        self._insert_user("user-1", "Alice", "alice correct test password")
        first = self._login("Alice", "alice correct test password")
        old_session = self.client.get_cookie("yumao_session").value
        old_csrf = first.get_json()["csrf_token"]
        second = self._login("Alice", "alice correct test password")
        new_session = self.client.get_cookie("yumao_session").value
        new_csrf = second.get_json()["csrf_token"]

        self.assertNotEqual(old_session, new_session)
        self.assertNotEqual(old_csrf, new_csrf)
        self.assertIsNone(self.sessions.resolve(old_session, self._now_ms()))
        self.assertIsNotNone(self.sessions.resolve(new_session, self._now_ms()))
        self.assertFalse(self.sessions.verify_csrf(new_session, old_csrf))
        self.assertFalse(self.sessions.verify_csrf(old_session, new_csrf))

    def test_logging_in_as_another_user_does_not_revoke_previous_server_session(self) -> None:
        self._insert_user("user-a", "Alice", "alice correct test password")
        self._insert_user("user-b", "Bob", "bob correct test password")
        self.assertEqual(self._login("Alice", "alice correct test password").status_code, 200)
        alice_session = self.client.get_cookie("yumao_session").value
        bob_login = self._login("Bob", "bob correct test password")
        bob_session = self.client.get_cookie("yumao_session").value

        self.assertEqual(bob_login.status_code, 200)
        self.assertNotEqual(alice_session, bob_session)
        self.assertEqual(self.sessions.resolve(alice_session, self._now_ms()).user.user_id, "user-a")
        self.assertEqual(self.sessions.resolve(bob_session, self._now_ms()).user.user_id, "user-b")
        self.assertEqual(self.client.get("/api/auth/session").get_json()["user"]["user_id"], "user-b")

    def test_logout_revokes_session_and_second_logout_is_definitively_invalid(self) -> None:
        csrf = self._login_user("user-1", "Alice", "alice correct test password")
        session_id = self.client.get_cookie("yumao_session").value
        logout = self._post_with_csrf(self.client, "/api/auth/logout", csrf)
        self.assertEqual(logout.status_code, 204)
        self.assertIsNone(self.sessions.resolve(session_id, self._now_ms()))
        again = self.client.post(
            "/api/auth/logout", headers=self._origin_headers({"X-CSRF-Token": csrf})
        )
        self.assertEqual(again.status_code, 401)
        self.assertIn(again.get_json()["error"], {"session_invalid", "session_expired", "session_revoked"})

    def test_expired_session_is_not_authenticated_and_logout_returns_expired_code(self) -> None:
        csrf = self._login_user("user-1", "Alice", "alice correct test password")
        session_id = self.client.get_cookie("yumao_session").value
        conn = self.db.connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            conn.execute(
                "UPDATE sessions SET expires_at_utc_ms=0 WHERE session_id_hash=?",
                (hashlib.sha256(session_id.encode()).hexdigest(),),
            )
        finally:
            conn.close()
        self.assertFalse(self.client.get("/api/auth/session").get_json()["authenticated"])
        logout = self.client.post(
            "/api/auth/logout", headers=self._origin_headers({"X-CSRF-Token": csrf})
        )
        self.assertEqual(logout.status_code, 401)
        self.assertIn(logout.get_json()["error"], {"session_invalid", "session_expired", "session_revoked"})

    def test_server_revoked_session_cannot_logout_as_success(self) -> None:
        csrf = self._login_user("user-1", "Alice", "alice correct test password")
        session_id = self.client.get_cookie("yumao_session").value
        self.assertTrue(self.sessions.revoke(session_id, 10_000))
        response = self.client.post(
            "/api/auth/logout", headers=self._origin_headers({"X-CSRF-Token": csrf})
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn(response.get_json()["error"], {"session_invalid", "session_expired", "session_revoked"})

    def test_password_change_revokes_all_user_sessions_and_clears_cookie(self) -> None:
        self._insert_user("user-1", "Alice", "alice correct test password")
        first = self._login("Alice", "alice correct test password")
        first_session = self.client.get_cookie("yumao_session").value
        other_client = self.app.test_client()
        self.assertEqual(
            other_client.post(
                "/api/auth/login",
                json={"username": "Alice", "password": "alice correct test password"},
                headers=self._origin_headers(),
            ).status_code,
            200,
        )
        other_session = other_client.get_cookie("yumao_session").value
        response = self._post_with_csrf(
            self.client,
            "/api/auth/change-password",
            first.get_json()["csrf_token"],
            json={
                "current_password": "alice correct test password",
                "new_password": "alice newer strong test password",
            },
        )
        self.assertEqual(response.status_code, 204)
        self.assertIsNone(self.sessions.resolve(first_session, self._now_ms()))
        self.assertIsNone(self.sessions.resolve(other_session, self._now_ms()))
        self.assertIsNone(self.client.get_cookie("yumao_session"))

    def test_wrong_current_password_does_not_invalidate_the_session(self) -> None:
        csrf = self._login_user("user-1", "Alice", "alice correct test password")
        response = self._post_with_csrf(
            self.client,
            "/api/auth/change-password",
            csrf,
            json={
                "current_password": "wrong current password",
                "new_password": "alice newer strong test password",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "current_password_invalid")
        self.assertTrue(self.client.get("/api/auth/session").get_json()["authenticated"])

    def test_password_change_attempts_are_rate_limited_per_user_before_password_verification(self) -> None:
        self._insert_user("user-1", "Alice", "alice correct test password")
        limited_app = _module("backend.app").create_app({
            **self.config,
            "PASSWORD_CHANGE_USER_ATTEMPT_LIMIT": 1,
            "PASSWORD_CHANGE_USER_WINDOW_SECONDS": 900,
            "PASSWORD_CHANGE_IP_ATTEMPT_LIMIT": 10,
            "PASSWORD_CHANGE_IP_WINDOW_SECONDS": 900,
        })
        client = limited_app.test_client()
        login = client.post(
            "/api/auth/login",
            json={"username": "Alice", "password": "alice correct test password"},
            headers=self._origin_headers(),
        )
        self.assertEqual(login.status_code, 200)
        csrf = login.get_json()["csrf_token"]
        body = {
            "current_password": "wrong current password",
            "new_password": "alice newer strong password",
        }

        with patch("backend.api.auth.verify_password", return_value=False) as verify:
            first = self._post_with_csrf(
                client, "/api/auth/change-password", csrf, json=body,
                environ_overrides={"REMOTE_ADDR": "198.51.100.10"},
            )
            second = self._post_with_csrf(
                client, "/api/auth/change-password", csrf, json=body,
                environ_overrides={"REMOTE_ADDR": "198.51.100.11"},
            )

        self.assertEqual(first.status_code, 400)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.get_json()["error"], "rate_limited")
        self.assertGreaterEqual(int(second.headers["Retry-After"]), 1)
        verify.assert_called_once()

    def test_old_session_and_csrf_pair_cannot_reach_protected_mutation_after_rotation(self) -> None:
        self._insert_user("user-1", "Alice", "alice correct test password")
        first = self._login("Alice", "alice correct test password")
        old_session = self.client.get_cookie("yumao_session").value
        old_csrf = first.get_json()["csrf_token"]
        self._login("Alice", "alice correct test password")

        old_client = self.app.test_client()
        old_client.set_cookie("yumao_session", old_session)
        old_pair = old_client.post(
            "/api/auth/logout",
            headers=self._origin_headers({"X-CSRF-Token": old_csrf}),
        )
        new_session_old_csrf = self.client.post(
            "/api/auth/logout",
            headers=self._origin_headers({"X-CSRF-Token": old_csrf}),
        )

        self.assertEqual(old_pair.status_code, 401)
        self.assertEqual(new_session_old_csrf.status_code, 403)
        self.assertTrue(self.client.get("/api/auth/session").get_json()["authenticated"])

    def test_admin_can_create_single_use_invitation_but_user_cannot(self) -> None:
        admin_csrf = self._login_user(
            "admin-1", "Admin", "admin password for tests", role="admin"
        )
        response = self._post_with_csrf(
            self.client, "/api/admin/invitations", admin_csrf, json={}
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        code = response.get_json()["invitation_code"]
        self.assertTrue(code)
        conn = self.db.connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            stored = conn.execute("SELECT invitation_code_hash FROM invitations").fetchone()[0]
            self.assertEqual(stored, hashlib.sha256(code.encode()).hexdigest())
            self.assertNotIn(code, stored)
        finally:
            conn.close()

        self._insert_user("user-1", "Alice", "alice correct test password")
        user_client = self.app.test_client()
        user_login = user_client.post(
            "/api/auth/login",
            json={"username": "Alice", "password": "alice correct test password"},
            headers=self._origin_headers(),
        )
        forbidden = user_client.post(
            "/api/admin/invitations",
            json={},
            headers=self._origin_headers({"X-CSRF-Token": user_login.get_json()["csrf_token"]}),
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_admin_cannot_disable_self_and_can_disable_another_admin(self) -> None:
        csrf = self._login_user("admin-1", "Admin", "admin password for tests", role="admin")
        self_response = self._post_with_csrf(
            self.client, "/api/admin/users/admin-1/disable", csrf, json={}
        )
        self.assertEqual(self_response.status_code, 409)
        self.assertEqual(self._user_status("admin-1")[0], "active")

        self._insert_user("admin-2", "Admin Two", "second admin test password", role="admin")
        disable_other = self._post_with_csrf(
            self.client, "/api/admin/users/admin-2/disable", csrf, json={}
        )
        self.assertEqual(disable_other.status_code, 204)
        self.assertEqual(self._user_status("admin-2")[0], "disabled")

    def test_disabling_user_revokes_all_of_their_sessions(self) -> None:
        csrf = self._login_user("admin-1", "Admin", "admin password for tests", role="admin")
        self._insert_user("user-1", "Alice", "alice correct test password")
        user_client = self.app.test_client()
        user_client.post(
            "/api/auth/login",
            json={"username": "Alice", "password": "alice correct test password"},
            headers=self._origin_headers(),
        )
        user_session = user_client.get_cookie("yumao_session").value
        response = self._post_with_csrf(
            self.client, "/api/admin/users/user-1/disable", csrf, json={}
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self._user_status("user-1")[0], "disabled")
        self.assertIsNone(self.sessions.resolve(user_session, self._now_ms()))

    def test_concurrent_admin_disables_cannot_remove_last_active_admin(self) -> None:
        self._insert_user("admin-a", "Admin A", "admin a strong password", role="admin")
        self._insert_user("admin-b", "Admin B", "admin b strong password", role="admin")
        clients = [self.app.test_client(), self.app.test_client()]
        tokens = []
        for client, username, password in zip(
            clients, ("Admin A", "Admin B"), ("admin a strong password", "admin b strong password")
        ):
            login = client.post(
                "/api/auth/login",
                json={"username": username, "password": password},
                headers=self._origin_headers(),
            )
            self.assertEqual(login.status_code, 200)
            tokens.append(login.get_json()["csrf_token"])

        barrier = Barrier(2)

        def disable(index: int):
            actor, target = (("admin-a", "admin-b"), ("admin-b", "admin-a"))[index]
            barrier.wait()
            return clients[index].post(
                f"/api/admin/users/{target}/disable",
                json={},
                headers=self._origin_headers({"X-CSRF-Token": tokens[index]}),
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(disable, (0, 1)))
        conn = self.db.connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            active_admins = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND status='active'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertGreaterEqual(active_admins, 1)
        self.assertTrue(all(status in (204, 401, 403, 409) for status in statuses), statuses)


class FirstAdminBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory(prefix="yumao-first-admin-")
        self.addCleanup(temp_dir.cleanup)
        self.database_path = Path(temp_dir.name) / "identity.sqlite3"
        _module("backend.migrate").migrate_database(self.database_path, BUSY_TIMEOUT_MS)

    def test_concurrent_first_admin_bootstrap_creates_exactly_one_administrator(self) -> None:
        create_first_admin = _module("backend.cli").create_first_admin
        password_hash = _module("backend.auth.passwords").hash_password(
            "first administrator synthetic password"
        )

        barrier = Barrier(2)

        def create(username: str):
            barrier.wait()
            try:
                return create_first_admin(
                    self.database_path,
                    BUSY_TIMEOUT_MS,
                    username,
                    password_hash,
                    1000,
                )
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, ("Admin One", "Admin Two")))
        self.assertEqual(sum(result is not None for result in results), 1)

        conn = _module("backend.db").connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0], 1
            )
        finally:
            conn.close()

    def test_cli_does_not_accept_a_password_command_line_argument(self) -> None:
        main = _module("backend.cli").main
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main(["create-admin", "--username", "Admin One", "--password", "not-on-command-line"])
        self.assertEqual(raised.exception.code, 2)

    def test_python_module_entrypoint_dispatches_to_the_cli(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "backend.cli", "--help"],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("create-admin", completed.stdout)


if __name__ == "__main__":
    unittest.main()
