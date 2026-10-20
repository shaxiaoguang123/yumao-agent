import random
import unittest
from datetime import date

from backend.ai import conversation as conv
from backend.ai.conversation import Phase, Reason, Slot, SlotStatus, can_follow, decide
from backend.ai.queue_draft import fold
from backend.ai.queue_slots import build_entries, build_slots, question, strip

TODAY = date(2026, 10, 18)


def slots(**status):
    return {field: Slot(field, status.get(field, SlotStatus.VERIFIED), reason=(
        Reason.MISSING if status.get(field) is SlotStatus.EMPTY else None
    )) for field in conv.PRIORITY}


def run(turns, asked=(), kinds=None):
    draft = fold(turns, list(asked), TODAY, turn_kinds=kinds)
    built = build_slots(draft, TODAY)
    return decide(built, list(asked), len(turns) - 1), built, draft


def entries(draft):
    return [(e["duration_minutes"], e["court_preference"], e["start_time"]) for e in build_entries(draft)]


class DecideTests(unittest.TestCase):
    def test_fixed_order_starts_with_mode_and_keeps_duration_groups_separate(self):
        self.assertEqual(conv.PRIORITY, (
            "booking_mode", "target_date", "windows_2h", "overlap_2h", "courts_2h",
            "windows_1h", "overlap_1h", "courts_1h",
        ))
        state = decide(slots(booking_mode=SlotStatus.EMPTY, target_date=SlotStatus.EMPTY), [], 0)
        self.assertEqual((state.phase, state.asking), (Phase.COLLECTING, "booking_mode"))
        state = decide(slots(target_date=SlotStatus.EMPTY, windows_2h=SlotStatus.EMPTY), ["booking_mode"], 1)
        self.assertEqual(state.asking, "target_date")

    def test_repair_and_turn_limits_remain_deterministic(self):
        self.assertEqual(decide(slots(target_date=SlotStatus.AMBIGUOUS), [], 0).phase, Phase.REPAIRING)
        self.assertEqual(decide(slots(courts_2h=SlotStatus.INVALID), [], 0).phase, Phase.REPAIRING)
        stalled = decide(slots(courts_2h=SlotStatus.EMPTY), ["courts_2h"] * 3, 3)
        self.assertEqual((stalled.phase, stalled.escalation), (Phase.ESCALATED, "stalled"))
        capped = decide(slots(courts_2h=SlotStatus.EMPTY), [None] * conv.MAX_ANSWERS, conv.MAX_ANSWERS)
        self.assertEqual(capped.escalation, "turn_limit")

    def test_inactive_groups_do_not_block(self):
        built = slots()
        built["windows_1h"] = Slot("windows_1h", SlotStatus.EMPTY, active=False)
        self.assertEqual(decide(built, [], 0).phase, Phase.READY)
        built["windows_1h"] = Slot("windows_1h", SlotStatus.EMPTY, active=True)
        self.assertEqual(decide(built, [], 0).asking, "windows_1h")

    def test_execution_requests_are_refused_and_terminal_states_do_not_continue(self):
        self.assertEqual(decide(slots(target_date=SlotStatus.EMPTY), [], 0, has_command=True).phase, Phase.UNSUPPORTED)
        for phase in conv.TERMINAL:
            self.assertEqual(conv.TRANSITIONS[phase], frozenset())
            self.assertFalse(can_follow(phase, Phase.COLLECTING))


