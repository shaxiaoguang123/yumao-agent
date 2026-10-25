from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests

from backend.db import connect_database


_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z", re.ASCII)
_PROVIDER_CODE = re.compile(r"[A-Z0-9_]{1,48}\Z", re.ASCII)
_MAX_RESPONSE_BYTES = 4096
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_ATTEMPTS = 4


class NotificationError(ValueError):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


def _provider_error_code(chunks: list[bytes]) -> str | None:
    try:
        result = json.loads(b"".join(chunks).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    code = result.get("provider_code") if type(result) is dict else None
    return f"cloudflare_{code.lower()}" if type(code) is str and _PROVIDER_CODE.fullmatch(code) else None


class EmailNotificationService:
    """Schedules owner-scoped email reminders and durable final-result events."""

    def __init__(self, database_path: Path, busy_timeout_ms: int, *,
                 timezone_name: str, owner_username: str | None,
                 recipient: str | None, worker_url: str | None,
                 hmac_secret: str | None, default_enabled: bool = False,
                 worker_enabled: bool = False, plan_service=None, execution_settings_service=None,
                 clock_utc_ms=None, sender=None):
        self.database_path = Path(database_path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.zone = ZoneInfo(timezone_name)
        self.timezone_name = timezone_name
        self.owner_username = owner_username.casefold() if owner_username else None
        self.recipient = recipient
        self.worker_url = worker_url
        self.hmac_secret = hmac_secret
        self.default_enabled = bool(default_enabled)
        self.worker_enabled = bool(worker_enabled)
        self._plan_service = plan_service
        self._execution_settings_service = execution_settings_service
        self._clock = clock_utc_ms or (lambda: time.time_ns() // 1_000_000)
        self._sender = sender or self._send

    @property
    def configured(self) -> bool:
        return all((self.owner_username, self.recipient, self.worker_url, self.hmac_secret))

    def _owner_row(self, db, user_id: str):
        if not self.configured:
            return None
        row = db.execute(
            "SELECT username FROM users WHERE user_id=? AND status='active'", (user_id,),
        ).fetchone()
        if row is None or row["username"].casefold() != self.owner_username:
            return None
        return row

    def owns_notifications(self, user_id: str) -> bool:
        if not self.configured:
            return False
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            return self._owner_row(db, user_id) is not None

    def _settings_row(self, db, user_id: str, now_utc_ms: int):
        row = db.execute(
            "SELECT version,enabled,reminder_time,last_test_sent_at_utc_ms,updated_at_utc_ms "
            "FROM user_email_notification_settings WHERE user_id=?", (user_id,),
        ).fetchone()
        if row is not None:
            return row
        db.execute(
            """INSERT OR IGNORE INTO user_email_notification_settings
               (user_id,version,enabled,reminder_time,last_test_sent_at_utc_ms,updated_at_utc_ms)
               VALUES (?,1,?,'20:00',NULL,?)""",
            (user_id, int(self.default_enabled), now_utc_ms),
        )
        return db.execute(
            "SELECT version,enabled,reminder_time,last_test_sent_at_utc_ms,updated_at_utc_ms "
            "FROM user_email_notification_settings WHERE user_id=?", (user_id,),
        ).fetchone()

    def _settings_dto(self, row, recipient: str):
        return {
            "available": True,
            "worker_enabled": self.worker_enabled,
            "version": row["version"],
            "enabled": bool(row["enabled"]),
            "reminder_time": row["reminder_time"],
            "result_time": "08:00",
            "recipient": recipient,
        }

    def get_settings(self, user_id: str) -> dict:
        if not self.configured:
            return {"available": False}
        now = self._clock()
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            if self._owner_row(db, user_id) is None:
                return {"available": False}
            row = self._settings_row(db, user_id, now)
            recent = db.execute(
                """SELECT notification_id,credential_id,target_date,kind,status,
                          attempt_count,provider_message_id,safe_error_code,
                          scheduled_at_utc_ms,sent_at_utc_ms
                   FROM booking_email_notification_outbox WHERE user_id=?
                   ORDER BY scheduled_at_utc_ms DESC,notification_id DESC LIMIT 8""",
                (user_id,),
            ).fetchall()
        return {
            **self._settings_dto(row, self.recipient),
            "recent": [dict(item) for item in recent],
        }

    def save_settings(self, user_id: str, expected_version: object,
                      enabled: object, reminder_time: object, now_utc_ms: int) -> dict:
        if not self.configured or type(expected_version) is not int or not 0 <= expected_version < 2**53:
            raise NotificationError("invalid_email_notification_settings")
        if (type(enabled) is not bool or type(reminder_time) is not str
                or not _TIME.fullmatch(reminder_time) or reminder_time < "18:00"):
            raise NotificationError("invalid_email_notification_settings")
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if self._owner_row(db, user_id) is None:
                    raise NotificationError("email_notification_not_available", 404)
                current = self._settings_row(db, user_id, now_utc_ms)
                if current["version"] != expected_version:
                    raise NotificationError("email_notification_version_conflict", 409)
                version = current["version"] + 1
                db.execute(
                    """UPDATE user_email_notification_settings
                       SET version=?,enabled=?,reminder_time=?,updated_at_utc_ms=? WHERE user_id=?""",
                    (version, int(enabled), reminder_time, now_utc_ms, user_id),
                )
                if not enabled:
                    db.execute(
                        """UPDATE booking_email_notification_outbox
                           SET status='cancelled',updated_at_utc_ms=?,lease_owner_id=NULL,
                               lease_expires_at_utc_ms=NULL,safe_error_code='notifications_disabled'
                           WHERE user_id=? AND status IN ('pending','failed')""",
                        (now_utc_ms, user_id),
                    )
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        return self.get_settings(user_id)

    def send_test_email(self, user_id: str, now_utc_ms: int) -> dict:
        if not self.configured:
            raise NotificationError("email_notification_not_available", 404)
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if self._owner_row(db, user_id) is None:
                    raise NotificationError("email_notification_not_available", 404)
                settings = self._settings_row(db, user_id, now_utc_ms)
                last_sent = settings["last_test_sent_at_utc_ms"]
                if last_sent is not None and now_utc_ms - last_sent < 60_000:
                    raise NotificationError("email_notification_test_rate_limited", 429)
                db.execute(
                    "UPDATE user_email_notification_settings SET last_test_sent_at_utc_ms=?,updated_at_utc_ms=? WHERE user_id=?",
                    (now_utc_ms, now_utc_ms, user_id),
                )
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        payload = {"notification_id": str(uuid.uuid4()), "kind": "test", "outcome": "test",
                   "status_label": "这是一封邮件通知测试，不代表抢票成功。"}
        try:
            result = self._sender(payload)
        except NotificationSendError as exc:
            raise NotificationError(exc.code, 503) from None
        except Exception:
            raise NotificationError("email_notification_test_failed", 503) from None
        if (type(result) is not dict or result.get("accepted") is not True
                or type(result.get("message_id")) is not str or not result["message_id"]):
            raise NotificationError("email_notification_test_failed", 503)
        return {"accepted": True, "message_id": result["message_id"]}

    def _upsert_event(self, db, user_id, credential_id, target_date, kind,
                      queue, due_at_utc_ms, now_utc_ms):
        if due_at_utc_ms < now_utc_ms:
            return
        queue_revision_id = queue["current_revision_id"]
        queue_version = queue["version"]
        db.execute(
            """INSERT INTO booking_email_notification_outbox
               (notification_id,user_id,credential_id,target_date,kind,queue_revision_id,
                queue_version,scheduled_at_utc_ms,status,attempt_count,next_attempt_at_utc_ms,
                created_at_utc_ms,updated_at_utc_ms)
               VALUES (?,?,?,?,?,?,?,?,'pending',0,?,?,?)
               ON CONFLICT(user_id,credential_id,target_date,kind) DO UPDATE SET
                 queue_revision_id=excluded.queue_revision_id,
                 queue_version=excluded.queue_version,
                 scheduled_at_utc_ms=excluded.scheduled_at_utc_ms,
                 next_attempt_at_utc_ms=excluded.next_attempt_at_utc_ms,
                 status='pending',attempt_count=0,lease_owner_id=NULL,
                 lease_expires_at_utc_ms=NULL,provider_message_id=NULL,safe_error_code=NULL,
                 sent_at_utc_ms=NULL,updated_at_utc_ms=excluded.updated_at_utc_ms
               WHERE booking_email_notification_outbox.status='cancelled'
                  OR (booking_email_notification_outbox.status IN ('pending','failed')
                      AND (booking_email_notification_outbox.queue_revision_id!=excluded.queue_revision_id
                           OR booking_email_notification_outbox.scheduled_at_utc_ms!=excluded.scheduled_at_utc_ms))""",
            (str(uuid.uuid4()), user_id, credential_id, target_date, kind,
             queue_revision_id, queue_version, due_at_utc_ms, due_at_utc_ms,
             now_utc_ms, now_utc_ms),
        )

    @staticmethod
    def _cancel_pending(db, user_id, credential_id, target_date, now_utc_ms, reason):
        db.execute(
            """UPDATE booking_email_notification_outbox
               SET status='cancelled',safe_error_code=?,updated_at_utc_ms=?,
                   lease_owner_id=NULL,lease_expires_at_utc_ms=NULL
               WHERE user_id=? AND credential_id=? AND target_date=?
                 AND status IN ('pending','failed')""",
            (reason, now_utc_ms, user_id, credential_id, target_date),
        )

    def sync_queue(self, user_id: str, credential_id: str, target_date: str,
                   queue: dict | None, now_utc_ms: int) -> None:
        if not self.configured or not credential_id:
            return
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if self._owner_row(db, user_id) is None:
                    db.execute("COMMIT")
                    return
                prefs = self._settings_row(db, user_id, now_utc_ms)
                if not prefs["enabled"] or not self.worker_enabled:
                    self._cancel_pending(db, user_id, credential_id, target_date, now_utc_ms,
                                         "notifications_or_executor_disabled")
                    db.execute("COMMIT")
                    return
                if not queue or queue.get("deleted") or not queue.get("candidates"):
                    reminder = db.execute(
                        """SELECT status FROM booking_email_notification_outbox
                           WHERE user_id=? AND credential_id=? AND target_date=? AND kind='reminder'""",
                        (user_id, credential_id, target_date),
                    ).fetchone()
                    if reminder is None or reminder["status"] != "sent":
                        self._cancel_pending(db, user_id, credential_id, target_date, now_utc_ms,
                                             "queue_empty_or_deleted")
                    else:
                        result = db.execute(
                            """SELECT notification_id FROM booking_email_notification_outbox
                               WHERE user_id=? AND credential_id=? AND target_date=? AND kind='result'
                                 AND status IN ('pending','failed')""",
                            (user_id, credential_id, target_date),
                        ).fetchone()
                        if result and queue is not None:
                            db.execute(
                                """UPDATE booking_email_notification_outbox
                                   SET status='pending',queue_revision_id=?,queue_version=?,
                                       safe_error_code='queue_empty_or_deleted',updated_at_utc_ms=?
                                   WHERE notification_id=?""",
                                (queue["current_revision_id"], queue["version"], now_utc_ms,
                                 result["notification_id"]),
                            )
                    db.execute("COMMIT")
                    return
                target = date.fromisoformat(target_date)
                execution_day = target - timedelta(days=2)
                reminder_day = execution_day - timedelta(days=1)
                hour, minute = (int(part) for part in prefs["reminder_time"].split(":"))
                reminder_at = int(datetime.combine(reminder_day, clock_time(hour, minute),
                                                   self.zone).timestamp() * 1000)
                result_at = int(datetime.combine(execution_day, clock_time(8, 0),
                                                 self.zone).timestamp() * 1000)
                execution_open_at = int(datetime.combine(
                    execution_day, clock_time(7, 30), self.zone,
                ).timestamp() * 1000)
                if now_utc_ms < execution_open_at and now_utc_ms <= reminder_at:
                    self._upsert_event(db, user_id, credential_id, target_date, "reminder",
                                       queue, reminder_at, now_utc_ms)
                else:
                    db.execute(
                        """UPDATE booking_email_notification_outbox
                           SET status='cancelled',safe_error_code='reminder_time_passed',updated_at_utc_ms=?
                           WHERE user_id=? AND credential_id=? AND target_date=? AND kind='reminder'
                             AND status IN ('pending','failed')""",
                        (now_utc_ms, user_id, credential_id, target_date),
                    )
                if now_utc_ms <= result_at + 86_400_000:
                    self._upsert_event(db, user_id, credential_id, target_date, "result",
                                       queue, result_at, now_utc_ms)
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def sync_queue_dates(self, user_id: str, credential_id: str, business_date: date,
                         queues: dict[str, dict | None], now_utc_ms: int) -> None:
        for offset in (2, 3, 4):
            target_date = (business_date + timedelta(days=offset)).isoformat()
            self.sync_queue(user_id, credential_id, target_date, queues.get(target_date), now_utc_ms)

    def next_due_at_utc_ms(self):
        if not self.configured or not self.worker_enabled:
            return None
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            row = db.execute(
                """SELECT min(max(scheduled_at_utc_ms,next_attempt_at_utc_ms)) AS due
                   FROM booking_email_notification_outbox WHERE status='pending'""",
            ).fetchone()
        return row["due"] if row and row["due"] is not None else None

    def _claim(self, now_utc_ms: int):
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """UPDATE booking_email_notification_outbox
                       SET status='uncertain',safe_error_code='send_outcome_unknown',
                           lease_owner_id=NULL,lease_expires_at_utc_ms=NULL,updated_at_utc_ms=?
                       WHERE status='sending' AND lease_expires_at_utc_ms<=?""",
                    (now_utc_ms, now_utc_ms),
                )
                row = db.execute(
                    """SELECT notification_id FROM booking_email_notification_outbox
                       WHERE status='pending' AND scheduled_at_utc_ms<=? AND next_attempt_at_utc_ms<=?
                       ORDER BY scheduled_at_utc_ms,notification_id LIMIT 1""",
                    (now_utc_ms, now_utc_ms),
                ).fetchone()
                if row is None:
                    db.execute("COMMIT")
                    return None
                lease_owner = str(uuid.uuid4())
                updated = db.execute(
                    """UPDATE booking_email_notification_outbox
                       SET status='sending',attempt_count=attempt_count+1,lease_owner_id=?,
                           lease_expires_at_utc_ms=?,updated_at_utc_ms=?
                       WHERE notification_id=? AND status='pending'""",
                    (lease_owner, now_utc_ms + 30_000, now_utc_ms, row["notification_id"]),
                )
                db.execute("COMMIT")
                return (row["notification_id"], lease_owner) if updated.rowcount == 1 else None
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def _load_notification(self, notification_id: str):
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            row = db.execute(
                "SELECT * FROM booking_email_notification_outbox WHERE notification_id=?",
                (notification_id,),
            ).fetchone()
        return dict(row) if row else None

    def _result_payload(self, row: dict) -> dict:
        from backend.execution.repository import BookingExecutionRepository
        repository = BookingExecutionRepository(self.database_path, self.busy_timeout_ms)
        queue = self._plan_service.get_manual_queue(
            row["user_id"], row["target_date"], row["credential_id"],
        ) if self._plan_service is not None else None
        run = repository.latest_run(row["user_id"], row["credential_id"], row["target_date"])
        payload = {"notification_id": row["notification_id"], "kind": "result",
                   "target_date": row["target_date"], "execution_date": (date.fromisoformat(row["target_date"])-timedelta(days=2)).isoformat(),
                   "outcome": "not_executed", "status_label": "未执行",
                   "credential_label": self._credential_label(row["user_id"], row["credential_id"])}
        if run is None:
            if queue is None or queue.get("deleted") or not queue.get("candidates"):
                payload["outcome"] = "not_executed"
                payload["status_label"] = "计划已取消或没有有效队列，本次未执行。"
            else:
                payload["outcome"] = "needs_attention"
                payload["status_label"] = "未找到本次执行记录，请在预约计划中核对。"
            return payload
        verification = next((stage for stage in reversed(run["stages"])
                             if stage["stage_key"] == "payment_verification"), None)
        if run["state"] == "succeeded" and verification and verification["outcome"] == "success":
            candidate = next((item for item in run["candidates"]
                              if int(item.get("queue_index", -1)) == verification["candidate_index"]), None)
            if (candidate is None or type(candidate.get("court_preference")) is not str
                    or type(candidate.get("start_time")) is not str
                    or type(candidate.get("end_time")) is not str
                    or candidate.get("duration_minutes") not in {60, 120}):
                payload["outcome"] = "needs_attention"
                payload["status_label"] = "订单已确认，但场地信息未能匹配，请在计划页核对。"
                return payload
            payload.update({
                "outcome": "succeeded", "status_label": "已抢到并核验成功",
                "scope_label": candidate.get("scope_label") or "羽毛球",
                "court": candidate.get("court_preference"),
                "start_time": candidate.get("start_time"),
                "end_time": candidate.get("end_time"),
                "duration_minutes": candidate.get("duration_minutes"),
                "confirmed_at_utc_ms": verification["completed_at_utc_ms"],
                "execution_started_at_utc_ms": run.get("started_at_utc_ms"),
            })
        elif run["state"] == "failed":
            changed_after_run = bool(queue and queue.get("current_revision_id")
                                     != run.get("source_revision_id"))
            payload.update(outcome="failed", status_label=(
                "本次尝试的队列没有抢到场地；之后队列有修改，修改后的版本未执行。"
                if changed_after_run else "本次候选已尝试，未抢到场地。"))
        elif run["state"] == "empty":
            payload.update(outcome="empty", status_label="复核后没有可执行场地，本次未尝试预约。")
        elif run["state"] == "stale":
            payload.update(outcome="not_executed", status_label="队列版本已变更，本次计划未执行。")
        elif run["state"] == "needs_attention":
            payload.update(outcome="needs_attention", status_label="订单或付款状态未能确认，请在计划页核对。")
        elif run["state"] == "succeeded":
            payload.update(outcome="needs_attention", status_label="执行记录缺少付款核验凭据，请在计划页核对。")
        else:
            payload.update(outcome="needs_attention", status_label="执行状态异常，请在计划页核对。")
        return payload

    def _credential_label(self, user_id, credential_id):
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            row = db.execute(
                "SELECT label FROM credentials WHERE user_id=? AND credential_id=?",
                (user_id, credential_id),
            ).fetchone()
        value = row["label"] if row else "预约凭据"
        safe = "".join(char for char in value if char.isprintable())[:80].strip()
        return safe or "预约凭据"

    def _reminder_payload(self, row: dict) -> dict:
        queue = (self._plan_service.manual_queue_revision(
            row["user_id"], row["target_date"], row["credential_id"], row["queue_revision_id"],
        ) if self._plan_service is not None else None)
        if (not queue or queue.get("deleted") or not queue.get("candidates")
                or queue.get("revision_number") != row["queue_version"]):
            return None
        # Reminder pins the saved intent revision; it makes no live-availability claim.
        entries = []
        for candidate in queue.get("candidates", []):
            entries.append({
                "duration_minutes": candidate.get("duration_minutes"),
                "scope_label": candidate.get("query_scope_label") or candidate.get("venue_preference"),
                "courts": candidate.get("court_preferences", []),
                "start_times": candidate.get("preferred_start_times", []),
            })
        execution_settings = (self._execution_settings_service.get(row["user_id"])
                              if self._execution_settings_service is not None else None)
        start_offset_ms = ((execution_settings or {}).get("settings", {}).get("start_offset_ms", 0))
        if type(start_offset_ms) is not int or not 0 <= start_offset_ms <= 60_000:
            raise NotificationError("invalid_email_notification_settings")
        return {"notification_id": row["notification_id"], "kind": "reminder",
                "target_date": row["target_date"], "execution_date": (date.fromisoformat(row["target_date"])-timedelta(days=2)).isoformat(),
                "queue_version": row["queue_version"],
                "start_offset_ms": start_offset_ms,
                "credential_label": self._credential_label(row["user_id"], row["credential_id"]),
                "outcome": "planned", "status_label": "已保存这些队列偏好；开抢时会重新查询场地状态。",
                "candidates": entries}

    def dispatch_due(self, now_utc_ms: int | None = None, *, limit: int = 8) -> int:
        if not self.configured or not self.worker_enabled:
            return 0
        now = self._clock() if now_utc_ms is None else now_utc_ms
        claimed_events = []
        for _ in range(limit):
            claimed = self._claim(now)
            if claimed is None:
                break
            claimed_events.append(claimed)
        if not claimed_events:
            return 0
        with ThreadPoolExecutor(max_workers=min(8, len(claimed_events)),
                                thread_name_prefix="email-notification") as executor:
            return sum(executor.map(lambda item: self._deliver_claimed(*item, now), claimed_events))

    def _deliver_claimed(self, notification_id: str, lease_owner: str, now_utc_ms: int) -> int:
        row = self._load_notification(notification_id)
        if row is None:
            return 0
        try:
            payload = (self._reminder_payload(row) if row["kind"] == "reminder"
                       else self._result_payload(row))
            if payload is None:
                self._mark_cancelled(notification_id, lease_owner, now_utc_ms, "queue_revision_unavailable")
                return 0
            result = self._sender(payload)
            if (type(result) is not dict or result.get("accepted") is not True
                    or type(result.get("message_id")) is not str or not result["message_id"]):
                raise NotificationSendError("provider_invalid_response", permanent=True)
        except NotificationSendError as exc:
            self._finish_attempt(notification_id, lease_owner, now_utc_ms, exc)
            return 0
        except Exception:
            self._finish_attempt(notification_id, lease_owner, now_utc_ms,
                                 NotificationSendError("notification_payload_unavailable", permanent=True))
            return 0
        self._mark_sent(notification_id, lease_owner, now_utc_ms, result["message_id"])
        return 1

    def _mark_cancelled(self, notification_id, lease_owner, now_utc_ms, safe_code):
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            db.execute(
                """UPDATE booking_email_notification_outbox
                   SET status='cancelled',safe_error_code=?,lease_owner_id=NULL,
                       lease_expires_at_utc_ms=NULL,updated_at_utc_ms=?
                   WHERE notification_id=? AND status='sending' AND lease_owner_id=?""",
                (safe_code, now_utc_ms, notification_id, lease_owner),
            )

    def _finish_attempt(self, notification_id, lease_owner, now, error):
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT attempt_count FROM booking_email_notification_outbox "
                    "WHERE notification_id=? AND status='sending' AND lease_owner_id=?",
                    (notification_id, lease_owner),
                ).fetchone()
                if row is None:
                    db.execute("COMMIT")
                    return
                attempts = row["attempt_count"]
                if error.uncertain:
                    status, next_attempt, safe_code = "uncertain", now, error.code
                elif error.permanent or not error.retryable or attempts >= _MAX_ATTEMPTS:
                    status, next_attempt, safe_code = "failed", now, error.code
                else:
                    status = "pending"
                    next_attempt = now + min(3600_000, 30_000 * (2 ** (attempts - 1)))
                    safe_code = error.code
                db.execute(
                    """UPDATE booking_email_notification_outbox
                       SET status=?,next_attempt_at_utc_ms=?,safe_error_code=?,
                           lease_owner_id=NULL,lease_expires_at_utc_ms=NULL,updated_at_utc_ms=?
                       WHERE notification_id=? AND lease_owner_id=?""",
                    (status, next_attempt, safe_code, now, notification_id, lease_owner),
                )
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def _mark_sent(self, notification_id, lease_owner, now, message_id):
        with closing(connect_database(self.database_path, self.busy_timeout_ms)) as db:
            db.execute(
                """UPDATE booking_email_notification_outbox
                   SET status='sent',provider_message_id=?,safe_error_code=NULL,sent_at_utc_ms=?,
                       lease_owner_id=NULL,lease_expires_at_utc_ms=NULL,updated_at_utc_ms=?
                   WHERE notification_id=? AND status='sending' AND lease_owner_id=?""",
                (message_id[:256], now, now, notification_id, lease_owner),
            )

    def _send(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(body) > _MAX_REQUEST_BYTES:
            raise NotificationSendError("notification_payload_too_large", permanent=True)
        timestamp = str(self._clock() // 1000)
        signature = hmac.new(
            bytes.fromhex(self.hmac_secret), timestamp.encode() + b"\n" + body, hashlib.sha256,
        ).hexdigest()
        try:
            response = requests.post(
                self.worker_url, data=body,
                headers={"Content-Type": "application/json", "X-Yumao-Timestamp": timestamp,
                         "X-Yumao-Signature": signature},
                timeout=(3, 8), stream=True, allow_redirects=False,
            )
        except requests.Timeout as exc:
            raise NotificationSendError("provider_timeout", uncertain=True) from exc
        except requests.RequestException as exc:
            raise NotificationSendError("provider_unavailable", uncertain=True) from exc
        try:
            chunks, size = [], 0
            for chunk in response.iter_content(1024):
                size += len(chunk)
                if size > _MAX_RESPONSE_BYTES:
                    raise NotificationSendError("provider_invalid_response", permanent=True)
                chunks.append(chunk)
            provider_code = _provider_error_code(chunks)
            if response.status_code == 429:
                raise NotificationSendError(provider_code or "provider_retryable", retryable=True)
            if response.status_code == 409 or response.status_code >= 500:
                raise NotificationSendError(provider_code or "provider_outcome_unknown", uncertain=True)
            if response.status_code != 200:
                raise NotificationSendError(provider_code or "provider_rejected", permanent=True)
            result = json.loads(b"".join(chunks).decode("utf-8"))
            if type(result) is not dict or result.get("accepted") is not True:
                raise NotificationSendError("provider_invalid_response", permanent=True)
            message_id = result.get("message_id")
            if type(message_id) is not str or not 1 <= len(message_id) <= 256:
                raise NotificationSendError("provider_invalid_response", permanent=True)
            return {"accepted": True, "message_id": message_id}
        except NotificationSendError:
            raise
        except requests.Timeout as exc:
            raise NotificationSendError("provider_timeout", uncertain=True) from exc
        except requests.RequestException as exc:
            raise NotificationSendError("provider_unavailable", uncertain=True) from exc
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NotificationSendError("provider_invalid_response", permanent=True) from exc
        finally:
            response.close()


class NotificationSendError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False, uncertain: bool = False,
                 permanent: bool = False):
        self.code = code
        self.retryable = retryable
        self.uncertain = uncertain
        self.permanent = permanent
        super().__init__(code)
