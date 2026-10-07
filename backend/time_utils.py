from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment]

from .config import APP_TIMEZONE

DEFAULT_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")


def _load_app_timezone() -> tzinfo:
    if APP_TIMEZONE in {"Asia/Shanghai", "PRC", "+08:00", "UTC+8"}:
        return DEFAULT_TIMEZONE
    if ZoneInfo is None:
        return DEFAULT_TIMEZONE
    try:
        return ZoneInfo(APP_TIMEZONE)
    except ZoneInfoNotFoundError:
        return DEFAULT_TIMEZONE


APP_TZ = _load_app_timezone()
APP_TIMEZONE_NAME = getattr(APP_TZ, "key", None) or APP_TZ.tzname(None) or "Asia/Shanghai"


def now_tz() -> datetime:
    return datetime.now(APP_TZ)


def today_str() -> str:
    return now_tz().strftime("%Y-%m-%d")


def format_timestamp(ts: datetime | None = None) -> str:
    target = ts.astimezone(APP_TZ) if ts else now_tz()
    return target.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def isoformat_ms(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.astimezone(APP_TZ).isoformat(timespec="milliseconds")


def epoch_ms(ts: datetime | None) -> int | None:
    if ts is None:
        return None
    return int(ts.timestamp() * 1000)


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def parse_time_to_minutes(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    return hour * 60 + minute


def parse_datetime_text(date_str: Any, time_str: Any) -> datetime | None:
    date_text = str(date_str or "").strip()
    time_text = str(time_str or "").strip()
    if not date_text or not time_text:
        return None
    formats = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")
    for fmt in formats:
        try:
            parsed = datetime.strptime(f"{date_text} {time_text}", fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=APP_TZ)
    return None


def booking_window_check_enforced(meta: dict[str, Any], reserve_date: str) -> bool:
    is_new = normalize_bool(meta.get("isNew"))
    end_date = str(meta.get("bookingenddate") or "").strip()
    if not is_new:
        return True
    return bool(reserve_date and end_date and reserve_date == end_date)


def booking_window_open(meta: dict[str, Any], reserve_date: str, now: datetime | None = None) -> bool:
    start = parse_time_to_minutes(meta.get("bookingstarttime"))
    end = parse_time_to_minutes(meta.get("bookingendtime"))
    if start is None or end is None:
        return True
    if not booking_window_check_enforced(meta, reserve_date):
        return True
    target = now.astimezone(APP_TZ) if now else now_tz()
    now_minutes = target.hour * 60 + target.minute
    return start <= now_minutes <= end


def build_timing_payload(meta: dict[str, Any], reserve_date: str, now: datetime | None = None) -> dict[str, Any]:
    target_now = now.astimezone(APP_TZ) if now else now_tz()
    open_at = parse_datetime_text(meta.get("bookingstartdate") or reserve_date, meta.get("bookingstarttime"))
    return {
        "timezone": APP_TIMEZONE_NAME,
        "serverNowIso": isoformat_ms(target_now),
        "serverNowEpochMs": epoch_ms(target_now),
        "serverToday": target_now.strftime("%Y-%m-%d"),
        "openAtIso": isoformat_ms(open_at),
        "openAtEpochMs": epoch_ms(open_at),
        "bookingWindowOpen": booking_window_open(meta, reserve_date, target_now),
        "bookingWindowCheckEnforced": booking_window_check_enforced(meta, reserve_date),
    }
