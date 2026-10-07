from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from backend.db import connect_database


@dataclass(frozen=True, slots=True)
class RateLimitBucket:
    event_type: str
    bucket_type: str
    bucket_key: str
    limit: int
    window_seconds: int


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


class RateLimitService:
    def __init__(self, database_path, busy_timeout_ms: int):
        self.database_path = database_path
        self.busy_timeout_ms = busy_timeout_ms

    def check_and_record(
        self,
        event_type: str,
        buckets: Sequence[RateLimitBucket],
        now_utc_ms: int,
    ) -> RateLimitDecision:
        if not event_type or not buckets:
            raise ValueError("event_type and at least one bucket are required")
        for bucket in buckets:
            if (
                bucket.event_type != event_type
                or not bucket.bucket_type
                or not bucket.bucket_key
                or bucket.limit <= 0
                or bucket.window_seconds <= 0
                or bucket.window_seconds > 86400
            ):
                raise ValueError("rate-limit bucket configuration is invalid")

        connection = connect_database(self.database_path, self.busy_timeout_ms)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM auth_attempts WHERE attempted_at_utc_ms < ?",
                (now_utc_ms - 86_400_000,),
            )

            blocked_waits: list[int] = []
            for bucket in buckets:
                window_ms = bucket.window_seconds * 1000
                rows = connection.execute(
                    """SELECT attempted_at_utc_ms FROM auth_attempts
                       WHERE event_type=?
                         AND bucket_type=?
                         AND bucket_key=?
                         AND attempted_at_utc_ms>=?
                       ORDER BY attempted_at_utc_ms ASC""",
                    (
                        event_type,
                        bucket.bucket_type,
                        bucket.bucket_key,
                        now_utc_ms - window_ms,
                    ),
                ).fetchall()
                if len(rows) >= bucket.limit:
                    earliest_attempt = int(rows[0]["attempted_at_utc_ms"])
                    wait_ms = earliest_attempt + window_ms - now_utc_ms + 1
                    blocked_waits.append(max(1, math.ceil(wait_ms / 1000)))

            if blocked_waits:
                connection.execute("COMMIT")
                return RateLimitDecision(False, max(blocked_waits))

            for bucket in buckets:
                connection.execute(
                    """INSERT INTO auth_attempts
                       (event_type, bucket_type, bucket_key, attempted_at_utc_ms)
                       VALUES (?, ?, ?, ?)""",
                    (event_type, bucket.bucket_type, bucket.bucket_key, now_utc_ms),
                )
            connection.execute("COMMIT")
            return RateLimitDecision(True, 0)
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
