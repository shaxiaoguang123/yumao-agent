from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.availability_matching.models import AvailabilityError, clock, minutes
from backend.plans.validation import IntentValidationError, parse_target_date


GRID_STATES = frozenset({"selectable", "reserved", "activity_occupied", "unbookable", "unknown"})
GRID_NOTICE = (
    "这是合成网格预览，不是实时场馆库存。场馆和场地仅为人工偏好标签；"
    "选择后只更新预约意向，不会查询、预约或支付。"
)


class VenueTimeGridError(AvailabilityError):
    def __init__(self, code: str = "invalid_venue_time_grid", status: int = 400):
        super().__init__(code, status)


def _manual_text(value: object, maximum: int) -> str:
    if type(value) is not str:
        raise VenueTimeGridError()
    normalized = value.strip()
    if (not 1 <= len(normalized) <= maximum
            or any(unicodedata.category(char) in {"Cc", "Cs"} for char in normalized)):
        raise VenueTimeGridError()
    return normalized


@dataclass(frozen=True, slots=True)
class VenueGridCell:
    state: str
    reason_code: str
    category_label: str | None = None

    def __post_init__(self):
        if self.state not in GRID_STATES:
            raise VenueTimeGridError()
        if type(self.reason_code) is not str or not 1 <= len(self.reason_code) <= 64:
            raise VenueTimeGridError()
        if self.category_label is not None:
            _manual_text(self.category_label, 40)
        if (self.state == "activity_occupied") != (self.category_label is not None):
            raise VenueTimeGridError()

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "selectable": self.state == "selectable",
            "reason_code": self.reason_code,
            "category_label": self.category_label,
        }


@dataclass(frozen=True, slots=True)
class VenueGridRow:
    start_time: str
    end_time: str
    cells: tuple[VenueGridCell, ...]

    def __post_init__(self):
        if minutes(self.start_time) >= minutes(self.end_time, end=True):
            raise VenueTimeGridError()
        if type(self.cells) is not tuple or not self.cells or any(type(cell) is not VenueGridCell for cell in self.cells):
            raise VenueTimeGridError()

    def to_dict(self) -> dict:
        return {"start_time": self.start_time, "end_time": self.end_time,
                "cells": [cell.to_dict() for cell in self.cells]}


