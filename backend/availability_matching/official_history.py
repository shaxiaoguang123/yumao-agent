from __future__ import annotations

import re
import unicodedata

from backend.availability_matching.models import AvailabilityError


_TIME_LABEL = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", re.ASCII)
_INDEX = re.compile(r"[0-9]{1,3}", re.ASCII)
_COURT_LIMIT = 32
_ROW_LIMIT = 48
_CONFLICT_LIMIT = 4096


def _invalid():
    raise AvailabilityError("invalid_official_history_response", 400)


def _display_text(value):
    if (type(value) is not str or not 1 <= len(value.strip()) <= 100
            or any(unicodedata.category(char) in {"Cc", "Cs"} for char in value)):
        _invalid()
    return value.strip()


class OfficialBookingByTimeHistoryAdapter:
    """Turn a captured response into a historical display DTO, never inventory."""

    def preview(self, envelope: object) -> dict:
        if type(envelope) is not dict or envelope.get("success") is not True:
            _invalid()
        result = envelope.get("resultData")
        if type(result) is not dict:
            _invalid()
        required = {"stepnumber", "nodeList", "timeList", "conflictList", "priceList"}
        if not required.issubset(result):
            _invalid()

        stepnumber = result["stepnumber"]
        if type(stepnumber) is not str or not _INDEX.fullmatch(stepnumber):
            _invalid()
        row_count = int(stepnumber)
        courts_raw, times_raw = result["nodeList"], result["timeList"]
        if (type(courts_raw) is not list or not 1 <= len(courts_raw) <= _COURT_LIMIT
                or type(times_raw) is not list or not 1 <= len(times_raw) <= _ROW_LIMIT
                or row_count != len(times_raw)):
            _invalid()

        courts = []
        for item in courts_raw:
            if type(item) is not dict or "sitename" not in item or "nodeid" not in item:
                _invalid()
            node_id = item["nodeid"]
            if (type(node_id) not in (str, int) or type(node_id) is bool
                    or (type(node_id) is str and not 1 <= len(node_id) <= 128)):
                _invalid()
            courts.append({"display_name": _display_text(item["sitename"]),
                           "verification": "historical_unverified"})

        time_rows = []
        for item in times_raw:
            if type(item) is not dict or "time" not in item or "status" not in item:
                _invalid()
            raw_label = item["time"]
            label = raw_label if type(raw_label) is str and _TIME_LABEL.fullmatch(raw_label) else None
            raw_status = item["status"]
            status = raw_status if type(raw_status) is str and raw_status in {"0", "1"} else None
            time_rows.append((label, status))

        conflicts = result["conflictList"]
        prices = result["priceList"]
        if (type(conflicts) is not list or len(conflicts) > _CONFLICT_LIMIT
                or type(prices) is not list or len(prices) > _CONFLICT_LIMIT):
            _invalid()
        by_cell: dict[tuple[int, int], set[tuple[str, int | None]]] = {}
        for conflict in conflicts:
            if type(conflict) is not str:
                _invalid()
            parts = conflict.split("-")
            if len(parts) not in (2, 3) or any(not _INDEX.fullmatch(part) for part in parts):
                _invalid()
            court_index, row_index = int(parts[0]), int(parts[1])
            if court_index >= len(courts) or row_index >= row_count:
                _invalid()
            if len(parts) == 2:
                observation = ("reserved", None)
            else:
                category = int(parts[2])
                state = "activity_occupied" if 0 <= category <= 6 else "unbookable" if category == 7 else "unknown"
                observation = (state, category)
            by_cell.setdefault((court_index, row_index), set()).add(observation)

        rows = []
        for row_index, (label, row_status) in enumerate(time_rows):
            row_status_known = row_status is not None and label is not None
            cells = []
            for court_index in range(len(courts)):
                observed_states = by_cell.get((court_index, row_index), set())
                if not row_status_known or len(observed_states) > 1:
                    state = "unknown"
                elif observed_states:
                    state = next(iter(observed_states))[0]
                else:
                    # The official client initializes the grid as display-state 1.
                    # It is retained only as a historical observation, not availability.
                    state = "selectable"
                cells.append({
                    "state": "historical_" + state,
                    "selectable": False,
                    "reason_code": "historical_unverified",
                    "category_label": "客户端活动类别（语义未核验）" if state == "activity_occupied" else None,
                })
            rows.append({
                "time_label": label if label is not None else "时间标签未知",
                "time_status": {"state": "recognized_unverified", "code": row_status}
                    if row_status_known else {"state": "unknown", "code": None},
                "cells": cells,
            })

        return {
            "grid_version": "official-history-grid-v1",
            "simulation": False,
            "source": {
                "source": "official-bookingByTime-history",
                "data_state": "historical_unverified",
                "trust_state": "normalized_unverified",
                "freshness_state": "unknown",
                "captured_at_utc_ms": None,
                "client_version_state": "unknown",
                "venue_scope_state": "unverified",
                "time_atom_state": "unknown",
                "availability_semantics_state": "unverified",
            },
            "notice": (
                "此网格只还原官方客户端对历史响应的显示观察。采集时间、客户端版本、"
                "场馆归属、时段长度及状态业务含义未核验；不代表当前库存。"
            ),
            "target_date": None,
            "timezone_name": None,
            "venue": {"display_name": "场馆查询范围未知", "verification": "unverified"},
            "courts": courts,
            "rows": rows,
            "row_count": row_count,
            "price_state": "omitted_unit_unverified",
            "can_select": False,
            "can_match": False,
            "can_bind": False,
            "can_query_upstream": False,
            "can_book": False,
            "can_pay": False,
            "can_create_job": False,
        }
