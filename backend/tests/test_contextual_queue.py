"""Deterministic product regressions; these doubles do not measure live model quality."""
import json
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from test_planning import Base
from backend.ai.queue_draft import deserialize_draft
from backend.ai.planning import assistant_history_entry
from backend.plans.manual_queue import automatic_queue_schedule


class ContextualQueueTests(Base):
    def start(self, message='10月26日只抢2小时，14-16，1号和2号场'):
        self.message, self.answers, self.asked = message, [], []
        self.current = self.result(message)
        self.assertIn(self.current['status'], ('ready', 'needs_input'), self.current)
        return self.current

    def turn(self, text, updates=(), *, unresolved=(), action='continue', fields=(), asking=None, question='', kind='answer', reply='', next_action=None):
        self.provider.turn_replies = [json.dumps({
            'kind': kind, 'updates': list(updates), 'unresolved': list(unresolved), 'reply': reply,
            'next_field': asking, 'next_question': question,
            'dialogue_action': {'type': action, 'fields': list(fields), 'evidence': text if action != 'continue' else ''},
            'next_action': next_action or ('ask' if asking else 'preview'), 'dialogue_focus': asking,
        }, ensure_ascii=False)]
        self.asked.append(self.current['conversation']['asking'])
        self.answers.append(text)
        response = self.post(self.message, answers=list(self.answers), asked_fields=list(self.asked), conversation_id=self.current['conversation_id'])
        self.assertEqual(response.status_code, 200, response.get_json())
        self.current = response.get_json()
        return self.current

    @staticmethod
    def update(field, operation, value, evidence):
        return {'field': field, 'operation': operation, 'value': value, 'evidence': evidence}

    def state(self):
        return self.app.extensions['planning_conversation_store'].get(self.current['conversation_id'], 'a', 'cred-a')['agent_state']

    def test_edit_a_historical_field_then_resume_the_unfinished_flow(self):
        self.start('10月26日只抢2小时，14-16')
        self.assertEqual(self.current['conversation']['asking'], 'courts_2h')
        editing = self.turn('先改一下日期', action='begin_edit', fields=['target_date'], asking='target_date', question='日期改成哪一天？例如10月28日。')
        self.assertEqual(editing['conversation']['asking'], 'target_date')
        self.assertEqual(editing['conversation']['pending_edit']['resume_focus'], 'courts_2h')
        changed = self.turn('改成明天', [self.update('target_date', 'set', '2026-10-11', '改成明天')])
        self.assertEqual(changed['conversation']['asking'], 'courts_2h')
        self.assertIsNone(changed['conversation']['pending_edit'])
        self.assertEqual(deserialize_draft(self.state()['draft']).dates, (date(2026, 10, 11),))

    def test_cancel_partial_edit_restores_only_its_fields(self):
        self.start()
        self.turn('修改2小时时段和场地', action='begin_edit', fields=['windows_2h', 'courts_2h'], asking='windows_2h', question='时段想改成什么？例如18-20。')
        partial = self.turn('时段改成18-20', [self.update('windows_2h', 'replace', [{'start':'18:00','end':'20:00'}], '改成18-20')])
        self.assertEqual(partial['conversation']['pending_edit']['remaining'], ['courts_2h'])
        restored = self.turn('日期改为10月28日，取消这次修改', [self.update('target_date', 'set', '2026-10-28', '改为10月28日')], action='cancel_edit')
        self.assertEqual(restored['status'], 'ready')
        self.assertEqual(restored['proposal']['target_date'], '2026-10-28')
        self.assertEqual([(e['start_time'], e['court_preference']) for e in restored['proposal']['entries']], [('14:00','1号场'),('14:00','2号场')])
        self.assertIsNone(restored['conversation']['pending_edit'])

    def test_same_field_compound_operations_and_idempotent_undo(self):
        self.start()
        changed = self.turn('去掉1号场，再加4号场', [self.update('courts_2h','remove',[1],'去掉1号场'), self.update('courts_2h','add',[4],'再加4号场')])
        self.assertEqual([e['court_preference'] for e in changed['proposal']['entries']], ['2号场','4号场'])
        undone = self.turn('撤销刚才的场地修改', action='undo', fields=['courts_2h'])
        self.assertEqual([e['court_preference'] for e in undone['proposal']['entries']], ['1号场','2号场'])
        count = len(self.provider.calls)
        replay = self.result(self.message, answers=self.answers, asked_fields=self.asked, conversation_id=undone['conversation_id'])
        self.assertEqual(replay['proposal']['entries'], undone['proposal']['entries'])
        self.assertEqual(len(self.provider.calls), count)

    def test_wrong_range_and_operation_are_business_clarifications_not_provider_retries(self):
        self.start()
        before = len(self.provider.calls)
        rejected = self.turn('只保留1到8号场', [self.update('courts_2h','replace',[1,8],'只保留1到8号场')])
        self.assertEqual((rejected['status'],rejected['conversation']['asking']), ('needs_input','courts_2h'))
        self.assertEqual(len(self.provider.calls), before+1)
        self.assertIn('courts_2h', self.state()['dialogue']['unresolved'])
        self.assertTrue(rejected['conversation']['turn_trace']['semantic_errors'])
        self.turn('场地改成1号和2号场', [self.update('courts_2h','replace',[1,2],'改成1号和2号场')])
        rejected = self.turn('去掉1号场', [self.update('courts_2h','add',[1],'去掉1号场')])
        self.assertEqual(rejected['status'], 'needs_input')
        changed = self.turn('时段改成18-20', [self.update('windows_2h','replace',[{'start':'18:00','end':'20:00'}],'改成18-20')])
        self.assertEqual(changed['conversation']['asking'], 'courts_2h')
        self.assertIsNone(changed['proposal'])

    def test_wrong_relative_date_is_not_accepted_because_its_evidence_is_a_substring(self):
        self.start()
        bad = self.turn('日期改成明天', [self.update('target_date','set','2026-10-12','明天')])
        self.assertEqual(bad['conversation']['asking'], 'target_date')
        self.assertIn('target_date', self.state()['dialogue']['unresolved'])
        fixed = self.turn('改成2026年10月11日', [self.update('target_date','set','2026-10-11','2026年10月11日')])
        self.assertEqual(fixed['proposal']['target_date'], '2026-10-11')
        self.assertFalse(fixed['proposal']['schedule']['eligible'])

    def test_confirmed_date_stays_fixed_but_new_relative_date_uses_new_day(self):
        first = int(datetime(2026,10,10,23,59,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()*1000)
        second = int(datetime(2026,10,11,0,1,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()*1000)
        with patch('backend.api.planning.time.time_ns', return_value=first*1000000):
            self.start('明天只抢2小时，14-16，1号场')
        with patch('backend.api.planning.time.time_ns', return_value=second*1000000):
            kept = self.turn('改成18-20', [self.update('windows_2h','replace',[{'start':'18:00','end':'20:00'}],'改成18-20')])
            self.assertEqual(kept['proposal']['target_date'],'2026-10-11')
            changed = self.turn('日期改成后天', [self.update('target_date','set','2026-10-13','改成后天')])
            self.assertEqual(changed['proposal']['target_date'],'2026-10-13')

    def test_question_only_turns_do_not_consume_field_retries_or_repeat_review(self):
        self.start('10月26日只抢2小时，14-16')
        for _ in range(4):
            result = self.turn('我还缺什么？', kind='question', reply='还缺2小时场地，例如1号场。', next_action='answer')
            self.assertFalse(result['conversation']['escalation'])
            self.assertEqual(result['questions'], [])
        ready = self.turn('1号场',[self.update('courts_2h','replace',[1],'1号场')])
        self.assertEqual(ready['status'],'ready')
        reviews = sum('预约队列复核员' in call[0]['content'] for call in self.provider.calls)
        question = self.turn('保存以后会立即付款吗？',kind='question',reply='保存仅写候选；到开票时才由独立执行器处理。',next_action='answer')
        self.assertEqual(question['status'],'ready')
        self.assertEqual(sum('预约队列复核员' in call[0]['content'] for call in self.provider.calls),reviews)

    def test_unknown_edit_target_is_clarified_without_overwriting_facts(self):
        self.start()
        result = self.turn('我想修改一下',action='begin_edit',question='你想修改哪一项？例如日期或2小时场地。',next_action='clarify_edit')
        self.assertEqual(result['status'],'needs_input')
        self.assertIsNone(result['conversation']['asking'])
        self.assertIn('哪一项',result['questions'][0])
        resumed = self.turn('算了，不改了',action='cancel_edit')
        self.assertEqual(resumed['status'],'ready')
        self.assertEqual(resumed['proposal']['entry_count'],2)

    def test_save_rechecks_opening_millisecond_and_preserves_idempotency(self):
        self.start()
        service=self.app.extensions['plan_service']
        opening=int(datetime(2026,10,24,7,30,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()*1000)
        entries=self.current['proposal']['entries']
        saved=service.save_manual_queue('a','2026-10-26',0,entries,opening-1,'cred-a')
        self.assertTrue(saved['automatic_schedule']['eligible'])
        replay=service.save_manual_queue('a','2026-10-26',1,entries,opening,'cred-a')
        self.assertFalse(replay['automatic_schedule']['eligible'])
        self.assertEqual(replay['version'],saved['version'])
        self.assertEqual(automatic_queue_schedule(date(2026,10,26),opening+1,'Asia/Shanghai')['state'],'passed')


    def test_model_cannot_silently_drop_explicit_invalid_time_or_duration(self):
        self.start()
        bad = self.turn('时段改成14-16和25-27', [self.update('windows_2h','replace',[{'start':'14:00','end':'16:00'}],'改成14-16')])
        self.assertEqual(bad['conversation']['asking'],'windows_2h')
        self.assertIn('25-27',bad['questions'][0])
        self.assertIn('windows_2h',self.state()['dialogue']['unresolved'])
        self.turn('改成18-20',[self.update('windows_2h','replace',[{'start':'18:00','end':'20:00'}],'改成18-20')])
        bad = self.turn('14-16打3小时',[self.update('windows_2h','replace',[{'start':'14:00','end':'16:00'}],'14-16')])
        self.assertEqual(bad['conversation']['asking'],'windows_2h')
        self.assertIn('3小时',bad['questions'][0])
        changed = self.turn('时段改成18-20',[self.update('windows_2h','replace',[{'start':'18:00','end':'20:00'}],'改成18-20')])
        self.assertIsNone(changed['proposal'])
        self.assertIn('3小时',changed['questions'][0])


    def test_cancel_edit_resumes_the_previous_dynamic_group_focus(self):
        self.provider.turn_replies=[json.dumps({
            'kind':'answer','updates':[
                self.update('booking_mode','set','both','两种都抢'),
                self.update('target_date','set','2026-10-26','10月26日'),
            ],'unresolved':[],'reply':'','next_field':'windows_1h','next_question':'先确认1小时时段，例如18-19。',
        },ensure_ascii=False)]
        self.start('10月26日两种都抢，我想先排1小时')
        self.assertEqual(self.current['conversation']['asking'],'windows_1h')
        self.turn('先改一下日期',action='begin_edit',fields=['target_date'],asking='target_date',question='日期改成哪天？')
        resumed=self.turn('取消这次修改',action='cancel_edit',asking='windows_2h',question='2小时想选什么时段？')
        self.assertEqual(resumed['conversation']['asking'],'windows_1h')


    def test_an_invalid_dormant_group_does_not_poison_the_selected_group(self):
        self.start()
        staged=self.turn('1小时备选想打3小时',unresolved=[{'field':'windows_1h','evidence':'打3小时','issue':'unsupported_duration','duration_minutes':180}])
        self.assertEqual(staged['status'],'ready')
        self.assertEqual(staged['proposal']['entry_count'],2)
        self.assertEqual(self.state()['draft']['duration_issue'],[180,60])
        selected=self.turn('改成两种都抢',[self.update('booking_mode','set','both','两种都抢')])
        self.assertEqual(selected['conversation']['asking'],'windows_1h')
        self.assertIn('3小时',selected['questions'][0])

    def test_the_last_duration_correction_is_not_lost_by_deduplication(self):
        self.start()
        fixed=self.turn('只抢2小时，14-16打3小时说错了，按2小时',[
            self.update('windows_2h','replace',[{'start':'14:00','end':'16:00'}],'只抢2小时，14-16打3小时说错了，按2小时'),
        ])
        self.assertEqual(fixed['status'],'ready')
        self.assertIsNone(self.state()['draft']['duration_issue'])


    def test_compound_operations_can_share_a_whole_sentence_as_evidence(self):
        self.start()
        text='去掉1号场，再加4号场'
        changed=self.turn(text,[self.update('courts_2h','remove',[1],text),self.update('courts_2h','add',[4],text)])
        self.assertEqual(changed['status'],'ready')
        self.assertEqual([item['court_preference'] for item in changed['proposal']['entries']],['2号场','4号场'])

    def test_noncommutative_operations_must_preserve_the_users_order(self):
        self.start()
        text='先去掉1号场，再加上1号场'
        wrong=self.turn(text,[self.update('courts_2h','add',[1],text),self.update('courts_2h','remove',[1],text)])
        self.assertEqual(wrong['status'],'needs_input')
        self.assertEqual(deserialize_draft(self.state()['draft']).g2.courts,[1,2])
        self.assertTrue(any(item['reason']=='operation_order_mismatch' for item in wrong['conversation']['turn_trace']['semantic_errors']))


    def test_schema_retry_identifies_user_kind_instead_of_deleting_a_correction(self):
        self.start()
        base={'updates':[self.update('windows_2h','replace',[{'start':'18:00','end':'20:00'}],'改成18-20')],
              'unresolved':[],'reply':'时段已改为18-20。','next_field':None,'next_question':''}
        self.provider.turn_replies=[json.dumps({'kind':'question',**base},ensure_ascii=False),json.dumps({'kind':'answer',**base},ensure_ascii=False)]
        self.asked.append(self.current['conversation']['asking']);self.answers.append('改成18-20')
        result=self.result(self.message,answers=self.answers,asked_fields=self.asked,conversation_id=self.current['conversation_id'])
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['proposal']['entries'][0]['start_time'],'18:00')
        retry=next(call for call in self.provider.calls if call[-1]['role']=='system')
        self.assertIn('question_with_fact_updates',retry[-1]['content'])
        self.assertIn('不能删除明确事实',retry[-1]['content'])


    def test_provider_truncation_does_not_retry_or_persist_a_partial_turn(self):
        from backend.ai.service import AIModelError
        self.start()
        before=self.app.extensions['planning_conversation_store'].get(self.current['conversation_id'],'a','cred-a')
        calls=len(self.provider.calls)
        self.provider.turn_replies=[AIModelError('provider_output_truncated',502)]
        response=self.post(self.message,answers=['改成18-20'],asked_fields=[self.current['conversation']['asking']],conversation_id=self.current['conversation_id'])
        self.assertEqual((response.status_code,response.get_json()['error']),(502,'provider_output_truncated'))
        self.assertEqual(len(self.provider.calls),calls+1)
        after=self.app.extensions['planning_conversation_store'].get(self.current['conversation_id'],'a','cred-a')
        self.assertEqual(after,before)
        self.assertEqual(self.counts(),(0,0))

    def test_a_new_overlap_uncertainty_cannot_reuse_an_old_keep_confirmation(self):
        self.start('10月26日只抢2小时，14-16和15-17，1号场')
        self.turn('都保留',[self.update('overlap_2h','confirm','keep','都保留')])
        disputed=self.turn('刚才是否保留重叠还没想好',unresolved=[{'field':'overlap_2h','evidence':'还没想好','issue':'ambiguous'}])
        self.assertEqual(disputed['conversation']['asking'],'overlap_2h')
        self.assertIsNone(disputed['proposal'])
        fixed=self.turn('去掉15-17',[self.update('windows_2h','remove',[{'start':'15:00','end':'17:00'}],'去掉15-17')])
        self.assertEqual(fixed['status'],'ready')
        self.assertEqual(fixed['proposal']['entry_count'],1)

    def test_unresolved_time_handling_is_not_silently_ignored_when_there_is_no_overlap(self):
        self.start()
        result=self.turn('我还没想好如何处理那个时段',unresolved=[{'field':'overlap_2h','evidence':'还没想好','issue':'ambiguous'}])
        self.assertEqual(result['status'],'needs_input')
        self.assertNotIn('有重叠',result['questions'][0])
        self.assertIsNone(result['proposal'])


    def test_positional_choice_uses_the_pending_options_without_inferring_from_windows(self):
        self.start('10月26日14-16，1号场')
        self.assertEqual(self.current['conversation']['asking'],'booking_mode')
        chosen=self.turn('最后一个',[self.update('booking_mode','set','both','最后一个')])
        self.assertEqual(chosen['conversation']['asking'],'windows_1h')
        self.assertEqual(self.state()['draft']['booking_mode'],'both')
        self.assertEqual(self.state()['draft']['groups']['2h']['courts'],[1])

    def test_explicit_mode_corrections_are_applied_in_quoted_order(self):
        self.start()
        text='先改成只抢1小时，再改成只抢2小时'
        changed=self.turn(text,[self.update('booking_mode','set','one_hour_only','只抢1小时'),self.update('booking_mode','set','two_hour_only','只抢2小时')])
        self.assertEqual(changed['status'],'ready')
        self.assertEqual(self.state()['draft']['booking_mode'],'two_hour_only')


    def test_context_projection_retains_server_confirmed_save_lifecycle(self):
        entry=assistant_history_entry({'status':'ready','workflow_state':'saved','conversation':{'phase':'ready','asking':None}})
        self.assertEqual(entry['workflow_state'],'saved')
        self.assertEqual(entry['phase'],'ready')


    def test_replacing_one_member_keeps_other_courts_in_the_same_duration_group(self):
        self.start('10月26日两种都抢，2小时14-16选1号场，1小时18-19选4号和6号场')
        text='1小时场地去掉4号场换成5号场'
        changed=self.turn(text,[self.update('courts_1h','remove',[4],'去掉4号场'),self.update('courts_1h','add',[5],text)])
        self.assertEqual(changed['status'],'ready')
        self.assertEqual(deserialize_draft(self.state()['draft']).g1.courts,[6,5])
        self.assertEqual(deserialize_draft(self.state()['draft']).g2.courts,[1])

    def test_replacing_one_window_keeps_the_other_windows(self):
        self.start('10月26日只抢2小时，14-16和20-22，1号场')
        text='把14-16换成18-20'
        changed=self.turn(text,[self.update('windows_2h','remove',[{'start':'14:00','end':'16:00'}],text),self.update('windows_2h','add',[{'start':'18:00','end':'20:00'}],text)])
        self.assertEqual(changed['status'],'ready')
        self.assertEqual(deserialize_draft(self.state()['draft']).g2.windows,[(1200,1320),(1080,1200)])


    def test_obvious_secrets_without_a_colon_are_rejected_before_any_model_call(self):
        for text in ('支付密码 123456','我的密码abcdef123456','password 123456','token '+'OpaqueExampleForTestsOnly42'):
            with self.subTest(text=text):
                response=self.post(text)
                self.assertEqual(response.status_code,400)
                self.assertEqual(response.get_json()['error'],'sensitive_planning_input')
        self.assertEqual(self.provider.calls,[])
        self.assertEqual(self.counts(),(0,0))


    def test_spaced_invalid_window_can_be_removed_without_a_phantom_ambiguity(self):
        self.start()
        text='时段改成14 - 16和25 - 27'
        invalid=self.turn(text,[self.update('windows_2h','replace',[{'start':'14:00','end':'16:00'},{'start':'25:00','end':'27:00'}],text)])
        self.assertEqual(invalid['conversation']['asking'],'windows_2h')
        self.assertNotIn('windows_2h',self.state()['dialogue']['unresolved'])
        fixed=self.turn('去掉25 - 27',[self.update('windows_2h','remove',[{'start':'25:00','end':'27:00'}],'去掉25 - 27')])
        self.assertEqual(fixed['status'],'ready')
        self.assertEqual(deserialize_draft(self.state()['draft']).g2.windows,[(840,960)])


    def test_a_mixed_question_does_not_lose_its_answer_when_repeating_valid_facts(self):
        self.start('10月26日只抢2小时，14-16，1号场')
        reply='1号场在1到10的范围内，当前仍使用1号场。'
        result=self.turn('1号场为什么可以？还是保留1号场',[self.update('courts_2h','replace',[1],'保留1号场')],kind='mixed',reply=reply)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['conversation']['contextual_reply'],reply)

    def test_an_explicit_clear_is_acknowledged_even_though_it_opens_a_required_field(self):
        self.start()
        result=self.turn('把场地清空',[self.update('courts_2h','clear',None,'清空')],reply='已清空2小时场地，请重新选择。')
        self.assertEqual(result['conversation']['asking'],'courts_2h')
        self.assertIn('已清空',result['conversation']['contextual_reply'])
        self.assertIsNone(result['proposal'])


    def test_undo_cannot_target_the_wrong_explicit_duration_group(self):
        self.start('10月26日两种都抢，2小时14-16选1号场，1小时18-19选4号场')
        self.turn('2小时场地加上3号场',[self.update('courts_2h','add',[3],'2小时场地加上3号场')])
        wrong=self.turn('撤销2小时场地的修改',action='undo',fields=['courts_1h'])
        self.assertEqual(wrong['status'],'needs_input')
        state=deserialize_draft(self.state()['draft'])
        self.assertEqual(state.g2.courts,[1,3])
        self.assertEqual(state.g1.courts,[4])
        self.assertIn('确认',wrong['questions'][0])

    def test_bare_undo_restores_the_whole_last_transaction(self):
        self.start()
        self.turn('日期改成10月28日，场地改成4号场',[
            self.update('target_date','set','2026-10-28','10月28日'),self.update('courts_2h','replace',[4],'改成4号场')])
        undone=self.turn('撤销刚才的修改',action='undo',fields=['target_date'])
        self.assertEqual(undone['status'],'ready')
        self.assertEqual(undone['proposal']['target_date'],'2026-10-26')
        self.assertEqual(deserialize_draft(self.state()['draft']).g2.courts,[1,2])


    def test_an_unspecified_edit_can_be_completed_by_a_later_explicit_fact(self):
        self.start()
        self.turn('想改一下',action='begin_edit',question='你想修改哪项？例如日期或场地。',next_action='clarify_edit')
        fixed=self.turn('场地换成4号场',[self.update('courts_2h','replace',[4],'换成4号场')])
        self.assertEqual(fixed['status'],'ready')
        self.assertIsNone(fixed['conversation']['pending_edit'])
        self.assertEqual([entry['court_preference'] for entry in fixed['proposal']['entries']],['4号场'])


    def test_clear_delta_cannot_erase_a_field_not_named_by_the_user(self):
        self.start()
        bad=self.turn('清空场地',[self.update('target_date','clear',None,'清空场地')])
        draft=deserialize_draft(self.state()['draft'])
        self.assertEqual(draft.dates,(date(2026,10,26),))
        self.assertEqual(draft.g2.courts,[1,2])
        self.assertIsNone(bad['proposal'])
        self.assertTrue(bad['conversation']['turn_trace']['semantic_errors'])


    def test_undo_a_rejected_model_delta_restores_the_preexisting_confirmed_facts(self):
        self.start()
        self.turn('日期改成明天',[self.update('target_date','set','2026-10-12','明天')])
        undone=self.turn('撤销刚才的修改',action='undo')
        self.assertEqual(undone['status'],'ready')
        self.assertEqual(undone['proposal']['target_date'],'2026-10-26')
        self.assertNotIn('target_date',self.state()['dialogue']['unresolved'])


    def test_a_unique_just_chosen_court_reference_uses_current_facts(self):
        self.start('10月26日只抢2小时，14-16，1号场')
        kept=self.turn('还是刚才那个场地',[self.update('courts_2h','replace',[1],'刚才那个场地')])
        self.assertEqual(kept['status'],'ready')
        self.assertEqual(kept['proposal']['entries'][0]['court_preference'],'1号场')


    def test_live_evaluation_never_counts_a_provider_interruption_as_a_pass(self):
        import sys
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import Mock
        from backend.tests import eval_queue_live as evaluation
        from backend.ai.service import AIModelError
        provider=Mock()
        provider.config.model='synthetic-test'
        provider.calls=1
        with TemporaryDirectory() as directory:
            output=Path(directory)/'report.json'
            with patch.object(sys,'argv',['eval_queue_live','--env-file','unused','--output',str(output)]), \
                 patch.object(evaluation,'load_key',return_value=('test-only','test-only')), \
                 patch.object(evaluation,'LiveProvider',return_value=provider), \
                 patch.object(evaluation,'scenarios',return_value=[('one',[('hello',{})])]), \
                 patch.object(evaluation.Scenario,'send',side_effect=AIModelError('provider_payment_required',502)):
                self.assertEqual(evaluation.main(),2)
            report=json.loads(output.read_text())
        self.assertFalse(report['ok'])
        self.assertFalse(report['cases'][0]['ok'])
        self.assertFalse(report['cases'][0]['completed'])
        self.assertEqual(report['cases'][0]['steps'],[])
        self.assertEqual(report['cases'][0]['interrupted_by'],'provider_payment_required')


    def test_compound_changes_to_one_field_are_not_partially_applied_after_semantic_rejection(self):
        self.start()
        text='去掉1号场，再加4号场'
        bad=self.turn(text,[self.update('courts_2h','remove',[1],'去掉1号场'),self.update('courts_2h','add',[5],'再加4号场')])
        self.assertEqual(deserialize_draft(self.state()['draft']).g2.courts,[1,2])
        self.assertEqual(bad['status'],'needs_input')
        self.assertIsNone(bad['proposal'])
        self.assertIn('courts_2h',self.state()['dialogue']['unresolved'])

    def test_negated_date_evidence_is_rejected_and_the_correction_recovers(self):
        self.start()
        bad=self.turn('日期不是10月26日，改成10月28日',[
            self.update('target_date','set','2026-10-26','10月26日')])
        self.assertEqual(bad['conversation']['asking'],'target_date')
        self.assertEqual(deserialize_draft(self.state()['draft']).dates,(date(2026,10,26),))
        fixed=self.turn('改成10月28日',[
            self.update('target_date','set','2026-10-28','10月28日')])
        self.assertEqual(fixed['proposal']['target_date'],'2026-10-28')

    def test_relative_date_correction_and_multiple_choices_are_not_guessed(self):
        self.start()
        bad=self.turn('日期不是明天，改成后天',[
            self.update('target_date','set','2026-10-11','明天')])
        self.assertEqual(bad['conversation']['asking'],'target_date')
        fixed=self.turn('不是10月26日或10月28日，我还没选好',[
            self.update('target_date','set','2026-10-28','10月28日')])
        self.assertEqual(fixed['conversation']['asking'],'target_date')
        final=self.turn('就选后天',[
            self.update('target_date','set','2026-10-12','后天')])
        self.assertEqual(final['proposal']['target_date'],'2026-10-12')

    def test_duration_group_mismatch_cannot_change_the_other_windows(self):
        self.start('10月26日两种都抢，2小时14-16选1号场，1小时18-19选4号场')
        bad=self.turn('1小时时段改成20点',[
            self.update('windows_2h','replace',[{'start':'20:00','end':'22:00'}],'20点')])
        state=deserialize_draft(self.state()['draft'])
        self.assertEqual((bad['conversation']['asking'],state.g2.windows,state.g1.windows),
                         ('windows_1h',[(840,960)],[(1080,1140)]))
        fixed=self.turn('1小时时段改成20点',[
            self.update('windows_1h','replace',[{'start':'20:00','end':'21:00'}],'20点')])
        state=deserialize_draft(self.state()['draft'])
        self.assertEqual((fixed['status'],state.g2.windows,state.g1.windows),
                         ('ready',[(840,960)],[(1200,1260)]))
        reverse=self.turn('2小时时段改成18点',[
            self.update('windows_1h','replace',[{'start':'18:00','end':'19:00'}],'18点')])
        self.assertEqual(reverse['conversation']['asking'],'windows_2h')

    def test_duration_group_mismatch_cannot_change_courts_or_overlap(self):
        self.start('10月26日两种都抢，2小时14-16选1号场，1小时18-19选4号场')
        bad=self.turn('1小时场地改成5号场',[
            self.update('courts_2h','replace',[5],'5号场')])
        state=deserialize_draft(self.state()['draft'])
        self.assertEqual((bad['conversation']['asking'],state.g2.courts,state.g1.courts),
                         ('courts_1h',[1],[4]))
        self.provider.turn_replies=[]
        self.start('10月26日两种都抢，2小时14-16和15-17选1号场，1小时18-19选4号场')
        overlap=self.turn('1小时都保留，2小时我还没想好',[
            self.update('overlap_2h','confirm','keep','1小时都保留')])
        self.assertIsNone(overlap['proposal'])
        self.assertFalse(deserialize_draft(self.state()['draft']).g2.acked)
        kept=self.turn('2小时重叠都保留',[
            self.update('overlap_2h','confirm','keep','2小时重叠都保留')])
        self.assertTrue(deserialize_draft(self.state()['draft']).g2.acked)

    def test_both_duration_groups_can_share_complete_sentence_evidence(self):
        self.start('10月26日两种都抢，2小时14-16选1号场，1小时18-19选4号场')
        text='2小时改成20-22，1小时改成19-20'
        changed=self.turn(text,[
            self.update('windows_2h','replace',[{'start':'20:00','end':'22:00'}],text),
            self.update('windows_1h','replace',[{'start':'19:00','end':'20:00'}],text),
        ])
        state=deserialize_draft(self.state()['draft'])
        self.assertEqual((changed['status'],state.g2.windows,state.g1.windows),
                         ('ready',[(1200,1320)],[(1140,1200)]))
        wrong=self.turn('清空1小时场地',[
            self.update('courts_2h','clear',None,'清空1小时场地')])
        state=deserialize_draft(self.state()['draft'])
        self.assertEqual((state.g1.courts,state.g2.courts),([4],[1]))
        self.assertIn('courts_1h',self.state()['dialogue']['unresolved'])
        clear='清空1小时场地，再清空2小时场地'
        cleared=self.turn(clear,[
            self.update('courts_1h','clear',None,clear),
            self.update('courts_2h','clear',None,clear),
        ])
        state=deserialize_draft(self.state()['draft'])
        self.assertEqual((state.g1.courts,state.g2.courts),([],[]))
        self.assertIsNone(cleared['proposal'])
