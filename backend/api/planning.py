from __future__ import annotations

import sqlite3
import secrets
import time
from datetime import date
from flask import Blueprint, current_app, g, jsonify, request

from backend.api.auth import require_csrf, require_session
from backend.api.ai_models import _body
from backend.ai.planning import assistant_history_entry
from backend.ai.service import AIModelError
from backend.plans.service import PlanError

planning_bp = Blueprint("planning", __name__, url_prefix="/api/planning")


@planning_bp.errorhandler(AIModelError)
def _provider_error(exc):
    response = jsonify({"error": exc.code})
    if hasattr(exc, "retry_after_seconds"):
        response.headers["Retry-After"] = str(exc.retry_after_seconds)
    return response, exc.status


@planning_bp.errorhandler(PlanError)
def _error(exc):
    return jsonify({"error": exc.code, **({"fields": exc.fields} if exc.fields else {})}), exc.status


@planning_bp.errorhandler(sqlite3.Error)
def _storage(_exc):
    return jsonify({"error": "plan_storage_unavailable"}), 503


def _queue_trace_event(result: dict, state: dict, now_utc_ms: int) -> dict:
    conversation = result.get("conversation") or {}
    trace = conversation.get("turn_trace") or {}
    if conversation.get("escalation"):
        title, detail = "建议改用手动选场", "这一项多次没能确认；已确认的日期可带到选择预约页。"
    elif result["status"] == "needs_input":
        title = "本轮理解完成"
        detail = trace.get("summary") or "先确认当前这一项；答复后继续。当前没有保存队列。"
    elif result["status"] == "ready":
        count = (result.get("proposal") or {}).get("entry_count", 0)
        title = "候选队列已整理好"
        detail = f"{trace.get('summary', '')}共 {count} 项，等待核对并确认保存。"
    else:
        title, detail = "请求不属于整理范围", "助手不会代为查询、预约、付款或创建任务。"
    return {
        "submitted_title": "提交补充回答" if state["answers"] else "提交预约需求",
        "submitted_detail": "继续核对必需信息。" if state["answers"] else "开始确认队列类型、日期、时段和场地。",
        "result_title": title, "result_detail": detail, "at_utc_ms": now_utc_ms,
    }


def _queue_signature(entries: object) -> list[tuple]:
    if type(entries) is not list or not entries:
        return []
    result = []
    for entry in entries:
        if type(entry) is not dict:
            return []
        courts = entry.get("court_preferences")
        starts = entry.get("preferred_start_times")
        court = entry.get("court_preference") or (courts[0] if type(courts) is list and courts else None)
        start = entry.get("start_time") or (starts[0] if type(starts) is list and starts else None)
        result.append((entry.get("duration_minutes"), start, court,
                       entry.get("scope_label") or entry.get("query_scope_label")))
    return result


@planning_bp.post("/proposals")
@require_session
@require_csrf
def proposals():
    """LLM-backed plan creation and edit proposal; saving still uses the plans API."""
    body = _body({"message", "plan_id", "base_version"},
                 {"message", "plan_id", "base_version", "answers", "follow_up_questions", "credential_id", "conversation_id"})
    if "answers" in body and type(body["answers"]) is not list:
        raise PlanError("invalid_planning_request", 400)
    user_id = g.session_context.user.user_id
    credential_id = body.get("credential_id")
    if credential_id is not None:
        if type(credential_id) is not str or not credential_id or current_app.extensions["credential_service"].get_for_user(user_id, credential_id) is None:
            raise PlanError("credential_not_found", 404)
    now_utc_ms = time.time_ns() // 1_000_000
    store = current_app.extensions["planning_conversation_store"]
    conversation_id = body.get("conversation_id")
    expected_conversation_version = 0
    answers = body.get("answers") or []
    state = {
        "message": body["message"].strip() if type(body["message"]) is str else body["message"],
        "answers": [item.strip() if type(item) is str else item for item in answers],
        "follow_up_questions": body.get("follow_up_questions") or [],
        "plan_id": body["plan_id"], "base_version": body["base_version"], "credential_id": credential_id,
    }
    if conversation_id is not None:
        if type(conversation_id) is not str or not 20 <= len(conversation_id) <= 128:
            raise PlanError("invalid_planning_request", 400)
        previous = store.get(conversation_id, user_id, credential_id, kind="intent")
        if previous is None:
            raise PlanError("planning_conversation_not_found", 404)
        expected_conversation_version = previous["version"]
        store.validate_next(previous, state)
        business_date = date.fromisoformat(previous["business_date"])
    else:
        conversation_id = secrets.token_urlsafe(24)
        business_date = current_app.extensions["intent_planning_service"].business_date_at(now_utc_ms)
    with current_app.extensions["ai_call_guard"].hold(user_id):
        result = current_app.extensions["intent_planning_service"].propose(
            user_id, body["message"], body["plan_id"], body["base_version"],
            now_utc_ms, answers=body.get("answers"),
            follow_up_questions=body.get("follow_up_questions"), credential_id=credential_id,
            reference_date=business_date,
        )
    result["conversation_id"] = conversation_id
    result["conversation_version"] = store.save(
        conversation_id, user_id, credential_id, business_date.isoformat(), state, result,
        now_utc_ms, kind="intent", expected_version=expected_conversation_version,
    )
    return jsonify(result)


