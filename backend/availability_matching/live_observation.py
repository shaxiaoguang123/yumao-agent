from __future__ import annotations

import re
import unicodedata
from datetime import date

from backend.availability_matching.models import AvailabilityError


_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", re.ASCII)
_INDEX = re.compile(r"[0-9]{1,3}", re.ASCII)
_MAX_COURTS = 32
_MAX_ROWS = 48
_MAX_CONFLICTS = 4096

LIVE_OBSERVATION_NOTICE = (
    "这是刚读取的官方预约类别时段显示，只是当前只读观察；场馆归属、时间长度和可预约语义尚未核验。"
    "所有格子均不可用于下单，过期后请重新读取。"
)


class LiveAvailabilityObservationError(AvailabilityError):
    def __init__(self, code: str = "invalid_live_availability_response", status: int = 502):
        super().__init__(code, status)


def _invalid():
    raise LiveAvailabilityObservationError()


def _text(value: object, *, limit: int = 100) -> str:
    if (type(value) is not str or not 1 <= len(value.strip()) <= limit
            or any(unicodedata.category(char) in {"Cc", "Cs"} for char in value)):
        _invalid()
    return value.strip()


def _number(value: object, *, low: int, high: int) -> int | None:
    if type(value) is int:
        parsed = value
    elif type(value) is str and _INDEX.fullmatch(value):
        parsed = int(value)
    else:
        return None
    return parsed if low <= parsed <= high else None


