"""Bounded edit transactions around canonical facts; no model or database access."""
from __future__ import annotations

from copy import deepcopy
from datetime import date

from backend.ai.conversation import SlotStatus
from backend.ai.queue_draft import deserialize_draft, serialize_draft, overlapping_pairs
from backend.ai.queue_policy import FIELD_ORDER, MAX_ANSWER_COUNT
from backend.ai.queue_slots import build_slots
from backend.ai.queue_updates import restore_fields
from backend.ai.queue_turn import validate_update


def empty_dialogue():
    return {"pending_edit": None, "dialogue_focus": None, "next_action": "ask", "undo": [],
            "sources": {}, "unresolved": {}, "review_cache": None}


def _fields(value):
    return (type(value) is list and len(value) <= len(FIELD_ORDER)
            and all(type(item) is str and item in FIELD_ORDER for item in value)
            and len(set(value)) == len(value))


def _metadata(sources, issues):
    if any(type(value) is not dict or not value.keys() <= set(FIELD_ORDER) for value in (sources, issues)):
        return False
    for field, record in sources.items():
        if (type(record) is not dict or record.keys() != {"business_date", "operations"}
                or type(record["business_date"]) is not str or len(record["business_date"]) != 10
                or type(record["operations"]) is not list or not 1 <= len(record["operations"]) <= 12):
            return False
        try:
            date.fromisoformat(record["business_date"])
        except ValueError:
            return False
        for operation in record["operations"]:
            if type(operation) is not dict or operation.keys() != {"operation", "value", "evidence"} or validate_update({"field": field, **operation}, operation.get("evidence", "")) is None:
                return False
    for field, issue in issues.items():
        if (type(issue) is not dict or not {"field", "evidence"} <= issue.keys()
                or not issue.keys() <= {"field", "evidence", "issue", "duration_minutes"}
                or issue["field"] != field or type(issue["evidence"]) is not str or not 1 <= len(issue["evidence"]) <= 240
                or type(issue.get("issue", "ambiguous")) is not str):
            return False
    return True


def load_dialogue(raw):
    if raw is None:
        return empty_dialogue()
    if type(raw) is not dict or raw.keys() != empty_dialogue().keys():
        return None
    if (raw["dialogue_focus"] not in (*FIELD_ORDER, None)
            or type(raw["next_action"]) is not str or raw["next_action"] not in {"ask", "answer", "preview", "clarify_edit", "edit", "refuse", "escalate"}
            or type(raw["undo"]) is not list or len(raw["undo"]) > MAX_ANSWER_COUNT + 1
            or any(type(raw[key]) is not dict or not raw[key].keys() <= set(FIELD_ORDER)
                   for key in ("sources", "unresolved"))):
        return None
    if not _metadata(raw["sources"], raw["unresolved"]):
        return None
    cache = raw["review_cache"]
    if cache is not None and (type(cache) is not dict or cache.keys() != {"fingerprint", "warnings", "review", "provider"}
            or type(cache["fingerprint"]) is not str or len(cache["fingerprint"]) != 64
            or type(cache["warnings"]) is not list or len(cache["warnings"]) > 8
            or any(type(item) is not str or len(item) > 500 for item in cache["warnings"])
            or type(cache["review"]) is not dict or cache["review"].get("state") != "reviewed"
            or type(cache["provider"]) is not dict):
        return None
    records = list(raw["undo"])
    pending = raw["pending_edit"]
    if pending is not None:
        if (type(pending) is not dict or pending.keys() != {
                "fields", "remaining", "before", "before_sources", "before_issues", "resume_focus", "undo_start", "question"}
                or not _fields(pending["fields"]) or not _fields(pending["remaining"])
                or not set(pending["remaining"]) <= set(pending["fields"])
                or pending["resume_focus"] not in (*FIELD_ORDER, None)
                or type(pending["undo_start"]) is not int or not 0 <= pending["undo_start"] <= len(records)
                or type(pending["question"]) is not str or len(pending["question"]) > 240):
            return None
        records.append(pending)
    for item in records:
        if (type(item) is not dict or not {"fields", "before", "before_sources", "before_issues"} <= item.keys()
                or not _fields(item["fields"]) or deserialize_draft(item["before"]) is None
                or any(type(item[key]) is not dict or not item[key].keys() <= set(FIELD_ORDER)
                       for key in ("before_sources", "before_issues"))):
            return None
    if any(not _metadata(item["before_sources"], item["before_issues"]) for item in records):
        return None
    return deepcopy(raw)


def field_value(draft, field):
    if field == "booking_mode":
        return draft.booking_mode, draft.mode_issue
    if field == "target_date":
        return draft.date_state, tuple(draft.dates)
    group = draft.g1 if field.endswith("_1h") else draft.g2
    if field.startswith("windows_"):
        return (group.windows, group.invalid_windows, group.issue, group.issue_text,
                draft.duration_issue if draft.duration_issue and draft.duration_issue[1] == group.minutes else None)
    if field.startswith("courts_"):
        return group.courts, group.bad_courts, group.courts_issue, group.court_scope_ambiguous
    return group.acked


def _restore_metadata(state, record, fields):
    for key, before in (("sources", "before_sources"), ("unresolved", "before_issues")):
        for field in fields:
            state[key].pop(field, None)
            if field in record[before]:
                state[key][field] = deepcopy(record[before][field])


