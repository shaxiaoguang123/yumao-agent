"""One-request LangGraph orchestration for queue conversation turns."""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.ai.conversation import Phase
from backend.ai.queue_policy import FIELD_LABELS


class QueueTurn(TypedDict, total=False):
    service: Any
    request: dict[str, Any]
    prepared: Any
    interpreted: dict | None
    evaluated: Any
    result: dict[str, Any]
    workflow_state: str
    workflow_trace: list[dict[str, str]]


def _trace(state: QueueTurn, node: str, detail: str) -> list[dict[str, str]]:
    return [*state.get("workflow_trace", []), {"stage": node, "detail": detail}]


def _after_apply(state: QueueTurn) -> str:
    phase = state["evaluated"].decision.phase
    if phase is Phase.UNSUPPORTED:
        return "unsupported"
    if phase is Phase.ESCALATED:
        return "escalated"
    if phase is Phase.READY:
        return "preview"
    return "clarification"


def _finish(state: QueueTurn) -> dict:
    result = dict(state["result"])
    trace = state.get("workflow_trace", [])
    result["workflow_trace"] = trace
    conversation = result.get("conversation")
    if isinstance(conversation, dict):
        result["conversation"] = {**conversation, "workflow_state": state["workflow_state"],
                                   "workflow_trace": trace}
    result["workflow_state"] = state["workflow_state"]
    return {"result": result}


class QueuePlanningGraph:
    """Interpret one user turn, validate it, then route to clarification or preview."""

    def __init__(self):
        builder = StateGraph(QueueTurn)
        builder.add_node("prepare_context", self._prepare)
        builder.add_node("interpret_turn", self._interpret)
        builder.add_node("apply_and_validate", self._apply)
        builder.add_node("clarification", self._clarification)
        builder.add_node("preview", self._preview)
        builder.add_node("escalated", self._escalated)
        builder.add_node("unsupported", self._unsupported)
        builder.add_node("finish", _finish)
        builder.add_edge(START, "prepare_context")
        builder.add_edge("prepare_context", "interpret_turn")
        builder.add_edge("interpret_turn", "apply_and_validate")
        builder.add_conditional_edges("apply_and_validate", _after_apply,
                                      {"clarification": "clarification", "preview": "preview",
                                       "escalated": "escalated", "unsupported": "unsupported"})
        for node in ("clarification", "preview", "escalated", "unsupported"):
            builder.add_edge(node, "finish")
        builder.add_edge("finish", END)
        self._graph = builder.compile()

    @staticmethod
    def _prepare(state: QueueTurn) -> dict:
        prepared = state["service"].prepare_turn(state["request"])
        detail = f"已加载{len(prepared.turns)}轮用户消息、{len(prepared.assistant_history)}轮助手校验记录。"
        return {"prepared": prepared, "workflow_trace": _trace(state, "准备上下文", detail)}

    @staticmethod
    def _interpret(state: QueueTurn) -> dict:
        interpreted = state["service"].interpret_turn(state["prepared"])
        provider = interpreted.get("provider", {}) if interpreted else {}
        detail = ("模型判断为当前队列意向。" if interpreted and interpreted.get("intent") == "queue"
                  else "模型判断为即时执行请求，将拒绝执行。" if interpreted else "重放已校验的对话状态。")
        if provider.get("model"):
            detail += f"模型：{provider['model']}。"
        return {"interpreted": interpreted, "workflow_trace": _trace(state, "模型理解", detail)}

    @staticmethod
    def _apply(state: QueueTurn) -> dict:
        evaluated = state["service"].apply_interpretation(state["prepared"], state.get("interpreted"))
        decision = evaluated.decision
        trace = _trace(
            state, "应用更新并校验",
            f"有效候选 {evaluated.turn_trace['candidate_count']}；"
            f"待确认：{FIELD_LABELS.get(decision.asking, '修改内容' if evaluated.dialogue['pending_edit'] else '无')}。",
        )
        return {"evaluated": evaluated, "workflow_trace": trace}

    @staticmethod
    def _result(state: QueueTurn, method: str, workflow_state: str, node: str, detail: str) -> dict:
        result = getattr(state["service"], method)(state["evaluated"])
        return {"result": result, "workflow_state": workflow_state,
                "workflow_trace": _trace(state, node, detail)}

    @classmethod
    def _clarification(cls, state: QueueTurn) -> dict:
        evaluated = state["evaluated"]
        if evaluated.dialogue["next_action"] == "answer":
            stage, detail = "回答问题", "已回答上下文问题，保留当前预约进度。"
        elif evaluated.decision.asking is None:
            stage, detail = "确认修改内容", "请先说明想修改哪一项信息。"
        else:
            stage, detail = "追问", f"等待确认{FIELD_LABELS[evaluated.decision.asking]}。"
        return cls._result(state, "render_clarification", "awaiting_clarification", stage, detail)

    @classmethod
    def _preview(cls, state: QueueTurn) -> dict:
        return cls._result(state, "render_preview", "awaiting_review", "生成预览", "候选队列通过确定性校验，等待用户核对。")

    @classmethod
    def _escalated(cls, state: QueueTurn) -> dict:
        return cls._result(state, "render_escalation", "escalated", "升级处理", "当前字段多次无法确认，转为手动选场建议。")

    @classmethod
    def _unsupported(cls, state: QueueTurn) -> dict:
        return cls._result(state, "render_unsupported", "unsupported", "范围拒绝", "请求包含此 Agent 不执行的预约或付款动作。")

    def invoke(self, service, request: dict[str, Any]) -> dict:
        return self._graph.invoke({"service": service, "request": request})["result"]
