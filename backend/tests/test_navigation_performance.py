from datetime import timedelta
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.ai.call_guard import AICallGuard
from backend.ai.provider import model_call_budget, PinnedChatCompletionsTransport, ProviderConfig, ProviderFailure
from backend.ai.service import AIModelError
import test_plans_api as plan_tests


class ModelCapacityTests(unittest.TestCase):
    def test_capacity_is_shared_between_guards_and_released_after_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'app.sqlite3'
            limits = SimpleNamespace(check_and_record=lambda *args: SimpleNamespace(allowed=True))
            first, second = AICallGuard(database, limits), AICallGuard(database, limits)
            with first.hold('user-a'), second.hold('user-b'):
                with self.assertRaises(AIModelError) as caught:
                    first.hold('user-c').__enter__()
                self.assertEqual((caught.exception.code, caught.exception.status), ('ai_service_busy', 503))
                with self.assertRaises(AIModelError) as caught:
                    second.hold('user-a').__enter__()
                self.assertEqual(caught.exception.code, 'ai_call_in_progress')
            with self.assertRaisesRegex(RuntimeError, 'synthetic'):
                with first.hold('user-c'):
                    raise RuntimeError('synthetic')
            with second.hold('user-c'), first.hold('user-d'):
                pass

    def test_one_budget_covers_nested_calls_and_resets_after_the_request(self):
        from langgraph.graph import StateGraph, START, END
        clock = [100.0]
        resolver = Mock(side_effect=ProviderFailure('provider_dns_resolution_failed'))
        transport = PinnedChatCompletionsTransport(resolver=resolver)
        config = ProviderConfig('m', 'm', 'https://vendor.example/v1', 'model', 'none')
        graph = StateGraph(dict)
        graph.add_node('probe', lambda state: transport.chat(config, [{'role':'user','content':'synthetic'}]))
        graph.add_edge(START, 'probe')
        graph.add_edge('probe', END)
        workflow = graph.compile()
        with patch('backend.ai.provider.time.monotonic', side_effect=lambda: clock[0]):
            with model_call_budget(5), model_call_budget(20):
                clock[0] = 106
                with self.assertRaises(ProviderFailure) as caught:
                    workflow.invoke({})
                self.assertEqual(caught.exception.code, 'provider_timeout')
                resolver.assert_not_called()
            with self.assertRaises(ProviderFailure) as caught:
                transport.chat(config, [{'role': 'user', 'content': 'synthetic'}])
            self.assertEqual(caught.exception.code, 'provider_dns_resolution_failed')
            resolver.assert_called_once()


class RevisionPageTests(unittest.TestCase):
    setUp = plan_tests.PlansApiTests.setUp

    def test_current_view_skips_old_payloads_without_deleting_history(self):
        policy = self.app.extensions['plan_service'].policy
        first = policy.business_date_at_utc(plan_tests.NOW)
        dates = [(first+timedelta(days=index)).isoformat() for index in range(3)]
        for target in dates:
            entry = {'court_preference':'1号场','start_time':'18:00','end_time':'20:00','duration_minutes':120,'scope_label':'羽毛球'}
            self.assertEqual(self.a.put('/api/plans/manual-queues/'+target,
                             json={'base_version':0,'entries':[entry]},headers=self.headers['a']).status_code,200)
            self.assertEqual(self.a.post('/api/plans',json={'intent':plan_tests.draft(target_date=target)},headers=self.headers['a']).status_code,201)
        with patch('backend.api.plans._now_utc_ms',return_value=plan_tests.NOW+2*86400000):
            queues = self.a.get('/api/plans/manual-queues?view=current').get_json()['queues']
            plans = self.a.get('/api/plans?view=current').get_json()['plans']
            self.assertEqual(sorted(row['target_date'] for row in queues),dates[1:])
            self.assertEqual(sorted(row['intent']['target_date'] for row in plans),dates[1:])
            self.assertEqual(len(self.a.get('/api/plans/manual-queues').get_json()['queues']),3)
            self.assertEqual(self.b.get('/api/plans/manual-queues?view=current').get_json()['queues'],[])
            self.assertEqual(self.a.get('/api/plans?view=unknown').status_code,400)
            self.assertEqual(len(self.a.get('/api/plans/manual-queues/'+dates[0]+'/revisions?limit=20').get_json()['revisions']),1)
        self.network.assert_not_called()

    def test_queue_history_pages_are_complete_and_remain_owner_scoped(self):
        for version in range(25):
            entry = {'court_preference': f'{version % 10 + 1}号场', 'start_time': '18:00',
                     'end_time': '20:00', 'duration_minutes': 120, 'scope_label': '羽毛球'}
            response = self.a.put('/api/plans/manual-queues/2026-10-20',
                                  json={'base_version': version, 'entries': [entry]}, headers=self.headers['a'])
            self.assertEqual(response.status_code, 200)
        path = '/api/plans/manual-queues/2026-10-20/revisions'
        seen, cursor = [], None
        while True:
            query = {'limit': 7, **({'before_version': cursor} if cursor else {})}
            result = self.a.get(path, query_string=query).get_json()
            self.assertLessEqual(len(result['revisions']), 7)
            seen.extend(row['revision_number'] for row in result['revisions'])
            cursor = result['next_before_version']
            if cursor is None:
                break
        self.assertEqual(seen, list(range(25, 0, -1)))
        self.assertEqual(len(self.a.get(path).get_json()['revisions']), 25)
        self.assertEqual(self.b.get(path, query_string={'limit': 7}).status_code, 404)
        for query in ({'limit': 0}, {'limit': 51}, {'before_version': -1}, {'limit': 'bad'}, {'limit': ['2', '3']}):
            self.assertEqual(self.a.get(path, query_string=query).status_code, 400)
        self.network.assert_not_called()
