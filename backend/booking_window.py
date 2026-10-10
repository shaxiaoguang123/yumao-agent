from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
QUERY_OPEN_LOCAL_TIME = time.min
ESTIMATED_OPEN_LOCAL_TIME = time(7, 30)


@dataclass(frozen=True, slots=True)
class BookingWindowState:
    business_timezone_name: str
    business_date: date
    default_target_date: date
    target_date: date
    queryable_target_dates: tuple[date, date, date]
    query_open_at_utc_ms: int | None
    estimated_open_at_local: str
    estimated_open_is_confirmed: bool
    resolved_official_open_at_utc_ms: int | None
    can_query: bool
    can_book: bool
    can_pay: bool
    contract_status: str
    reason_code: str | None


def _utc_datetime_from_milliseconds(value: int) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("now_utc_ms must be an integer")
    try:
        return EPOCH + timedelta(milliseconds=value)
    except OverflowError as exc:
        raise ValueError("now_utc_ms is outside the supported datetime range") from exc


def _utc_milliseconds(value: datetime) -> int:
    return (value.astimezone(UTC) - EPOCH) // timedelta(milliseconds=1)


def _local_wall_time_utc(local_wall_time: datetime, zone: ZoneInfo) -> datetime | None:
    """Resolve a local wall time, choosing its first occurrence or first valid instant."""
    candidates: set[datetime] = set()
    for fold in (0, 1):
        candidate = local_wall_time.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        round_trip = candidate.astimezone(zone)
        if round_trip.replace(tzinfo=None) == local_wall_time:
            candidates.add(candidate)
    if candidates:
        return min(candidates)

    # At a forward clock jump, fold=0 maps a nonexistent wall time to the
    # transition instant. Accept it only when it resolves later on this date.
    candidate = local_wall_time.replace(tzinfo=zone, fold=0).astimezone(UTC)
    round_trip = candidate.astimezone(zone).replace(tzinfo=None)
    if round_trip.date() == local_wall_time.date() and round_trip > local_wall_time:
        return candidate
    return None


class BookingWindowPolicy:
    """Pure calendar eligibility using an explicit IANA business timezone.

    `can_query` reports only the configured date/time window predicate. It is
    not an authorization to make an upstream request.
    """

    def __init__(self, timezone_name: str) -> None:
        if not isinstance(timezone_name, str) or not timezone_name or timezone_name != timezone_name.strip():
            raise ValueError("timezone_name must be a valid IANA timezone key")
        try:
            self._zone = ZoneInfo(timezone_name)
        except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("timezone_name must be a valid IANA timezone key") from exc
        self.timezone_name = timezone_name

    def business_date_at_utc(self, now_utc_ms: int) -> date:
        return _utc_datetime_from_milliseconds(now_utc_ms).astimezone(self._zone).date()

    def queryable_target_dates(self, now_utc_ms: int) -> tuple[date, date, date]:
        business_date = self.business_date_at_utc(now_utc_ms)
        return (
            business_date,
            business_date + timedelta(days=1),
            business_date + timedelta(days=2),
        )

    def describe(
        self,
        target_date: date,
        now_utc_ms: int,
        intent_timezone_snapshot: str | None = None,
    ) -> BookingWindowState:
        if not isinstance(target_date, date) or isinstance(target_date, datetime):
            raise TypeError("target_date must be a date, not a datetime")

        now_utc = _utc_datetime_from_milliseconds(now_utc_ms)
        business_date = now_utc.astimezone(self._zone).date()
        queryable_dates = (
            business_date,
            business_date + timedelta(days=1),
            business_date + timedelta(days=2),
        )
        default_target_date = queryable_dates[2]

        try:
            query_date = target_date - timedelta(days=2)
        except OverflowError as exc:
            raise ValueError("target_date is outside the supported range") from exc

        query_open_local = datetime.combine(query_date, QUERY_OPEN_LOCAL_TIME)
        query_open_utc = _local_wall_time_utc(query_open_local, self._zone)
        query_open_at_utc_ms = _utc_milliseconds(query_open_utc) if query_open_utc else None
        estimated_open_at_local = datetime.combine(
            query_date, ESTIMATED_OPEN_LOCAL_TIME
        ).isoformat(timespec="seconds")

        reason_code: str | None = None
        if intent_timezone_snapshot is not None:
            if not isinstance(intent_timezone_snapshot, str) or not intent_timezone_snapshot:
                reason_code = "invalid_intent_timezone_snapshot"
            else:
                try:
                    ZoneInfo(intent_timezone_snapshot)
                except (TypeError, ValueError, ZoneInfoNotFoundError):
                    reason_code = "invalid_intent_timezone_snapshot"
                if reason_code is None and intent_timezone_snapshot != self.timezone_name:
                    reason_code = "timezone_context_mismatch"

        if reason_code is None and target_date not in queryable_dates:
            reason_code = "target_outside_query_window"
        if reason_code is None and query_open_at_utc_ms is None:
            reason_code = "query_open_local_date_unavailable"
        if (
            reason_code is None
            and query_open_at_utc_ms is not None
            and now_utc_ms < query_open_at_utc_ms
        ):
            reason_code = "before_query_open"

        return BookingWindowState(
            business_timezone_name=self.timezone_name,
            business_date=business_date,
            default_target_date=default_target_date,
            target_date=target_date,
            queryable_target_dates=queryable_dates,
            query_open_at_utc_ms=query_open_at_utc_ms,
            estimated_open_at_local=estimated_open_at_local,
            estimated_open_is_confirmed=False,
            resolved_official_open_at_utc_ms=None,
            can_query=reason_code is None,
            can_book=False,
            can_pay=False,
            contract_status="not_checked",
            reason_code=reason_code,
        )