@planning_bp.post("/queue-proposals")
@require_session
@require_csrf
def queue_proposals():
    body = _body({"message", "credential_id"},
                 {"message", "credential_id", "answers", "asked_fields", "scope_label", "conversation_id", "regenerate"})
    if "answers" in body and type(body["answers"]) is not list:
        raise PlanError("invalid_planning_request", 400)
    regenerate = body.get("regenerate", False)
    if type(regenerate) is not bool:
        raise PlanError("invalid_planning_request", 400)
    user_id = g.session_context.user.user_id
    credential_id = body["credential_id"]
    if type(credential_id) is not str or not credential_id or current_app.extensions["credential_service"].get_for_user(user_id, credential_id) is None:
        raise PlanError("credential_not_found", 404)
    now_utc_ms = time.time_ns() // 1_000_000
    store = current_app.extensions["planning_conversation_store"]
    conversation_id = body.get("conversation_id")
    expected_conversation_version = 0
    answers = body.get("answers") or []
    asked_fields = body.get("asked_fields")
    previous_turn_kinds = ["answer"] * len(answers)
    legacy_snapshot = None
    if asked_fields is None:
        asked_fields = [None] * len(answers)
    state = {
        "message": body["message"].strip() if type(body["message"]) is str else body["message"],
        "answers": [item.strip() if type(item) is str else item for item in answers],
        "asked_fields": asked_fields,
        "scope_label": body.get("scope_label"),
    }
    if conversation_id is not None:
        if type(conversation_id) is not str or not 20 <= len(conversation_id) <= 128:
            raise PlanError("invalid_planning_request", 400)
        previous = store.get(conversation_id, user_id, credential_id)
        if previous is None:
            raise PlanError("planning_conversation_not_found", 404)
        expected_conversation_version = previous["version"]
        replaying = len(answers) == len(previous["answers"])
        if regenerate and not replaying:
            raise PlanError("invalid_planning_request", 400)
        previous_turn_kinds = previous.get("turn_kinds") or ["answer"] * (len(previous["answers"]) + 1)
        state["turn_kinds"] = previous_turn_kinds if replaying else [*previous_turn_kinds, "answer"]
        store.validate_next(previous, state)
        if replaying and previous.get("response_history") and not regenerate:
            return jsonify(previous["response_history"][-1])
        business_date = date.fromisoformat(previous["business_date"])
        response_history = previous.get("response_history", [])
        assistant_history = [assistant_history_entry(item) for item in response_history]
        agent_state = previous.get("agent_state")
        if agent_state is None and previous.get("response_history"):
            latest_conversation = previous["response_history"][-1].get("conversation") or {}
            if isinstance(latest_conversation, dict) and type(latest_conversation.get("slots")) is list:
                legacy_snapshot = {"slots": latest_conversation["slots"]}
    else:
        if regenerate:
            raise PlanError("invalid_planning_request", 400)
        conversation_id = secrets.token_urlsafe(24)
        business_date = current_app.extensions["planning_service"].business_date_at(now_utc_ms)
        assistant_history = []
        agent_state = None
    with current_app.extensions["ai_call_guard"].hold(user_id):
        result = current_app.extensions["queue_planning_graph"].invoke(
            current_app.extensions["planning_service"],
            {"user_id": user_id, "message": body["message"], "now_utc_ms": now_utc_ms,
             "credential_id": credential_id, "answers": body.get("answers"),
             "asked_fields": body.get("asked_fields"), "scope_label": body.get("scope_label"),
             "reference_date": business_date, "previous_turn_kinds": previous_turn_kinds,
             "agent_state": agent_state, "assistant_history": assistant_history,
             "legacy_snapshot": legacy_snapshot},
        )
    result["conversation_id"] = conversation_id
    state["turn_kinds"] = result["conversation"]["turn_kinds"]
    agent_state = result["conversation"].pop("_agent_state", None)
    if agent_state is not None:
        state["agent_state"] = agent_state
    result["conversation_version"] = store.save(
        conversation_id, user_id, credential_id, business_date.isoformat(), state,
        {**result, "trace_event": _queue_trace_event(result, state, now_utc_ms)}, now_utc_ms,
        expected_version=expected_conversation_version,
    )
    return jsonify(result)


