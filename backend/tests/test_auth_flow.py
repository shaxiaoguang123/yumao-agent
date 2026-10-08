from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from backend.app import create_app
from backend.auth.passwords import hash_password
from backend.auth.types import UserSummary
from backend.cli import create_first_admin
from backend.db import connect_database
from backend.migrate import migrate_database
from support import credential_test_settings


BUSY_TIMEOUT_MS = 5000
ORIGIN = "http://localhost:5173"


class AuthFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="yumao-auth-flow-")
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "flow.sqlite3"
        migrate_database(self.database_path, BUSY_TIMEOUT_MS)
        self.app = create_app({
            **credential_test_settings(self.database_path),
            "TESTING": True,
            "APP_ALLOWED_ORIGINS": ORIGIN,
        })
        self.admin: UserSummary = create_first_admin(
            self.database_path,
            BUSY_TIMEOUT_MS,
            "Bootstrap Admin",
            hash_password("synthetic bootstrap admin password"),
            time.time_ns() // 1_000_000,
        )
        self.admin_client = self.app.test_client()
        admin_login = self.admin_client.post(
            "/api/auth/login",
            json={"username": self.admin.username, "password": "synthetic bootstrap admin password"},
            headers={"Origin": ORIGIN},
        )
        self.assertEqual(admin_login.status_code, 200)
        self.admin_csrf = admin_login.get_json()["csrf_token"]
        self.invitation_service = self.app.extensions["invitation_service"]

    def _register_user(self, client, username: str, invitation_code: str, password: str) -> None:
        response = client.post(
            "/api/auth/register",
            json={
                "invitation_code": invitation_code,
                "username": username,
                "password": password,
            },
            headers={"Origin": ORIGIN},
        )
        self.assertEqual(response.status_code, 201)

    def test_two_invited_users_remain_isolated_across_sessions_and_admin_routes(self) -> None:
        expires_at = time.time_ns() // 1_000_000 + 60 * 60 * 1000
        invitation_a = self.invitation_service.create(self.admin.user_id, expires_at)
        invitation_b = self.invitation_service.create(self.admin.user_id, expires_at)
        client_a = self.app.test_client()
        client_b = self.app.test_client()

        self._register_user(client_a, "Alice Example", invitation_a, "alice synthetic password")
        self._register_user(client_b, "Bob Example", invitation_b, "bob synthetic password")

        login_a = client_a.post(
            "/api/auth/login",
            json={"username": "Alice Example", "password": "alice synthetic password"},
            headers={"Origin": ORIGIN},
        )
        login_b = client_b.post(
            "/api/auth/login",
            json={"username": "Bob Example", "password": "bob synthetic password"},
            headers={"Origin": ORIGIN},
        )
        self.assertEqual(login_a.status_code, 200)
        self.assertEqual(login_b.status_code, 200)

        session_a = client_a.get("/api/auth/session?user_id=not-the-current-user")
        session_b = client_b.get("/api/auth/session")
        self.assertEqual(session_a.get_json()["user"]["username"], "Alice Example")
        self.assertEqual(session_b.get_json()["user"]["username"], "Bob Example")

        forged_admin_request = client_a.post(
            "/api/admin/invitations",
            json={"user_id": self.admin.user_id},
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": login_a.get_json()["csrf_token"],
            },
        )
        self.assertEqual(forged_admin_request.status_code, 403)

        valid_admin_request = self.admin_client.post(
            "/api/admin/invitations",
            json={},
            headers={"Origin": ORIGIN, "X-CSRF-Token": self.admin_csrf},
        )
        self.assertEqual(valid_admin_request.status_code, 201)

        conn = connect_database(self.database_path, BUSY_TIMEOUT_MS)
        try:
            conn.execute(
                "UPDATE users SET status='disabled', disabled_at_utc_ms=? "
                "WHERE normalized_username='bob example'",
                (time.time_ns() // 1_000_000,),
            )
        finally:
            conn.close()
        inactive_session = client_b.get("/api/auth/session")
        self.assertEqual(inactive_session.get_json(), {"authenticated": False})


if __name__ == "__main__":
    unittest.main()
