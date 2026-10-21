import unittest
from types import SimpleNamespace

from backend.ai.conversation import Phase
from backend.ai.queue_graph import QueuePlanningGraph


class StubService:
    def __init__(self, phase):
        self.phase = phase
        self.request = None

    def prepare_turn(self, request):
        self.request = request
        return SimpleNamespace(has_command=False, turns=[request["message"]], assistant_history=[])

    def interpret_turn(self, _prepared):
        return {"kind": "answer", "provider": {"model": "synthetic"}}

    def apply_interpretation(self, prepared, interpreted):
        asking = "courts_2h" if self.phase in {Phase.COLLECTING, Phase.ESCALATED} else None
        return SimpleNamespace(
            prepared=prepared, interpreted=interpreted,
            dialogue={"next_action":"ask", "pending_edit":None},
            decision=SimpleNamespace(phase=self.phase, asking=asking),
            turn_trace={"candidate_count": 4, "candidate_limit": 32},
        )

    @staticmethod
    def _result(status):
        return {"status": status, "conversation": {"phase": status}}

    def render_clarification(self, _evaluated):
        return self._result("needs_input")

    def render_preview(self, _evaluated):
        return self._result("ready")

    def render_escalation(self, _evaluated):
        return self._result("escalated")

    def render_unsupported(self, _evaluated):
        return self._result("unsupported")


class QueuePlanningGraphTests(unittest.TestCase):
    def test_graph_runs_interpret_apply_validate_and_routes_each_terminal_outcome(self):
        cases = (
            (Phase.READY, "awaiting_review", "ready"),
            (Phase.COLLECTING, "awaiting_clarification", "needs_input"),
            (Phase.ESCALATED, "escalated", "escalated"),
            (Phase.UNSUPPORTED, "unsupported", "unsupported"),
        )
        graph = QueuePlanningGraph()
        for phase, expected_workflow, expected_status in cases:
            with self.subTest(phase=phase):
                service = StubService(phase)
                output = graph.invoke(service, {"message": "用户输入"})
                self.assertEqual(output["workflow_state"], expected_workflow)
                self.assertEqual(output["status"], expected_status)
                self.assertEqual(output["conversation"]["workflow_state"], expected_workflow)
                self.assertEqual(service.request, {"message": "用户输入"})
                self.assertEqual([item["stage"] for item in output["workflow_trace"]], [
                    "准备上下文", "模型理解", "应用更新并校验", {
                        "awaiting_review": "生成预览", "awaiting_clarification": "追问",
                        "escalated": "升级处理", "unsupported": "范围拒绝",
                    }[expected_workflow],
                ])


if __name__ == "__main__":
    unittest.main()
