import unittest

from backend.ai.queue_graph import QueuePlanningGraph


class StubPlanner:
    def __init__(self, result):
        self.result = result
        self.request = None

    def propose(self, **request):
        self.request = request
        return self.result


class QueuePlanningGraphTests(unittest.TestCase):
    def test_routes_complete_clarification_escalation_and_unsupported_turns(self):
        cases = (
            ({"status": "ready", "conversation": {"phase": "ready"}}, "awaiting_review"),
            ({"status": "needs_input", "conversation": {"phase": "collecting"}}, "awaiting_clarification"),
            ({"status": "needs_input", "conversation": {"phase": "escalated", "escalation": {"kind": "stalled"}}}, "escalated"),
            ({"status": "unsupported", "conversation": {"phase": "unsupported"}}, "unsupported"),
            ({"status": "failed", "conversation": {"phase": "failed"}}, "failed"),
        )
        graph = QueuePlanningGraph()
        for result, expected_state in cases:
            with self.subTest(expected_state=expected_state):
                planner = StubPlanner(result)
                output = graph.invoke(planner, {"message": "用户输入"})
                self.assertEqual(output["workflow_state"], expected_state)
                self.assertEqual(output["conversation"]["workflow_state"], expected_state)
                self.assertEqual(planner.request, {"message": "用户输入"})


if __name__ == "__main__":
    unittest.main()
