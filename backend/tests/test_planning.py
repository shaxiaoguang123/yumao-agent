import json
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.ai import conversation as conv
from backend.ai.planning import PlanningService
from backend.ai.service import AIModelError
from backend.app import create_app
from backend.db import connect_database
from backend.migrate import migrate_database
from support import credential_test_settings
from plan_test_support import NOW

ORIGIN = 'http://localhost:5173'
ONE_SHOT = '10月20日 14-16 和 18-20，1号4号场，不要一小时，不用候选'
OK = json.dumps({'warnings': []})


class ScriptedProvider:
    """Replies in order; the last one repeats. A reply that is an Exception is raised."""

    def __init__(self):
        self.queue, self.calls = [OK], []

    def chat(self, user_id, messages, **_kw):
        self.calls.append(messages)
        reply = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if reply == OK and '追问排序器' in messages[0]['content']:
            payload = json.loads(messages[-1]['content'])
            reply = json.dumps({'field': payload['blocking_fields'][0]['field']})
        if isinstance(reply, Exception):
            raise reply
        return reply, {'name': '合成模型', 'model': 'synthetic-model'}

    def payload(self, index=-1):
        return json.loads(self.calls[index][1]['content'])


def add_account(path, user_id, credential_id):
    with closing(connect_database(path, 5000)) as db:
        db.execute("BEGIN")
        db.execute("INSERT OR IGNORE INTO users(user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms) VALUES(?,?,?,'x','user','active',1,1)", (user_id, user_id, user_id))
        db.execute("INSERT INTO credentials(credential_id,user_id,label,credential_version,enabled,current_token_revision_id,account_binding_state,last_confirmed_validation_state,requires_revalidation,created_at_utc_ms,updated_at_utc_ms) VALUES(?,?,'t',1,1,?,'unresolved','never_confirmed',0,1,1)", (credential_id, user_id, 'rev-' + credential_id))
        db.execute("INSERT INTO credential_token_revisions(revision_id,user_id,credential_id,revision_number,token_fingerprint,token_fingerprint_key_version,initial_validation_result,initial_validation_at_utc_ms,created_by_user_id,secret_material_active,ciphertext,nonce,tag,encryption_key_version) VALUES(?,?,?,1,?,'fp-v1','success',1,?,1,?,?,?,'enc-v1')", ('rev-' + credential_id, user_id, credential_id, 'a' * 64, user_id, b'c', b'n' * 12, b't' * 16))
        db.commit()


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='planning-queue-')
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'synthetic.sqlite3'
        migrate_database(self.path, 5000)
        self.app = create_app({**credential_test_settings(self.path), 'TESTING': True, 'APP_ALLOWED_ORIGINS': ORIGIN})
        for user, credential in (('a', 'cred-a'), ('b', 'cred-b')):
            add_account(self.path, user, credential)
        self.clients, self.headers = {}, {}
        for user in ('a', 'b'):
            client = self.app.test_client()
            cookie, csrf = self.app.extensions['session_service'].create(user, NOW)
            client.set_cookie('yumao_session', cookie)
            self.clients[user], self.headers[user] = client, {'Origin': ORIGIN, 'X-CSRF-Token': csrf}
        self.provider = ScriptedProvider()
        self.app.extensions['planning_service'] = PlanningService(self.app.extensions['plan_service'], self.provider)
        self.enterContext(patch('backend.api.planning.time.time_ns', return_value=NOW * 1_000_000))
        self.network = self.enterContext(patch('requests.sessions.Session.request', side_effect=AssertionError('upstream forbidden')))

    def post(self, message=ONE_SHOT, user='a', credential='cred-a', scope_label='羽毛球', **extra):
        body = {'message': message, **({'credential_id': credential} if credential else {}),
                **({'scope_label': scope_label} if scope_label is not None else {}),
                **{k: v for k, v in extra.items() if v is not None}}
        return self.clients[user].post('/api/planning/queue-proposals', json=body, headers=self.headers[user])

    def result(self, *args, **kwargs):
        return self.post(*args, **kwargs).get_json()

    def counts(self):
        with closing(connect_database(self.path, 5000)) as db:
            return tuple(db.execute('SELECT (SELECT count(*) FROM booking_plans),(SELECT count(*) FROM booking_plan_revisions)').fetchone())

