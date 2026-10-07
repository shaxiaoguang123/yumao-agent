from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
import unicodedata
import uuid

from backend.auth.types import UserSummary
from backend.db import connect_database


def normalize_username(username: str) -> str:
    if not isinstance(username, str):
        raise ValueError("username must be text")
    return unicodedata.normalize("NFKC", username).strip().casefold()


def _validated_username(username: str) -> tuple[str, str]:
    if not isinstance(username, str):
        raise ValueError("username must be text")
    if any(unicodedata.category(character).startswith("C") for character in username):
        raise ValueError("username contains a control character")
    normalized = normalize_username(username)
    if not 3 <= len(normalized) <= 64:
        raise ValueError("normalized username length must be between 3 and 64 code points")
    return username, normalized


def _hash_invitation(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class InvitationService:
    def __init__(self, database_path, busy_timeout_ms: int):
        self.database_path = database_path
        self.busy_timeout_ms = busy_timeout_ms

    def create(self, created_by_user_id: str, expires_at_utc_ms: int) -> str:
        now_utc_ms = time.time_ns() // 1_000_000
        if expires_at_utc_ms <= now_utc_ms:
            raise ValueError("invitation expiry must be in the future")

        code = secrets.token_urlsafe(32)
        code_hash = _hash_invitation(code)
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            connection.execute("BEGIN IMMEDIATE")
            creator = connection.execute(
                "SELECT role, status FROM users WHERE user_id=?",
                (created_by_user_id,),
            ).fetchone()
            if creator is None or creator["role"] != "admin" or creator["status"] != "active":
                raise ValueError("an active administrator is required")
            connection.execute(
                """INSERT INTO invitations
                   (invitation_code_hash, created_by_user_id, created_at_utc_ms,
                    expires_at_utc_ms, redeemed_at_utc_ms, revoked_at_utc_ms)
                   VALUES (?, ?, ?, ?, NULL, NULL)""",
                (code_hash, created_by_user_id, now_utc_ms, expires_at_utc_ms),
            )
            connection.execute("COMMIT")
            return code
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def redeem(
        self,
        code: str,
        username: str,
        password_hash: str,
        now_utc_ms: int,
    ) -> UserSummary:
        display_username, normalized_username = _validated_username(username)
        if not isinstance(code, str) or not code:
            raise ValueError("invalid or unavailable invitation")
        code_hash = _hash_invitation(code)
        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            connection.execute("BEGIN IMMEDIATE")
            invitation = connection.execute(
                """SELECT invitation_code_hash FROM invitations
                   WHERE invitation_code_hash=?
                     AND expires_at_utc_ms>?
                     AND redeemed_at_utc_ms IS NULL
                     AND revoked_at_utc_ms IS NULL""",
                (code_hash, now_utc_ms),
            ).fetchone()
            if invitation is None:
                raise ValueError("invalid or unavailable invitation")

            user_id = uuid.uuid4().hex
            connection.execute(
                """INSERT INTO users
                   (user_id, username, normalized_username, password_hash, role, status,
                    created_at_utc_ms, updated_at_utc_ms, disabled_at_utc_ms)
                   VALUES (?, ?, ?, ?, 'user', 'active', ?, ?, NULL)""",
                (
                    user_id,
                    display_username,
                    normalized_username,
                    password_hash,
                    now_utc_ms,
                    now_utc_ms,
                ),
            )
            updated = connection.execute(
                """UPDATE invitations SET redeemed_at_utc_ms=?
                   WHERE invitation_code_hash=?
                     AND redeemed_at_utc_ms IS NULL
                     AND revoked_at_utc_ms IS NULL
                     AND expires_at_utc_ms>?""",
                (now_utc_ms, code_hash, now_utc_ms),
            )
            if updated.rowcount != 1:
                raise ValueError("invalid or unavailable invitation")
            connection.execute("COMMIT")
            return UserSummary(user_id, display_username, "user")
        except sqlite3.IntegrityError as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if "normalized_username" in str(exc):
                raise ValueError("username is already registered") from exc
            raise
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
