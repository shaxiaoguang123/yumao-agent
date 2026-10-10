import importlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.booking_window import BookingWindowPolicy
from backend.db import connect_database
from backend.migrate import migrate_database
from plan_test_support import NOW, draft


class PlanServiceTests(unittest.TestCase):
    def setUp(self):
        module=importlib.import_module('backend.plans.service')
        self.error=module.PlanError
        self.tmp=tempfile.TemporaryDirectory(prefix='plan-service-')
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'new.sqlite3'
        migrate_database(self.path,5000)
        db=connect_database(self.path,5000)
        for name in ('a','b'):
            db.execute("INSERT INTO users (user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms) VALUES (?,?,?,'synthetic','user','active',1,1)",(name,name,name))
        db.close()
        self.service=module.PlanService(self.path,5000,BookingWindowPolicy('Asia/Shanghai'),'CNY',2)

    def test_roundtrip_immutable_history_noop_and_stale_conflict(self):
        first=self.service.create_plan('a',draft(),NOW)
        self.assertEqual(first['version'],1)
        plan_id=first['plan_id']
        self.assertEqual(self.service.list_plans('a',NOW)[0]['plan_id'],plan_id)
        self.assertEqual(self.service.get_plan('a',plan_id,NOW),first)
        same=self.service.update_plan('a',plan_id,1,draft(),NOW+1)
        self.assertEqual(same['current_revision_id'],first['current_revision_id'])
        second=self.service.update_plan('a',plan_id,1,draft(venue_preference='编辑后的人工场馆'),NOW+2)
        self.assertEqual(second['version'],2)
        history=self.service.list_revisions('a',plan_id,NOW)
        self.assertEqual([r['revision_number'] for r in history],[2,1])
        self.assertEqual(history[1]['intent']['venue_preference'],'人工意向场馆')
        for payload in (draft(venue_preference='编辑后的人工场馆'),{'invalid':'payload'}):
            with self.assertRaises(self.error) as caught: self.service.update_plan('a',plan_id,1,payload,NOW+3)
            self.assertEqual(caught.exception.status,409)
        self.assertEqual(len(self.service.list_revisions('a',plan_id)),2)

    def test_every_lookup_is_owned_and_missing_looks_identical(self):
        p=self.service.create_plan('a',draft(),NOW)['plan_id']
        self.assertEqual(self.service.list_plans('b'),[])
        for identifier in (p,'missing'):
            for operation in (lambda:self.service.get_plan('b',identifier),lambda:self.service.list_revisions('b',identifier),lambda:self.service.update_plan('b',identifier,1,draft(),NOW)):
                with self.assertRaises(self.error) as caught: operation()
                self.assertEqual((caught.exception.code,caught.exception.status),('plan_not_found',404))

    def test_concurrent_writers_have_one_winner(self):
        p=self.service.create_plan('a',draft(),NOW)['plan_id']
        def update(name):
            try:return self.service.update_plan('a',p,1,draft(venue_preference=name),NOW)['version']
            except self.error as e:return e.status
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(update,('first','second')))
        self.assertEqual(sorted(results),[2,409])
        self.assertEqual(len(self.service.list_revisions('a',p)),2)

    def test_failed_pointer_advance_rolls_back_revision_insert(self):
        p=self.service.create_plan('a',draft(),NOW)['plan_id']
        db=connect_database(self.path,5000)
        db.execute("CREATE TRIGGER synthetic_reject_advance BEFORE UPDATE ON booking_plans BEGIN SELECT RAISE(ABORT,'synthetic failure'); END;")
        db.close()
        with self.assertRaises(sqlite3.IntegrityError): self.service.update_plan('a',p,1,draft(venue_preference='changed'),NOW)
        self.assertEqual(self.service.get_plan('a',p)['version'],1)
        self.assertEqual(len(self.service.list_revisions('a',p)),1)

    def test_settings_changes_preserve_context_and_disable_calendar_query(self):
        first=self.service.create_plan('a',draft(target_date='2026-10-12',price_ceiling_minor=1234),NOW)
        changed=importlib.import_module('backend.plans.service').PlanService(self.path,5000,BookingWindowPolicy('UTC'),'USD',0)
        edited=changed.update_plan('a',first['plan_id'],1,draft(target_date='2026-10-12',price_ceiling_minor=1500),NOW)
        self.assertEqual(edited['context'],first['context'])
        self.assertEqual(edited['booking_window']['reason_code'],'timezone_context_mismatch')
        self.assertFalse(edited['booking_window']['can_query'])
        self.assertFalse(edited['can_create_job'])
        self.assertEqual(changed.create_plan('a',draft(),NOW)['context']['currency_code'],'USD')
        self.assertTrue(first['booking_window']['can_query'])
        for key in ('can_query_upstream','can_book','can_pay','can_create_job'): self.assertFalse(first[key])

    def test_invalid_base_version_is_not_an_integer_boolean(self):
        p=self.service.create_plan('a',draft(),NOW)['plan_id']
        for base in (True,False,1.0,'1',0,-1):
            with self.subTest(base=base):
                with self.assertRaises(self.error) as caught:self.service.update_plan('a',p,base,draft(),NOW)
                self.assertEqual(caught.exception.status,400)