class ReadyTests(Base):
    def test_one_message_builds_the_ordered_queue_and_the_model_only_reviews(self):
        result = self.result()
        proposal = result['proposal']
        self.assertEqual((result['status'], result['conversation']['phase']), ('ready', 'ready'))
        self.assertEqual([(e['court_preference'], e['start_time'], e['end_time'], e['duration_minutes']) for e in proposal['entries']],
                         [('1号场', '14:00', '16:00', 120), ('4号场', '14:00', '16:00', 120),
                          ('1号场', '18:00', '20:00', 120), ('4号场', '18:00', '20:00', 120)])
        self.assertEqual((proposal['target_date'], proposal['target_label']), ('2026-10-20', '10月20日 周二'))
        self.assertEqual((proposal['base_version'], proposal['existing_count'], proposal['replaces_existing']), (0, 0, False))
        self.assertEqual(proposal['review']['state'], 'reviewed')
        self.assertEqual(len(self.provider.calls), 1)
        for flag in ('can_book', 'can_pay', 'can_create_job', 'can_query_upstream'):
            self.assertFalse(proposal[flag])
        self.assertEqual(self.counts(), (0, 0))
        self.network.assert_not_called()

    def test_the_review_prompt_explains_the_phrases_that_caused_false_alarms(self):
        self.result()
        rules = self.provider.calls[0][0]['content']
        self.assertIn('不是要删掉已经说出的时间段', rules)   # "不用候选" means: no extra candidates
        self.assertIn('不要一小时', rules)
        self.assertIn('不用提醒', rules)                  # the 2h-before-1h order is by design

    def test_the_model_sees_the_users_words_and_the_built_queue_but_nothing_private(self):
        self.result()
        payload = self.provider.payload()
        self.assertEqual(set(payload), {'business_date', 'user_turns', 'queue'})
        self.assertEqual(payload['user_turns'], [ONE_SHOT])
        self.assertEqual(payload['queue']['candidates'][0], '2小时 14:00-16:00 1号场')
        text = json.dumps(self.provider.calls[0], ensure_ascii=False)
        for secret in ('cred-a', 'user_id', 'token'):
            self.assertNotIn(secret, text)

    def test_model_ranks_open_fields_but_the_date_gate_stays_server_owned(self):
        self.result('我想订场')
        self.assertEqual(self.provider.calls, [])
        self.provider.queue = [json.dumps({'field': 'courts_2h'})]
        result = self.result('后天 14-16')
        self.assertEqual(result['conversation']['asking'], 'courts_2h')
        self.assertIn('号场', result['questions'][0])
        self.assertEqual(self.provider.payload()['blocking_fields'][0]['field'], 'more_2h')

    def test_model_cannot_choose_a_field_that_is_not_blocking(self):
        self.provider.queue = [json.dumps({'field': 'target_date'})]
        result = self.result('后天 14-16')
        self.assertEqual(result['conversation']['asking'], 'more_2h')
        self.assertIn('默认顺序', result['conversation']['notices'][-1])

    def test_warnings_are_cleaned_and_never_change_the_queue(self):
        self.provider.queue = [json.dumps({'warnings': ['你提到的 3 号场没有出现在队列里', 'x' * 200, 'sk-' + 'a' * 30, '  多  余  空格  ', '第四条'] })]
        result = self.result()
        # only the first three are read; the too-long and key-like ones are dropped, spaces are collapsed
        self.assertEqual(result['proposal']['warnings'], ['你提到的 3 号场没有出现在队列里'])
        for warning in result['proposal']['warnings']:
            self.assertNotIn('sk-', warning)
            self.assertLessEqual(len(warning), 80)
        self.assertEqual(len(result['proposal']['entries']), 4)

    def test_a_missing_model_does_not_stop_the_queue(self):
        self.provider.queue = [AIModelError('provider_not_configured', 409)]
        result = self.result()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['proposal']['review']['state'], 'skipped')
        self.assertIn('尚未配置模型', result['conversation']['notices'][-1])
        self.provider.queue = [AIModelError('provider_timeout', 504)]
        self.assertIn('暂时不可用', self.result()['conversation']['notices'][-1])

    def test_a_broken_review_reply_is_retried_once_then_skipped(self):
        self.provider.queue = ['not json', OK]
        self.assertEqual(self.result()['proposal']['review'], {'state': 'reviewed', 'attempts': 2})
        self.assertIn('format_error', self.provider.payload())
        self.provider.queue = ['not json']
        result = self.result()
        self.assertEqual((result['status'], result['proposal']['review']['state']), ('ready', 'skipped'))
        self.assertEqual(len(self.provider.calls), 4)

    def test_a_model_cannot_add_fields_or_entries(self):
        for reply in (json.dumps({'warnings': [], 'entries': [{'court_preference': '9号场'}]}), json.dumps({'warnings': 'oops'}),
                      json.dumps({'warnings': [1]})):
            self.provider.queue = [reply]
            result = self.result()
            self.assertEqual(result['proposal']['review']['state'], 'skipped')
            self.assertEqual(len(result['proposal']['entries']), 4)