def begin_control(draft, dialogue, decision, focus):
    """Apply an explicit edit/rollback action before applying this turn's fact deltas."""
    state, result, events = deepcopy(dialogue), deepcopy(draft), []
    action = decision.get("dialogue_action", {"type": "continue", "fields": []})
    kind, fields = action["type"], action["fields"]
    if kind == "begin_edit":
        pending = state["pending_edit"]
        if pending is None:
            pending = {"fields": list(fields), "remaining": list(fields), "before": serialize_draft(result),
                       "before_sources": deepcopy(state["sources"]), "before_issues": deepcopy(state["unresolved"]),
                       "resume_focus": focus, "undo_start": len(state["undo"]), "question": decision.get("next_question", "")}
            state["pending_edit"] = pending
        else:
            pending["fields"] = list(dict.fromkeys([*pending["fields"], *fields]))
            pending["remaining"] = list(dict.fromkeys([*pending["remaining"], *fields]))
            pending["question"] = decision.get("next_question", "")
        events.append("editing_started")
    elif kind == "cancel_edit":
        pending = state["pending_edit"]
        if pending is not None:
            result = restore_fields(result, deserialize_draft(pending["before"]), pending["fields"])
            _restore_metadata(state, pending, pending["fields"])
            for record in state["undo"][pending["undo_start"]:]:
                record["fields"] = [field for field in record["fields"] if field not in pending["fields"]]
            state["undo"] = [record for record in state["undo"] if record["fields"]]
            state["pending_edit"] = None
            events.append("editing_cancelled")
        else:
            events.append("no_pending_edit")
    elif kind == "undo":
        index = next((index for index in range(len(state["undo"]) - 1, -1, -1)
                      if not fields or set(state["undo"][index]["fields"]) & set(fields)), None)
        if index is not None:
            record = state["undo"][index]
            selected = [field for field in record["fields"] if not fields or field in fields]
            result = restore_fields(result, deserialize_draft(record["before"]), selected)
            _restore_metadata(state, record, selected)
            record["fields"] = [field for field in record["fields"] if field not in selected]
            if not record["fields"]:
                state["undo"].pop(index)
            if state["pending_edit"]:
                state["pending_edit"]["undo_start"] = min(state["pending_edit"]["undo_start"], len(state["undo"]))
            events.append("change_undone")
        else:
            events.append("nothing_to_undo")
    return result, state, events


def finish_updates(before, after, state, decision, today):
    newly_unresolved = {item["field"] for item in decision["unresolved"]
                        if item != state["unresolved"].get(item["field"])}
    changed = [field for field in FIELD_ORDER if field_value(before, field) != field_value(after, field)
               or field in newly_unresolved]
    if changed:
        state["undo"].append({"fields": changed, "before": serialize_draft(before),
                              "before_sources": deepcopy(state["sources"]), "before_issues": deepcopy(state["unresolved"])})
        state["undo"] = state["undo"][-(MAX_ANSWER_COUNT + 1):]
    touched = {item["field"] for item in decision["updates"]}
    for field in touched:
        state["sources"][field] = {"business_date": today.isoformat(), "operations": [
            {key: deepcopy(item[key]) for key in ("operation", "value", "evidence")}
            for item in decision["updates"] if item["field"] == field]}
        if any(item["field"] == field and item["operation"] in {"replace", "set", "clear", "confirm"}
               for item in decision["updates"]):
            state["unresolved"].pop(field, None)
    for field in touched:
        if field.startswith("windows_"):
            group = after.g1 if field.endswith("_1h") else after.g2
            if not overlapping_pairs(group.windows):
                state["unresolved"].pop(field.replace("windows_", "overlap_"), None)
    for item in decision["unresolved"]:
        state["unresolved"][item["field"]] = deepcopy(item)
    resume_focus = None
    pending = state["pending_edit"]
    if pending and not pending["fields"] and touched:
        pending["fields"] = [field for field in FIELD_ORDER if field in touched]
        pending["remaining"] = list(pending["fields"])
    if pending and pending["fields"]:
        # Dormant groups can be edited without enabling them or inheriting other facts.
        inspection = deepcopy(after)
        inspection.booking_mode = "both"
        slots = build_slots(inspection, today)
        pending["remaining"] = [field for field in pending["remaining"]
                                if field not in touched or field in state["unresolved"]
                                or slots[field].status not in {SlotStatus.PROPOSED, SlotStatus.VERIFIED}]
        if not pending["remaining"]:
            resume_focus = pending["resume_focus"]
            state["pending_edit"] = None
    return state, resume_focus, changed


def public_dialogue(state):
    pending = state["pending_edit"]
    return {"pending_edit": ({"fields": pending["fields"], "remaining": pending["remaining"],
                              "resume_focus": pending["resume_focus"]} if pending else None),
            "dialogue_focus": state["dialogue_focus"], "next_action": state["next_action"],
            "last_change_fields": state["undo"][-1]["fields"] if state["undo"] else [],
            "fact_sources": {field: {"business_date": record["business_date"],
                                      "operations": [item["operation"] for item in record["operations"][-3:]],
                                      "evidence": record["operations"][-1]["evidence"][:120]}
                             for field, record in state["sources"].items()},
            "unresolved_facts": state["unresolved"]}
