import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.app import create_app
from backend.ai.planning import PlanningService
from backend.ai.service import AIModelError
from backend.db import connect_database
from backend.migrate import migrate_database
from support import credential_test_settings
from plan_test_support import NOW, draft

ORIGIN = 'http://localhost:5173'
MESSAGE = '下周六18:00打两个小时，东区体育馆，6号场优先，5号场备选。'


def ready(intent=None, evidence=None):
    return json.dumps({'status': 'ready', 'intent': intent or draft(
        target_date='2026-10-17', preferred_start_times=['18:00'],
        venue_preference='东区体育馆', court_preferences=['6号场', '5号场']),
        'questions': [], 'evidence': evidence if evidence is not None else {
            'target_date': '下周六', 'preferred_start_times': '18:00', 'duration_minutes': '两个小时',
            'venue_preference': '东区体育馆', 'court_preferences': '6号场优先，5号场备选'}}, ensure_ascii=False)


class FakeProvider:
    def __init__(self):
        self.content = ready()
        self.calls = []
        self.failure = None

    def chat(self, user_id, messages):
        self.calls.append((user_id, messages))
        if self.failure:
            raise self.failure
        return self.content, {'name': '合成模型', 'model': 'synthetic-model'}


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='planning-fake-')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'synthetic.sqlite3'
        migrate_database(self.path, 5000)
        self.app = create_app({**credential_test_settings(self.path), 'TESTING': True,
            'APP_ALLOWED_ORIGINS': ORIGIN, 'BOOKING_CURRENCY_CODE': 'CNY', 'BOOKING_CURRENCY_MINOR_UNIT_EXPONENT': '2'})
        with closing(connect_database(self.path, 5000)) as db:
            for user in ('a', 'b'):
                db.execute("INSERT INTO users(user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms) VALUES(?,?,?,'never-send-this-password','user','active',1,1)", (user,user,user))
        self.a, self.b = self.app.test_client(), self.app.test_client()
        self.headers = {}
        for user, client in (('a', self.a), ('b', self.b)):
            cookie, csrf = self.app.extensions['session_service'].create(user, NOW)
            client.set_cookie('yumao_session', cookie)
            self.headers[user] = {'Origin': ORIGIN, 'X-CSRF-Token': csrf}
        self.fake = FakeProvider()
        self.app.extensions['planning_service'] = PlanningService(self.app.extensions['plan_service'], self.fake)
        self.enterContext(patch('backend.api.planning.time.time_ns', return_value=NOW*1_000_000))
        self.network = self.enterContext(patch('requests.sessions.Session.request', side_effect=AssertionError('upstream forbidden')))

    def propose(self, message=MESSAGE, plan=None, client=None, user='a'):
        return (client or self.a).post('/api/planning/proposals', json={'message': message,
            'plan_id': plan['plan_id'] if plan else None, 'base_version': plan['version'] if plan else None}, headers=self.headers[user])

    def counts(self):
        with closing(connect_database(self.path,5000)) as db:
            return tuple(db.execute('SELECT (SELECT count(*) FROM booking_plans),(SELECT count(*) FROM booking_plan_revisions)').fetchone())

    def test_proposal_does_not_write_and_confirmation_uses_plan_service(self):
        response = self.propose()
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result['status'], 'ready')
        proposal = result['proposal']
        self.assertEqual(proposal['intent']['target_date'], '2026-10-17')
        self.assertFalse(proposal['booking_window']['can_query'])
        self.assertEqual(self.counts(), (0,0))
        saved = self.a.post('/api/plans', json={'intent':proposal['intent']}, headers=self.headers['a'])
        self.assertEqual(saved.status_code,201)
        self.assertEqual(self.counts(),(1,1))
        self.assertEqual(saved.get_json()['plan']['kind'],'unbound_draft')
        self.assertEqual(saved.get_json()['plan']['context']['preference_verification'],'unverified_manual')
        for field in ('can_book','can_pay','can_query_upstream','can_create_job'):
            self.assertFalse(proposal[field])
        self.network.assert_not_called()

    def test_edit_diff_history_and_cas_preserves_current_data(self):
        old = self.app.extensions['plan_service'].create_plan('a',draft(),NOW)
        intent = {**old['intent'], 'preferred_start_times':['19:00'], 'court_preferences':['5号场备选','6号场优先']}
        self.fake.content = ready(intent,{'preferred_start_times':'19:00','court_preferences':'5号场改为第一优先级'})
        response = self.propose('把开始时间改成19:00，5号场改为第一优先级。',old)
        self.assertEqual(response.status_code,200)
        proposal=response.get_json()['proposal']
        self.assertEqual({x['field'] for x in proposal['changes']},{'preferred_start_times','court_preferences'})
        self.assertEqual(proposal['before_intent'],old['intent'])
        payload={'base_version':proposal['base_version'],'intent':proposal['intent']}
        saved=self.a.patch('/api/plans/'+old['plan_id'],json=payload,headers=self.headers['a'])
        self.assertEqual(saved.get_json()['plan']['version'],2)
        self.assertEqual(self.a.patch('/api/plans/'+old['plan_id'],json=payload,headers=self.headers['a']).status_code,409)
        revisions=self.a.get('/api/plans/'+old['plan_id']+'/revisions').get_json()['revisions']
        self.assertEqual([r['revision_number'] for r in revisions],[2,1])
        self.assertEqual(revisions[1]['intent'],old['intent'])
        self.assertEqual(self.counts(),(1,2))

    def test_b_cannot_access_a_context_and_stale_generation_does_not_call_model(self):
        plan=self.app.extensions['plan_service'].create_plan('a',draft(),NOW)
        self.assertEqual(self.propose(plan=plan,client=self.b,user='b').status_code,404)
        self.assertEqual(self.fake.calls,[])
        self.app.extensions['plan_service'].update_plan('a',plan['plan_id'],1,draft(venue_preference='新意向'),NOW)
        self.assertEqual(self.propose(plan=plan).status_code,409)
        self.assertEqual(self.fake.calls,[])
        self.assertEqual(self.counts(),(1,2))

    def test_model_context_is_minimal_and_relative_date_server_owned(self):
        self.propose()
        user,messages=self.fake.calls[0]
        context=json.loads(messages[1]['content'])
        self.assertEqual(user,'a')
        self.assertEqual(set(context),{'user_request','business_date','relative_dates','context','current_intent'})
        self.assertEqual(context['business_date'],'2026-10-10')
        self.assertEqual(context['relative_dates']['下周六'],'2026-10-17')
        self.assertEqual(context['context']['timezone_name'],'Asia/Shanghai')
        self.assertNotIn('never-send-this-password',json.dumps(messages))
        self.assertNotIn('user_id',json.dumps(messages))
        self.assertNotIn('credential_id',json.dumps(messages))

    def test_missing_information_and_hallucinated_venue_return_questions(self):
        self.fake.content=json.dumps({'status':'needs_input','intent':None,'questions':['请补充场馆名称。'],'evidence':{}})
        result=self.propose('下周六18:00打两个小时，6号场优先。').get_json()
        self.assertEqual(result['status'],'needs_input');self.assertIsNone(result['proposal'])
        self.fake.content=ready()
        result=self.propose('下周六18:00打两个小时，6号场优先，5号场备选。').get_json()
        self.assertEqual(result['status'],'needs_input')
        self.assertIn('人工场馆偏好',result['questions'][0])
        self.assertEqual(self.counts(),(0,0))

    def test_bad_schema_cannot_create_plan_or_execution_capability(self):
        for intent in (draft(nodeid='invented'),draft(duration_minutes=True),draft(fallback_policy={'allow_any_court_in_venue':True}),draft(target_date='2026-02-30')):
            self.fake.content=ready(intent)
            result=self.propose().get_json()
            self.assertEqual(result['status'],'needs_input')
            self.assertIsNone(result['proposal'])
        self.assertEqual(self.counts(),(0,0))

    def test_incorrect_relative_date_and_unsupported_expansion_fail_closed(self):
        intent=json.loads(ready())['intent'];intent['target_date']='2026-10-18'
        self.fake.content=ready(intent)
        self.assertEqual(self.propose().get_json()['status'],'needs_input')
        intent=json.loads(ready())['intent'];intent['preferred_start_times']=['19:00']
        self.fake.content=ready(intent)
        self.assertEqual(self.propose().get_json()['status'],'needs_input')
        intent=json.loads(ready())['intent'];intent['fallback_policy']['allow_any_court_in_venue']=True
        self.fake.content=ready(intent)
        self.assertEqual(self.propose().get_json()['status'],'needs_input')
        self.assertEqual(self.counts(),(0,0))

    def test_malformed_model_outputs_are_safe(self):
        for content in ('not JSON','{"status":"ready","status":"ready"}','{"status":NaN}',ready()+'\nextra','x'*16385, json.dumps({'status':'unsupported','intent':{},'questions':[],'evidence':{}})):
            self.fake.content=content
            response=self.propose()
            self.assertEqual((response.status_code,response.get_json()['error']),(502,'invalid_model_proposal'))
        self.assertEqual(self.counts(),(0,0))

    def test_unsupported_request_and_sensitive_input_do_not_call_model(self):
        result=self.propose('帮我直接预约并付款。').get_json()
        self.assertEqual(result['status'],'unsupported')
        self.assertEqual(self.fake.calls,[])
        response=self.propose('Bearer '+'x'*32)
        self.assertEqual(response.status_code,400)
        self.assertNotIn('x'*32,response.get_data(as_text=True))
        self.assertEqual(self.fake.calls,[])
        self.assertEqual(self.a.post('/api/jobs',json={},headers=self.headers['a']).status_code,404)

    def test_model_unavailable_does_not_break_manual_create(self):
        for code,status in (('provider_not_configured',409),('provider_timeout',504),('provider_auth_failed',502)):
            self.fake.failure=AIModelError(code,status)
            response=self.propose()
            self.assertEqual((response.status_code,response.get_json()['error']),(status,code))
        self.assertEqual(self.a.post('/api/plans',json={'intent':draft()},headers=self.headers['a']).status_code,201)

    def test_session_csrf_body_and_unknown_fields(self):
        self.assertEqual(self.app.test_client().post('/api/planning/proposals',json={},headers={'Origin':ORIGIN}).status_code,401)
        self.assertEqual(self.a.post('/api/planning/proposals',json={},headers={'Origin':ORIGIN}).status_code,403)
        for body in ({'message':MESSAGE},{'message':MESSAGE,'plan_id':None,'base_version':None,'token':'forbidden'}, {'message':True,'plan_id':None,'base_version':None}, {'message':MESSAGE,'plan_id':None,'base_version':1}):
            self.assertEqual(self.a.post('/api/planning/proposals',json=body,headers=self.headers['a']).status_code,400)
        self.assertEqual(self.a.post('/api/planning/proposals',data='x'*16385,content_type='application/json',headers=self.headers['a']).status_code,413)

    def test_saved_timezone_is_used_for_edit(self):
        from backend.booking_window import BookingWindowPolicy
        plan=self.app.extensions['plan_service'].create_plan('a',draft(),NOW)
        self.app.extensions['plan_service'].active_context = type(self.app.extensions['plan_service'].active_context)('UTC',None,None)
        self.app.extensions['plan_service'].policy=BookingWindowPolicy('UTC')
        self.fake.content=ready(plan['intent'],{})
        response=self.propose('保留当前计划。',plan)
        self.assertEqual(response.status_code,200)
        context=json.loads(self.fake.calls[0][1][1]['content'])
        self.assertEqual(context['context']['timezone_name'],'Asia/Shanghai')