class ConversationTests(Base):
    def test_questions_come_in_the_described_order_and_carry_asked_fields(self):
        first = self.result('我想订场')
        self.assertEqual(first['conversation']['asking'], 'target_date')
        second = self.result('我想订场', answers=['10月20日'], asked_fields=['target_date'])
        self.assertEqual(second['conversation']['asking'], 'windows_2h')
        self.assertIn('已记录：10月20日 周二', second['questions'][0])
        third = self.result('我想订场', answers=['10月20日', '14-16'], asked_fields=['target_date', 'windows_2h'])
        self.assertEqual(third['conversation']['asking'], 'more_2h')

    def test_the_view_describes_progress_for_the_ui(self):
        view = self.result('10月20日 14-16')['conversation']
        self.assertEqual([i['id'] for i in view['strip']], ['date', 'windows', 'courts', 'one'])
        self.assertEqual(view['heading'], '候选时间')
        self.assertEqual({i['id']: i['state'] for i in view['strip']}, {'date': 'done', 'windows': 'current', 'courts': 'empty', 'one': 'empty'})
        self.assertEqual([s['field'] for s in view['slots']], list(conv.PRIORITY))
        self.assertEqual((view['turns_used'], view['turns_max']), (0, conv.MAX_ANSWERS))

    def test_the_one_hour_queue_is_a_second_stage(self):
        message = '10月20日 14-16 不用候选 1号场'
        result = self.result(message)
        self.assertEqual(result['conversation']['asking'], 'want_1h')
        result = self.result(message, answers=['要', '15-16', '不用', '1号场'],
                             asked_fields=['want_1h', 'windows_1h', 'more_1h', 'courts_1h'])
        self.assertEqual(result['status'], 'ready')
        self.assertEqual([(e['duration_minutes'], e['start_time']) for e in result['proposal']['entries']], [(120, '14:00'), (60, '15:00')])

    def test_declining_both_durations_never_reactivates_a_queue(self):
        message = '后天14-16 1号场 不要一小时 不要两个小时 不用候选'
        result = self.result(message)
        self.assertEqual((result['status'], result['conversation']['asking']), ('needs_input', 'want_1h'))
        self.assertEqual(result['conversation']['phase'], 'repairing')
        self.assertEqual(result['conversation']['heading'], '选择预约时长')
        self.assertIn('目前没有可保存的候选', result['questions'][0])
        self.assertIsNone(result['proposal'])
        strip = {item['id']: item for item in result['conversation']['strip']}
        self.assertEqual(strip['windows']['display'], '')
        self.assertEqual((strip['one']['state'], strip['one']['display']), ('current', '正在确认'))
        self.assertEqual(self.provider.calls, [])

    def test_reenabling_a_duration_keeps_its_original_courts(self):
        message = '后天14-16 1号场 不要一小时 不要两个小时 不用候选'
        result = self.result(message, answers=['只要2小时'], asked_fields=['want_1h'])
        self.assertEqual(result['status'], 'ready')
        self.assertEqual([(entry['duration_minutes'], entry['court_preference'])
                          for entry in result['proposal']['entries']], [(120, '1号场')])

    def test_overlap_is_explained_and_resolved_by_the_user(self):
        message = '10月20日 14-16 15-17 不用候选'
        result = self.result(message)
        self.assertEqual(result['conversation']['asking'], 'overlap_2h')
        self.assertIn('14-16 与 15-17', result['questions'][0])
        result = self.result(message, answers=['去掉15-17', '1号场', '不用'], asked_fields=['overlap_2h', 'courts_2h', 'want_1h'])
        self.assertEqual([e['start_time'] for e in result['proposal']['entries']], ['14:00'])

    def test_the_questions_never_mention_a_venue_or_minutes(self):
        for message, answers, asked in (('我想订场', [], []), ('我想订场', ['10月20日'], ['target_date']), ('10月20日 14-16', [], [])):
            question = self.result(message, answers=answers or None, asked_fields=asked or None)['questions'][0]
            self.assertNotIn('场馆', question)
            self.assertNotIn('分钟', question)

    def test_asked_fields_must_match_the_answers_and_be_known_fields(self):
        for asked in ([], ['target_date', 'target_date'], ['nodeid'], 'target_date', [5]):
            self.assertEqual(self.post(ONE_SHOT, answers=['好'], asked_fields=asked).status_code, 400, asked)
        self.assertEqual(self.post(ONE_SHOT, answers=['好'], asked_fields=[None]).status_code, 200)

    def test_a_field_asked_three_times_hands_over_with_the_confirmed_date(self):
        message = '10月20日 14-16 不用候选'
        asked = ['courts_2h'] * 3
        result = self.result(message, answers=['不知道', '随便', '再说'], asked_fields=asked)
        view = result['conversation']
        self.assertEqual((result['status'], view['phase'], view['escalation']['kind']), ('needs_input', 'escalated', 'stalled'))
        self.assertEqual(view['escalation']['prefill'], {'target_date': '2026-10-20'})
        self.assertEqual(self.provider.calls, [])

    def test_the_turn_budget_is_twenty_answers(self):
        answers = ['嗯'] * conv.MAX_ANSWERS
        result = self.result('想订场', answers=answers, asked_fields=[None] * conv.MAX_ANSWERS)
        self.assertEqual(result['conversation']['escalation']['kind'], 'turn_limit')
        self.assertEqual(self.post('想订场', answers=['嗯'] * (conv.MAX_ANSWERS + 1)).status_code, 400)

    def test_the_last_turn_can_still_finish(self):
        answers = ['嗯'] * (conv.MAX_ANSWERS - 1) + ['好的']
        self.assertEqual(self.result(ONE_SHOT, answers=answers)['status'], 'ready')


