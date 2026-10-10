import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

from backend.app import create_app
from backend.availability_matching.models import AvailabilitySlot as Slot, AvailabilitySnapshot as Snapshot, AvailabilityError
from backend.availability_matching.matcher import AvailabilityMatcher
from backend.availability_matching.synthetic import SyntheticAvailabilitySource
from backend.db import connect_database
from backend.migrate import migrate_database
from support import credential_test_settings
from plan_test_support import NOW, draft

ORIGIN='http://localhost:5173'


def plan(**changes):
    return {'intent':draft(venue_preference='合成示例场馆',court_preferences=['6号场','5号场'],**changes),
            'context':{'timezone_name':'Asia/Shanghai','currency_code':'CNY','currency_minor_unit_exponent':2}}


def snapshot(slots, **changes):
    fields={'target_date':'2026-10-20','timezone_name':'Asia/Shanghai','venue_name':'合成示例场馆',
            'slots':tuple(slots),'source':'synthetic-test','simulation':True,'currency_code':'CNY','currency_minor_unit_exponent':2}
    return Snapshot(**{**fields,**changes})


def hourly(court='6号场',price=1000,status='available'):
    return [Slot(court,f'{hour}:00',f'{hour+1}:00',status,price) for hour in (18,19,20)]


class AvailabilityMatcherTests(unittest.TestCase):
    def setUp(self): self.matcher=AvailabilityMatcher()

    def codes(self,result): return {r['code'] for r in result['reason_summary']}

    def test_complete_duration_price_and_preference_order_not_input_or_price_order(self):
        slots=hourly('5号场',100)+hourly('6号场',1000)
        result=self.matcher.match(plan(),snapshot(slots))
        self.assertEqual([(c['start_time'],c['court_name']) for c in result['candidates']],
                         [('18:00','6号场'),('18:00','5号场'),('19:00','6号场'),('19:00','5号场')])
        first=result['candidates'][0]
        self.assertEqual((first['end_time'],first['duration_minutes'],first['slot_count']),('20:00',120,2))
        self.assertEqual(first['price']['total_minor'],2000)
        self.assertFalse(first['uses_fallback']);self.assertTrue(result['candidates'][1]['fallback']['lower_priority_court'])
        self.assertTrue(result['candidates'][2]['fallback']['lower_priority_time'])
        random.Random(42).shuffle(slots)
        self.assertEqual(result,self.matcher.match(plan(),snapshot(slots)))
        reversed_times=self.matcher.match(plan(preferred_start_times=['19:00','18:00']),snapshot(slots))
        self.assertEqual(reversed_times['candidates'][0]['start_time'],'19:00')

    def test_partial_occupancy_uses_only_explicit_backup_and_unknown_blocks(self):
        slots=hourly()+hourly('5号场')
        slots[1]=replace(slots[1],status='unavailable')
        result=self.matcher.match(plan(),snapshot(slots))
        self.assertEqual(result['candidates'][0]['court_name'],'5号场')
        self.assertIn('unavailable',self.codes(result))
        result=self.matcher.match(plan(),snapshot([replace(s,status='unknown') for s in hourly()]))
        self.assertFalse(result['candidates']);self.assertIn('availability_unknown',self.codes(result))

    def test_gaps_missing_boundaries_and_indivisible_atoms_do_not_create_coverage(self):
        for slots in ([hourly()[0],hourly()[2]],[Slot('6号场','18:00','21:00','available',1000)],
                      [Slot('6号场','18:00','18:30','available',1000),Slot('6号场','18:45','20:00','available',1000)]):
            result=self.matcher.match(plan(preferred_start_times=['18:00']),snapshot(slots))
            self.assertFalse(result['candidates']);self.assertIn('time_discontinuous',self.codes(result))

    def test_other_court_requires_authorization(self):
        snap=snapshot(hourly('模拟其他场地'))
        result=self.matcher.match(plan(),snap)
        self.assertFalse(result['candidates']);self.assertIn('court_not_authorized',self.codes(result))
        policy={'allow_any_court_in_venue':True,'allow_time_shift':False,'allowed_start_time_range':None}
        result=self.matcher.match(plan(fallback_policy=policy),snap)
        self.assertEqual(len(result['candidates']),2)
        self.assertTrue(result['candidates'][0]['fallback']['other_court'])

    def test_time_shift_requires_explicit_range_and_exact_starts_rank_first(self):
        slots=[Slot('6号场',start,end,'available',1000) for start,end in
               [('17:30','18:00'),('18:00','18:30'),('18:30','19:00'),('19:00','19:30'),('19:30','20:00'),('20:00','20:30'),('20:30','21:00')]]
        result=self.matcher.match(plan(preferred_start_times=['18:00'],duration_minutes=60),snapshot(slots))
        self.assertEqual([c['start_time'] for c in result['candidates']],['18:00'])
        policy={'allow_any_court_in_venue':False,'allow_time_shift':True,'allowed_start_time_range':{'start':'18:00','end':'19:30'}}
        result=self.matcher.match(plan(preferred_start_times=['19:00','18:00'],duration_minutes=60,fallback_policy=policy),snapshot(slots))
        starts=[c['start_time'] for c in result['candidates']]
        self.assertEqual(starts[:2],['19:00','18:00'])
        self.assertEqual(set(starts),{'18:00','18:30','19:00','19:30'})
        self.assertTrue(all(c['fallback']['time_shift'] for c in result['candidates'][2:]))

    def test_budget_boundary_unknown_prices_and_exact_currency_context(self):
        snap=snapshot(hourly())
        self.assertEqual(len(self.matcher.match(plan(price_ceiling_minor=2000),snap)['candidates']),2)
        result=self.matcher.match(plan(price_ceiling_minor=1999),snap)
        self.assertFalse(result['candidates']);self.assertIn('over_budget',self.codes(result))
        for unknown in (snapshot(hourly(price=None)),snapshot(hourly(),currency_code=None,currency_minor_unit_exponent=None)):
            result=self.matcher.match(plan(price_ceiling_minor=3000),unknown)
            self.assertFalse(result['candidates']);self.assertIn('price_unconfirmed',self.codes(result))
            no_budget=self.matcher.match(plan(),unknown)
            self.assertIsNone(no_budget['candidates'][0]['price'])
        for incompatible in (replace(snap,currency_code='USD'),replace(snap,currency_minor_unit_exponent=0)):
            result=self.matcher.match(plan(price_ceiling_minor=3000),incompatible)
            self.assertFalse(result['candidates']);self.assertIn('currency_mismatch',self.codes(result))
        self.assertEqual(self.matcher.match(plan(price_ceiling_minor=0),snapshot(hourly(price=0)))['candidates'][0]['price']['total_minor'],0)

    def test_wrong_scope_date_timezone_and_empty_snapshot_are_explained(self):
        for key,value,code in [('target_date','2026-10-21','date_mismatch'),('timezone_name','UTC','timezone_mismatch'),('venue_name','其他场馆','venue_mismatch')]:
            result=self.matcher.match(plan(),snapshot(hourly(),**{key:value}))
            self.assertFalse(result['candidates']);self.assertIn(code,self.codes(result))
        self.assertIn('no_slots',self.codes(self.matcher.match(plan(),snapshot([]))))

    def test_snapshot_rejects_ambiguous_overlap_duplicates_types_and_status_codes(self):
        for slots in (hourly()+[hourly()[0]],hourly()+[Slot('6号场','18:30','19:30','available')]):
            with self.assertRaises(AvailabilityError): snapshot(slots)
        for args in [('6号场','18:00','19:00','1',100),('6号场','18:00','19:00','available',True),('6号场','19:00','18:00','available',100)]:
            with self.assertRaises(AvailabilityError): Slot(*args)
        with self.assertRaises(AvailabilityError): snapshot(hourly(),simulation='true')
        with self.assertRaises(AvailabilityError): snapshot(hourly(),currency_minor_unit_exponent=True)

    def test_midnight_endpoint_and_different_atom_lengths(self):
        slots=[Slot('6号场','22:00','23:00','available',100),Slot('6号场','23:00','23:30','available',50),Slot('6号场','23:30','24:00','available',50)]
        result=self.matcher.match(plan(preferred_start_times=['22:00']),snapshot(slots))
        self.assertEqual(result['candidates'][0]['end_time'],'24:00')
        self.assertEqual(result['candidates'][0]['price']['total_minor'],200)

    def test_normalized_non_simulated_snapshot_reuses_matcher_but_never_grants_execution(self):
        result=self.matcher.match(plan(),snapshot(hourly(),simulation=False,source='normalized-adapter-example'))
        self.assertEqual(result['source']['trust_state'],'normalized_unverified')
        for flag in ('can_book','can_pay','can_create_job','can_query_upstream'): self.assertIs(result[flag],False)

    def test_local_clock_contract_rejects_dst_gaps_folds_and_offset_change_days(self):
        for target in ('2026-03-08','2026-11-01'):
            with self.assertRaises(AvailabilityError) as failure:
                snapshot(hourly(),target_date=target,timezone_name='America/New_York')
            self.assertEqual(failure.exception.code,'availability_timezone_day_unsupported')

    def test_synthetic_scenarios_reproducible_and_do_not_bind_manual_labels(self):
        source=SyntheticAvailabilitySource();p=plan()
        self.assertEqual(source.snapshot(p,'complete'),source.snapshot(p,'complete'))
        self.assertIsNone(source.snapshot(p,'complete').venue_semantic_key)
        partial=self.matcher.match(p,source.snapshot(p,'partially_occupied'))
        self.assertEqual(partial['candidates'][0]['court_name'],'5号场')
        self.assertFalse(self.matcher.match(p,source.snapshot(p,'no_match'))['candidates'])
        pricey=plan(price_ceiling_minor=10000)
        self.assertIn('over_budget',self.codes(self.matcher.match(pricey,source.snapshot(pricey,'high_price'))))
        self.assertIn('price_unconfirmed',self.codes(self.matcher.match(pricey,source.snapshot(pricey,'price_unknown'))))


class SimulationApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='availability-simulation-');self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'fresh.sqlite3';migrate_database(self.path,5000)
        self.config={**credential_test_settings(self.path),'TESTING':True,'APP_ENV':'development','APP_ALLOWED_ORIGINS':ORIGIN,
                     'AVAILABILITY_SIMULATION_ENABLED':'true','BOOKING_CURRENCY_CODE':'CNY','BOOKING_CURRENCY_MINOR_UNIT_EXPONENT':'2'}
        self.app=create_app(self.config)
        with closing(connect_database(self.path,5000)) as db:
            for user in ('a','b'):
                db.execute("INSERT INTO users(user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms) VALUES(?,?,?,'synthetic','user','active',1,1)",(user,user,user))
        self.a,self.b=self.app.test_client(),self.app.test_client();self.headers={}
        for user,client in (('a',self.a),('b',self.b)):
            cookie,csrf=self.app.extensions['session_service'].create(user,NOW);client.set_cookie('yumao_session',cookie)
            self.headers[user]={'Origin':ORIGIN,'X-CSRF-Token':csrf}
        self.saved=self.app.extensions['plan_service'].create_plan('a',plan()['intent'],NOW)
        self.endpoint='/api/availability/simulation/plans/'+self.saved['plan_id']
        self.network=self.enterContext(patch('requests.sessions.Session.request',side_effect=AssertionError('real HTTP forbidden')))

    def match(self,scenario='complete',body=None,client=None,user='a'):
        return (client or self.a).post(self.endpoint,json=body or {'base_version':1,'scenario':scenario},headers=self.headers[user])

    def test_owned_saved_plan_matching_is_read_only_and_explicitly_synthetic(self):
        self.assertTrue(self.a.get('/api/availability/simulation/options').get_json()['enabled'])
        result=self.match().get_json()
        self.assertTrue(result['simulation']);self.assertEqual(result['source']['trust_state'],'synthetic')
        self.assertEqual(result['base_version'],1);self.assertEqual(result['candidates'][0]['court_name'],'6号场')
        self.assertEqual(result,self.match().get_json())
        with closing(connect_database(self.path,5000)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM booking_plan_revisions').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],6)
        self.network.assert_not_called()

    def test_cross_user_and_missing_plan_are_identical_and_do_not_call_source(self):
        source=self.app.extensions['availability_simulation_service'].source
        with patch.object(source,'snapshot',side_effect=AssertionError('must not read unauthorized context')):
            other=self.match(client=self.b,user='b')
            missing=self.b.post('/api/availability/simulation/plans/missing',json={'base_version':1,'scenario':'complete'},headers=self.headers['b'])
            self.assertEqual((other.status_code,other.get_json()),(missing.status_code,missing.get_json()))
            self.assertEqual(other.status_code,404)

    def test_session_csrf_unknown_fields_body_bounds_and_stale_version(self):
        self.assertEqual(self.app.test_client().get('/api/availability/simulation/options').status_code,401)
        self.assertEqual(self.a.post(self.endpoint,json={},headers={'Origin':ORIGIN}).status_code,403)
        for body in ({'base_version':True,'scenario':'complete'},{'base_version':1,'scenario':'real'},
                     {'base_version':1,'scenario':'complete','intent':self.saved['intent']},{'base_version':1,'scenario':'complete','nodeid':'forbidden'}):
            self.assertEqual(self.match(body=body).status_code,400)
        self.assertEqual(self.a.post(self.endpoint,data='x'*16385,content_type='application/json',headers=self.headers['a']).status_code,413)
        self.assertEqual(self.match(body={'base_version':2,'scenario':'complete'}).status_code,409)

    def test_production_and_default_development_do_not_serve_simulation(self):
        for config in ({**self.config,'APP_ENV':'production'},{**self.config,'AVAILABILITY_SIMULATION_ENABLED':'false'}):
            app=create_app(config);client=app.test_client()
            cookie,csrf=app.extensions['session_service'].create('a',NOW);client.set_cookie('yumao_session',cookie)
            self.assertFalse(client.get('/api/availability/simulation/options').get_json()['enabled'])
            response=client.post(self.endpoint,json={'base_version':1,'scenario':'complete'},headers={'Origin':ORIGIN,'X-CSRF-Token':csrf})
            self.assertEqual(response.get_json()['error'],'simulation_not_enabled')

    def test_result_rejected_when_plan_changes_during_calculation_or_source_is_not_simulation(self):
        service=self.app.extensions['availability_simulation_service'];original=service.source.snapshot
        def change(plan,scenario):
            self.app.extensions['plan_service'].update_plan('a',plan['plan_id'],1,{**plan['intent'],'venue_preference':'新人工标签'},NOW)
            return original(plan,scenario)
        with patch.object(service.source,'snapshot',side_effect=change): self.assertEqual(self.match().status_code,409)
        with patch.object(service.source,'snapshot',return_value=replace(original(self.saved,'complete'),simulation=False)):
            self.assertEqual(self.match(body={'base_version':2,'scenario':'complete'}).status_code,503)
