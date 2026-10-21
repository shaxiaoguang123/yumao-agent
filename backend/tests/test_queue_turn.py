import json
import unittest

from backend.ai.queue_turn import parse_turn_decision


class QueueTurnTests(unittest.TestCase):
    def decision(self, **changes):
        value = {
            "kind": "answer", "updates": [], "unresolved": [], "reply": "",
            "next_field": "target_date", "next_question": "想订哪一天？例如2026-10-27。",
        }
        value.update(changes)
        return value

    def update(self, field, operation, value, evidence):
        return {"field": field, "operation": operation, "value": value, "evidence": evidence}

    def test_accepts_multiple_typed_updates_with_exact_user_evidence(self):
        latest = "下周二，14-16和18-20，保留1到4号场"
        value = self.decision(updates=[
            self.update("target_date", "set", "2026-10-27", "下周二"),
            self.update("windows_2h", "replace", [
                {"start": "14:00", "end": "16:00"}, {"start": "18:00", "end": "20:00"},
            ], "14-16和18-20"),
            self.update("courts_2h", "replace", [1, 2, 3, 4], "保留1到4号场"),
        ], next_field="windows_1h", next_question="还想排1小时吗？例如14-15。")
        parsed = parse_turn_decision(json.dumps(value, ensure_ascii=False), latest)
        self.assertEqual([item["field"] for item in parsed["updates"]], [
            "target_date", "windows_2h", "courts_2h",
        ])

    def test_question_only_cannot_update_booking_facts(self):
        value = self.decision(kind="question", reply="1小时和2小时分别组队列。",
                              updates=[self.update("courts_2h", "replace", [1], "1号场")])
        self.assertIsNone(parse_turn_decision(json.dumps(value, ensure_ascii=False), "1号场可以吗？"))
        value["updates"] = []
        value["next_field"] = "courts_2h"
        parsed = parse_turn_decision(json.dumps(value, ensure_ascii=False), "1号场可以吗？")
        self.assertEqual(parsed["kind"], "question")

    def test_unresolved_and_mixed_turns_require_grounded_evidence(self):
        latest = "10号，我想问一个问题"
        value = self.decision(kind="mixed", unresolved=[{"field": "target_date", "evidence": "10号"}],
                              reply="我会先确认月份。")
        self.assertIsNotNone(parse_turn_decision(json.dumps(value, ensure_ascii=False), latest))
        value["unresolved"][0]["evidence"] = "下个月10号"
        self.assertIsNone(parse_turn_decision(json.dumps(value, ensure_ascii=False), latest))
        value["unresolved"][0]["evidence"] = "10号"
        value["reply"] = ""
        self.assertIsNone(parse_turn_decision(json.dumps(value, ensure_ascii=False), latest))

    def test_unresolved_issue_codes_are_typed_and_field_scoped(self):
        value = self.decision(unresolved=[{
            "field": "windows_2h", "evidence": "打3小时", "issue": "unsupported_duration",
            "duration_minutes": 180,
        }], reply="你说的3小时是单个时段还是当天累计？")
        parsed = parse_turn_decision(json.dumps(value, ensure_ascii=False), "后天14-16打3小时")
        self.assertEqual(parsed["unresolved"][0]["duration_minutes"], 180)
        value["unresolved"][0]["issue"] = "scoped_preferences"
        self.assertIsNone(parse_turn_decision(json.dumps(value, ensure_ascii=False), "后天14-16打3小时"))
        value["unresolved"][0]["issue"] = "unsupported_duration"
        value["unresolved"][0]["duration_minutes"] = True
        self.assertIsNone(parse_turn_decision(json.dumps(value, ensure_ascii=False), "后天14-16打3小时"))

    def test_rejects_duplicate_unresolved_fields_but_keeps_partial_facts(self):
        unresolved = {"field": "windows_2h", "evidence": "15-19", "issue": "bad_length"}
        value = self.decision(unresolved=[unresolved, dict(unresolved)])
        self.assertIsNone(parse_turn_decision(json.dumps(value, ensure_ascii=False), "15-19"))
        value = self.decision(
            updates=[self.update("windows_2h", "replace", [{"start": "14:00", "end": "16:00"}], "14-16")],
            unresolved=[{"field": "windows_2h", "evidence": "3小时", "issue": "unsupported_duration",
                         "duration_minutes": 180}],
        )
        parsed = parse_turn_decision(json.dumps(value, ensure_ascii=False), "14-16但打3小时")
        self.assertEqual(parsed["updates"][0]["value"], [{"start": "14:00", "end": "16:00"}])
        self.assertEqual(parsed["unresolved"][0]["duration_minutes"], 180)

    def test_question_turn_requires_a_contextual_answer(self):
        value = self.decision(kind="question", updates=[], unresolved=[], reply="",
                              next_field="booking_mode", next_question="选哪种队列？例如1。")
        self.assertIsNone(parse_turn_decision(json.dumps(value, ensure_ascii=False), "为什么要分开确认？"))

    def test_execution_request_is_a_typed_no_update_route(self):
        value = self.decision(intent="execution_request", updates=[], unresolved=[], reply="我不能直接预约或付款。",
                              next_field=None, next_question="")
        parsed = parse_turn_decision(json.dumps(value, ensure_ascii=False), "帮我直接预约并付款")
        self.assertEqual(parsed["intent"], "execution_request")
        value["updates"] = [self.update("courts_2h", "replace", [1], "1号场")]
        self.assertIsNone(parse_turn_decision(json.dumps(value, ensure_ascii=False), "帮我直接预约并付款，1号场"))

    def test_rejects_wrong_fields_operations_types_and_model_invented_evidence(self):
        latest = "保留1-8"
        cases = [
            self.decision(updates=[self.update("payment", "set", True, "保留1-8")]),
            self.decision(updates=[self.update("courts_2h", "set", [1, 8], "保留1-8")]),
            self.decision(updates=[self.update("windows_2h", "replace", [{"start": "14", "end": "16"}], "保留1-8")]),
            self.decision(updates=[self.update("courts_2h", "replace", [1, 8], "1号和8号")]),
            self.decision(next_field="payment"),
            self.decision(kind="mixed"),
        ]
        for value in cases:
            with self.subTest(value=value):
                self.assertIsNone(parse_turn_decision(json.dumps(value, ensure_ascii=False), latest))

    def test_keeps_multiple_operations_for_one_field_in_order(self):
        value = self.decision(updates=[
            self.update('windows_2h', 'replace', [{'start': '14:00', 'end': '16:00'}], '14-16'),
            self.update('windows_2h', 'add', [{'start': '18:00', 'end': '20:00'}], '18-20'),
        ])
        parsed = parse_turn_decision(json.dumps(value, ensure_ascii=False), '14-16后再加18-20')
        self.assertEqual([item['operation'] for item in parsed['updates']], ['replace', 'add'])

    def test_preserves_out_of_range_court_numbers_for_server_validation(self):
        values = list(range(1, 12))
        parsed = parse_turn_decision(json.dumps(self.decision(updates=[
            self.update("courts_2h", "replace", values, "1到11号场"),
        ]), ensure_ascii=False), "只保留1到11号场")
        self.assertEqual(parsed["updates"][0]["value"], values)

    def test_rejects_duplicate_keys_non_json_and_prompt_injection_outputs(self):
        self.assertIsNone(parse_turn_decision('{"kind":"answer","kind":"question"}', "你好"))
        self.assertIsNone(parse_turn_decision("not json", "你好"))
        value = self.decision(reply="sk-" + "a" * 24)
        self.assertIsNone(parse_turn_decision(json.dumps(value, ensure_ascii=False), "你好"))
        value = self.decision(reply="支付密码：314159")
        self.assertIsNone(parse_turn_decision(json.dumps(value, ensure_ascii=False), "你好"))

    def test_natural_multiline_options_and_answer_only_focus_are_valid(self):
        value=self.decision(next_field='overlap_2h',next_question='要怎么处理？\n1. 都保留\n2. 去掉后一个')
        self.assertIsNotNone(parse_turn_decision(json.dumps(value,ensure_ascii=False),'14-16和15-17'))
        value=self.decision(kind='question',reply='还缺场地。',next_field='courts_2h',next_question='',next_action='answer')
        self.assertIsNotNone(parse_turn_decision(json.dumps(value,ensure_ascii=False),'还缺什么？'))
        value['reply']='不能有空字符\x00'
        self.assertIsNone(parse_turn_decision(json.dumps(value,ensure_ascii=False),'还缺什么？'))

    def test_mixed_question_and_edit_action_do_not_require_a_fake_fact_update(self):
        value=self.decision(kind='mixed',reply='我记得你选的是1号场。',next_field='target_date',next_question='日期想改成哪天？',
                            dialogue_action={'type':'begin_edit','fields':['target_date'],'evidence':'先改一下日期'})
        self.assertIsNotNone(parse_turn_decision(json.dumps(value,ensure_ascii=False),'先改一下日期，你还记得我选的场地吗？'))


if __name__ == "__main__":
    unittest.main()