class SafetyTests(Base):
    def test_commands_are_refused_and_wishes_are_noted(self):
        for text in ('帮我直接预约并付款', ONE_SHOT + ' 然后立即下单'):
            result = self.result(text)
            self.assertEqual((result['status'], result['conversation']['phase']), ('unsupported', 'unsupported'))
        self.assertEqual(self.provider.calls, [])
        ok = self.result(ONE_SHOT + '，到点自动预约')
        self.assertEqual(ok['status'], 'ready')
        self.assertEqual(len(ok['conversation']['notices']), 1)
        authorized = self.result('不要自动付款，' + ONE_SHOT)
        self.assertEqual(authorized['status'], 'ready')
        self.assertFalse(authorized['proposal']['can_pay'])

    def test_secrets_are_rejected_without_being_echoed(self):
        response = self.post('Bearer ' + 'x' * 32)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('x' * 32, response.get_data(as_text=True))
        self.assertEqual(self.provider.calls, [])

    def test_a_credential_is_required_and_must_belong_to_the_user(self):
        self.assertEqual(self.post(credential=None).status_code, 400)
        self.assertEqual(self.post(credential='cred-b').status_code, 404)
        self.assertEqual(self.post(user='b', credential='cred-a').status_code, 404)
        self.assertEqual(self.post(user='b', credential='cred-b').status_code, 200)

    def test_body_shape_session_and_csrf(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.post('/api/planning/queue-proposals', json={}, headers={'Origin': ORIGIN}).status_code, 401)
        self.assertEqual(self.clients['a'].post('/api/planning/queue-proposals', json={}, headers={'Origin': ORIGIN}).status_code, 403)
        for body in ({'message': ONE_SHOT}, {'message': ONE_SHOT, 'credential_id': 'cred-a', 'plan_id': 'p'},
                     {'message': ONE_SHOT, 'credential_id': 'cred-a', 'token': 'forbidden'}, {'message': True, 'credential_id': 'cred-a'}):
            self.assertEqual(self.clients['a'].post('/api/planning/queue-proposals', json=body, headers=self.headers['a']).status_code, 400, body)
        big = self.clients['a'].post('/api/planning/queue-proposals', data='x' * 70000, content_type='application/json', headers=self.headers['a'])
        self.assertEqual(big.status_code, 413)

    def test_scope_label_is_validated_and_carried_into_entries(self):
        result = self.result(scope_label='羽毛球')
        self.assertTrue(all(e['scope_label'] == '羽毛球' for e in result['proposal']['entries']))
        missing = self.post(scope_label=None)
        self.assertEqual(missing.status_code, 409)
        self.assertEqual(missing.get_json()['error'], 'planning_scope_required')
        for bad in ('', ' x', 'x ', 'a' * 101, 5, 'bad\nlabel', '羽毛球场', '其他活动'):
            self.assertEqual(self.post(scope_label=bad).status_code, 400, bad)

    def test_queue_conversation_is_restored_and_isolated_by_user_and_credential(self):
        first = self.post('后天')
        self.assertEqual(first.status_code, 200)
        conversation_id = first.get_json()['conversation_id']
        latest = self.clients['a'].get('/api/planning/queue-conversations?credential_id=cred-a', headers=self.headers['a'])
        self.assertEqual(latest.get_json()['conversation']['message'], '后天')
        self.assertEqual(latest.get_json()['conversation']['response_history'][0]['questions'], first.get_json()['questions'])

        continued = self.post('后天', answers=['14-16'], asked_fields=['windows_2h'], conversation_id=conversation_id)
        self.assertEqual(continued.status_code, 200)
        restored = self.clients['a'].get('/api/planning/queue-conversations?credential_id=cred-a', headers=self.headers['a']).get_json()['conversation']
        self.assertEqual(restored['answers'], ['14-16'])
        self.assertEqual(len(restored['response_history']), 2)
        self.assertIsNone(self.clients['b'].get('/api/planning/queue-conversations?credential_id=cred-b', headers=self.headers['b']).get_json()['conversation'])
        cross_user = self.clients['b'].post(
            '/api/planning/queue-proposals', json={'message':'后天','credential_id':'cred-b','conversation_id':conversation_id},
            headers=self.headers['b'],
        )
        self.assertEqual(cross_user.status_code, 404)
        closed = self.clients['a'].post(
            f'/api/planning/queue-conversations/{conversation_id}/close?credential_id=cred-a',
            json={}, headers=self.headers['a'],
        )
        self.assertEqual(closed.status_code, 204)
        self.assertIsNone(self.clients['a'].get('/api/planning/queue-conversations?credential_id=cred-a', headers=self.headers['a']).get_json()['conversation'])

    def test_relative_date_uses_the_first_turn_business_date_across_midnight(self):
        first_ms = int(datetime(2026, 10, 10, 23, 59, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp() * 1000)
        second_ms = int(datetime(2026, 10, 11, 0, 1, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp() * 1000)
        timestamps = iter([first_ms * 1_000_000, second_ms * 1_000_000])
        with patch('backend.api.planning.time', SimpleNamespace(time_ns=lambda: next(timestamps))):
            first_response = self.post('后天')
            self.assertEqual(first_response.status_code, 200, first_response.get_json())
            first = first_response.get_json()
            second = self.post('后天', answers=['14-16'], asked_fields=['windows_2h'],
                               conversation_id=first['conversation_id']).get_json()
        self.assertEqual(first['conversation']['strip'][0]['display'], '10月12日 周一')
        self.assertEqual(second['conversation']['strip'][0]['display'], '10月12日 周一')

    def test_propose_never_writes_and_the_ai_call_guard_applies(self):
        for message in (ONE_SHOT, '想订场', '帮我直接付款'):
            self.post(message)
        self.assertEqual(self.counts(), (0, 0))
        guard = self.app.extensions['ai_call_guard']
        with guard.hold('a'):
            self.assertEqual(self.post().status_code, 429)
            self.assertEqual(self.post(user='b', credential='cred-b').status_code, 200)

    def test_the_credential_user_pair_scopes_the_existing_queue(self):
        entries = [{'court_preference': '2号场', 'start_time': '10:00', 'end_time': '12:00', 'duration_minutes': 120}]
        saved = self.clients['a'].put('/api/plans/manual-queues/2026-10-20', json={'base_version': 0, 'entries': entries, 'credential_id': 'cred-a'}, headers=self.headers['a'])
        self.assertEqual(saved.status_code, 200)
        mine = self.result()['proposal']
        self.assertEqual((mine['base_version'], mine['existing_count'], mine['replaces_existing']), (1, 1, True))
        theirs = self.result(user='b', credential='cred-b')['proposal']
        self.assertEqual((theirs['base_version'], theirs['existing_count']), (0, 0))
        saved = self.clients['a'].put('/api/plans/manual-queues/2026-10-20', json={'base_version': mine['base_version'], 'entries': mine['entries'], 'credential_id': 'cred-a'}, headers=self.headers['a'])
        self.assertEqual(saved.status_code, 200)
        queue = saved.get_json()['queue']
        self.assertEqual([(c['court_preferences'][0], c['preferred_start_times'][0]) for c in queue['candidates']],
                         [('1号场', '14:00'), ('4号场', '14:00'), ('1号场', '18:00'), ('4号场', '18:00')])


class ScheduleTests(Base):
    """NOW is Saturday 2026-10-10 10:00 in Shanghai."""

    def schedule(self, message):
        return self.result(message)['proposal']['schedule']

    def test_a_far_date_names_its_opening_day(self):
        schedule = self.schedule('10月20日 14-16 1号场 不用候选 不要一小时')
        self.assertEqual(schedule['state'], 'scheduled')
        self.assertIn('10月18日 周日 07:30', schedule['text'])

    def test_two_days_ahead_after_the_opening_hour_is_not_automatic(self):
        schedule = self.schedule('10月12日 14-16 1号场 不用候选 不要一小时')
        self.assertEqual(schedule['state'], 'passed')

    def test_tomorrow_is_not_automatic(self):
        self.assertEqual(self.schedule('10月11日 14-16 1号场 不用候选 不要一小时')['state'], 'not_automatic')

    def test_today_is_accepted_but_flagged(self):
        self.assertEqual(self.schedule('10月10日 14-16 1号场 不用候选 不要一小时')['state'], 'not_automatic')

    def test_a_past_date_is_asked_again(self):
        result = self.result('10月1日 14-16 1号场 不用候选 不要一小时')
        self.assertEqual((result['status'], result['conversation']['asking']), ('needs_input', 'target_date'))
        self.assertIn('已经过了', result['questions'][0])


class ParsingTestEndpoint(Base):
    def test_the_synthetic_wording_builds_a_queue(self):
        result = self.app.extensions['planning_service'].test_parsing('a', None, NOW)
        self.assertEqual((result['ok'], result['outcome']), (True, 'parsed'))
        self.assertTrue(result['proposal']['entries'])

    def test_a_failing_model_is_reported_not_hidden(self):
        service = self.app.extensions['planning_service']
        self.provider.queue = [AIModelError('provider_timeout', 504)]
        with self.assertRaises(AIModelError):
            service.test_parsing('a', None, NOW)
        self.provider.queue = ['not json']
        from backend.plans.service import PlanError
        with self.assertRaises(PlanError):
            service.test_parsing('a', None, NOW)


if __name__ == '__main__':
    unittest.main()


class QueueSafetyRegressionTests(Base):
    def test_time_and_duration_answers_cannot_supply_a_court_number(self):
        message = '后天14-16，不要一小时，不用候选'
        for answer in ('打2小时', '改成18:00开始，打2小时', '2026年10月20日'):
            with self.subTest(answer=answer):
                result = self.result(message, answers=[answer], asked_fields=['courts_2h'])
                self.assertEqual((result['status'], result['conversation']['asking']), ('needs_input', 'courts_2h'))
                self.assertIsNone(result['proposal'])
        self.assertEqual(self.provider.calls, [])

    def test_court_replacements_and_only_cues_do_not_keep_old_preferences(self):
        for correction in ('只留4号场', '场地改成4号场', '换成4号场'):
            with self.subTest(correction=correction):
                result = self.result(f'后天14-16，1号和4号场，{correction}，不要一小时，不用候选')
                self.assertEqual(result['status'], 'ready')
                self.assertEqual([e['court_preference'] for e in result['proposal']['entries']], ['4号场'])

    def test_negated_all_courts_never_expands_the_queue(self):
        result = self.result('后天14-16，1号场，不要所有场地，不要一小时，不用候选')
        self.assertEqual((result['status'], result['conversation']['asking']), ('needs_input', 'courts_2h'))
        self.assertIsNone(result['proposal'])
        result = self.result('后天14-16，所有场地，不要4号场，不要一小时，不用候选')
        self.assertEqual(result['status'], 'ready')
        self.assertEqual([e['court_preference'] for e in result['proposal']['entries']], [f'{n}号场' for n in range(1, 11) if n != 4])

    def test_window_specific_courts_require_explicit_common_courts(self):
        message = '后天14-16选1号场，18-20选4号场，不要一小时，不用候选'
        result = self.result(message)
        self.assertEqual((result['status'], result['conversation']['asking']), ('needs_input', 'courts_2h'))
        self.assertIn('不能直接交叉组合', result['questions'][0])
        self.assertIsNone(result['proposal'])
        self.assertEqual(self.provider.calls, [])
        agreed = self.result(message, answers=['1号和4号'], asked_fields=['courts_2h'])
        self.assertEqual(agreed['status'], 'ready')
        self.assertEqual(len(agreed['proposal']['entries']), 4)

    def test_scoped_courts_without_the_word_select_do_not_cross_combine(self):
        result = self.result('后天14-16 1号场，18-20 4号场，不用候选，不要一小时')
        self.assertEqual((result['status'], result['conversation']['asking']), ('needs_input', 'courts_2h'))
        self.assertIsNone(result['proposal'])
        common = self.result('后天14-16和18-20，不用候选，1号和4号场，不要一小时')
        self.assertEqual(common['status'], 'ready')
        self.assertEqual(len(common['proposal']['entries']), 4)

    def test_window_specific_courts_stay_ambiguous_when_added_in_a_later_turn(self):
        message = '后天14-16选1号场，不要一小时'
        first = self.result(message)
        self.assertEqual(first['conversation']['asking'], 'more_2h')
        second = self.result(message, answers=['再加18-20选4号场'], asked_fields=['more_2h'])
        self.assertEqual((second['status'], second['conversation']['asking']), ('needs_input', 'more_2h'))
        third = self.result(message, answers=['再加18-20选4号场', '不用'],
                            asked_fields=['more_2h', 'more_2h'])
        self.assertEqual((third['status'], third['conversation']['asking']), ('needs_input', 'courts_2h'))
        self.assertIn('不能直接交叉组合', third['questions'][0])
        self.assertIsNone(second['proposal'])
        agreed = self.result(message, answers=['再加18-20选4号场', '不用', '1号和4号'],
                             asked_fields=['more_2h', 'more_2h', 'courts_2h'])
        self.assertEqual(agreed['status'], 'ready')
        self.assertEqual(len(agreed['proposal']['entries']), 4)

    def test_explicit_three_hour_intent_is_clarified_before_queue_generation(self):
        message = '后天14-16打3小时，1号场，不要一小时，不用候选'
        result = self.result(message)
        self.assertEqual((result['status'], result['conversation']['asking']), ('needs_input', 'windows_2h'))
        self.assertIn('当天累计时长还是单个时段', result['questions'][0])
        self.assertIsNone(result['proposal'])
        self.assertEqual(self.provider.calls, [])
        corrected = self.result(message, answers=['我说错了，按2小时'], asked_fields=['windows_2h'])
        self.assertEqual(corrected['status'], 'ready')
        self.assertEqual([(e['start_time'], e['duration_minutes']) for e in corrected['proposal']['entries']], [('14:00', 120)])

    def test_mixed_duration_time_slots_use_their_own_court_groups(self):
        result = self.result('后天14-16选1号场，18-19选4号场，不用候选')
        self.assertEqual(result['status'], 'ready')
        self.assertEqual([(e['start_time'], e['duration_minutes'], e['court_preference'])
                          for e in result['proposal']['entries']],
                         [('14:00', 120, '1号场'), ('18:00', 60, '4号场')])

    def test_yes_for_one_hour_and_no_to_more_candidates_are_separate_answers(self):
        message = '后天14-16，1号场，不要额外候选'
        result = self.result(message, answers=['我要，15-16，不用候选'], asked_fields=['want_1h'])
        self.assertEqual((result['status'], result['conversation']['asking']), ('needs_input', 'courts_1h'))
        self.assertIsNone(result['proposal'])
        result = self.result(message, answers=['我要，15-16，不用候选', '3号场'],
                             asked_fields=['want_1h', 'courts_1h'])
        self.assertEqual(result['status'], 'ready')
        self.assertEqual([(e['duration_minutes'], e['court_preference']) for e in result['proposal']['entries']],
                         [(120, '1号场'), (60, '3号场')])

    def test_invalid_time_is_not_silently_dropped_from_a_mixed_request(self):
        result = self.result('后天25-27和18-20，1号场，不要一小时，不用候选')
        self.assertEqual((result['status'], result['conversation']['asking']), ('needs_input', 'windows_2h'))
        self.assertIn('25-27', result['questions'][0])
        self.assertIsNone(result['proposal'])

    def test_saved_agent_entries_have_the_execution_query_scope(self):
        p = self.result()['proposal']
        queue = self.app.extensions['plan_service'].save_manual_queue('a', p['target_date'], p['base_version'], p['entries'], NOW, 'cred-a')
        self.assertTrue(all(c['query_scope_label'] == '羽毛球' for c in queue['candidates']))