class BookingQueueConversationTests(unittest.TestCase):
    def test_mode_is_required_even_when_a_date_time_and_court_were_provided(self):
        state, built, draft = run(["后天 14-16 1号场"])
        self.assertEqual(state.asking, "booking_mode")
        self.assertEqual(built["booking_mode"].status, SlotStatus.EMPTY)
        self.assertFalse(draft.effective(120))
        self.assertEqual(draft.g2.courts, [1])

    def test_choice_codes_and_explicit_mode_phrases(self):
        for code, expected in (("1", "two_hour_only"), ("A", "two_hour_only"),
                               ("2", "one_hour_only"), ("B", "one_hour_only"),
                               ("3", "both"), ("C", "both")):
            with self.subTest(code=code):
                _, built, draft = run(["想订场", code], ["booking_mode"])
                self.assertEqual(draft.booking_mode, expected)
                self.assertEqual(built["booking_mode"].display, {
                    "two_hour_only": "只抢2小时", "one_hour_only": "只抢1小时",
                    "both": "1小时和2小时都抢（独立队列）",
                }[expected])
        self.assertEqual(run(["后天 只要一小时 14-15 3号场"])[2].booking_mode, "one_hour_only")
        self.assertEqual(run(["后天 14-16、15-16"])[2].booking_mode, "both")

    def test_complete_required_flow_cannot_skip_the_venue_step(self):
        turns, asked = ["想订场"], []
        expected = ["booking_mode", "target_date", "windows_2h", "courts_2h", "windows_1h", "courts_1h"]
        answers = ["3", "后天", "14-16、18-20", "1号场", "15-16", "3号场"]
        for index, answer in enumerate(answers):
            state, _, _ = run(turns, asked)
            self.assertEqual(state.asking, expected[index])
            asked.append(state.asking)
            turns.append(answer)
        state, built, draft = run(turns, asked)
        self.assertEqual(state.phase, Phase.READY)
        self.assertEqual([(e["duration_minutes"], e["court_preference"]) for e in build_entries(draft)],
                         [(120, "1号场"), (120, "1号场"), (60, "3号场")])
        self.assertEqual(built["courts_1h"].display, "3号")
        self.assertEqual([item["label"] for item in strip(draft, built, None)], ["队列类型", "日期", "2小时", "1小时"])

    def test_only_one_hour_never_inherits_two_hour_values(self):
        turns = ["想订场", "2", "后天", "14-15"]
        asked = ["booking_mode", "target_date", "windows_1h"]
        state, _, draft = run(turns, asked)
        self.assertEqual((state.asking, draft.booking_mode), ("courts_1h", "one_hour_only"))
        self.assertEqual(draft.g2.windows, [])
        self.assertEqual(draft.g2.courts, [])
        state, _, draft = run([*turns, "3号场"], [*asked, "courts_1h"])
        self.assertEqual(state.phase, Phase.READY)
        self.assertEqual(entries(draft), [(60, "3号场", "14:00")])

    def test_both_duration_groups_have_separate_windows_and_courts(self):
        turns = ["后天 两小时14-16用1号场，一小时15-16"]
        state, _, draft = run(turns)
        self.assertEqual((draft.booking_mode, state.asking), ("both", "courts_1h"))
        self.assertEqual(draft.g2.courts, [1])
        self.assertEqual(draft.g1.courts, [])
        state, _, draft = run([*turns, "3号场"], ["courts_1h"])
        self.assertEqual(state.phase, Phase.READY)
        self.assertEqual(entries(draft), [(120, "1号场", "14:00"), (60, "3号场", "15:00")])

    def test_question_turn_is_answered_separately_and_not_folded_as_booking_data(self):
        turns = ["后天 只要2小时 14-16", "1号场可以吗？"]
        asked = ["courts_2h"]
        kinds = ["answer", "question"]
        draft = fold(turns, asked, TODAY, turn_kinds=kinds)
        self.assertEqual(draft.g2.courts, [])
        state, built, _ = run(turns, asked, kinds)
        self.assertEqual(state.asking, "courts_2h")
        self.assertIn("1～10", question(built, state.asking, draft, TODAY))

    def test_dates_times_and_courts_are_validated_without_silent_drops(self):
        _, built, _ = run(["只要2小时 10月17日 14-16 1号场"])
        self.assertEqual(built["target_date"].status, SlotStatus.INVALID)
        _, built, draft = run(["只要2小时 后天 14-17 1号场"])
        self.assertEqual(built["windows_2h"].status, SlotStatus.INVALID)
        self.assertIn("不是 1 小时或 2 小时", question(built, "windows_2h", draft, TODAY))
        _, built, draft = run(["只要2小时 后天 21-23 1号场"])
        self.assertIn("09:00–22:00", question(built, "windows_2h", draft, TODAY))
        _, built, draft = run(["只要2小时 后天 14-16 11号场"])
        self.assertEqual(built["courts_2h"].status, SlotStatus.INVALID)
        self.assertIn("1～10号场", question(built, "courts_2h", draft, TODAY))

    def test_overlapping_candidates_require_resolution_but_can_be_kept(self):
        turns = ["只要2小时 后天14-16、15-17 1号场"]
        state, built, draft = run(turns)
        self.assertEqual(state.asking, "overlap_2h")
        self.assertIn("14-16 与 15-17", question(built, state.asking, draft, TODAY))
        state, _, draft = run([*turns, "都保留"], ["overlap_2h"])
        self.assertEqual(state.phase, Phase.READY)
        self.assertEqual(len(draft.g2.windows), 2)

    def test_unclear_overlap_answers_never_count_as_confirmation(self):
        turns = ["只要2小时 后天14-16、15-17 1号场"]
        asked = []
        for answer in ("不确定", "还是不清楚"):
            turns.append(answer)
            asked.append("overlap_2h")
            state, built, _ = run(turns, asked)
            self.assertEqual((state.phase, state.asking), (Phase.REPAIRING, "overlap_2h"))
            self.assertEqual(built["overlap_2h"].status, SlotStatus.AMBIGUOUS)

        turns.append("我不知道")
        asked.append("overlap_2h")
        state, built, _ = run(turns, asked)
        self.assertEqual((state.phase, state.escalation), (Phase.ESCALATED, "stalled"))
        self.assertEqual(built["overlap_2h"].status, SlotStatus.AMBIGUOUS)

    def test_candidate_limit_is_enforced(self):
        text = "只要2小时 后天 9-11、11-13、13-15、15-17、17-19、19-21 1到10号场"
        state, built, draft = run([text])
        self.assertEqual(state.asking, "courts_2h")
        self.assertEqual(built["courts_2h"].status, SlotStatus.INVALID)
        self.assertIn("最多 32 项", built["courts_2h"].detail)


