from __future__ import annotations

from datetime import date

from backend.availability_matching.live_observation import (
    LiveAvailabilityObservationError,
    OfficialBookingByTimeObservationAdapter,
)


class ReconciliationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _minute(value: str) -> int:
    if type(value) is not str or len(value) != 5 or value[2] != ":":
        raise ValueError("invalid_time")
    hour, minute = value[:2], value[3:]
    if not hour.isdecimal() or not minute.isdecimal():
        raise ValueError("invalid_time")
    result = int(hour) * 60 + int(minute)
    if not 0 <= result < 24 * 60:
        raise ValueError("invalid_time")
    return result


def _candidate(intent: dict, queue_index: int) -> dict:
    start = intent.get("preferred_start_times", [None])[0]
    duration = intent.get("duration_minutes")
    court_preferences = intent.get("court_preferences")
    scope_label = intent.get("query_scope_label")
    # Older manual snapshots only stored this fixed official query category in
    # venue_preference. Resolve the label again against the current Token response;
    # never carry forward an old node ID or court index.
    if scope_label is None and intent.get("venue_preference") == "羽毛球（场馆未绑定）":
        scope_label = "羽毛球"
    if (type(start) is not str or type(duration) is not int
            or duration not in {60, 120} or type(court_preferences) is not list
            or len(court_preferences) != 1 or type(court_preferences[0]) is not str):
        raise ReconciliationError("saved_queue_contract_invalid")
    try:
        end_minutes = _minute(start) + duration
    except ValueError as exc:
        raise ReconciliationError("saved_queue_contract_invalid") from exc
    if end_minutes > 24 * 60:
        raise ReconciliationError("saved_queue_contract_invalid")
    end = "24:00" if end_minutes == 24 * 60 else f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
    return {
        "queue_index": queue_index,
        "priority": "two_hour" if duration == 120 else "one_hour",
        "scope_label": scope_label if type(scope_label) is str else None,
        "court_preference": court_preferences[0],
        "start_time": start,
        "end_time": end,
        "duration_minutes": duration,
    }


def _checked_response(envelope: object, *, target_date: str, timezone_name: str,
                      scope_label: str, captured_at_utc_ms: int) -> dict:
    try:
        OfficialBookingByTimeObservationAdapter().adapt(
            envelope,
            target_date=target_date,
            timezone_name=timezone_name,
            query_scope_label=scope_label,
            captured_at_utc_ms=captured_at_utc_ms,
        )
    except LiveAvailabilityObservationError as exc:
        raise ReconciliationError("booking_response_contract_invalid") from exc
    result = envelope["resultData"]
    try:
        start_date = result["bookingstartdate"]
        end_date = result["bookingenddate"]
        if (type(start_date) is not str or type(end_date) is not str
                or date.fromisoformat(start_date).isoformat() != start_date
                or date.fromisoformat(end_date).isoformat() != end_date
                or start_date > end_date):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ReconciliationError("booking_window_metadata_unknown") from None
    if not start_date <= target_date <= end_date:
        raise ReconciliationError("target_outside_booking_window")
    return result


def _conflicts(result: dict, *, ignore_preopening_unbookable: bool) -> set[tuple[int, int]]:
    conflicts = set()
    for raw in result["conflictList"]:
        parts = raw.split("-")
        if ignore_preopening_unbookable and len(parts) == 3 and parts[2] == "7":
            continue
        conflicts.add((int(parts[0]), int(parts[1])))
    return conflicts


