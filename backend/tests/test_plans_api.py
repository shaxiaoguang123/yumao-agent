import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.app import create_app
from backend.db import connect_database
from backend.migrate import migrate_database
from support import credential_test_settings
from plan_test_support import NOW, draft

ORIGIN='http://localhost:5173'


class PlansApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='plans-api-')
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'new.sqlite3'
        migrate_database(self.path,5000)
        self.app=create_app({**credential_test_settings(self.path),'TESTING':True,'APP_ALLOWED_ORIGINS':ORIGIN,'BOOKING_CURRENCY_CODE':'CNY','BOOKING_CURRENCY_MINOR_UNIT_EXPONENT':'2'})
        with closing(connect_database(self.path,5000)) as db:
            for user in ('a','b'):
                db.execute("INSERT INTO users (user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms) VALUES (?,?,?,'synthetic','user','active',1,1)",(user,user,user))
        self.a,self.b=self.app.test_client(),self.app.test_client()
        self.headers={}
        for user,client in (('a',self.a),('b',self.b)):
            cookie,csrf=self.app.extensions['session_service'].create(user,NOW)
            client.set_cookie('yumao_session',cookie)
            self.headers[user]={'Origin':ORIGIN,'X-CSRF-Token':csrf}
        self.network=self.enterContext(patch('requests.sessions.Session.request',side_effect=AssertionError('upstream forbidden')))

    def create(self):
        response=self.a.post('/api/plans',json={'intent':draft()},headers=self.headers['a'])
        self.assertEqual(response.status_code,201)
        return response.get_json()['plan']

    def test_actual_database_crud_and_history(self):
        p=self.create(); identifier=p['plan_id']
        with closing(connect_database(self.path,5000)) as db:
            self.assertEqual(db.execute('SELECT version FROM booking_plans WHERE user_id=? AND plan_id=?',('a',identifier)).fetchone()[0],1)
        self.assertEqual(self.a.get('/api/plans').get_json()['plans'][0]['plan_id'],identifier)
        self.assertEqual(self.a.get(f'/api/plans/{identifier}').get_json()['plan'],p)
        response=self.a.patch(f'/api/plans/{identifier}',json={'base_version':1,'intent':draft(venue_preference='新版人工场馆')},headers=self.headers['a'])
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()['plan']['version'],2)
        history=self.a.get(f'/api/plans/{identifier}/revisions').get_json()['revisions']
        self.assertEqual([r['revision_number'] for r in history],[2,1])
        self.assertEqual(history[1]['intent']['venue_preference'],'人工意向场馆')
        for key in ('can_book','can_pay','can_create_job','can_query_upstream'):self.assertIs(p[key],False)
        self.network.assert_not_called()

    def test_security_session_csrf_and_origin(self):
        self.assertEqual(self.app.test_client().get('/api/plans').status_code,401)
        self.assertEqual(self.a.post('/api/plans',json={'intent':draft()},headers={'Origin':ORIGIN}).status_code,403)
        self.assertEqual(self.a.post('/api/plans',json={'intent':draft()},headers={**self.headers['a'],'Origin':'https://wrong.invalid'}).status_code,403)
        self.assertEqual(self.app.test_client().get('/api/booking-window?target_date=2026-10-12').status_code,401)

    def test_missing_and_cross_user_reads_writes_and_history_are_identical(self):
        identifier=self.create()['plan_id']
        for suffix in ('','/revisions'):
            foreign=self.b.get(f'/api/plans/{identifier}{suffix}')
            absent=self.b.get(f'/api/plans/missing{suffix}')
            self.assertEqual((foreign.status_code,foreign.get_json()),(absent.status_code,absent.get_json()))
            self.assertEqual(foreign.status_code,404)
        response=self.b.patch(f'/api/plans/{identifier}',json={'base_version':1,'intent':draft()},headers=self.headers['b'])
        self.assertEqual(response.status_code,404)
        self.assertEqual(self.b.get('/api/plans').get_json()['plans'],[])

    def test_stale_patch_does_not_append_or_override(self):
        identifier=self.create()['plan_id']
        body={'base_version':1,'intent':draft(venue_preference='new')}
        self.assertEqual(self.a.patch(f'/api/plans/{identifier}',json=body,headers=self.headers['a']).status_code,200)
        response=self.a.patch(f'/api/plans/{identifier}',json=body,headers=self.headers['a'])
        self.assertEqual((response.status_code,response.get_json()['error']),(409,'plan_version_conflict'))
        self.assertEqual(len(self.a.get(f'/api/plans/{identifier}/revisions').get_json()['revisions']),2)

    def test_body_limit_invalid_json_duplicates_and_envelope(self):
        for raw in ('[]','{','{"intent":NaN}','{"intent":{},"intent":{}}','{"intent":'+('['*1000)+(']'*1000)+'}'):
            with self.subTest(raw=raw[:20]):
                self.assertEqual(self.a.post('/api/plans',data=raw,content_type='application/json',headers=self.headers['a']).status_code,400)
        self.assertEqual(self.a.post('/api/plans',data='x'*16385,content_type='application/json',headers=self.headers['a']).status_code,413)
        self.assertEqual(self.a.post('/api/plans',json={'intent':draft(),'nodeid':'forbidden'},headers=self.headers['a']).status_code,400)
        self.assertEqual(self.a.post('/api/plans',data='{}',content_type='text/plain',headers=self.headers['a']).status_code,400)

    def test_validation_fields_are_safe_and_execution_inputs_rejected(self):
        response=self.a.post('/api/plans',json={'intent':draft(duration_minutes=True)},headers=self.headers['a'])
        self.assertEqual(response.status_code,400)
        self.assertIn('duration_minutes',response.get_json()['fields'])
        for key in ('token','nodeid','coordinatesList','execute','catalog_version'):
            response=self.a.post('/api/plans',json={'intent':draft(**{key:'synthetic-private'})},headers=self.headers['a'])
            self.assertEqual(response.status_code,400)
            self.assertNotIn('synthetic-private',response.get_data(as_text=True))
        self.assertEqual(self.a.post('/api/jobs',json={},headers=self.headers['a']).status_code,404)
        self.network.assert_not_called()

    def test_window_is_server_calendar_only_and_far_date_is_savable(self):
        with patch('backend.api.booking_window._now_utc_ms',return_value=NOW):
            inside=self.a.get('/api/booking-window?target_date=2026-10-12').get_json()
            distant=self.a.get('/api/booking-window?target_date=2026-10-20').get_json()
            self.assertEqual(inside['queryable_target_dates'],['2026-10-10','2026-10-11','2026-10-12'])
            self.assertTrue(inside['can_query'])
            self.assertEqual(inside['query_open_at_utc_ms'],1791561600000)
            self.assertFalse(distant['can_query'])
            self.assertFalse(inside['estimated_open_is_confirmed'])
            for key in ('can_book','can_pay','can_query_upstream','can_create_job'):self.assertFalse(inside[key])
        self.create()
        self.network.assert_not_called()

    def test_catalog_unconfigured_and_invalid_window_parameters(self):
        response=self.a.get('/api/plans/options').get_json()
        self.assertEqual(response['catalog_status'],'not_configured')
        self.assertEqual(response['venues'],[])
        self.assertIsNone(response['context']['catalog_version'])
        for query in ('target_date=bad','target_date=0001-01-01','nodeid=bad','target_date=2026-10-12&target_date=2026-10-13'):
            self.assertEqual(self.a.get('/api/booking-window?'+query).status_code,400)
        self.assertEqual(self.a.get('/api/plans/options?catalog_version=fake').status_code,400)
