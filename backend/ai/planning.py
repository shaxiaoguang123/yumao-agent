"""Booking-queue drafting. Questions and the queue are server-built; the model only reviews.

This service has no plan-writing or booking tools: it returns a proposal and the user
confirms it through the normal manual-queue save.
"""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from backend.ai import conversation as conv
from backend.ai import queue_text as words
from backend.ai.conversation import Decision, Phase, Reason
from backend.ai.nlu.cues import classify_execution
from backend.ai.nlu.dates import WEEKDAY_NAMES
from backend.ai.queue_priority import SYSTEM_PROMPT as PRIORITY_PROMPT, parse_field as parse_priority_field
from backend.ai.queue_draft import Draft, fold
from backend.ai.queue_slots import build_entries, build_slots, question, strip, window_summary
from backend.ai.review import REVIEW_VERSION, SYSTEM_PROMPT as REVIEW_PROMPT, build_payload, parse_warnings
from backend.ai.service import AIModelError
from backend.booking_window import BookingWindowPolicy
from backend.plans.manual_queue import parse_queue
from backend.plans.service import PlanError
from backend.plans.validation import IntentValidationError

log = logging.getLogger("yumao.planning")
_SECRET = re.compile(r"(?:\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}|\bsk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{16,}|(?:token|api[_ ]?key)\s*[:=]\s*\S{16,})", re.I)
UNSUPPORTED_TEXT = "当前只能整理并保存预约队列，不能执行预约、付款或创建执行任务。"
# The daily worker books the date two days ahead at 07:30 (backend/execution/scheduler.py).
AUTO_DAYS_AHEAD, OPEN_HOUR, OPEN_MINUTE = 2, 7, 30
HEADING = {"target_date": "日期", "windows_2h": "2小时时段", "more_2h": "候选时间", "overlap_2h": "时间重叠",
           "courts_2h": "场地", "want_1h": "1小时备选", "windows_1h": "1小时时段", "more_1h": "1小时候选",
           "overlap_1h": "时间重叠", "courts_1h": "1小时场地"}
SAMPLE_REQUEST = "后天，14-16和18-20，1号4号场，不要一小时，不用候选"


@dataclass(frozen=True, slots=True)
class _Turn:
    turns: list
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


