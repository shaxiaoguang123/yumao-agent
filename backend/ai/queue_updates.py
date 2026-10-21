"""Apply validated model deltas to a copy of the canonical queue state."""
from __future__ import annotations

from copy import deepcopy
from datetime import date

from backend.ai import queue_text
from backend.ai.queue_draft import Draft, ONE, TWO, overlapping_pairs


def apply_updates(draft: Draft, decision: dict) -> Draft:
    """Apply the model's typed delta without reparsing generated natural language."""
    updated = deepcopy(draft)
    for item in decision["updates"]:
        field, operation, value = item["field"], item["operation"], item["value"]
        if operation == "clear":
            clear_field(updated, field)
        elif field == "booking_mode":
            updated.booking_mode, updated.mode_issue = value, None
        elif field == "target_date":
            updated.dates, updated.date_state = (date.fromisoformat(value),), "resolved"
        elif field.startswith("windows_"):
            _apply_windows(updated, field, operation, value)
            if item.get("resolves_duration") and updated.duration_issue and updated.duration_issue[1] == (ONE if field.endswith("_1h") else TWO):
                updated.duration_issue = None
        elif field.startswith("courts_"):
            _apply_courts(updated, field, operation, value)
        elif field.startswith("overlap_"):
            group = updated.g1 if field.endswith("_1h") else updated.g2
            group.acked.update(frozenset(pair) for pair in overlapping_pairs(group.windows))
    for item in decision["unresolved"]:
        field, evidence = item["field"], item["evidence"]
        issue = item.get("issue", "ambiguous")
        if field == "booking_mode":
            updated.mode_issue = "还不清楚要排只抢2小时、只抢1小时，还是两种都抢。"
        elif field == "target_date":
            updated.date_state, updated.dates = "ambiguous", ()
        elif field.startswith("windows_"):
            group = updated.g1 if field.endswith("_1h") else updated.g2
            group.issue, group.issue_text = issue, evidence
            if issue == "unsupported_duration" and type(item.get("duration_minutes")) is int:
                updated.duration_issue = (item["duration_minutes"], ONE if field.endswith("_1h") else TWO)
        elif field.startswith("courts_"):
            group = updated.g1 if field.endswith("_1h") else updated.g2
            if issue == "scoped_preferences":
                group.court_scope_ambiguous = True
                group.courts_issue = None
            else:
                group.courts_issue = "场地偏好还不明确。请说出要保留的场地，例如1号和4号。"
        elif field.startswith("overlap_"):
            (updated.g1 if field.endswith("_1h") else updated.g2).acked.clear()
    return updated


def _clock_minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _window_label(start: int, end: int) -> str:
    def clock(value: int) -> str:
        return "24:00" if value == 24 * 60 else f"{value // 60:02d}:{value % 60:02d}"
    return queue_text.show_windows([(start, end)]) if start < end else f"{clock(start)}-{clock(end)}"


def _apply_windows(draft: Draft, field: str, operation: str, value: list[dict]) -> None:
    minutes = ONE if field.endswith("_1h") else TWO
    group = draft.g1 if minutes == ONE else draft.g2
    windows = [(_clock_minutes(item["start"]), _clock_minutes(item["end"])) for item in value]
    old_windows = list(group.windows)
    if operation == "replace":
        group.windows = []
        group.invalid_windows = []
        group.acked.clear()
        group.issue, group.issue_text = None, ""
    if operation == "remove":
        removed = set(windows)
        group.windows = [window for window in group.windows if window not in windows]
        group.invalid_windows = [item for item in group.invalid_windows if (item[0], item[1]) not in removed]
        if group.issue and group.issue_text:
            normalized_issue = "".join(group.issue_text.split())
            if any("".join(_window_label(start, end).split()) == normalized_issue for start, end in windows):
                group.issue, group.issue_text = None, ""
                if draft.duration_issue and draft.duration_issue[1] == minutes:
                    draft.duration_issue = None
    elif operation in {"replace", "add"}:
        valid_windows, invalid_windows = [], []
        for start, end in windows:
            duration, label = end - start, _window_label(start, end)
            if end <= start:
                issue = "bad_order"
            elif duration != minutes:
                issue = "bad_length"
            elif start < 9 * 60 or end > 22 * 60:
                issue = "outside_hours"
            elif start % 60 or end % 60:
                issue = "unaligned"
            else:
                valid_windows.append((start, end))
                continue
            invalid_windows.append((start, end, issue, label))
        group.windows.extend(window for window in valid_windows if window not in group.windows)
        known_invalid = {(item[0], item[1]) for item in group.invalid_windows}
        group.invalid_windows.extend(item for item in invalid_windows if (item[0], item[1]) not in known_invalid)
    current_pairs = {frozenset(pair) for pair in overlapping_pairs(group.windows)}
    group.acked.intersection_update(current_pairs)
    if old_windows != group.windows:
        group.court_bindings = {window: list(group.courts) for window in group.windows if group.courts}


