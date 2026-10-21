import json
import unittest
from datetime import date

from backend.ai.queue_draft import Draft, deserialize_draft, reconcile_legacy_slots, serialize_draft
from backend.ai.queue_slots import build_entries, build_slots
from backend.ai.queue_updates import apply_updates, restore_fields
from backend.ai.queue_policy import MAX_INVALID_WINDOWS_PER_GROUP
from backend.ai.queue_dialogue import empty_dialogue, load_dialogue, public_dialogue

TODAY = date(2026, 10, 20)


def decision(updates=(), unresolved=()):
    return {"updates": list(updates), "unresolved": list(unresolved)}


def update(field, operation, value):
    return {"field": field, "operation": operation, "value": value}


class QueueUpdateTests(unittest.TestCase):
    def test_legacy_one_hour_choice_is_migrated_only_when_the_old_answer_was_settled(self):
        selected = reconcile_legacy_slots(Draft(booking_mode='two_hour_only'), {
            'slots': [{'field': 'want_1h', 'status': 'verified', 'display': '要', 'active': True}],
        })
        self.assertEqual(selected.booking_mode, 'both')

        unanswered = reconcile_legacy_slots(Draft(booking_mode='both'), {
            'slots': [{'field': 'want_1h', 'status': 'empty', 'display': '', 'active': True}],
        })
        self.assertIsNone(unanswered.booking_mode)

        ambiguous_date = reconcile_legacy_slots(
            Draft(date_state='resolved', dates=(date(2026, 10, 27),)),
            {'slots': [{'field': 'target_date', 'status': 'ambiguous', 'display': '', 'active': True}]},
        )
        self.assertEqual(ambiguous_date.date_state, 'ambiguous')
        self.assertEqual(ambiguous_date.dates, ())

    def test_typed_updates_change_a_copy_and_keep_duration_groups_independent(self):
        original = Draft(booking_mode='both', date_state='resolved', dates=(date(2026, 10, 27),))
        original.g2.windows, original.g2.courts = [(600, 720)], [1, 2]
        original.g1.windows, original.g1.courts = [(1080, 1140)], [5]
        result = apply_updates(original, decision([
            update('windows_2h', 'replace', [{'start': '14:00', 'end': '16:00'}]),
            update('courts_2h', 'add', [4]),
            update('courts_1h', 'replace', [3]),
        ]))
        self.assertEqual(original.g2.windows, [(600, 720)])
        self.assertEqual(original.g2.courts, [1, 2])
        self.assertEqual(result.g2.windows, [(840, 960)])
        self.assertEqual(result.g2.courts, [1, 2, 4])
        self.assertEqual(result.g1.windows, [(1080, 1140)])
        self.assertEqual(result.g1.courts, [3])
        self.assertEqual([entry['duration_minutes'] for entry in build_entries(result)], [120] * 3 + [60])

    def test_operations_are_applied_to_existing_facts_without_replacing_other_values(self):
        draft = Draft(booking_mode='two_hour_only', date_state='resolved', dates=(date(2026, 10, 27),))
        draft.g2.windows, draft.g2.courts = [(600, 720), (720, 840)], [1, 2]
        result = apply_updates(draft, decision([
            update('windows_2h', 'remove', [{'start': '10:00', 'end': '12:00'}]),
            update('courts_2h', 'remove', [2]),
        ]))
        self.assertEqual(result.g2.windows, [(720, 840)])
        self.assertEqual(result.g2.courts, [1])

    def test_valid_time_facts_survive_invalid_siblings_until_explicit_resolution(self):
        draft = Draft(booking_mode='two_hour_only', date_state='resolved', dates=(date(2026, 10, 27),))
        invalid_batch = apply_updates(draft, decision([
            update('windows_2h', 'replace', [
                {'start': '14:00', 'end': '16:00'},
                {'start': '15:00', 'end': '19:00'}, {'start': '21:00', 'end': '23:00'},
            ]),
        ]))
        invalid_slot = build_slots(invalid_batch, TODAY)['windows_2h']
        self.assertEqual(invalid_slot.status.value, 'invalid')
        self.assertEqual(invalid_slot.value, [(840, 960)])
        self.assertIn('15-19', invalid_slot.detail)
        self.assertIn('还有1个无效时段', invalid_slot.detail)

        added = apply_updates(invalid_batch, decision([
            update('windows_2h', 'add', [{'start': '18:00', 'end': '20:00'}]),
        ]))
        still_blocked = build_slots(added, TODAY)['windows_2h']
        self.assertEqual(still_blocked.status.value, 'invalid')
        self.assertEqual(still_blocked.value, [(840, 960), (1080, 1200)])
        self.assertIn('15-19', still_blocked.detail)
        self.assertIn('还有1个无效时段', still_blocked.detail)

        first_removed = apply_updates(added, decision([
            update('windows_2h', 'remove', [{'start': '15:00', 'end': '19:00'}]),
        ]))
        still_blocked = build_slots(first_removed, TODAY)['windows_2h']
        self.assertEqual(still_blocked.status.value, 'invalid')
        self.assertIn('21-23', still_blocked.detail)
        removed = apply_updates(first_removed, decision([
            update('windows_2h', 'remove', [{'start': '21:00', 'end': '23:00'}]),
        ]))
        resolved = build_slots(removed, TODAY)['windows_2h']
        self.assertEqual(resolved.status.value, 'proposed')
        self.assertEqual(resolved.display, '14-16、18-20')

    def test_server_constraints_mark_invalid_time_and_court_values_blocking(self):
        draft = Draft(booking_mode='two_hour_only', date_state='resolved', dates=(date(2026, 10, 27),))
        invalid = apply_updates(draft, decision([
            update('windows_2h', 'replace', [{'start': '22:00', 'end': '24:00'}]),
            update('courts_2h', 'replace', [11]),
        ]))
        slots = build_slots(invalid, TODAY)
        self.assertEqual(slots['windows_2h'].status.value, 'invalid')
        self.assertEqual(slots['courts_2h'].status.value, 'invalid')
        self.assertIn('09:00–22:00', slots['windows_2h'].detail)
        self.assertIn('11号场', slots['courts_2h'].detail)
        self.assertEqual(draft.g2.windows, [])

    def test_wrong_group_duration_and_unsupported_duration_remain_clarifications(self):
        draft = Draft(booking_mode='two_hour_only', date_state='resolved', dates=(date(2026, 10, 27),))
        wrong_group = apply_updates(draft, decision([
            update('windows_2h', 'replace', [{'start': '14:00', 'end': '15:00'}]),
        ]))
        self.assertEqual(build_slots(wrong_group, TODAY)['windows_2h'].status.value, 'invalid')

        unsupported = apply_updates(draft, decision([], [{
            'field': 'windows_2h', 'evidence': '打3小时', 'issue': 'unsupported_duration',
            'duration_minutes': 180,
        }]))
        self.assertEqual(build_slots(unsupported, TODAY)['windows_2h'].status.value, 'ambiguous')
        self.assertIn('累计时长还是单个时段', build_slots(unsupported, TODAY)['windows_2h'].detail)

    def test_unresolved_scope_and_overlap_confirmations_update_only_the_target_group(self):
        draft = Draft(booking_mode='both', date_state='resolved', dates=(date(2026, 10, 27),))
        draft.g2.windows = [(840, 960), (900, 1020)]
        result = apply_updates(draft, decision([
            update('overlap_2h', 'confirm', 'keep'),
        ], [
            {'field': 'courts_1h', 'evidence': '14-15选1号，18-19选4号', 'issue': 'scoped_preferences'},
        ]))
        slots = build_slots(result, TODAY)
        self.assertEqual(slots['overlap_2h'].status.value, 'verified')
        self.assertEqual(slots['overlap_1h'].status.value, 'verified')
        self.assertEqual(slots['courts_1h'].status.value, 'ambiguous')
        self.assertIn('不能直接交叉组合', slots['courts_1h'].detail)

    def test_serialized_state_is_json_safe_and_rejects_corruption(self):
        draft = Draft(booking_mode='both', date_state='resolved', dates=(date(2026, 10, 27),), asked=['windows_2h'])
        draft.g2.windows = [(840, 960), (900, 1020)]
        draft.g2.courts = [1, 4]
        draft.g2.acked = {frozenset({(840, 960), (900, 1020)})}
        payload = json.loads(json.dumps(serialize_draft(draft)))
        restored = deserialize_draft(payload)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.booking_mode, 'both')
        self.assertEqual(restored.dates, draft.dates)
        self.assertEqual(restored.g2.windows, draft.g2.windows)
        self.assertEqual(restored.g2.courts, draft.g2.courts)
        self.assertEqual(restored.g2.acked, draft.g2.acked)
        self.assertEqual(restored.asked, ['windows_2h'])
        old_payload = serialize_draft(draft)
        for group in old_payload['groups'].values():
            group.pop('invalid_windows')
        restored_v3 = deserialize_draft(old_payload)
        self.assertIsNotNone(restored_v3)
        self.assertEqual(restored_v3.g2.invalid_windows, [])
        self.assertIsNone(deserialize_draft({'booking_mode': 'admin', 'groups': {}}))

    def test_serialized_invalid_window_bound_matches_the_maximum_conversation_size(self):
        draft = Draft()
        draft.g2.invalid_windows = [(index, index + 1, 'bad_length', str(index))
                                    for index in range(MAX_INVALID_WINDOWS_PER_GROUP)]
        payload = json.loads(json.dumps(serialize_draft(draft)))
        restored = deserialize_draft(payload)
        self.assertIsNotNone(restored)
        self.assertEqual(len(restored.g2.invalid_windows), MAX_INVALID_WINDOWS_PER_GROUP)
        payload['groups']['2h']['invalid_windows'].append({
            'start': MAX_INVALID_WINDOWS_PER_GROUP, 'end': MAX_INVALID_WINDOWS_PER_GROUP + 1,
            'issue': 'bad_length', 'label': 'overflow',
        })
        self.assertIsNone(deserialize_draft(payload))

    def test_canonical_snapshot_cannot_smuggle_invalid_domain_values(self):
        draft=Draft(booking_mode='two_hour_only')
        draft.g2.windows=[(840,1020)]
        self.assertIsNone(deserialize_draft(serialize_draft(draft)))
        draft.g2.windows=[(840,960)]
        draft.g2.courts=[11]
        self.assertIsNone(deserialize_draft(serialize_draft(draft)))
        broken=serialize_draft(Draft())
        broken['date_state']=[]
        self.assertIsNone(deserialize_draft(broken))

    def test_dialogue_metadata_is_validated_and_model_context_does_not_repeat_undo_snapshots(self):
        state=empty_dialogue()
        state['sources']['courts_2h']={'business_date':'2026-10-21','operations':[
            {'operation':'add','value':[1],'evidence':'加上1号场'} for _ in range(12)]}
        self.assertIsNotNone(load_dialogue(state))
        public=public_dialogue(state)
        self.assertNotIn('undo',public)
        self.assertNotIn('review_cache',public)
        self.assertEqual(len(public['fact_sources']['courts_2h']['operations']),3)
        state['sources']['courts_2h']['operations'][0]['value']='1'
        self.assertIsNone(load_dialogue(state))

    def test_partial_rollback_keeps_bindings_consistent_with_both_current_fields(self):
        before=Draft(booking_mode='two_hour_only')
        before.g2.windows,before.g2.courts=[(840,960)],[1]
        current=apply_updates(before,decision([update('windows_2h','replace',[{'start':'18:00','end':'20:00'}]),update('courts_2h','replace',[4])]))
        restored=restore_fields(current,before,['windows_2h'])
        self.assertEqual(restored.g2.courts,[4])
        self.assertEqual(restored.g2.court_bindings,{(840,960):[4]})
        restored=restore_fields(current,before,['courts_2h'])
        self.assertEqual(restored.g2.windows,[(1080,1200)])
        self.assertEqual(restored.g2.court_bindings,{(1080,1200):[1]})


if __name__ == "__main__":
    unittest.main()