class ReplayInvariants(unittest.TestCase):
    ANSWERS = ["1", "2", "3", "后天", "14-16", "18-20", "1号场", "3号场", "都保留", "去掉15-17", "11号场", "14-17", "下周六"]

    def play(self, rng):
        turns, asked, phases = [rng.choice(["想订场", "后天 14-16", "后天 只要2小时 14-16"])], [], []
        for _ in range(conv.MAX_ANSWERS + 3):
            draft = fold(turns, asked, TODAY)
            built = build_slots(draft, TODAY)
            state = decide(built, asked, len(turns) - 1)
            phases.append(state.phase)
            if state.phase in conv.TERMINAL:
                return state, draft, asked, phases
            asked.append(state.asking)
            turns.append(rng.choice(self.ANSWERS))
        self.fail("the conversation never terminated")

    def test_random_conversations_terminate_with_valid_queues(self):
        rng = random.Random(7)
        for _ in range(500):
            state, draft, asked, phases = self.play(rng)
            self.assertLessEqual(len(asked), conv.MAX_ANSWERS)
            for earlier, later in zip(phases, phases[1:]):
                self.assertTrue(can_follow(earlier, later))
            if state.phase is Phase.ESCALATED:
                self.assertIn(state.escalation, {"stalled", "turn_limit"})
            if state.phase is Phase.READY:
                self.assertTrue(build_entries(draft))
                self.assertLessEqual(len(build_entries(draft)), 32)

    def test_no_open_field_is_skipped(self):
        rng = random.Random(31)
        for _ in range(300):
            turns, asked = [rng.choice(["想订场", "只要2小时 后天 14-16"])], []
            for _ in range(10):
                draft = fold(turns, asked, TODAY)
                built = build_slots(draft, TODAY)
                state = decide(built, asked, len(turns) - 1)
                if state.phase in conv.TERMINAL:
                    break
                self.assertIn(state.asking, [slot.field for slot in conv.blocking_slots(built)])
                self.assertTrue(question(built, state.asking, draft, TODAY))
                asked.append(state.asking)
                turns.append(rng.choice(self.ANSWERS))


if __name__ == "__main__":
    unittest.main()
