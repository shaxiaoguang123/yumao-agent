import copy
import importlib
import unittest
from datetime import date
from plan_test_support import draft


class DraftValidationTests(unittest.TestCase):
    def setUp(self):
        self.validation = importlib.import_module('backend.plans.validation')
        models = importlib.import_module('backend.plans.models')
        self.context = models.PlanInterpretationContext('Asia/Shanghai','CNY',2)

    def parse(self, payload, context=None):
        return self.validation.parse_manual_intent(payload, today_business_date=date(2026,10,10), context=context or self.context)

    def test_normalization_order_and_immutable_canonical_hash(self):
        a = self.parse(draft(venue_preference=' 人工意向场馆 '))
        b = self.parse(draft())
        self.assertEqual(a.canonical_json,b.canonical_json)
        self.assertEqual(a.sha256,b.sha256)
        self.assertEqual(len(a.sha256),64)
        self.assertEqual(a.value['intent']['preferred_start_times'], ['18:00','19:00'])
        self.assertEqual(a.value['kind'],'unbound_draft')
        self.assertIsNone(a.value['context']['catalog_version'])
        a.value['intent']['venue_preference']='changed copy'
        self.assertEqual(a.value['intent']['venue_preference'],'人工意向场馆')

    def test_strict_types_counts_dates_and_unknown_fields(self):
        cases = [draft(duration_minutes=x) for x in (True,False,30.0,'60',0,31,270)]
        cases += [draft(preferred_start_times=x) for x in ([],['18:00']*2,['9:00'],['24:00'],['10:00']*9,'18:00')]
        cases += [draft(target_date=x) for x in ('2026-02-30','2026-10-09','20261020',True)]
        cases += [draft(venue_preference=x) for x in ('',' '*2,'a'*201,{},'bad\x00text','bad\ud800')]
        cases += [draft(court_preferences=x) for x in ([],['same',' same '],['a'*101],['a']*17,[True],{})]
        cases += [draft(price_ceiling_minor=x) for x in (True,False,1.5,-1,9007199254740992,'100')]
        for key in ('nodeid','coordinatesList','token','credential_id','venue_key','booktype','appointmentType','context','catalog_version','execute'):
            cases.append(draft(**{key:'untrusted'}))
        for case in cases:
            with self.subTest(case=list(case.items())[-1]):
                with self.assertRaises(self.validation.IntentValidationError):
                    self.parse(case)

    def test_fallback_types_range_baseline_and_same_day(self):
        cases = [
            {'allow_any_court_in_venue':1,'allow_time_shift':False,'allowed_start_time_range':None},
            {'allow_any_court_in_venue':False,'allow_time_shift':'false','allowed_start_time_range':None},
            {'allow_any_court_in_venue':False,'allow_time_shift':True,'allowed_start_time_range':None},
            {'allow_any_court_in_venue':False,'allow_time_shift':False,'allowed_start_time_range':{'start':'18:00','end':'19:00'}},
            {'allow_any_court_in_venue':False,'allow_time_shift':True,'allowed_start_time_range':{'start':'18:30','end':'19:00'}},
            {'allow_any_court_in_venue':False,'allow_time_shift':True,'allowed_start_time_range':{'start':'18:00','end':'23:00'}},
            {'allow_any_court_in_venue':False,'allow_time_shift':True,'allowed_start_time_range':{'start':'20:00','end':'18:00'}},
        ]
        for fallback in cases:
            with self.subTest(fallback=fallback):
                with self.assertRaises(self.validation.IntentValidationError): self.parse(draft(fallback_policy=fallback))
        valid={'allow_any_court_in_venue':True,'allow_time_shift':True,'allowed_start_time_range':{'start':'17:00','end':'20:00'}}
        self.assertEqual(self.parse(draft(court_preferences=[],fallback_policy=valid)).value['intent']['court_preferences'],[])
        with self.assertRaises(self.validation.IntentValidationError): self.parse(draft(preferred_start_times=['23:00']))

    def test_price_requires_saved_currency_and_exact_safe_integer(self):
        models=importlib.import_module('backend.plans.models')
        with self.assertRaises(self.validation.IntentValidationError):
            self.parse(draft(price_ceiling_minor=0), models.PlanInterpretationContext('Asia/Shanghai',None,None))
        self.assertEqual(self.parse(draft(price_ceiling_minor=9007199254740991)).value['intent']['price_ceiling_minor'],9007199254740991)
