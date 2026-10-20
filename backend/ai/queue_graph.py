"""LangGraph routing for one queue-planning turn.

The conversation store remains the durable, user-scoped source of truth. Each
request rehydrates its turn from that store before entering this graph.
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class QueueTurn(TypedDict, total=False):
    service: Any
    request: dict[str, Any]
    result: dict[str, Any]
    workflow_state: str


def _route_result(state: QueueTurn) -> str:
    result = state["result"]
    if result.get("status") == "ready":
        return "review"
    if result.get("status") == "needs_input":
        conversation = result.get("conversation") or {}
        return "escalated" if conversation.get("escalation") else "clarification"
    return "unsupported" if result.get("status") == "unsupported" else "failed"


def _finish(state: QueueTurn) -> dict:
    result = dict(state["result"])
    conversation = result.get("conversation")
    if isinstance(conversation, dict):
        result["conversation"] = {**conversation, "workflow_state": state["workflow_state"]}
    result["workflow_state"] = state["workflow_state"]
    return {"result": result}


class QueuePlanningGraph:
    """Route planner outcomes without giving the graph booking or payment tools."""

    def __init__(self):
        builder = StateGraph(QueueTurn)
        builder.add_node("process_turn", self._process_turn)
        for name, workflow_state in (
            ("clarification", "awaiting_clarification"),
            ("review", "awaiting_review"),
            ("escalated", "escalated"),
            ("unsupported", "unsupported"),
            ("failed", "failed"),
        ):
            builder.add_node(name, lambda _state, value=workflow_state: {"workflow_state": value})
            builder.add_edge(name, "finish")
        builder.add_node("finish", _finish)
        builder.add_edge(START, "process_turn")
        builder.add_conditional_edges(
            "process_turn",
            _route_result,
            {"clarification": "clarification", "review": "review", "escalated": "escalated",
             "unsupported": "unsupported", "failed": "failed"},
        )
        builder.add_edge("finish", END)
        self._graph = builder.compile()

    @staticmethod
    def _process_turn(state: QueueTurn) -> dict:
        return {"result": state["service"].propose(**state["request"])}

    def invoke(self, service, request: dict[str, Any]) -> dict:
        return self._graph.invoke({"service": service, "request": request})["result"]
