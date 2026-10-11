from __future__ import annotations

from dataclasses import dataclass

from backend.availability_matching.models import AvailabilityError, AvailabilitySnapshot, clock, minutes


GRID_STATES = frozenset({
    "selectable", "reserved", "activity_occupied", "unbookable", "unknown",
    "historical_selectable", "historical_reserved", "historical_activity_occupied",
    "historical_unbookable", "historical_unknown",
})
GRID_NOTICE = (
    "这是合成网格预览，不是实时场馆库存。场馆和场地仅为人工偏好标签；"
    "选择后只更新预约意向，不会查询、预约或支付。"
)
HISTORICAL_NOTICE = (
    "这是官方客户端历史响应的只读显示观察，不代表当前库存。未知状态保持未知；"
    "历史格子不能用于选择、预约或支付。"
)


class VenueTimeGridError(AvailabilityError):
    def __init__(self, code: str = "invalid_venue_time_grid", status: int = 400):
        super().__init__(code, status)


@dataclass(frozen=True, slots=True)
class VenueGridCell:
    state: str
    reason_code: str
    category_label: str | None = None
    selectable: bool = False

    def __post_init__(self):
        if self.state not in GRID_STATES:
            raise VenueTimeGridError()
        if type(self.reason_code) is not str or not 1 <= len(self.reason_code) <= 64:
            raise VenueTimeGridError()
        if self.category_label is not None and (type(self.category_label) is not str or not 1 <= len(self.category_label) <= 40):
            raise VenueTimeGridError()
        is_activity = self.state in {"activity_occupied", "historical_activity_occupied"}
        if is_activity != (self.category_label is not None):
            raise VenueTimeGridError()
        if type(self.selectable) is not bool or (self.selectable and self.state != "selectable"):
            raise VenueTimeGridError()

    def to_dict(self) -> dict:
        return {"state": self.state, "selectable": self.selectable,
                "reason_code": self.reason_code, "category_label": self.category_label}


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


class AvailabilityGridProjector:
    """Project normalized slot facts to a display matrix without changing matcher status."""

    def project(self, snapshot: AvailabilitySnapshot, *, court_names: list[str] | tuple[str, ...],
                duration_minutes: int, scenario: str | None = None,
                window_start: str | None = None, window_end: str | None = None) -> dict:
        if type(snapshot) is not AvailabilitySnapshot:
            raise VenueTimeGridError()
        if type(court_names) not in (list, tuple) or not 1 <= len(court_names) <= 16:
            raise VenueTimeGridError("invalid_venue_grid_courts")
        if (any(type(name) is not str or not 1 <= len(name.strip()) <= 100 for name in court_names)
                or len(set(name.strip() for name in court_names)) != len(court_names)):
            raise VenueTimeGridError("invalid_venue_grid_courts")
        if type(duration_minutes) is not int or not 30 <= duration_minutes <= 240 or duration_minutes % 30:
            raise VenueTimeGridError("invalid_venue_grid_duration")

        bands = snapshot.time_bands or tuple(sorted({(slot.start_time, slot.end_time) for slot in snapshot.slots},
                                                      key=lambda band: minutes(band[0])))
        if (window_start is None) != (window_end is None):
            raise VenueTimeGridError()
        if window_start is None:
            visible_bands = bands
        else:
            window_start_minute, window_end_minute = minutes(window_start), minutes(window_end, end=True)
            if window_start_minute >= window_end_minute:
                raise VenueTimeGridError()
            visible_bands = tuple((start, end) for start, end in bands
                                  if minutes(start) >= window_start_minute and minutes(end, end=True) <= window_end_minute)
        if not visible_bands:
            raise VenueTimeGridError("venue_grid_has_no_visible_rows")
        if len(visible_bands) > 96:
            raise VenueTimeGridError("invalid_venue_time_grid")

        slot_index = {(slot.court_name, slot.start_time, slot.end_time): slot for slot in snapshot.slots}
        courts = tuple(name.strip() for name in court_names)
        rows = []
        for start_time, end_time in visible_bands:
            cells = []
            for court in courts:
                slot = slot_index.get((court, start_time, end_time))
                cells.append(self._cell(slot, snapshot.simulation))
            rows.append(VenueGridRow(start_time, end_time, tuple(cells)))

        lengths = {minutes(end, end=True) - minutes(start) for start, end in visible_bands}
        atom_minutes = lengths.pop() if len(lengths) == 1 else None
        source = snapshot.provenance()
        source["data_state"] = "synthetic" if snapshot.simulation else "historical_unverified"
        scenario = scenario or (snapshot.source.split(":", 1)[1] if snapshot.source.startswith("synthetic-v1:") else None)
        return {
            "grid_version": "venue-time-grid-v2",
            "simulation": snapshot.simulation,
            "scenario": scenario,
            "source": source,
            "notice": GRID_NOTICE if snapshot.simulation else HISTORICAL_NOTICE,
            "target_date": snapshot.target_date,
            "timezone_name": snapshot.timezone_name,
            "venue": {"display_name": snapshot.venue_name, "verification": "unverified_manual"},
            "atom_minutes": atom_minutes,
            "duration_minutes": duration_minutes,
            "courts": [{"display_name": name, "verification": "unverified_manual"} for name in courts],
            "rows": [row.to_dict() for row in rows],
            "can_query_upstream": False,
            "can_book": False,
            "can_pay": False,
            "can_create_job": False,
        }

    @staticmethod
    def _cell(slot, simulation: bool) -> VenueGridCell:
        if slot is None:
            return VenueGridCell("unknown" if simulation else "historical_unknown", "missing_snapshot_slot")
        observed = slot.display_state or {
            "available": "selectable", "unavailable": "reserved", "unknown": "unknown",
        }[slot.status]
        if simulation:
            if slot.status == "available" and observed == "selectable":
                state = "selectable"
            elif slot.status == "unavailable" and observed in {"reserved", "activity_occupied", "unbookable"}:
                state = observed
            else:
                state = "unknown"
            reason = "synthetic_" + state
            return VenueGridCell(state, reason,
                                 slot.display_label if state == "activity_occupied" else None,
                                 selectable=state == "selectable")

        # A normalized non-simulation Snapshot has no live execution authority.
        # Keep the observed client display state visible but make every cell read-only.
        historical_state = "historical_" + observed if observed in {"selectable", "reserved", "activity_occupied", "unbookable"} else "historical_unknown"
        label = slot.display_label if historical_state == "historical_activity_occupied" else None
        return VenueGridCell(historical_state, "historical_unverified", label, selectable=False)