def _apply_courts(draft: Draft, field: str, operation: str, value: list[int]) -> None:
    minutes = ONE if field.endswith("_1h") else TWO
    group = draft.g1 if minutes == ONE else draft.g2
    valid = [number for number in value if 1 <= number <= 10]
    invalid = [number for number in value if not 1 <= number <= 10]
    if operation == "replace":
        group.courts, group.bad_courts = [], []
    if operation == "remove":
        group.courts = [number for number in group.courts if number not in value]
        group.bad_courts = [number for number in group.bad_courts if number not in value]
    else:
        group.courts.extend(number for number in valid if number not in group.courts)
        group.bad_courts.extend(number for number in invalid if number not in group.bad_courts)
    if operation == "replace":
        group.courts_issue = None
        group.court_scope_ambiguous = False
    group.court_bindings = {window: list(group.courts) for window in group.windows if group.courts}


def clear_field(draft: Draft, field: str) -> None:
    if field == "booking_mode":
        draft.booking_mode, draft.mode_issue = None, None
    elif field == "target_date":
        draft.dates, draft.date_state = (), "empty"
    elif field.startswith("windows_"):
        group = draft.g1 if field.endswith("_1h") else draft.g2
        group.windows, group.invalid_windows, group.acked, group.court_bindings = [], [], set(), {}
        group.issue, group.issue_text = None, ""
        if draft.duration_issue and draft.duration_issue[1] == group.minutes:
            draft.duration_issue = None
    elif field.startswith("courts_"):
        group = draft.g1 if field.endswith("_1h") else draft.g2
        group.courts, group.bad_courts, group.court_bindings = [], [], {}
        group.courts_issue, group.court_scope_ambiguous = None, False
    else:
        (draft.g1 if field.endswith("_1h") else draft.g2).acked.clear()


def restore_fields(draft: Draft, before: Draft, fields: list[str]) -> Draft:
    """Rollback only the requested facts, retaining unrelated conversation progress."""
    result = deepcopy(draft)
    for field in fields:
        if field == "booking_mode":
            result.booking_mode, result.mode_issue = before.booking_mode, before.mode_issue
        elif field == "target_date":
            result.dates, result.date_state = before.dates, before.date_state
        else:
            minutes = ONE if field.endswith("_1h") else TWO
            group, source = result.groups[minutes], before.groups[minutes]
            keys = ("windows", "invalid_windows", "issue", "issue_text", "acked") if field.startswith("windows_") else (
                ("courts", "bad_courts", "court_bindings", "court_scope_ambiguous", "courts_issue")
                if field.startswith("courts_") else ("acked",))
            for key in keys:
                setattr(group, key, deepcopy(getattr(source, key)))
            if field.startswith("windows_") and (before.duration_issue is None or before.duration_issue[1] == minutes):
                if result.duration_issue is None or result.duration_issue[1] == minutes:
                    result.duration_issue = before.duration_issue
    for group in result.groups.values():
        if group.court_scope_ambiguous:
            group.court_bindings = {window: courts for window, courts in group.court_bindings.items() if window in group.windows}
        else:
            group.court_bindings = {window: list(group.courts) for window in group.windows if group.courts}
    return result