@planning_bp.get("/queue-conversations")
@require_session
def active_queue_conversation():
    credential_id = request.args.get("credential_id", "")
    user_id = g.session_context.user.user_id
    if not credential_id or current_app.extensions["credential_service"].get_for_user(user_id, credential_id) is None:
        raise PlanError("credential_not_found", 404)
    store = current_app.extensions["planning_conversation_store"]
    conversation = store.latest(user_id, credential_id)
    if conversation:
        conversation.pop("agent_state", None)
    return jsonify({"conversation": conversation,
                    "conversations": store.list_recent(user_id, credential_id)})


@planning_bp.get("/queue-conversations/<conversation_id>")
@require_session
def queue_conversation(conversation_id):
    if not 20 <= len(conversation_id) <= 128:
        raise PlanError("invalid_planning_request", 400)
    user_id = g.session_context.user.user_id
    credential_id = request.args.get("credential_id", "")
    if not credential_id or current_app.extensions["credential_service"].get_for_user(user_id, credential_id) is None:
        raise PlanError("credential_not_found", 404)
    saved = current_app.extensions["planning_conversation_store"].get(conversation_id, user_id, credential_id)
    if saved is None:
        raise PlanError("planning_conversation_not_found", 404)
    saved.pop("agent_state", None)
    return jsonify({"conversation": saved})


@planning_bp.post("/queue-conversations/<conversation_id>/resume")
@require_session
@require_csrf
def resume_queue_conversation(conversation_id):
    _body(set(), set())
    if not 20 <= len(conversation_id) <= 128:
        raise PlanError("invalid_planning_request", 400)
    user_id = g.session_context.user.user_id
    credential_id = request.args.get("credential_id", "")
    if not credential_id or current_app.extensions["credential_service"].get_for_user(user_id, credential_id) is None:
        raise PlanError("credential_not_found", 404)
    store = current_app.extensions["planning_conversation_store"]
    if not store.activate(conversation_id, user_id, credential_id, time.time_ns() // 1_000_000):
        raise PlanError("planning_conversation_not_found", 404)
    conversation = store.get(conversation_id, user_id, credential_id)
    conversation.pop("agent_state", None)
    return jsonify({"conversation": conversation})


@planning_bp.post("/queue-conversations/<conversation_id>/close")
@require_session
@require_csrf
def close_queue_conversation(conversation_id):
    body = _body(set(), {"outcome"})
    outcome = body.get("outcome", "cancelled")
    if outcome not in {"saved", "cancelled"}:
        raise PlanError("invalid_planning_request", 400)
    if not 20 <= len(conversation_id) <= 128:
        raise PlanError("invalid_planning_request", 400)
    user_id = g.session_context.user.user_id
    credential_id = request.args.get("credential_id", "")
    store = current_app.extensions["planning_conversation_store"]
    if outcome == "saved":
        if not credential_id or current_app.extensions["credential_service"].get_for_user(user_id, credential_id) is None:
            raise PlanError("credential_not_found", 404)
        saved_conversation = store.get(conversation_id, user_id, credential_id)
        history = saved_conversation.get("response_history", []) if saved_conversation else []
        latest = history[-1] if history else {}
        proposal = latest.get("proposal") or {}
        valid_proposal = (
            latest.get("status") == "ready" and proposal.get("kind") == "manual_queue_draft"
            and type(proposal.get("target_date")) is str and type(proposal.get("base_version")) is int
            and type(proposal.get("entry_count")) is int and proposal["entry_count"] > 0
        )
        queue = current_app.extensions["plan_service"].get_manual_queue(
            user_id, proposal["target_date"], credential_id,
        ) if valid_proposal else None
        if (queue is None or queue.get("deleted") or queue.get("version", 0) < proposal.get("base_version", 0)
                or len(queue.get("candidates") or []) != proposal.get("entry_count")
                or _queue_signature(queue.get("candidates")) != _queue_signature(proposal.get("entries"))):
            raise PlanError("planning_queue_not_saved", 409)
    store.close(
        conversation_id, user_id, credential_id, time.time_ns() // 1_000_000,
        workflow_state=outcome,
    )
    return "", 204


@planning_bp.post("/conversations/<conversation_id>/close")
@require_session
@require_csrf
def close_intent_conversation(conversation_id):
    _body(set(), set())
    if not 20 <= len(conversation_id) <= 128:
        raise PlanError("invalid_planning_request", 400)
    current_app.extensions["planning_conversation_store"].close(
        conversation_id, g.session_context.user.user_id, None, time.time_ns() // 1_000_000, kind="intent",
    )
    return "", 204