@dataclass(frozen=True, slots=True)
class VenueTimeGridSnapshot:
    target_date: str
    timezone_name: str
    venue_name: str
    court_names: tuple[str, ...]
    rows: tuple[VenueGridRow, ...]
    duration_minutes: int
    atom_minutes: int = 30
    source: str = "synthetic-grid-v1"
    simulation: bool = True

    def __post_init__(self):
        try:
            target = parse_target_date(self.target_date)
            zone = ZoneInfo(self.timezone_name)
        except (IntentValidationError, TypeError, ValueError, ZoneInfoNotFoundError):
            raise VenueTimeGridError() from None
        _manual_text(self.venue_name, 200)
        if (type(self.simulation) is not bool or self.simulation is not True
                or self.source != "synthetic-grid-v1"):
            raise VenueTimeGridError()
        if type(self.atom_minutes) is not int or self.atom_minutes != 30:
            raise VenueTimeGridError()
        if (type(self.duration_minutes) is not int or not 30 <= self.duration_minutes <= 240
                or self.duration_minutes % self.atom_minutes):
            raise VenueTimeGridError()
        if type(self.court_names) is not tuple or not 1 <= len(self.court_names) <= 16:
            raise VenueTimeGridError()
        normalized = tuple(_manual_text(name, 100) for name in self.court_names)
        if normalized != self.court_names or len(set(normalized)) != len(normalized):
            raise VenueTimeGridError()
        if type(self.rows) is not tuple or not 1 <= len(self.rows) <= 32:
            raise VenueTimeGridError()
        if any(type(row) is not VenueGridRow or len(row.cells) != len(self.court_names) for row in self.rows):
            raise VenueTimeGridError()
        # The synthetic fixture has a 30-minute local grid and does not span midnight.
        if any(minutes(row.end_time, end=True) - minutes(row.start_time) != self.atom_minutes for row in self.rows):
            raise VenueTimeGridError()
        if any(minutes(left.end_time, end=True) != minutes(right.start_time)
               for left, right in zip(self.rows, self.rows[1:])):
            raise VenueTimeGridError()
        # Reject DST transition dates, which a local HH:MM matrix cannot represent uniquely.
        midnight = datetime.combine(target, time())
        offsets = set()
        for minute in range(1441):
            try:
                local = midnight + timedelta(minutes=minute)
            except OverflowError:
                raise VenueTimeGridError() from None
            aware = local.replace(tzinfo=zone, fold=0)
            alternate = local.replace(tzinfo=zone, fold=1)
            if aware.utcoffset() != alternate.utcoffset() or aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local:
                raise VenueTimeGridError("venue_grid_timezone_day_unsupported")
            offsets.add(aware.utcoffset())
        if len(offsets) != 1:
            raise VenueTimeGridError("venue_grid_timezone_day_unsupported")

    def to_dict(self) -> dict:
        return {
            "grid_version": "venue-time-grid-v1",
            "simulation": True,
            "source": {"source": self.source, "data_state": "synthetic", "trust_state": "synthetic"},
            "notice": GRID_NOTICE,
            "target_date": self.target_date,
            "timezone_name": self.timezone_name,
            "venue": {"display_name": self.venue_name, "verification": "unverified_manual"},
            "atom_minutes": self.atom_minutes,
            "duration_minutes": self.duration_minutes,
            "courts": [{"display_name": name, "verification": "unverified_manual"} for name in self.court_names],
            "rows": [row.to_dict() for row in self.rows],
            "can_query_upstream": False,
            "can_book": False,
            "can_pay": False,
            "can_create_job": False,
        }


class SyntheticVenueTimeGridSource:
    """Deterministic, explicitly synthetic grid; manual labels never become catalog IDs."""

    def preview(self, *, target_date: str, timezone_name: str, venue_preference: str,
                court_preferences: list[str], duration_minutes: int) -> dict:
        try:
            target = parse_target_date(target_date)
        except IntentValidationError:
            raise VenueTimeGridError("invalid_venue_grid_date") from None
        venue = _manual_text(venue_preference, 200)
        if type(court_preferences) is not list or not 1 <= len(court_preferences) <= 16:
            raise VenueTimeGridError("invalid_venue_grid_courts")
        courts = tuple(_manual_text(name, 100) for name in court_preferences)
        if len(set(courts)) != len(courts):
            raise VenueTimeGridError("invalid_venue_grid_courts")
        if type(duration_minutes) is not int or not 30 <= duration_minutes <= 240 or duration_minutes % 30:
            raise VenueTimeGridError("invalid_venue_grid_duration")

        rows = []
        start_minute = 17 * 60
        for row_index in range(12):
            row_start = start_minute + row_index * 30
            cells = []
            for court_index in range(len(courts)):
                if row_index <= 7:
                    cell = VenueGridCell("selectable", "synthetic_selectable")
                elif row_index == 8 and court_index == 0:
                    cell = VenueGridCell("reserved", "synthetic_reserved")
                elif row_index == 9 and court_index == min(1, len(courts) - 1):
                    cell = VenueGridCell("activity_occupied", "synthetic_activity", "示例活动")
                elif row_index == 10:
                    cell = VenueGridCell("unbookable", "synthetic_unbookable")
                elif row_index == 11 and court_index == 0:
                    cell = VenueGridCell("unknown", "synthetic_unknown")
                else:
                    cell = VenueGridCell("selectable", "synthetic_selectable")
                cells.append(cell)
            rows.append(VenueGridRow(clock(row_start), clock(row_start + 30), tuple(cells)))

        return VenueTimeGridSnapshot(
            target_date=target.isoformat(), timezone_name=timezone_name, venue_name=venue,
            court_names=courts, rows=tuple(rows), duration_minutes=duration_minutes,
        ).to_dict()
