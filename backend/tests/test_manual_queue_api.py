import json
from contextlib import closing
from unittest.mock import patch
from backend.db import connect_database
import unittest
import test_plans_api as plan_tests


def entry(court='人工场1', start='18:00', duration=120, end=None):
    return dict(court_preference=court, start_time=start, duration_minutes=duration,
                end_time=end or f'{int(start[:2])+duration//60:02d}:00')


class ManualQueueTests(unittest.TestCase):
    setUp = plan_tests.PlansApiTests.setUp
    # Reuse isolated authenticated DB setup, not the parent's test cases.
    def save_queue(self, entries, base=0, client=None, user='a', date='2026-10-20'):
        return (client or self.a).put('/api/plans/manual-queues/'+date,
                    json={'base_version':base,'entries':entries},headers=self.headers[user])

    def test_queue_priority_and_semantic_revision_history(self):
        q=self.save_queue([entry('一小时',duration=60),entry('首选'),entry('备选')]).get_json()['queue']
        self.assertEqual([i['duration_minutes'] for i in q['candidates']],[120,120,60])
        self.assertEqual([i['court_preferences'][0] for i in q['candidates']],['首选','备选','一小时'])
        self.assertEqual(q['duration_priority'],[120,60])
        for i in q['candidates']:
            self.assertFalse(i['fallback_policy']['allow_any_court_in_venue'])
            self.assertFalse(i['fallback_policy']['allow_time_shift'])
        response=self.save_queue([entry('备选'),entry('首选')],base=1)
        self.assertEqual(response.get_json()['queue']['version'],2)
        self.assertEqual(self.save_queue([entry('备选'),entry('首选')],base=2).get_json()['queue']['version'],2)
        history=self.a.get('/api/plans/manual-queues/2026-10-20/revisions').get_json()['revisions']
        self.assertEqual([r['revision_number'] for r in history],[2,1])
        self.assertEqual(history[-1]['candidates'][0]['court_preferences'],['首选'])
        self.assertEqual(self.a.get('/api/plans').get_json()['plans'],[])
        self.assertEqual(self.a.get('/api/plans/'+q['plan_id']).status_code,404)
        with closing(connect_database(self.path,5000)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM booking_plan_revisions').fetchone()[0],2)
            raw=db.execute('SELECT intent_json FROM booking_plan_revisions').fetchone()[0]
        for field in ('coordinatesList','nodeid','token','credential_id','stock','job'):
            self.assertNotIn('"'+field+'"',raw)
        self.network.assert_not_called()

    def test_isolation_cas_empty_and_no_duplicate_after_lost_response(self):
        q=self.save_queue([entry()]).get_json()['queue']
        self.assertIsNone(self.b.get('/api/plans/manual-queues/2026-10-20').get_json()['queue'])
        self.assertEqual(self.b.get('/api/plans/manual-queues/2026-10-20/revisions').status_code,404)
        other=self.save_queue([entry('B')],client=self.b,user='b').get_json()['queue']
        self.assertNotEqual(other['plan_id'],q['plan_id'])
        self.assertEqual(self.save_queue([entry()],base=0).status_code,409)
        self.assertEqual(self.save_queue([],base=1).get_json()['queue']['version'],2)
        self.assertEqual(self.a.get('/api/plans/manual-queues/2026-10-20').get_json()['queue']['candidates'],[])
        self.assertEqual(len(self.a.get('/api/plans/manual-queues').get_json()['queues']),1)

    def test_strict_hours_end_boundary_and_execution_rejection(self):
        for value in (entry(duration=True),entry(duration=90),entry(start='18:30'),entry(end='21:00'),entry(start='23:00'),{**entry(),'nodeid':'private'},{**entry(),'credential_id':'private'}):
            with self.subTest(value=value):self.assertEqual(self.save_queue([value]).status_code,400)
        self.assertEqual(self.save_queue([entry(),entry()]).status_code,400)
        self.assertEqual(self.save_queue([entry()],base=True).status_code,400)
        self.assertEqual(self.save_queue([entry(start='22:00',end='24:00')]).status_code,200)
        self.assertEqual(self.a.get('/api/plans/manual-queues/bad').status_code,400)
        self.assertEqual(self.a.put('/api/plans/manual-queues/2026-10-20',json={'base_version':1,'entries':[]}).status_code,403)
        self.assertEqual(self.app.test_client().get('/api/plans/manual-queues').status_code,401)
        self.network.assert_not_called()
