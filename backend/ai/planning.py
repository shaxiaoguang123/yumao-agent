"""Booking-queue drafting. The server builds the queue; the model answers context Q&A and reviews.

This service has no plan-writing or booking tools: it returns a proposal and the user
confirms it through the normal manual-queue save.
"""
from __future__ import annotations

import json
import hashlib
import logging
import re
import time
import unicodedata
from copy import deepcopy
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from backend.ai import conversation as conv
from backend.ai import queue_cues as cues
from backend.ai import queue_text as words
from backend.ai.conversation import Decision, Phase
from backend.ai.nlu.dates import WEEKDAY_NAMES
from backend.ai.nlu.windows import scan_windows
from backend.ai.queue_draft import ONE, TWO, Draft, entry_count, fold
from backend.ai.queue_draft import deserialize_draft, reconcile_legacy_slots, serialize_draft
from backend.ai.queue_slots import build_entries, build_slots, question, strip, window_summary
from backend.ai.queue_policy import FIELD_LABELS, WORKFLOW_CONTEXT, eligible_fields
from backend.ai.queue_turn import SENSITIVE_TEXT as _SECRET, SYSTEM_PROMPT as TURN_PROMPT, parse_turn_decision
from backend.ai.queue_updates import apply_updates
from backend.ai.queue_dialogue import empty_dialogue, load_dialogue, begin_control, finish_updates, public_dialogue, field_value
from backend.ai.queue_grounding import ground_decision
from backend.ai.review import REVIEW_VERSION, SYSTEM_PROMPT as REVIEW_PROMPT, build_payload, parse_warnings
from backend.ai.service import AIModelError, MAX_MODEL_MESSAGE_BYTES
from backend.booking_window import BookingWindowPolicy
from backend.plans.manual_queue import parse_queue, automatic_queue_schedule
from backend.plans.service import PlanError
from backend.plans.validation import IntentValidationError

log = logging.getLogger("yumao.planning")
_POSITIVE_ACK = re.compile(r"已(?:记录|记下|确认|选择|设置|保存)|已经(?:记录|记下|确认|选择|设置)|收到.{0,4}(?:已|已经)")
UNSUPPORTED_TEXT = "当前只能整理并保存预约队列，不能执行预约、付款或创建执行任务。"
# The daily worker books the date two days ahead at 07:30 (backend/execution/scheduler.py).
AUTO_DAYS_AHEAD, OPEN_HOUR, OPEN_MINUTE = 2, 7, 30
HEADING = FIELD_LABELS
_PARSING_PROVIDER_ERRORS = frozenset({
    "provider_address_rejected", "provider_auth_failed", "provider_access_denied",
    "provider_dns_resolution_failed", "provider_dns_timeout", "provider_model_or_endpoint_not_found",
    "provider_payment_required", "provider_rate_limited", "provider_redirect_rejected",
    "provider_request_failed", "provider_request_rejected", "provider_response_invalid",
    "provider_response_too_large", "provider_output_truncated", "provider_server_error", "provider_timeout",
    "provider_tls_failed", "provider_tls_verification_failed", "provider_unavailable",
})


def assistant_history_entry(response: object) -> dict:
    """Project a saved response into the bounded, non-secret context sent to the model."""
    if type(response) is not dict:
        return {}
    conversation = response.get("conversation")
    if type(conversation) is not dict:
        conversation = {}
    trace = conversation.get("turn_trace")
    if type(trace) is not dict:
        trace = {}
    raw_questions = response.get("questions")
    questions = ([question[:500] for question in raw_questions[:1]
                  if isinstance(question, str)] if type(raw_questions) is list else [])
    raw_updates = trace.get("updated_fields")
    updates = ([{"field": update.get("field"), "status": update.get("status")}
                for update in raw_updates[:8] if type(update) is dict]
               if type(raw_updates) is list else [])
    eligible = trace.get("eligible_fields")
    return {
        "asking": conversation.get("asking"), "phase": conversation.get("phase"),
        "turn_kind": trace.get("kind"), "turn_intent": trace.get("intent"),
        "workflow_state": response.get("workflow_state") or conversation.get("workflow_state"),
        "questions": questions,
        "reply": str(conversation.get("contextual_reply") or "")[:500],
        "validated_summary": str(trace.get("summary") or "")[:160],
        "validated_updates": updates,
        "eligible_fields": eligible[:8] if type(eligible) is list else [],
        "model_next_field": trace.get("model_next_field"),
        "candidate_count": trace.get("candidate_count"),
        "business_date": conversation.get("business_date"),
        "dialogue_focus": conversation.get("dialogue_focus"), "next_action": conversation.get("next_action"),
    }


def _queue_context_messages(payload: dict, turns: list[str], assistant_history: list[dict]) -> list[dict]:
    messages = [
        {"role": "system", "content": TURN_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, allow_nan=False)},
    ]
    for index, turn in enumerate(turns[:-1]):
        messages.append({"role": "user", "content": f"[历史用户轮次 {index + 1}]\n{turn}"})
        if index < len(assistant_history):
            record = json.dumps(assistant_history[index], ensure_ascii=False, allow_nan=False)
            messages.append({"role": "assistant", "content": f"[历史助手上下文投影 {index + 1}]\n{record}"})
    for index in range(len(turns) - 1, len(assistant_history)):
        record = json.dumps(assistant_history[index], ensure_ascii=False, allow_nan=False)
        messages.append({"role": "assistant", "content": f"[历史助手上下文投影 {index + 1}]\n{record}"})
    messages.append({"role": "user", "content": f"[本轮用户原文]\n{turns[-1]}"})
    try:
        oversized = any(len(message["content"].encode("utf-8")) > MAX_MODEL_MESSAGE_BYTES for message in messages)
    except UnicodeEncodeError:
        raise PlanError("invalid_planning_request", 400) from None
    if len(messages) > 64 or oversized:
        raise PlanError("planning_context_limit", 400)
    return messages


def _mode_update_is_explicit(update: dict, latest: str, asking: str | None) -> bool:
    field = "booking_mode" if asking == "booking_mode" else None
    return cues.booking_mode(update["evidence"], field) == update["value"]


