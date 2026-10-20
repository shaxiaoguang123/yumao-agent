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
from backend.ai.conversation import Decision, Phase
from backend.ai.nlu.cues import classify_execution
from backend.ai.nlu.dates import WEEKDAY_NAMES
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
HEADING = {"booking_mode": "选择队列类型", "target_date": "日期", "windows_2h": "2小时时段",
           "overlap_2h": "2小时时间确认", "courts_2h": "2小时场地", "windows_1h": "1小时时段",
           "overlap_1h": "1小时时间确认", "courts_1h": "1小时场地"}
SAMPLE_REQUEST = "后天，14-16和18-20，1号4号场，不要一小时，不用候选"
CONTEXT_QUESTION_PROMPT = """你是羽毛球预约队列助手。判断用户最新一句是纯问题、预约信息加问题，还是预约信息。
根据提供的产品规则和当前进度，用简短中文回答纯问题或混合消息。只回答可由上下文确认的事实；不知道的要明确说无法确认。
不要声称已查到实时余位，不要补造场地状态；真实场地状态只能在开票流程中读取。
不要调用工具，不要创建或保存队列，不要预约、下单或付款；不要决定流程下一步，也不要把用户问题中的假设当成已确认意图。
必须只返回 JSON：{\"kind\":\"question|mixed|answer\",\"reply\":\"对用户的简短回答；answer 类型留空\"}。
如果消息同时明确给出了场地/日期/时间/队列类型并提出问题，返回 mixed；只问规则或原因且没有明确预约选择，返回 question；纯粹给预约信息或选择，返回 answer。"""
_QUESTION_CUE = re.compile(
    r"[?？]|为什么|怎么(?:办|选|样|做)|如何|是否|是不是|能不能|可不可以|可以吗|行不行|什么区别|是什么|哪一个|哪个|几号|多少|能否|需要吗|要不要"
)


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