def _match_cells(intent: dict, result: dict, *, ignore_preopening_unbookable: bool = False) -> str | None:
    candidates = intent
    court_list = result["nodeList"]
    time_list = result["timeList"]
    court_matches = [i for i, item in enumerate(court_list)
                     if item.get("sitename") == candidates["court_preference"]]
    if len(court_matches) != 1:
        return "court_not_found" if not court_matches else "court_name_ambiguous"
    try:
        start_minute = _minute(candidates["start_time"])
    except ValueError:
        return "time_label_unknown"
    row_matches = [i for i, item in enumerate(time_list)
                   if item.get("time") == candidates["start_time"]]
    if len(row_matches) != 1:
        return "time_label_unknown" if not row_matches else "time_label_ambiguous"
    row_index = row_matches[0]
    row_count = candidates["duration_minutes"] // 60
    court_index = court_matches[0]
    conflicts = _conflicts(
        result,
        ignore_preopening_unbookable=ignore_preopening_unbookable,
    )
    for offset in range(row_count):
        index = row_index + offset
        if index >= len(time_list):
            return "time_interval_incomplete"
        raw_time = time_list[index].get("time")
        expected_minute = start_minute + offset * 60
        expected = ("24:00" if expected_minute == 24 * 60
                    else f"{expected_minute // 60:02d}:{expected_minute % 60:02d}")
        if raw_time != expected:
            return "time_interval_not_contiguous"
        if time_list[index].get("status") != "0":
            return "time_row_not_selectable"
        if (court_index, index) in conflicts:
            return "explicit_conflict"
    return None


def reconcile_queue(candidates: list[dict], responses_by_scope: dict[str, dict], *,
                    target_date: str, timezone_name: str) -> tuple[list[dict], dict]:
    """Build a pre-opening candidate snapshot from explicit client blockers only.

    An unmarked cell before bookingstarttime is retained as a candidate because the
    official client applies a global closed-window display state before opening.
    It is not called available; the executor must read and validate it again at 07:30.
    """
    if type(candidates) is not list:
        raise ReconciliationError("saved_queue_contract_invalid")
    retained, discarded = [], {}
    validated: dict[str, dict] = {}
    for index, raw_intent in enumerate(candidates):
        candidate = _candidate(raw_intent, index)
        scope = candidate["scope_label"]
        if not scope:
            reason = "scope_unbound"
        elif scope not in responses_by_scope:
            reason = "scope_query_missing"
        else:
            if scope not in validated:
                envelope, captured_at = responses_by_scope[scope]
                validated[scope] = _checked_response(
                    envelope, target_date=target_date, timezone_name=timezone_name,
                    scope_label=scope, captured_at_utc_ms=captured_at,
                )
            reason = _match_cells(
                candidate,
                validated[scope],
                ignore_preopening_unbookable=True,
            )
        if reason is None:
            retained.append(candidate)
        else:
            discarded[reason] = discarded.get(reason, 0) + 1
    return retained, {
        "input_candidate_count": len(candidates),
        "retained_candidate_count": len(retained),
        "discarded_candidate_counts": discarded,
        "availability_claim": "none_pre_open; every candidate requires a fresh 07:30 query",
        "pre_open_global_gate_ignored": True,
    }


def candidate_coordinates(candidate: dict, envelope: dict, *, target_date: str,
                          timezone_name: str, captured_at_utc_ms: int) -> tuple[list[str] | None, str | None]:
    """Re-map one frozen preference to indexes from this fresh 07:30 response."""
    if type(envelope) is not dict or envelope.get("success") is not True:
        return None, "booking_query_failed"
    try:
        result = _checked_response(
            envelope,
            target_date=target_date,
            timezone_name=timezone_name,
            scope_label=candidate["scope_label"],
            captured_at_utc_ms=captured_at_utc_ms,
        )
        observation = OfficialBookingByTimeObservationAdapter().adapt(
            envelope,
            target_date=target_date,
            timezone_name=timezone_name,
            query_scope_label=candidate["scope_label"],
            captured_at_utc_ms=captured_at_utc_ms,
        )
    except ReconciliationError as exc:
        return None, exc.code
    if observation["client_selection_window"] != "open":
        return None, "booking_window_not_open"
    # Do not trust or reuse preflight court/time IDs. Re-run mapping on this response.
    reason = _match_cells(candidate, result)
    if reason:
        return None, reason
    court_index = next(i for i, item in enumerate(result["nodeList"])
                       if item.get("sitename") == candidate["court_preference"])
    row_index = next(i for i, item in enumerate(result["timeList"])
                     if item.get("time") == candidate["start_time"])
    return [f"{court_index}-{row_index + offset}"
            for offset in range(candidate["duration_minutes"] // 60)], None
