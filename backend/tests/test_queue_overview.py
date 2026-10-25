import json
from contextlib import closing
from datetime import datetime
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.db import connect_database
from backend.execution.repository import BookingExecutionRepository
import test_execution_settings as settings_tests
from test_manual_queue_api import entry
import test_plans_api as plans_tests


def clock(day, hour=8, minute=0, second=0):
    return int(datetime(2026, 10, day, hour, minute, second, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp() * 1000)


class QueueOverviewTests(TestCase):
    setUp = plans_tests.PlansApiTests.setUp

    def prepare(self):
        self.database = self.path
        for user, credential in [('a', 'token-a'), ('a', 'token-b'), ('b', 'token-private')]:
            settings_tests.ExecutionSettingsTests._insert_account(self, user, credential)
        self.plans = self.app.extensions['plan_service']
        self.runs = BookingExecutionRepository(self.path, 5000)

    def queue(self, day=27, credential='token-a', user='a', entries=None):
        return self.plans.save_manual_queue(user, f'2026-10-{day:02d}', 0, [entry()] if entries is None else entries, clock(10), credential)

    def execution_run(self, queue, state, when, *, verified=False):
        candidates = [dict(entry(), queue_index=0)]
        run = self.runs.create_run(user_id='a', credential_id=queue['credential_id'], target_date=queue['target_date'], queue=queue,
            candidates=candidates, reconciliation={'retained_candidate_count':1}, state='ready', now_utc_ms=when-1000)
        if verified:
            self.runs.record_stage(run['run_id'], dict(round_number=1, candidate_index=0, stage_key='payment_verification',
                started_at_utc_ms=when-5, completed_at_utc_ms=when, elapsed_ms=5, outcome='success', safe_code=None))
        if state != 'ready':
            self.runs.update_state(run['run_id'], ('ready',), state, when, completed=state not in {'running', 'calibrated'})
        return run

    def overview(self, category='pending', now=None, **filters):
        return self.plans.queue_overview('a', 'token-a', now or clock(25), category=category, **filters)

    def test_state_classification_pending_priority_and_result_order(self):
        self.prepare()
        waiting = self.queue(30)
        ready = self.queue(27)
        running = self.queue(29)
        success_old = self.queue(20)
        success_new = self.queue(21)
        failed = self.queue(22)
        self.execution_run(ready, 'ready', clock(25, 0, 30))
        self.execution_run(running, 'running', clock(25, 7, 30))
        self.execution_run(success_old, 'succeeded', clock(18), verified=True)
        self.execution_run(success_new, 'succeeded', clock(19), verified=True)
        self.execution_run(failed, 'failed', clock(20))
        pending = self.overview()
        self.assertEqual([item['target_date'] for item in pending['queues']], [running['target_date'], ready['target_date'], waiting['target_date']])
        self.assertEqual(pending['counts'], dict(pending=3, succeeded=2, attention=1, all=6))
        self.assertEqual([item['target_date'] for item in self.overview('succeeded')['queues']], ['2026-10-21', '2026-10-20'])
        self.assertEqual(self.overview('attention')['queues'][0]['lifecycle']['label'], '三轮未成功')
        self.assertEqual(self.overview('succeeded')['queues'][0]['success']['court_preference'], '1号场')
        self.network.assert_not_called()

    def test_all_terminal_states_are_distinguished_without_claiming_success(self):
        self.prepare()
        for day, state in [(16, 'failed'), (17, 'empty'), (18, 'stale'), (19, 'needs_attention')]:
            self.execution_run(self.queue(day), state, clock(20, 7, day))
        items = self.overview('attention')['queues']
        self.assertEqual({item['execution_state'] for item in items}, {'failed', 'empty', 'stale', 'needs_attention'})
        self.assertTrue(all(item['success'] is None for item in items))

    def test_old_dates_are_searchable_and_do_not_disappear_at_retention_cutoff(self):
        self.prepare()
        self.queue(12)
        value = self.overview('all', target_date='2026-10-12')
        self.assertEqual(value['total'], 1)
        self.assertEqual(value['queues'][0]['lifecycle']['state'], 'missed')
        self.assertEqual(self.plans.list_manual_queues('a', 'token-a', recent_only=True, now_utc_ms=clock(25)), [])

    def test_a_new_revision_never_inherits_success_but_original_success_remains(self):
        self.prepare()
        queue = self.queue(27)
        self.execution_run(queue, 'succeeded', clock(25, 7, 30, 8), verified=True)
        updated = self.plans.save_manual_queue('a', queue['target_date'], 1, [entry('2号场')], clock(25, 7, 40), 'token-a')
        success = self.overview('succeeded')['queues'][0]
        attention = self.overview('attention')['queues'][0]
        self.assertEqual(success['version'], 1)
        self.assertFalse(success['lifecycle']['is_current_revision'])
        self.assertEqual(success['lifecycle']['current_version'], 2)
        self.assertEqual(attention['version'], updated['version'])
        self.assertEqual(attention['execution_state'], 'missed')
        self.assertTrue(attention['lifecycle']['is_current_revision'])
        self.assertEqual(self.overview('all')['total'], 2)

    def test_cleared_and_deleted_queues_keep_actual_execution_history(self):
        self.prepare()
        queue = self.queue(27)
        self.execution_run(queue, 'succeeded', clock(25, 7, 30, 8), verified=True)
        self.plans.delete_manual_queue('a', queue['target_date'], 1, clock(25), 'token-a')
        self.assertEqual(self.overview('all')['total'], 1)
        self.assertEqual(self.overview('succeeded')['queues'][0]['success']['court_preference'], '1号场')
        self.queue(29, entries=[])
        self.assertEqual(self.overview('all')['total'], 1)
        selected = self.overview('all', target_date='2026-10-29')['queues']
        self.assertEqual(selected[0]['execution_state'], 'cleared')

    def test_opening_boundary_uses_business_time_and_keeps_existing_ready_run_pending(self):
        self.prepare()
        self.queue(27)
        self.assertEqual(self.overview(now=clock(25, 7, 29, 59))['total'], 1)
        self.assertEqual(self.overview(now=clock(25, 7, 30))['total'], 0)
        self.assertEqual(self.overview('attention', now=clock(25, 7, 30))['queues'][0]['execution_state'], 'missed')
        queue = self.queue(28)
        self.execution_run(queue, 'ready', clock(26, 0, 30))
        pending = self.overview(now=clock(26, 7, 30))
        self.assertEqual(pending['queues'][0]['execution_state'], 'ready')

    def test_token_and_user_isolation_and_invalid_queries(self):
        self.prepare()
        self.queue(29)
        self.queue(29, 'token-b')
        self.queue(29, 'token-private', 'b')
        url = '/api/plans/queue-overview?credential_id=token-a'
        self.assertEqual(self.a.get(url).get_json()['counts']['all'], 1)
        self.assertEqual(self.b.get(url).status_code, 404)
        self.assertEqual(self.app.test_client().get(url).status_code, 401)
        for query in ['', '?credential_id=token-private', '?credential_id=missing']:
            self.assertIn(self.a.get('/api/plans/queue-overview'+query).status_code, [400, 404])
        for query in ['&category=nope', '&page=0', '&page=true', '&limit=51', '&limit=-1', '&target_date=2026-02-30', '&token=secret', '&credential_id=token-b', '&category=all&category=pending']:
            with self.subTest(query=query):
                self.assertEqual(self.a.get(url+query).status_code, 400)
        self.network.assert_not_called()

    def test_pagination_is_bounded_and_sorts_before_slicing(self):
        self.prepare()
        for day in range(1, 29):
            self.plans.save_manual_queue('a', f'2026-11-{day:02d}', 0, [entry()], clock(10), 'token-a')
        first = self.overview(limit=5)
        second = self.overview(page=2, limit=5)
        self.assertEqual(first['total'], 28)
        self.assertEqual(first['next_page'], 2)
        self.assertEqual(first['queues'][0]['target_date'], '2026-11-01')
        self.assertEqual(second['queues'][0]['target_date'], '2026-11-06')
        self.assertFalse({item['record_id'] for item in first['queues']} & {item['record_id'] for item in second['queues']})
        self.assertIsNone(self.overview(page=6, limit=5)['next_page'])
        self.assertEqual(self.overview(page=99, limit=5)['queues'], [])

    def test_overview_batches_reads_and_exposes_no_material_or_execution_tools(self):
        self.prepare()
        for day in range(1, 12):
            self.plans.save_manual_queue('a', f'2026-11-{day:02d}', 0, [entry()], clock(10), 'token-a')
        statements = []
        def connect(*args):
            connection = connect_database(*args)
            connection.set_trace_callback(statements.append)
            return connection
        with patch('backend.plans.service.connect_database', side_effect=connect):
            response = self.overview('all', limit=5)
        selects = [sql for sql in statements if sql.lstrip().upper().startswith('SELECT')]
        self.assertEqual(len(selects), 2)
        self.assertFalse(any(sql.lstrip().upper().startswith(('UPDATE', 'INSERT', 'DELETE')) for sql in statements))
        raw = json.dumps(response)
        for secret in ['ciphertext', 'current_token_revision_id', 'token_fingerprint', 'source_sha256']:
            self.assertNotIn(secret, raw)
        for queue in response['queues']:
            for field in ['can_book', 'can_pay', 'can_create_job', 'can_query_upstream']:
                self.assertFalse(queue[field])
        self.network.assert_not_called()

    def test_revision_details_use_exact_owned_revision_and_never_another_tokens_run(self):
        self.prepare()
        queue = self.queue(27)
        run = self.execution_run(queue, 'succeeded', clock(25), verified=True)
        url = f'/api/booking-execution/credentials/token-a/queues/{queue["target_date"]}?revision_id={queue["current_revision_id"]}'
        self.assertEqual(self.a.get(url).get_json()['run']['run_id'], run['run_id'])
        self.assertEqual(self.b.get(url).status_code, 404)
        self.assertIsNone(self.a.get(url.replace('/token-a/', '/token-b/')).get_json()['run'])
        self.assertIsNone(self.a.get(url.replace(queue['current_revision_id'], 'missing')).get_json()['run'])
        self.assertEqual(self.a.get(url+'&revision_id=other').status_code, 400)
        self.assertEqual(self.a.get(url+'&unexpected=true').status_code, 400)