class PlanningService:
    def __init__(self, plan_service, provider_service):
        self._plans = plan_service
        self._providers = provider_service

    def business_date_at(self, now_utc_ms: int) -> date:
        return BookingWindowPolicy(self._plans.active_context.timezone_name).business_date_at_utc(now_utc_ms)

    def propose(self, user_id: str, message: object, now_utc_ms: int, *, credential_id=None, answers=None,
                asked_fields=None, scope_label=None, model_id=None, require_model=False,
                reference_date: date | None = None, previous_turn_kinds=None) -> dict:
        started = time.monotonic()
        result = self._propose(user_id, message, now_utc_ms, credential_id, answers, asked_fields, scope_label,
                               model_id, require_model, reference_date, previous_turn_kinds)
        view = result.get("conversation") or {}
        log.info("planning status=%s phase=%s asking=%s turns=%s elapsed_ms=%d", result["status"], view.get("phase"),
                 view.get("asking"), view.get("turns_used"), (time.monotonic() - started) * 1000)
        return result

    def test_parsing(self, user_id, model_id, now_utc_ms):
        """Exercise contextual Q&A and queue review against synthetic wording without saving."""
        question_result = self.propose(user_id, "为什么要分别确认1小时和2小时的场地？", now_utc_ms,
                                       scope_label="羽毛球", model_id=model_id, require_model=True)
        reply = (question_result.get("conversation") or {}).get("contextual_reply")
        if question_result["status"] != "needs_input" or not isinstance(reply, str) or not reply.strip():
            raise PlanError("invalid_model_proposal", 502)
        result = self.propose(user_id, SAMPLE_REQUEST, now_utc_ms, scope_label="羽毛球", model_id=model_id, require_model=True)
        return {"ok": result["status"] == "ready", "outcome": "parsed" if result["status"] == "ready" else result["status"],
                "question_check": {"answered": True}, **result}

    def _propose(self, user_id, message, now_utc_ms, credential_id, answers, asked_fields, scope_label,
                 model_id, require_model, reference_date, previous_turn_kinds):
        turns = self._turns(message, answers)
        used = len(turns) - 1
        asked = self._asked(asked_fields, used)
        kinds = self._turn_kinds(previous_turn_kinds, len(turns))
        is_new_turn = previous_turn_kinds is None or len(previous_turn_kinds) == len(turns) - 1
        if is_new_turn:
            kinds[-1] = "question" if _QUESTION_CUE.search(turns[-1]) else "answer"
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
        draft = fold(turns, asked, today, reference_date=reference_date, turn_kinds=kinds)
        slots = build_slots(draft, today)
        state = conv.decide(slots, asked, used, has_command=has_command)
        ctx = _Turn(turns, kinds, asked, used, today, draft, notes, policy, now_utc_ms, credential_id, scope, require_model)
        contextual_reply = None
        if is_new_turn and kinds[-1] == "question" and not has_command:
            kind, contextual_reply = self._contextual_reply(user_id, model_id, turns[-1], ctx, state, slots)
            if kind in {"answer", "mixed"}:
                kinds[-1] = kind
                draft = fold(turns, asked, today, reference_date=reference_date, turn_kinds=kinds)
                slots = build_slots(draft, today)
                state = conv.decide(slots, asked, used, has_command=False)
                ctx = _Turn(turns, kinds, asked, used, today, draft, notes, policy, now_utc_ms, credential_id, scope, require_model)
        if state.phase is Phase.UNSUPPORTED:
            return self._reply("unsupported", [UNSUPPORTED_TEXT], None, self._view(ctx, state, slots))
        if state.phase is Phase.ESCALATED:
            return self._escalated(ctx, state, slots)
        if state.phase is Phase.READY:
            result = self._ready(ctx, state, slots, user_id, model_id)
            if contextual_reply:
                result["conversation"]["contextual_reply"] = contextual_reply
            return result
        view = self._view(ctx, state, slots)
        if contextual_reply:
            view["contextual_reply"] = contextual_reply
        return self._reply("needs_input", [question(slots, state.asking, draft, today)], None, view)

    @staticmethod
    def _turn_kinds(previous, turn_count: int) -> list[str]:
        previous = [] if previous is None else previous
        if (type(previous) is not list or len(previous) not in (turn_count - 1, turn_count)
                or any(kind not in {"answer", "question", "mixed"} for kind in previous)):
            raise PlanError("invalid_planning_request", 400)
        return list(previous) if len(previous) == turn_count else [*previous, "answer"]

    def _contextual_reply(self, user_id, model_id, latest, ctx, state, slots):
        facts = {
            "business_date": ctx.today.isoformat(),
            "next_required_step": HEADING.get(state.asking, "队列核对完成"),
            "selected": [{"field": field, "value": slot.display, "status": slot.status.value}
                         for field, slot in slots.items() if slot.active and slot.display],
            "rules": [
                "只整理候选队列；此处不会查询实时余位、预约、下单或付款。",
                "场地编号范围为1至10；预约时间为09:00至22:00。",
                "1小时和2小时候选分别确认时间和场地，不互相继承。",
                "真实场地状态要在开票流程中读取，模型不能推断可订状态。",
                "模式选择：1/A只抢2小时，2/B只抢1小时，3/C两种都抢。",
            ],
            "recent_user_messages": ctx.turns[-6:],
        }
        messages = [
            {"role": "system", "content": CONTEXT_QUESTION_PROMPT},
            {"role": "user", "content": json.dumps({"question_or_message": latest, "context": facts},
                                                        ensure_ascii=False, allow_nan=False)},
        ]
        content, _provider = (self._providers.chat(user_id, messages, model_id=model_id) if model_id is not None
                              else self._providers.chat(user_id, messages))
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"\A```(?:json)?\s*|\s*```\Z", "", content, flags=re.I).strip()
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            raise PlanError("invalid_model_proposal", 502) from None
        if (type(parsed) is not dict or parsed.keys() != {"kind", "reply"}
                or parsed["kind"] not in {"question", "answer", "mixed"}
                or not isinstance(parsed["reply"], str) or len(parsed["reply"]) > 1000
                or any(unicodedata.category(char) == "Cs" for char in parsed["reply"])):
            raise PlanError("invalid_model_proposal", 502)
        reply = parsed["reply"].strip()
        if parsed["kind"] != "answer" and (not reply or _SECRET.search(reply)):
            raise PlanError("invalid_model_proposal", 502)
        return parsed["kind"], reply if parsed["kind"] != "answer" else None

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
        return {"phase": state.phase.value, "asking": state.asking, "heading": heading,
                "business_date": ctx.today.isoformat(),
                "reason": state.reason.value if state.reason else None, "turns_used": ctx.used, "turns_max": conv.MAX_ANSWERS,
                "attempts": dict(Counter(f for f in ctx.asked if f)), "turn_kinds": ctx.turn_kinds,
                "slots": [slots[f].public() for f in conv.PRIORITY],
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