class OfficialBookingByTimeObservationAdapter:
    """Normalize one live response for read-only display; never produce inventory."""

    def adapt(
        self,
        envelope: object,
        *,
        target_date: str,
        timezone_name: str,
        query_scope_label: str,
        captured_at_utc_ms: int,
    ) -> dict:
        if type(envelope) is not dict or envelope.get("success") is not True:
            _invalid()
        try:
            parsed_date = date.fromisoformat(target_date)
        except (TypeError, ValueError):
            _invalid()
        if parsed_date.isoformat() != target_date:
            _invalid()
        if (type(timezone_name) is not str or not timezone_name
                or type(captured_at_utc_ms) is not int or captured_at_utc_ms < 0):
            _invalid()

        result = envelope.get("resultData")
        if type(result) is not dict:
            _invalid()
        row_count = _number(result.get("stepnumber"), low=1, high=_MAX_ROWS)
        courts_raw, times_raw = result.get("nodeList"), result.get("timeList")
        conflicts = result.get("conflictList")
        if (row_count is None or type(courts_raw) is not list
                or not 1 <= len(courts_raw) <= _MAX_COURTS
                or type(times_raw) is not list or len(times_raw) != row_count
                or type(conflicts) is not list or len(conflicts) > _MAX_CONFLICTS):
            _invalid()

        courts: list[dict[str, str]] = []
        court_names: set[str] = set()
        for item in courts_raw:
            if type(item) is not dict:
                _invalid()
            node_id = item.get("nodeid")
            if (type(node_id) not in {str, int} or type(node_id) is bool
                    or (type(node_id) is str and not 1 <= len(node_id) <= 128)):
                _invalid()
            name = _text(item.get("sitename"))
            if name in court_names:
                _invalid()
            court_names.add(name)
            # Upstream court IDs are validated but intentionally never serialized.
            courts.append({"display_name": name, "verification": "unverified"})

        time_rows: list[tuple[str | None, str | None]] = []
        seen_times: set[str] = set()
        for item in times_raw:
            if type(item) is not dict:
                _invalid()
            raw_time = item.get("time")
            label = raw_time if type(raw_time) is str and _TIME.fullmatch(raw_time) else None
            if label in seen_times:
                label = None
            elif label is not None:
                seen_times.add(label)
            raw_status = item.get("status")
            status = raw_status if type(raw_status) is str and raw_status in {"0", "1"} else None
            time_rows.append((label, status))

        cell_states: dict[tuple[int, int], set[tuple[str, int | None]]] = {}
        duplicate_conflict_count = 0
        for raw in conflicts:
            if type(raw) is not str:
                _invalid()
            parts = raw.split("-")
            if len(parts) not in {2, 3} or any(not _INDEX.fullmatch(part) for part in parts):
                _invalid()
            court_index, row_index = int(parts[0]), int(parts[1])
            if court_index >= len(courts) or row_index >= row_count:
                _invalid()
            if len(parts) == 2:
                observation = ("observed_reserved", None)
            else:
                category = int(parts[2])
                if 0 <= category <= 6:
                    observation = ("observed_activity_occupied", category)
                elif category == 7:
                    observation = ("observed_unbookable", category)
                else:
                    observation = ("observed_unknown", category)
            observed = cell_states.setdefault((court_index, row_index), set())
            if observation in observed:
                duplicate_conflict_count += 1
            observed.add(observation)

        rows = []
        for row_index, (label, status_code) in enumerate(time_rows):
            cells = []
            for court_index in range(len(courts)):
                observed = cell_states.get((court_index, row_index), set())
                if status_code != "0" or label is None:
                    state = "observed_unknown"
                    reason = "official_client_hides_row_cells" if status_code == "1" else "unknown_time_row_state"
                elif len(observed) > 1:
                    state, reason = "observed_unknown", "conflicting_duplicate_conflicts"
                elif observed:
                    state, category = next(iter(observed))
                    reason = "official_conflict_display_rule"
                    if state == "observed_unknown":
                        reason = "unknown_conflict_category"
                else:
                    # The client initializes an unmarked cell as display state 1.
                    # This is an observation only; no claim of confirmed availability is made.
                    state, reason = "observed_clear_unmarked", "no_conflict_marker_in_response"
                cells.append({
                    "state": state,
                    "label": _activity_label(observed) if state == "observed_activity_occupied" else None,
                    "selectable": False,
                    "reason_code": reason,
                })
            rows.append({
                "time_label": label or "时间未知",
                "client_displays_cells": status_code == "0" and label is not None,
                "time_status_code": status_code,
                "time_status_semantics": "unverified",
                "cells": cells,
            })

        min_slots = _number(result.get("mintimeselect"), low=1, high=_MAX_ROWS)
        max_slots = _number(result.get("maxtimeselect"), low=1, high=_MAX_ROWS)
        max_courts = _number(result.get("maxAppointmentNodeNum"), low=1, high=_MAX_COURTS)
        scope_label = _text(query_scope_label)
        return {
            "grid_version": "official-bookingByTime-live-observation-v1",
            "data_state": "live_observed_unverified",
            "simulation": False,
            "notice": LIVE_OBSERVATION_NOTICE,
            "target_date": target_date,
            "timezone_name": timezone_name,
            "query_scope": {"display_name": scope_label, "kind": "booking_category", "physical_venue_verified": False},
            "courts": courts,
            "rows": rows,
            "row_count": row_count,
            "selection_limits": {
                "min_slots_observed": min_slots,
                "max_slots_observed": max_slots,
                "max_courts_observed": max_courts,
                "semantics": "official_client_ui_limit_unverified",
            },
            "diagnostics": {"duplicate_conflict_count": duplicate_conflict_count},
            "source": {
                "source": "official-bookingByTime-live-read",
                "data_state": "live_observed_unverified",
                "trust_state": "display_only_unverified",
                "freshness_state": "observed_at_request",
                "captured_at_utc_ms": captured_at_utc_ms,
                "ui_stale_after_utc_ms": captured_at_utc_ms + 60_000,
                "venue_scope_state": "booking_category_only",
                "court_ownership_state": "unverified",
                "availability_semantics_state": "unverified",
                "time_atom_state": "unknown",
                "price_state": "omitted_unit_unverified",
                "client_version_state": "unknown",
            },
            "can_select": False,
            "can_match": False,
            "can_bind": False,
            "can_query_upstream": False,
            "can_book": False,
            "can_pay": False,
            "can_create_job": False,
        }


def _activity_label(observations: set[tuple[str, int | None]]) -> str | None:
    if len(observations) != 1:
        return None
    _state, category = next(iter(observations))
    return f"客户端活动类别 {category}（语义未核验）"