def _staged_facts(draft: Draft) -> dict:
    def group(minutes):
        value = draft.groups[minutes]
        return {
            "active": draft.effective(minutes),
            "windows": [words.show_windows([window]) for window in value.windows],
            "invalid_windows": [{"window": label, "reason": issue}
                                for _start, _end, issue, label in value.invalid_windows],
            "courts": list(value.courts),
            "invalid_courts": list(value.bad_courts),
            "court_bindings": [{"window": words.show_windows([window]), "courts": list(courts)}
                               for window, courts in sorted(value.court_bindings.items())],
            "window_issue": {"type": value.issue, "evidence": value.issue_text} if value.issue else None,
            "court_issue": value.courts_issue,
            "court_scope_ambiguous": value.court_scope_ambiguous,
        }

    duration_issue = draft.duration_issue
    return {
        "booking_mode": draft.booking_mode,
        "mode_issue": draft.mode_issue,
        "date_state": draft.date_state,
        "dates": [day.isoformat() for day in draft.dates],
        "groups": {"2h": group(TWO), "1h": group(ONE)},
        "duration_issue": ({"minutes": duration_issue[0],
                            "group": "1h" if duration_issue[1] == ONE else "2h"}
                           if duration_issue else None),
    }


@dataclass(frozen=True, slots=True)
class _Turn:
    turns: list
    turn_kinds: list
    asked: list
    used: int
    today: date
    draft: Draft
    notes: list
    policy: BookingWindowPolicy
    now_utc_ms: int
    credential_id: object
    scope: object
    require_model: bool
    dialogue: dict


@dataclass
class PreparedQueueTurn:
    request: dict
    turns: list
    used: int
    asked: list
    kinds: list
    is_new_turn: bool
    notes: list
    scope: object
    policy: BookingWindowPolicy
    today: date
    reference_date: date
    prior_draft: Draft
    prior_slots: dict
    prior_state: Decision
    assistant_history: list
    legacy_migration: bool
    dialogue: dict


@dataclass
class EvaluatedQueueTurn:
    prepared: PreparedQueueTurn
    interpreted: dict | None
    context: _Turn
    draft: Draft
    slots: dict
    decision: Decision
    contextual_reply: str | None
    turn_trace: dict
    dialogue: dict


