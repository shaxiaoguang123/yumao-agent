from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3

from backend.auth.types import SessionContext, UserSummary
from backend.db import connect_database


def _hash_session_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


class SessionService:
    def __init__(
        self,
        database_path,
        busy_timeout_ms: int,
        csrf_hmac_secret: bytes,
        session_ttl_seconds: int = 86400,
    ):
        if not isinstance(csrf_hmac_secret, bytes) or len(csrf_hmac_secret) < 32:
            raise ValueError("csrf_hmac_secret must contain at least 32 bytes")
        if session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        self.database_path = database_path
        self.busy_timeout_ms = busy_timeout_ms
        self._csrf_hmac_secret = csrf_hmac_secret
        self.session_ttl_seconds = session_ttl_seconds

    def _new_session(
        self,
        connection: sqlite3.Connection,
        user_id: str,
        now_utc_ms: int,
    ) -> tuple[str, str]:
        user = connection.execute(
            "SELECT user_id FROM users WHERE user_id=? AND status='active'",
            (user_id,),
        ).fetchone()
        if user is None:
            raise ValueError("an active user is required")

        session_id = secrets.token_urlsafe(32)
        connection.execute(
            """INSERT INTO sessions
               (session_id_hash, user_id, created_at_utc_ms, expires_at_utc_ms,
                revoked_at_utc_ms, csrf_scheme_version)
               VALUES (?, ?, ?, ?, NULL, 1)""",
            (
                _hash_session_id(session_id),
                user_id,
                now_utc_ms,
                now_utc_ms + self.session_ttl_seconds * 1000,
            ),
        )
        return session_id, self.csrf_token_for(session_id, scheme_version=1)

    def create(self, user_id: str, now_utc_ms: int) -> tuple[str, str]:
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            connection.execute("BEGIN IMMEDIATE")
            result = self._new_session(connection, user_id, now_utc_ms)
            connection.execute("COMMIT")
            return result
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def rotate(
        self,
        old_session_id: str | None,
        target_user_id: str,
        now_utc_ms: int,
    ) -> tuple[str, str]:
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            connection.execute("BEGIN IMMEDIATE")
            if isinstance(old_session_id, str) and old_session_id:
                old_hash = _hash_session_id(old_session_id)
                old_session = connection.execute(
                    """SELECT session_id_hash FROM sessions
                       WHERE session_id_hash=?
                         AND user_id=?
                         AND expires_at_utc_ms>?
                         AND revoked_at_utc_ms IS NULL""",
                    (old_hash, target_user_id, now_utc_ms),
                ).fetchone()
                if old_session is not None:
                    connection.execute(
                        """UPDATE sessions SET revoked_at_utc_ms=?
                           WHERE session_id_hash=?
                             AND user_id=?
                             AND revoked_at_utc_ms IS NULL""",
                        (now_utc_ms, old_hash, target_user_id),
                    )

            result = self._new_session(connection, target_user_id, now_utc_ms)
            connection.execute("COMMIT")
            return result
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def resolve(
        self,
        session_id: str,
        now_utc_ms: int,
    ) -> SessionContext | None:
        if not isinstance(session_id, str) or not session_id:
            return None
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            row = connection.execute(
                """SELECT u.user_id, u.username, u.role, u.status,
                          s.expires_at_utc_ms, s.revoked_at_utc_ms, s.csrf_scheme_version
                   FROM sessions AS s
                   JOIN users AS u ON u.user_id=s.user_id
                   WHERE s.session_id_hash=?""",
                (_hash_session_id(session_id),),
            ).fetchone()
        finally:
            connection.close()

        if (
            row is None
            or row["status"] != "active"
            or row["revoked_at_utc_ms"] is not None
            or row["expires_at_utc_ms"] <= now_utc_ms
        ):
            return None
        user = UserSummary(row["user_id"], row["username"], row["role"])
        return SessionContext(user, row["csrf_scheme_version"])

    def revoke(self, session_id: str, now_utc_ms: int) -> bool:
        if not isinstance(session_id, str) or not session_id:
            return False
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """UPDATE sessions SET revoked_at_utc_ms=?
                   WHERE session_id_hash=? AND revoked_at_utc_ms IS NULL""",
                (now_utc_ms, _hash_session_id(session_id)),
            )
            connection.execute("COMMIT")
            return cursor.rowcount == 1
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def csrf_token_for(self, session_id: str, scheme_version: int = 1) -> str:
        if scheme_version != 1:
            raise ValueError("unsupported CSRF scheme version")
        message = b"csrf-v1:" + session_id.encode("utf-8")
        digest = hmac.new(self._csrf_hmac_secret, message, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def verify_csrf(self, session_id: str, supplied_token: str) -> bool:
        if not isinstance(session_id, str) or not isinstance(supplied_token, str):
            return False
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            row = connection.execute(
                "SELECT csrf_scheme_version FROM sessions WHERE session_id_hash=?",
                (_hash_session_id(session_id),),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return False
        try:
            expected = self.csrf_token_for(session_id, row["csrf_scheme_version"])
            return hmac.compare_digest(expected, supplied_token)
        except (TypeError, ValueError):
            return False