class PlanningService:
    def __init__(self, plan_service, provider_service):
        self._plans = plan_service
        self._providers = provider_service

    def business_date_at(self, now_utc_ms: int) -> date:
        return BookingWindowPolicy(self._plans.active_context.timezone_name).business_date_at_utc(now_utc_ms)

    def propose(self, user_id: str, message: object, now_utc_ms: int, *, credential_id=None, answers=None,
                asked_fields=None, scope_label=None, model_id=None, require_model=False,
                reference_date: date | None = None) -> dict:
        started = time.monotonic()
        result = self._propose(user_id, message, now_utc_ms, credential_id, answers, asked_fields, scope_label,
                               model_id, require_model, reference_date)
        view = result.get("conversation") or {}
        log.info("planning status=%s phase=%s asking=%s turns=%s elapsed_ms=%d", result["status"], view.get("phase"),
                 view.get("asking"), view.get("turns_used"), (time.monotonic() - started) * 1000)
        return result

    def test_parsing(self, user_id, model_id, now_utc_ms):
        """Exercise model ranking and review against synthetic wording without saving."""
        priority = self.propose(user_id, "后天 14-16", now_utc_ms, scope_label='羽毛球',
                                model_id=model_id, require_model=True)
        if priority["status"] != "needs_input" or not priority.get("conversation", {}).get("asking"):
            raise PlanError("invalid_model_proposal", 502)
        result = self.propose(user_id, SAMPLE_REQUEST, now_utc_ms, scope_label='羽毛球', model_id=model_id, require_model=True)
        return {"ok": result["status"] == "ready", "outcome": "parsed" if result["status"] == "ready" else result["status"],
                "priority_check": {"asking": priority["conversation"]["asking"]}, **result}

    def _propose(self, user_id, message, now_utc_ms, credential_id, answers, asked_fields, scope_label,
                 model_id, require_model, reference_date):
        turns = self._turns(message, answers)
        used = len(turns) - 1
        asked = self._asked(asked_fields, used)
        if _SECRET.search("\n".join(turns)):
            raise PlanError("sensitive_planning_input", 400)
        scope = self._scope(scope_label)
        context = self._plans.active_context
        policy = BookingWindowPolicy(context.timezone_name)
        today = policy.business_date_at_utc(now_utc_ms)
        reference_date = reference_date or today
        if type(reference_date) is not date:
            raise PlanError("invalid_planning_request", 400)
        has_command, notes = classify_execution(turns)
        draft = fold(turns, asked, today, reference_date=reference_date)
        slots = build_slots(draft, today)
        state = conv.decide(slots, asked, used, has_command=has_command)
        ctx = _Turn(turns, asked, used, today, draft, notes, policy, now_utc_ms, credential_id, scope, require_model)
        if state.phase is Phase.UNSUPPORTED:
            return self._reply("unsupported", [UNSUPPORTED_TEXT], None, self._view(ctx, state, slots))
        if state.phase is Phase.ESCALATED:
            return self._escalated(ctx, state, slots)
        if state.phase is Phase.READY:
            return self._ready(ctx, state, slots, user_id, model_id)
        state = self._prioritize(ctx, state, slots, user_id, model_id)
        return self._reply("needs_input", [question(slots, state.asking, draft, today)], None, self._view(ctx, state, slots))

    def _prioritize(self, ctx, state: Decision, slots, user_id, model_id) -> Decision:
        if state.reason in {Reason.AMBIGUOUS, Reason.INVALID}:
            return state
        asked_counts = Counter(ctx.asked)
        blocking = [slot for slot in conv.blocking_slots(slots)
                    if asked_counts[slot.field] < conv.MAX_ASKS_PER_FIELD]
        allowed = [slot.field for slot in blocking]
        if len(allowed) < 2 or allowed[0] == "target_date":
            return state
        payload = {
            "user_turns": ctx.turns,
            "blocking_fields": [
                {"field": slot.field, "status": slot.status.value, "display": slot.display, "detail": slot.detail}
                for slot in blocking
            ],
        }
        messages = [
            {"role": "system", "content": PRIORITY_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, allow_nan=False)},
        ]
        try:
            content, _provider = (self._providers.chat(user_id, messages, model_id=model_id) if model_id is not None
                                  else self._providers.chat(user_id, messages))
        except AIModelError as exc:
            if ctx.require_model:
                raise
            note = "模型暂不可用，本轮按默认优先级继续追问。"
            if note not in ctx.notes:
                ctx.notes.append(note)
            return state
        selected = parse_priority_field(content, allowed)
        if selected is None:
            log.warning("queue priority rejected")
            if ctx.require_model:
                raise PlanError("invalid_model_proposal", 502)
            note = "模型未返回有效的追问优先级，本轮按默认顺序继续。"
            if note not in ctx.notes:
                ctx.notes.append(note)
            return state
        selected_slot = slots[selected]
        reason = selected_slot.reason or (Reason.AMBIGUOUS if selected_slot.status is conv.SlotStatus.AMBIGUOUS
                                          else Reason.INVALID if selected_slot.status is conv.SlotStatus.INVALID else Reason.MISSING)
        phase = Phase.REPAIRING if reason in {Reason.AMBIGUOUS, Reason.INVALID} else Phase.COLLECTING
        return Decision(phase, selected, reason)

    def _ready(self, ctx, state, slots, user_id, model_id) -> dict:
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
        zone = ZoneInfo(ctx.policy.timezone_name)
        local = datetime.fromtimestamp(ctx.now_utc_ms / 1000, zone)
        days = (target - local.date()).days
        if days < AUTO_DAYS_AHEAD:
            return {"state": "not_automatic", "text": "自动执行只处理“开票日”：目标日前两天的 07:30。这一天已经不会再自动执行，可以保存，但需要你自己去抢。"}
        opening = target - timedelta(days=AUTO_DAYS_AHEAD)
        if days == AUTO_DAYS_AHEAD and (local.hour, local.minute) >= (OPEN_HOUR, OPEN_MINUTE):
            return {"state": "passed", "text": f"今天 {OPEN_HOUR:02d}:{OPEN_MINUTE:02d} 的开票时间已经过了，这一天不会再自动执行。"}
        when = "今天" if days == AUTO_DAYS_AHEAD else f"{opening.month}月{opening.day}日 {WEEKDAY_NAMES[opening.weekday()]}"
        return {"state": "scheduled", "text": f"{when} {OPEN_HOUR:02d}:{OPEN_MINUTE:02d} 开票时自动执行；开票前会按真实场地表核对，用不上的候选会被去掉。"}

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
    def _view(ctx, state: Decision, slots, *, notes=None) -> dict:
        heading = HEADING.get(state.asking or "")
        if state.asking == "want_1h" and slots[state.asking].detail == "both_disabled":
            heading = "选择预约时长"
        return {"phase": state.phase.value, "asking": state.asking, "heading": heading,
                "reason": state.reason.value if state.reason else None, "turns_used": ctx.used, "turns_max": conv.MAX_ANSWERS,
                "attempts": dict(Counter(f for f in ctx.asked if f)), "slots": [slots[f].public() for f in conv.PRIORITY],
                "strip": strip(ctx.draft, slots, state.asking), "escalation": None,
                "notices": ctx.notes if notes is None else notes}

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
    def _asked(asked_fields, used) -> list:
        if asked_fields is None:
            return [None] * used
        if (type(asked_fields) is not list or len(asked_fields) != used
                or any(f is not None and f not in conv.PRIORITY for f in asked_fields)):
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