class PlanningService:
    def __init__(self, plan_service, provider_service):
        self._plans = plan_service
        self._providers = provider_service
        from backend.ai.queue_graph import QueuePlanningGraph
        self._standalone_graph = QueuePlanningGraph()

    def business_date_at(self, now_utc_ms: int) -> date:
        return BookingWindowPolicy(self._plans.active_context.timezone_name).business_date_at_utc(now_utc_ms)

    def propose(self, user_id: str, message: object, now_utc_ms: int, *, credential_id=None, answers=None,
                asked_fields=None, scope_label=None, model_id=None, require_model=False,
                reference_date: date | None = None, previous_turn_kinds=None, agent_state=None,
                assistant_history=None, legacy_snapshot=None) -> dict:
        started = time.monotonic()
        result = self._standalone_graph.invoke(self, {
            "user_id": user_id, "message": message, "now_utc_ms": now_utc_ms,
            "credential_id": credential_id, "answers": answers, "asked_fields": asked_fields,
            "scope_label": scope_label, "model_id": model_id, "require_model": require_model,
            "reference_date": reference_date, "previous_turn_kinds": previous_turn_kinds,
            "agent_state": agent_state, "assistant_history": assistant_history,
            "legacy_snapshot": legacy_snapshot,
        })
        view = result.get("conversation") or {}
        log.info("planning status=%s phase=%s asking=%s turns=%s elapsed_ms=%d", result["status"], view.get("phase"),
                 view.get("asking"), view.get("turns_used"), (time.monotonic() - started) * 1000)
        return result

    def test_parsing(self, user_id, model_id, now_utc_ms):
        """Exercise a short choice, contextual answer, queue draft, and final review without saving."""
        reference_date = self.business_date_at(now_utc_ms)
        target_date = reference_date + timedelta(days=2)
        target_text = f"{target_date.month}月{target_date.day}日"
        message = f"{target_text} 14-16"

        def public(result):
            conversation = result.get("conversation")
            if isinstance(conversation, dict):
                conversation.pop("_agent_state", None)
            return result

        question_check = {"mode_prompted": None, "initial_date_staged": None,
                          "initial_two_hour_time_staged": None, "selected_two_hour": None,
                          "retained_date": None, "retained_two_hour_time": None,
                          "short_choice": None, "mode_choices": None,
                          "answered": None, "duration_used": None, "context_used": None, "step_preserved": None,
                          "queue_ready": None, "reviewed": None, "invalid_court_blocked": None,
                          "correction_applied": None, "outside_hours_blocked": None,
                          "unsupported_duration_blocked": None, "reply": ""}

        def run(stage, input_message=None, **options):
            try:
                return self.propose(user_id, message if input_message is None else input_message,
                                    now_utc_ms, scope_label="羽毛球", model_id=model_id,
                                    require_model=True, reference_date=reference_date, **options)
            except AIModelError as exc:
                if exc.code not in _PARSING_PROVIDER_ERRORS:
                    raise
                return {"_provider_test_error": {"stage": stage, "code": exc.code}}

        def provider_failure(result):
            failure = result.get("_provider_test_error")
            if not failure:
                return None
            return {"ok": False, "outcome": "provider_failed", "failed_stage": failure["stage"],
                    "provider_error": failure["code"], "question_check": dict(question_check)}

        first = run("queue_mode_prompt")
        if failure := provider_failure(first):
            return failure
        first_conversation = first.get("conversation") or {}
        first_state = first_conversation.get("_agent_state")
        first_draft = (deserialize_draft(first_state.get("draft"))
                       if isinstance(first_state, dict) else None)
        question_check["initial_date_staged"] = bool(first_draft and target_date in first_draft.dates)
        question_check["initial_two_hour_time_staged"] = bool(first_draft and (14 * 60, 16 * 60) in first_draft.g2.windows)
        if not (question_check["initial_date_staged"] and question_check["initial_two_hour_time_staged"]):
            return {"ok": False, "outcome": "initial_facts_not_staged",
                    "question_check": question_check, **public(first)}
        first_question = (first.get("questions") or [""])[0]
        choice_text = "".join(char.upper() for char in first_question if char.isalnum())
        choice_prompted = all(option in choice_text for option in ("1", "2", "3", "A", "B", "C"))
        question_check["mode_prompted"] = bool(choice_prompted)
        if first["status"] != "needs_input" or first_conversation.get("asking") != "booking_mode" or not choice_prompted:
            question_check["short_choice"] = False
            return {"ok": False, "outcome": "short_choice_failed", "question_check": question_check, **public(first)}

        def choose_mode(answer, stage):
            return run(
                stage, answers=[answer], asked_fields=["booking_mode"],
                previous_turn_kinds=first_conversation.get("turn_kinds"),
                agent_state=first_conversation.get("_agent_state"),
                assistant_history=[assistant_history_entry(first)],
            )

        mode_result = choose_mode("1", "select_two_hour")
        if failure := provider_failure(mode_result):
            return failure
        mode_conversation = mode_result.get("conversation") or {}
        mode_slots = {slot.get("field"): slot for slot in mode_conversation.get("slots", [])
                      if isinstance(slot, dict)}
        question_check["selected_two_hour"] = "只抢2小时" in mode_slots.get("booking_mode", {}).get("display", "")
        question_check["retained_date"] = mode_slots.get("target_date", {}).get("status") == "proposed"
        question_check["retained_two_hour_time"] = mode_slots.get("windows_2h", {}).get("status") == "proposed"
        mode_selected = (mode_result["status"] == "needs_input"
                         and mode_conversation.get("asking") == "courts_2h"
                         and question_check["selected_two_hour"]
                         and question_check["retained_date"]
                         and question_check["retained_two_hour_time"])
        question_check["short_choice"] = bool(choice_prompted and mode_selected)
        if not question_check["short_choice"]:
            return {"ok": False, "outcome": "short_choice_failed", "question_check": question_check,
                    **public(mode_result)}

        one_hour = choose_mode("B", "select_one_hour")
        if failure := provider_failure(one_hour):
            return failure
        one_hour_conversation = one_hour.get("conversation") or {}
        one_hour_slots = {slot.get("field"): slot for slot in one_hour_conversation.get("slots", [])
                          if isinstance(slot, dict)}
        one_hour_selected = (one_hour["status"] == "needs_input"
                             and "只抢1小时" in one_hour_slots.get("booking_mode", {}).get("display", "")
                             and one_hour_slots.get("windows_1h", {}).get("active") is True
                             and one_hour_slots.get("windows_1h", {}).get("status") == "empty"
                             and one_hour_slots.get("windows_2h", {}).get("active") is False)
        both = choose_mode("C", "select_both_durations")
        if failure := provider_failure(both):
            return failure
        both_conversation = both.get("conversation") or {}
        both_slots = {slot.get("field"): slot for slot in both_conversation.get("slots", [])
                      if isinstance(slot, dict)}
        both_selected = (both["status"] == "needs_input"
                         and "都抢" in both_slots.get("booking_mode", {}).get("display", "")
                         and both_slots.get("windows_2h", {}).get("status") == "proposed"
                         and both_slots.get("windows_1h", {}).get("active") is True
                         and both_slots.get("windows_1h", {}).get("status") == "empty")
        question_check["mode_choices"] = bool(one_hour_selected and both_selected)
        if not question_check["mode_choices"]:
            return {"ok": False, "outcome": "mode_choice_failed", "question_check": question_check,
                    **public(both)}

        question_text = "你刚才让我选场地，是在确认1小时还是2小时？请说出已记录的日期和时段，以及还差什么。"
        question_result = run(
            "contextual_question", answers=["1", question_text],
            asked_fields=["booking_mode", mode_conversation["asking"]],
            previous_turn_kinds=mode_conversation.get("turn_kinds"),
            agent_state=mode_conversation.get("_agent_state"),
            assistant_history=[assistant_history_entry(first), assistant_history_entry(mode_result)],
        )
        if failure := provider_failure(question_result):
            return failure
        question_conversation = question_result.get("conversation") or {}
        reply = question_conversation.get("contextual_reply")
        reply = reply if isinstance(reply, str) else ""
        question_slots = {slot.get("field"): slot for slot in question_conversation.get("slots", [])
                          if isinstance(slot, dict)}
        date_display = str(mode_slots["target_date"].get("display") or "").split(" ", 1)[0]
        time_display = str(mode_slots["windows_2h"].get("display") or "").split("、", 1)[0]
        def parsed_windows(value):
            return {(window.start, window.end) for window in scan_windows(value).mentions
                    if window.kind == "range" and window.start is not None and window.end is not None}

        context_used = bool(date_display and time_display
                            and date_display in "".join(reply.split())
                            and bool(parsed_windows(time_display) & parsed_windows(reply)))
        question_check["duration_used"] = "2小时" in reply
        context_used = context_used and question_check["duration_used"]
        answered = bool(reply.strip()) and question_conversation.get("turn_kinds", [None])[-1] == "question"
        step_preserved = (question_result["status"] == "needs_input"
                          and question_conversation.get("asking") == mode_conversation.get("asking")
                          and question_slots.get("courts_2h", {}).get("status") == "empty")
        question_check.update({"answered": answered, "context_used": context_used,
                               "step_preserved": step_preserved, "reply": reply})
        if not (answered and context_used and step_preserved):
            return {"ok": False, "outcome": "context_failed", "question_check": question_check,
                    **public(question_result)}

        result = run(
            "final_queue_preview", answers=["1", question_text, "1号场"],
            asked_fields=["booking_mode", mode_conversation["asking"], question_conversation["asking"]],
            previous_turn_kinds=question_conversation.get("turn_kinds"),
            agent_state=question_conversation.get("_agent_state"),
            assistant_history=[assistant_history_entry(first), assistant_history_entry(mode_result),
                               assistant_history_entry(question_result)],
        )
        if failure := provider_failure(result):
            return failure
        proposal = result.get("proposal") or {}
        entries = proposal.get("entries") or []
        question_check["queue_ready"] = (result["status"] == "ready" and len(entries) == 1
            and entries[0].get("duration_minutes") == TWO
            and entries[0].get("start_time") == "14:00" and entries[0].get("end_time") == "16:00"
            and entries[0].get("court_preference") == "1号场")
        question_check["reviewed"] = (proposal.get("review") or {}).get("state") == "reviewed"

        correction_text = "把2小时的14-16时段改为18-20，场地换成4号场。"
        previous_conversation = result.get("conversation") or {}
        corrected = run(
            "correction_replace", answers=["1", question_text, "1号场", correction_text],
            asked_fields=["booking_mode", mode_conversation["asking"],
                          question_conversation["asking"], None],
            previous_turn_kinds=previous_conversation.get("turn_kinds"),
            agent_state=previous_conversation.get("_agent_state"),
            assistant_history=[assistant_history_entry(first), assistant_history_entry(mode_result),
                               assistant_history_entry(question_result), assistant_history_entry(result)],
        )
        if failure := provider_failure(corrected):
            return failure
        corrected_proposal = corrected.get("proposal") or {}
        corrected_entries = corrected_proposal.get("entries") or []
        question_check["correction_applied"] = (corrected.get("status") == "ready" and len(corrected_entries) == 1
            and corrected_entries[0].get("duration_minutes") == TWO
            and corrected_entries[0].get("start_time") == "18:00" and corrected_entries[0].get("end_time") == "20:00"
            and corrected_entries[0].get("court_preference") == "4号场"
            and (corrected_proposal.get("review") or {}).get("state") == "reviewed")
        if not question_check["correction_applied"]:
            return {"ok": False, "outcome": "correction_failed", "question_check": question_check,
                    **public(corrected)}
        result = corrected
        question_check["reviewed"] = (corrected_proposal.get("review") or {}).get("state") == "reviewed"

        court_case = run("court_11_boundary", input_message=f"{target_text} 14-16 11号场，只抢2小时")
        if failure := provider_failure(court_case):
            return failure
        court_conversation = court_case.get("conversation") or {}
        court_slots = {slot.get("field"): slot for slot in court_conversation.get("slots", [])
                       if isinstance(slot, dict)}
        question_check["invalid_court_blocked"] = (
            court_case.get("status") == "needs_input" and court_conversation.get("asking") == "courts_2h"
            and court_slots.get("courts_2h", {}).get("status") == "invalid"
            and any("11号场" in item for item in court_case.get("questions", [])))

        hours_case = run("outside_hours_boundary", input_message=f"{target_text} 22-24 1号场，只抢2小时")
        if failure := provider_failure(hours_case):
            return failure
        hours_conversation = hours_case.get("conversation") or {}
        hours_slots = {slot.get("field"): slot for slot in hours_conversation.get("slots", [])
                       if isinstance(slot, dict)}
        question_check["outside_hours_blocked"] = (
            hours_case.get("status") == "needs_input" and hours_conversation.get("asking") == "windows_2h"
            and hours_slots.get("windows_2h", {}).get("status") == "invalid"
            and hours_case.get("proposal") is None)

        duration_case = run("unsupported_duration_boundary",
                            input_message=f"{target_text} 14-17打3小时，1号场，只抢2小时")
        if failure := provider_failure(duration_case):
            return failure
        duration_conversation = duration_case.get("conversation") or {}
        duration_slots = {slot.get("field"): slot for slot in duration_conversation.get("slots", [])
                          if isinstance(slot, dict)}
        question_check["unsupported_duration_blocked"] = (
            duration_case.get("status") == "needs_input" and duration_conversation.get("asking") == "windows_2h"
            and duration_slots.get("windows_2h", {}).get("status") in {"ambiguous", "invalid"}
            and duration_case.get("proposal") is None)

        boundary_ok = all(question_check[field] for field in (
            "invalid_court_blocked", "outside_hours_blocked", "unsupported_duration_blocked"))
        ok = (question_check["initial_date_staged"] and question_check["initial_two_hour_time_staged"]
              and question_check["queue_ready"] and question_check["correction_applied"]
              and question_check["reviewed"] and boundary_ok)
        outcome = "parsed" if ok else "boundary_failed" if not boundary_ok else "context_failed"
        return {"ok": ok, "outcome": outcome,
                "question_check": question_check, **public(result)}

    def prepare_turn(self, request: dict) -> PreparedQueueTurn:
        user_id, message = request.get("user_id"), request.get("message")
        now_utc_ms = request.get("now_utc_ms")
        credential_id, answers = request.get("credential_id"), request.get("answers")
        asked_fields, scope_label = request.get("asked_fields"), request.get("scope_label")
        reference_date = request.get("reference_date")
        previous_turn_kinds, agent_state = request.get("previous_turn_kinds"), request.get("agent_state")
        assistant_history = request.get("assistant_history")
        legacy_snapshot = request.get("legacy_snapshot")
        turns = self._turns(message, answers)
        used = len(turns) - 1
        legacy_fields_allowed = (type(assistant_history) is list and bool(assistant_history)) or (
            isinstance(agent_state, dict) and agent_state.get("version") == 2
        )
        asked = self._asked(asked_fields, used, allow_legacy=legacy_fields_allowed)
        kinds = self._turn_kinds(previous_turn_kinds, len(turns))
        is_new_turn = previous_turn_kinds is None or len(previous_turn_kinds) == len(turns) - 1
        if assistant_history is None:
            assistant_history = []
        if (type(assistant_history) is not list or len(assistant_history) > conv.MAX_ANSWERS + 1
                or any(type(item) is not dict for item in assistant_history)):
            raise PlanError("invalid_planning_request", 400)
        try:
            history_text = json.dumps([assistant_history, agent_state], ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            raise PlanError("invalid_planning_request", 400) from None
        if _SECRET.search("\n".join(turns) + "\n" + history_text):
            raise PlanError("sensitive_planning_input", 400)
        scope = self._scope(scope_label)
        context = self._plans.active_context
        policy = BookingWindowPolicy(context.timezone_name)
        today = policy.business_date_at_utc(now_utc_ms)
        reference_date = reference_date or today
        if type(reference_date) is not date:
            raise PlanError("invalid_planning_request", 400)
        notes = []
        prior_kinds = kinds[:-1] if is_new_turn else kinds
        prior_turns = turns[:-1] if is_new_turn else turns
        prior_asked = asked[:-1] if is_new_turn and asked else ([] if is_new_turn else asked)
        legacy_migration = bool(prior_turns) and (
            (agent_state is None and bool(assistant_history))
            or (isinstance(agent_state, dict) and agent_state.get("version") == 2)
        )
        prior_draft = self._restore_draft(
            agent_state, prior_turns, prior_asked, today, reference_date, prior_kinds[:len(prior_turns)],
            legacy_snapshot,
        )
        if legacy_migration:
            # Old queues used different optional-field names and counted retries differently.
            # Start fresh attempt counters once, after restoring their validated facts.
            prior_draft.asked = []
        dialogue = load_dialogue(agent_state.get("dialogue") if isinstance(agent_state, dict) and agent_state.get("version") == 5 else None)
        if dialogue is None:
            raise PlanError("invalid_planning_response", 502)
        prior_slots = build_slots(prior_draft, today, dialogue["unresolved"])
        prior_state = conv.decide(prior_slots, prior_draft.asked, max(0, len(prior_turns) - 1),
                                 preferred_field=dialogue["dialogue_focus"], pending_edit=dialogue["pending_edit"])
        return PreparedQueueTurn(
            request=request, turns=turns, used=used, asked=asked, kinds=kinds, is_new_turn=is_new_turn,
            notes=notes, scope=scope, policy=policy, today=today,
            reference_date=reference_date, prior_draft=prior_draft,
            prior_slots=prior_slots, prior_state=prior_state, assistant_history=assistant_history,
            legacy_migration=legacy_migration, dialogue=dialogue,
        )

    def interpret_turn(self, prepared: PreparedQueueTurn) -> dict | None:
        if not prepared.is_new_turn:
            return None
        request = prepared.request
        interpreted, _provider = self._interpret_turn(
            request.get("user_id"), request.get("model_id"), prepared.turns[-1], prepared.turns,
            prepared.prior_slots, prepared.prior_state, prepared.prior_draft, prepared.today,
            prepared.reference_date,
            prepared.assistant_history, prepared.dialogue,
        )
        return interpreted

    def apply_interpretation(self, prepared: PreparedQueueTurn, interpreted: dict | None) -> EvaluatedQueueTurn:
        draft = deepcopy(prepared.prior_draft)
        dialogue = deepcopy(prepared.dialogue)
        kinds = list(prepared.kinds)
        rejected_mode_update = None
        events, changed, resume_focus = [], [], None
        if prepared.is_new_turn:
            if interpreted is None:
                raise PlanError("invalid_model_proposal", 502)
            interpreted = ground_decision(interpreted, prepared.turns[-1], draft, dialogue,
                                           prepared.prior_state.asking, prepared.assistant_history, prepared.today)
            kinds[-1] = interpreted["kind"]
            rejected_modes = [item for item in interpreted["updates"] if item["field"] == "booking_mode"
                              and item["operation"] != "clear" and item["value"] != draft.booking_mode
                              and not _mode_update_is_explicit(item, prepared.turns[-1], prepared.prior_state.asking)]
            if rejected_modes:
                rejected_mode_update = rejected_modes[0]
                interpreted = {**interpreted, "updates": [item for item in interpreted["updates"] if item not in rejected_modes]}
            draft, dialogue, events = begin_control(draft, dialogue, interpreted, prepared.prior_state.asking)
            before_updates = deepcopy(draft)
            rejected_fields = {item["field"] for item in interpreted.get("semantic_errors", []) if item["field"]}
            application = {**interpreted, "unresolved": [item for item in interpreted["unresolved"]
                                                       if item["field"] not in rejected_fields]}
            draft = apply_updates(draft, application)
            dialogue, resume_focus, changed = finish_updates(before_updates, draft, dialogue, interpreted, prepared.today)
        flow_asked = list(prepared.prior_draft.asked)
        slots = build_slots(draft, prepared.today, dialogue["unresolved"])
        if prepared.is_new_turn and interpreted:
            focus = prepared.prior_state.asking
            touched = {item["field"] for item in interpreted["updates"] + interpreted["unresolved"]}
            changed = [field for field in conv.PRIORITY if field_value(prepared.prior_draft, field) != field_value(draft, field)]
            for field in changed:
                if slots[field].status in {conv.SlotStatus.PROPOSED, conv.SlotStatus.VERIFIED}:
                    flow_asked = [asked for asked in flow_asked if asked != field]
            if (focus and interpreted["kind"] != "question" and not events
                    and (focus in touched or not touched)
                    and (slots[focus].blocking or focus not in changed)):
                flow_asked.append(focus)
        draft.asked = flow_asked
        if "editing_cancelled" in events and prepared.dialogue["pending_edit"]:
            resume_focus = prepared.dialogue["pending_edit"]["resume_focus"]
        selected_field = (resume_focus if resume_focus in eligible_fields(slots) else
                          (interpreted or {}).get("next_field") or dialogue["dialogue_focus"])
        execution_request = bool(interpreted and interpreted.get("intent") == "execution_request")
        decision = conv.decide(slots, flow_asked, prepared.used, has_command=execution_request,
                               preferred_field=selected_field, pending_edit=dialogue["pending_edit"])
        dialogue["dialogue_focus"] = ((interpreted or {}).get("dialogue_focus") or decision.asking)
        dialogue["next_action"] = ("refuse" if decision.phase is Phase.UNSUPPORTED else
                                   "escalate" if decision.phase is Phase.ESCALATED else
                                   "clarify_edit" if dialogue["pending_edit"] and not dialogue["pending_edit"]["fields"] else
                                   "edit" if dialogue["pending_edit"] else
                                   "answer" if interpreted and interpreted["kind"] == "question" and interpreted.get("next_action") == "answer" else
                                   "preview" if decision.phase is Phase.READY else "ask")
        request = prepared.request
        notes = list(prepared.notes)
        excluded_note = None
        if interpreted and interpreted["kind"] != "question":
            updated_fields = {item["field"] for item in interpreted["updates"]}
            if draft.booking_mode == "two_hour_only" and updated_fields & {"windows_1h", "courts_1h"}:
                excluded_note = "本次只抢2小时；消息中提到的1小时时段不会进入候选。"
            elif draft.booking_mode == "one_hour_only" and updated_fields & {"windows_2h", "courts_2h"}:
                excluded_note = "本次只抢1小时；消息中提到的2小时时段不会进入候选。"
            if excluded_note:
                notes.append(excluded_note)
        ctx = _Turn(prepared.turns, kinds, flow_asked, prepared.used, prepared.today, draft,
                    notes, prepared.policy, request.get("now_utc_ms"), request.get("credential_id"),
                    prepared.scope, request.get("require_model", False), dialogue)
        contextual_reply = interpreted.get("reply") if interpreted else None
        if "nothing_to_undo" in events:
            contextual_reply = "当前没有可以撤销的相关修改。"
        elif "no_pending_edit" in events:
            contextual_reply = "当前没有进行中的局部修改，已记录的信息保持不变。"
        turn_trace = self._turn_trace(prepared.prior_slots, slots, decision, interpreted, draft)
        turn_trace["dialogue_events"] = events
        turn_trace["semantic_errors"] = (interpreted or {}).get("semantic_errors", [])
        if events:
            turn_trace["summary"] = {"editing_started": "正在修改指定信息。", "editing_cancelled": "已取消局部修改，恢复编辑前的信息。",
                                      "no_pending_edit": "当前没有进行中的局部修改。", "change_undone": "已撤销最近的相关修改。",
                                      "nothing_to_undo": "没有可以撤销的相关修改。"}.get(events[-1], "") + turn_trace["summary"]
        if rejected_mode_update is not None:
            turn_trace["rejected_updates"] = [{"field": "booking_mode", "reason": "explicit_choice_required",
                                               "evidence": rejected_mode_update["evidence"]}]
            if interpreted["updates"]:
                turn_trace["summary"] = "已暂存其他预约信息。" + turn_trace["summary"]
            turn_trace["summary"] += "队列类型需要你明确选择，不能根据时段长度推断。"
            contextual_reply = None
        if excluded_note:
            turn_trace["summary"] += excluded_note
        if interpreted and interpreted["kind"] != "question":
            accepted, dormant_slots = set(), {}
            for item in interpreted["updates"]:
                field = item["field"]
                slot = slots[field]
                if not slot.active and field.endswith(("_1h", "_2h")):
                    tag = field[-2:]
                    if tag not in dormant_slots:
                        inspection = deepcopy(draft)
                        inspection.booking_mode = "one_hour_only" if tag == "1h" else "two_hour_only"
                        dormant_slots[tag] = build_slots(inspection, prepared.today)
                    slot = dormant_slots[tag][field]
                if (field not in dialogue["unresolved"] and (slot.status in {conv.SlotStatus.PROPOSED, conv.SlotStatus.VERIFIED}
                        or item["operation"] in {"clear", "remove"} and slot.status is conv.SlotStatus.EMPTY)):
                    accepted.add(field)
            proposed = {item["field"] for item in interpreted["updates"]}
            failed_update = bool(proposed - accepted) if proposed else bool(_POSITIVE_ACK.search(contextual_reply or ""))
            if failed_update:
                contextual_reply = None
        return EvaluatedQueueTurn(prepared, interpreted, ctx, draft, slots, decision,
                                  contextual_reply, turn_trace, dialogue)

    @staticmethod
    def _restore_draft(agent_state, turns, asked, today, reference_date, turn_kinds, legacy_snapshot=None):
        if isinstance(agent_state, dict):
            version = agent_state.get("version")
            if version in {3, 4, 5}:
                restored = deserialize_draft(agent_state.get("draft"))
                if restored is None:
                    raise PlanError("invalid_planning_response", 502)
                return restored
            if version == 2:
                legacy = agent_state.get("normalized_turns")
                if (type(legacy) is list and len(legacy) == len(turns)
                        and all(type(item) is str for item in legacy)):
                    return reconcile_legacy_slots(
                        fold(legacy, asked, today, reference_date=reference_date, turn_kinds=turn_kinds),
                        legacy_snapshot,
                    )
                raise PlanError("invalid_planning_response", 502)
            raise PlanError("invalid_planning_response", 502)
        return reconcile_legacy_slots(
            fold(turns, asked, today, reference_date=reference_date, turn_kinds=turn_kinds), legacy_snapshot,
        )

    @staticmethod
    def _with_agent_state(result, draft, dialogue):
        conversation = result.get("conversation")
        if isinstance(conversation, dict):
            conversation["_agent_state"] = {"version": 5, "draft": serialize_draft(draft), "dialogue": deepcopy(dialogue)}
        return result

    def _interpret_turn(self, user_id, model_id, latest, turns, slots, state, draft, today,
                        reference_date, assistant_history, dialogue):
        counts = entry_count(draft)
        blockers = [slot.field for slot in conv.blocking_slots(slots)]
        eligible = eligible_fields(slots)
        pending_question = next((item for record in reversed(assistant_history)
                                 for item in record.get("questions", []) if isinstance(item, str) and item.strip()), "")
        payload = {
            "conversation_start_date": reference_date.isoformat(),
            "current_business_date": today.isoformat(),
            "timezone": self._plans.active_context.timezone_name,
            "latest_user_message": latest,
            "current_step": {"field": state.asking, "label": HEADING.get(state.asking, "队列核对完成"),
                             "phase": state.phase.value, "reason": state.reason.value if state.reason else None,
                             "attempt_count": Counter(draft.asked)[state.asking] if state.asking else 0,
                             "pending_question": pending_question},
            "blocking_fields": blockers,
            "eligible_fields": eligible,
            "allowed_next_fields": list(conv.PRIORITY),
            "current_slots": [{"field": name, "status": slot.status.value, "value": slot.value,
                               "display": slot.display, "detail": slot.detail, "active": slot.active}
                              for name, slot in slots.items()],
            "staged_facts": _staged_facts(draft),
            "workflow_context": WORKFLOW_CONTEXT,
            "dialogue_state": public_dialogue(dialogue),
            "candidate_counts": {"by_duration": counts, "total": sum(counts.values())},
        }
        messages = _queue_context_messages(payload, turns, assistant_history)
        validation_reason = None
        for attempt in (1, 2):
            request_messages = messages if attempt == 1 else [
                *messages,
                {"role": "system", "content": (
                    "校验错误 question_with_fact_updates：kind 描述用户最新一轮的意图，不是你下一句要提问的性质。"
                    "用户提供事实或修改而没有提问时应为 answer；既问又补充时为 mixed。请结合原文修正标签，不能删除明确事实来迎合标签。"
                    if validation_reason == "question_with_fact_updates" else
                    "上一次输出没有通过 JSON 和证据校验。请重新输出指定字段的 JSON，并且只从 latest_user_message 逐字引用 evidence。")},
            ]
            content, provider = (self._providers.chat(user_id, request_messages, model_id=model_id)
                                 if model_id is not None else self._providers.chat(user_id, request_messages))
            validation_errors = []
            interpreted = parse_turn_decision(content, latest, errors=validation_errors)
            validation_reason = validation_errors[0] if validation_errors else None
            if interpreted is not None:
                interpreted["provider"] = {"name": provider["name"], "model": provider["model"]}
                interpreted["attempt"] = attempt
                return interpreted, provider
            log.warning("queue turn interpretation rejected attempt=%d", attempt)
        raise PlanError("invalid_model_proposal", 502)

    @staticmethod
    def _turn_trace(before, after, state, interpreted, draft):
        updates = []
        for field in conv.PRIORITY:
            old, new = before[field], after[field]
            if (old.status, old.value, old.display, old.detail, old.active) != (
                    new.status, new.value, new.display, new.detail, new.active):
                meaningful = bool(new.display or new.detail or new.value is not None)
                overlap_confirmed = field.startswith("overlap_") and new.status is conv.SlotStatus.VERIFIED
                cleared = new.status is conv.SlotStatus.EMPTY and any(item["field"] == field and item["operation"] in {"clear", "remove"}
                                                                            for item in (interpreted or {}).get("updates", []))
                if new.active and (meaningful or overlap_confirmed or cleared):
                    source = next((item["evidence"] for item in (interpreted or {}).get("updates", [])
                                   if item["field"] == field), None)
                    updates.append({"field": field, "label": HEADING.get(field, field),
                                    "display": new.display or new.detail or ("已清空" if cleared else "已确认"),
                                    "status": new.status.value, "evidence": source})
        counts = entry_count(draft)
        total = sum(counts.values())
        if updates:
            summary = "已识别：" + "；".join(f"{item['label']} {item['display'].rstrip('。.!！')}" for item in updates) + "。"
        elif interpreted and interpreted["kind"] in {"question", "mixed"}:
            summary = "已回答问题，保留当前预约进度。"
        else:
            summary = "本轮没有新增可确认的预约信息。"
        if state.asking:
            summary += f"下一步确认：{HEADING[state.asking]}。"
        elif state.phase is Phase.READY:
            summary += "必需信息已齐全，等待队列复核。"
        if total:
            summary += f"当前候选 {total} 项。"
        suggested = interpreted.get("next_field") if interpreted else None
        if suggested and suggested != state.asking and state.asking:
            summary += f"模型建议先确认{HEADING.get(suggested, suggested)}；流程门槛要求先确认{HEADING.get(state.asking, state.asking)}。"
        normalizations = (interpreted or {}).get("normalization_notes", [])
        if normalizations:
            summary += "已按用户原话校准字段值。"
        return {"intent": interpreted.get("intent", "queue") if interpreted else "queue",
                "kind": interpreted["kind"] if interpreted else "answer",
                "updated_fields": updates, "next_field": state.asking,
                "model_next_field": suggested, "eligible_fields": list(state.eligible_fields),
                "model_choice_accepted": state.model_choice_accepted,
                "normalization_notes": normalizations,
                "operations": (interpreted or {}).get("updates", []),
                "candidate_count": total, "summary": summary}

    def render_clarification(self, evaluated: EvaluatedQueueTurn) -> dict:
        ctx, state, slots = evaluated.context, evaluated.decision, evaluated.slots
        view = self._view(ctx, state, slots, turn_trace=evaluated.turn_trace)
        if evaluated.contextual_reply:
            view["contextual_reply"] = evaluated.contextual_reply
        pending = evaluated.dialogue["pending_edit"]
        if state.asking:
            next_question = question(slots, state.asking, evaluated.draft, ctx.today)
            if pending and slots[state.asking].status in {conv.SlotStatus.PROPOSED, conv.SlotStatus.VERIFIED}:
                next_question = f"{HEADING[state.asking]}目前是{slots[state.asking].display or '已确认'}，你想改成什么？"
        else:
            next_question = (pending or {}).get("question") or "你想修改哪一项？例如日期或2小时场地。"
        interpreted = evaluated.interpreted or {}
        if (state.asking is not None and state.asking != "booking_mode" and interpreted.get("next_field") == state.asking
                and interpreted.get("next_question")
                and (slots[state.asking].status is conv.SlotStatus.EMPTY or pending and not slots[state.asking].blocking)):
            detail = slots[state.asking].detail
            candidate = interpreted["next_question"]
            next_question = f"{detail}\n{candidate}" if detail and detail not in candidate else candidate
        questions = [] if evaluated.dialogue["next_action"] == "answer" else [next_question]
        result = self._reply("needs_input", questions, None, view)
        return self._with_agent_state(result, evaluated.draft, evaluated.dialogue)

    def render_preview(self, evaluated: EvaluatedQueueTurn) -> dict:
        request = evaluated.prepared.request
        result = self._ready(evaluated.context, evaluated.decision, evaluated.slots,
                             request.get("user_id"), request.get("model_id"), evaluated.dialogue.get("review_cache"))
        if evaluated.contextual_reply:
            result["conversation"]["contextual_reply"] = evaluated.contextual_reply
        result["conversation"]["turn_trace"] = evaluated.turn_trace
        proposal = result["proposal"]
        evaluated.dialogue["review_cache"] = {"fingerprint": self._review_fingerprint(proposal["target_date"], proposal["entries"]),
                                             "warnings": proposal["warnings"], "review": proposal["review"], "provider": proposal["provider"]} if proposal["review"]["state"] == "reviewed" else None
        return self._with_agent_state(result, evaluated.draft, evaluated.dialogue)

    def render_escalation(self, evaluated: EvaluatedQueueTurn) -> dict:
        result = self._escalated(evaluated.context, evaluated.decision, evaluated.slots)
        if evaluated.contextual_reply:
            result["conversation"]["contextual_reply"] = evaluated.contextual_reply
        result["conversation"]["turn_trace"] = evaluated.turn_trace
        return self._with_agent_state(result, evaluated.draft, evaluated.dialogue)

    def render_unsupported(self, evaluated: EvaluatedQueueTurn) -> dict:
        view = self._view(evaluated.context, evaluated.decision, evaluated.slots,
                          turn_trace=evaluated.turn_trace)
        result = self._reply("unsupported", [UNSUPPORTED_TEXT], None, view)
        return self._with_agent_state(result, evaluated.draft, evaluated.dialogue)

    @staticmethod
    def _turn_kinds(previous, turn_count: int) -> list[str]:
        previous = [] if previous is None else previous
        if (type(previous) is not list or len(previous) not in (turn_count - 1, turn_count)
                or any(kind not in {"answer", "question", "mixed"} for kind in previous)):
            raise PlanError("invalid_planning_request", 400)
        return list(previous) if len(previous) == turn_count else [*previous, "answer"]

    @staticmethod
    def _review_fingerprint(target, entries):
        return hashlib.sha256(json.dumps([REVIEW_VERSION, target, entries], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def _ready(self, ctx, state, slots, user_id, model_id, cache=None) -> dict:
        if not ctx.scope:
            raise PlanError('planning_scope_required', 409)
        draft = ctx.draft
        entries = build_entries(draft, ctx.scope)
        target = date.fromisoformat(slots["target_date"].value)
        try:
            parse_queue({"target_date": target.isoformat(), "entries": entries}, self._plans.active_context, ctx.today)
        except IntentValidationError as exc:
            raise PlanError("invalid_plan", 400, exc.fields) from exc
        existing = self._existing(user_id, target.isoformat(), ctx.credential_id)
        if isinstance(cache, dict) and cache.get("fingerprint") == self._review_fingerprint(target.isoformat(), entries):
            warnings, review, provider = deepcopy(cache["warnings"]), deepcopy(cache["review"]), deepcopy(cache["provider"])
        else:
            warnings, review, provider = self._review(ctx, user_id, model_id, target, entries)
        proposal = {
            "kind": "manual_queue_draft", "target_date": target.isoformat(), "target_label": words.show_date(target),
            "entries": entries, "windows": window_summary(draft), "entry_count": len(entries),
            "base_version": existing["version"], "existing_count": existing["count"], "replaces_existing": existing["count"] > 0,
            "schedule": self._schedule(ctx, target), "execution_note": words.EXECUTION_NOTE,
            "warnings": warnings, "review": review, "scope_label": ctx.scope, "provider": provider,
            "agent": {"review_version": REVIEW_VERSION},
            "can_book": False, "can_pay": False, "can_create_job": False, "can_query_upstream": False,
        }
        notes = ctx.notes + ([review["note"]] if review.get("note") else [])
        view = self._view(ctx, state, slots, notes=notes)
        return self._reply("ready", [], proposal, view)

    def _existing(self, user_id, target_date, credential_id) -> dict:
        if credential_id is None:
            return {"version": 0, "count": 0}
        queue = self._plans.get_manual_queue(user_id, target_date, credential_id)
        if not queue:
            return {"version": 0, "count": 0}
        return {"version": queue["version"], "count": 0 if queue.get("deleted") else len(queue.get("candidates") or [])}

    def _schedule(self, ctx, target: date) -> dict:
        schedule = automatic_queue_schedule(target, ctx.now_utc_ms, ctx.policy.timezone_name)
        if schedule["state"] == "not_automatic":
            text = "目标日前两天的07:30已经过去，仍可保存候选，但不会安排自动执行。"
        elif schedule["state"] == "passed":
            text = "今天07:30的开票时间已经过了，仍可保存候选，但不会安排自动执行。"
        else:
            opening = date.fromisoformat(schedule["opening_date"])
            when = "今天" if opening == ctx.today else f"{opening.month}月{opening.day}日 {WEEKDAY_NAMES[opening.weekday()]}"
            text = f"{when} 07:30 开票时自动执行；开票前会按真实场地表核对，用不上的候选会被去掉。"
        return {**schedule, "text": text}

    def _review(self, ctx, user_id, model_id, target: date, entries: list) -> tuple[list, dict, object]:
        lines = [f"{words.HOURS[e['duration_minutes']]} {e['start_time']}-{e['end_time']} {e['court_preference']}" for e in entries]
        payload = build_payload(ctx.turns, ctx.today.isoformat(), target.isoformat(), lines)
        reason = None
        for attempt in (1, 2):
            body = payload if reason is None else {**payload, "format_error": "上一条回复不是要求的 JSON，请只输出 {\"warnings\": [...]}。"}
            messages = [{"role": "system", "content": REVIEW_PROMPT},
                        {"role": "user", "content": json.dumps(body, ensure_ascii=False, allow_nan=False)}]
            try:
                content, provider = (self._providers.chat(user_id, messages, model_id=model_id) if model_id is not None
                                     else self._providers.chat(user_id, messages))
            except AIModelError as exc:
                if ctx.require_model:
                    raise
                note = "队列没有经过模型复核（尚未配置模型）。" if exc.code == "provider_not_configured" else "队列没有经过模型复核（模型暂时不可用）。"
                return [], {"state": "skipped", "note": note, "attempts": attempt - 1}, None
            warnings = parse_warnings(content, _SECRET)
            if warnings is not None:
                return warnings, {"state": "reviewed", "attempts": attempt}, {"name": provider["name"], "model": provider["model"]}
            log.warning("queue review rejected attempt=%d", attempt)
            reason = "bad_reply"
        if ctx.require_model:
            raise PlanError("invalid_model_proposal", 502)
        return [], {"state": "skipped", "note": "队列没有经过模型复核（模型回复不符合格式）。", "attempts": 2}, None

    @staticmethod
    def _view(ctx, state: Decision, slots, *, notes=None, turn_trace=None) -> dict:
        heading = HEADING.get(state.asking or "")
        return {"phase": state.phase.value, "asking": state.asking, "heading": heading,
                "business_date": ctx.today.isoformat(),
                "reason": state.reason.value if state.reason else None, "turns_used": ctx.used, "turns_max": conv.MAX_ANSWERS,
                "attempts": dict(Counter(f for f in ctx.asked if f)), "turn_kinds": ctx.turn_kinds,
                "slots": [slots[f].public() for f in conv.PRIORITY],
                "strip": strip(ctx.draft, slots, state.asking), "escalation": None,
                "notices": ctx.notes if notes is None else notes, "turn_trace": turn_trace,
                **{key: value for key, value in public_dialogue(ctx.dialogue).items()
                   if key in {"pending_edit", "dialogue_focus", "next_action"}}}

    @staticmethod
    def _reply(status, questions, proposal, view) -> dict:
        return {"status": status, "questions": questions, "proposal": proposal, "conversation": view}

    def _escalated(self, ctx, state: Decision, slots) -> dict:
        stalled = state.escalation == "stalled"
        message = ("这一项我连续几次都没能确认。可以改用“选择预约”页手动选场，已确认的日期会带过去。" if stalled
                   else "这次整理的轮数已经用完。可以改用“选择预约”页手动选场，已确认的日期会带过去。")
        day = slots["target_date"]
        prefill = {"target_date": day.value} if day.value and day.status is conv.SlotStatus.PROPOSED else {}
        view = self._view(ctx, state, slots)
        view["escalation"] = {"kind": state.escalation, "field": state.asking, "message": message, "prefill": prefill}
        return self._reply("needs_input", [message], None, view)

    @staticmethod
    def _asked(asked_fields, used, *, allow_legacy=False) -> list:
        if asked_fields is None:
            return [None] * used
        legacy_fields = {"more_2h", "more_1h", "want_1h"} if allow_legacy else set()
        if (type(asked_fields) is not list or len(asked_fields) != used
                or any(f is not None and f not in conv.PRIORITY and f not in legacy_fields for f in asked_fields)):
            raise PlanError("invalid_planning_request", 400)
        return list(asked_fields)

    @staticmethod
    def _scope(scope_label):
        if scope_label is None:
            return None
        if (type(scope_label) is not str or not 1 <= len(scope_label) <= 100 or scope_label != scope_label.strip()
                or any(unicodedata.category(c) in {"Cc", "Cs"} for c in scope_label)):
            raise PlanError("invalid_planning_request", 400)
        if scope_label != "羽毛球":
            raise PlanError("unsupported_planning_scope", 400)
        return scope_label

    @staticmethod
    def _turns(message, answers):
        if answers is None:
            answers = []
        if type(answers) is not list or len(answers) > conv.MAX_ANSWERS:
            raise PlanError("invalid_planning_request", 400)
        turns = [message, *answers]
        if any(type(v) is not str or not v.strip() or len(v) > 4000
               or any(unicodedata.category(c) == "Cs" for c in v) for v in turns):
            raise PlanError("invalid_planning_request", 400)
        if sum(len(v) for v in turns) > 4000 or sum(len(v.encode("utf-8")) for v in turns) > 12000:
            raise PlanError("planning_context_limit", 400)
        return [v.strip() for v in turns]
