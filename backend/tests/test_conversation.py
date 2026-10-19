import itertools
import random
import unittest
from datetime import date

from backend.ai import conversation as conv
from backend.ai.conversation import Phase, Reason, Slot, SlotStatus, can_follow, decide
from backend.ai.queue_draft import fold
from backend.ai.queue_slots import build_entries, build_slots, question, strip

TODAY = date(2026, 10, 18)  # a Sunday


def slots(**status):
    built = {}
    for field in conv.PRIORITY:
        value = status.get(field, SlotStatus.VERIFIED)
        reason = Reason.MISSING if value is SlotStatus.EMPTY else None
        built[field] = Slot(field, value, None, "", None, reason)
    return built


class DecideTests(unittest.TestCase):
    def test_priority_picks_the_first_open_slot(self):
        state = decide(slots(courts_2h=SlotStatus.EMPTY, windows_2h=SlotStatus.EMPTY), [], 0)
        self.assertEqual((state.phase, state.asking, state.reason), (Phase.COLLECTING, "windows_2h", Reason.MISSING))

    def test_the_questions_follow_the_conversation_the_user_described(self):
        self.assertEqual(conv.PRIORITY[:5], ("target_date", "windows_2h", "more_2h", "overlap_2h", "courts_2h"))
        self.assertLess(conv.PRIORITY.index("courts_2h"), conv.PRIORITY.index("want_1h"))

    def test_ambiguous_and_invalid_are_repairing(self):
        self.assertEqual(decide(slots(target_date=SlotStatus.AMBIGUOUS), [], 0).phase, Phase.REPAIRING)
        self.assertEqual(decide(slots(courts_2h=SlotStatus.INVALID), [], 0).phase, Phase.REPAIRING)

    def test_inactive_slots_never_block(self):
        built = slots()
        built["windows_1h"] = Slot("windows_1h", SlotStatus.EMPTY, active=False)
        self.assertEqual(decide(built, [], 0).phase, Phase.READY)
        built["windows_1h"] = Slot("windows_1h", SlotStatus.EMPTY, active=True)
        self.assertEqual(decide(built, [], 0).asking, "windows_1h")

    def test_nothing_open_means_ready_even_on_the_last_turn(self):
        self.assertEqual(decide(slots(), [None] * conv.MAX_ANSWERS, conv.MAX_ANSWERS).phase, Phase.READY)

    def test_command_wins_over_everything(self):
        self.assertEqual(decide(slots(target_date=SlotStatus.EMPTY), [], 0, has_command=True).phase, Phase.UNSUPPORTED)

    def test_a_field_asked_three_times_stalls(self):
        state = decide(slots(courts_2h=SlotStatus.EMPTY), ["courts_2h"] * 3, 3)
        self.assertEqual((state.phase, state.escalation, state.asking), (Phase.ESCALATED, "stalled", "courts_2h"))
        self.assertEqual(decide(slots(courts_2h=SlotStatus.EMPTY), ["courts_2h"] * 2, 2).phase, Phase.COLLECTING)

    def test_turn_limit_escalates_only_when_something_is_open(self):
        state = decide(slots(courts_2h=SlotStatus.EMPTY), [None] * conv.MAX_ANSWERS, conv.MAX_ANSWERS)
        self.assertEqual((state.phase, state.escalation), (Phase.ESCALATED, "turn_limit"))

    def test_terminal_phases_have_no_successor(self):
        for phase in conv.TERMINAL:
            self.assertEqual(conv.TRANSITIONS[phase], frozenset())
            self.assertFalse(can_follow(phase, Phase.COLLECTING))
        self.assertTrue(can_follow(Phase.REPAIRING, Phase.ESCALATED))


def run(turns, asked=()):
    """One service turn without the web layer: (decision, slots, draft)."""
    draft = fold(turns, list(asked), TODAY)
    built = build_slots(draft, TODAY)
    return decide(built, list(asked), len(turns) - 1), built, draft


def entries(draft):
    return [(e["court_preference"], e["start_time"], e["duration_minutes"]) for e in build_entries(draft)]


class FlowTests(unittest.TestCase):
    """The conversation the product owner described, step by step."""

    def test_date_comes_first_and_is_echoed_with_its_weekday(self):
        state, built, draft = run(["我想订场"])
        self.assertEqual(state.asking, "target_date")
        state, built, draft = run(["后天"], [])
        self.assertEqual(state.asking, "windows_2h")
        self.assertEqual(built["target_date"].display, "10月20日 周二")
        self.assertIn("已记录：10月20日 周二", question(built, state.asking, draft, TODAY))

    def test_only_accepting_the_named_window_and_courts_skips_more_candidate_questions(self):
        state, built, draft = run(["后天 14-16，1号和4号场，只接受这两个场地和这个时段，不要一小时候选"])
        self.assertEqual(state.phase, Phase.READY)
        self.assertEqual(entries(draft), [("1号场", "14:00", 120), ("4号场", "14:00", 120)])
        self.assertFalse(draft.effective(60))

    def test_two_hour_windows_then_more_candidates(self):
        state, built, draft = run(["后天", "14-16"], ["target_date"])
        self.assertEqual(state.asking, "more_2h")
        self.assertIn("还要再加候选时间", question(built, state.asking, draft, TODAY))

    def test_adding_a_window_keeps_the_question_open_until_the_user_says_enough(self):
        state, _, draft = run(["后天", "14-16", "18-20"], ["target_date", "more_2h"])
        self.assertEqual((state.asking, [w for w in draft.g2.windows]), ("more_2h", [(840, 960), (1080, 1200)]))
        state, _, _ = run(["后天", "14-16", "18-20", "不用了"], ["target_date", "more_2h", "more_2h"])
        self.assertEqual(state.asking, "courts_2h")

    def test_overlapping_windows_are_listed_and_the_user_chooses(self):
        state, built, draft = run(["后天", "14-16", "15-17", "不用"], ["target_date", "windows_2h", "more_2h"])
        self.assertEqual(state.asking, "overlap_2h")
        text = question(built, "overlap_2h", draft, TODAY)
        self.assertIn("14-16 与 15-17", text)
        self.assertIn("备选", text)
        state, _, draft = run(["后天", "14-16", "15-17", "不用", "去掉15-17"], ["target_date", "windows_2h", "more_2h", "overlap_2h"])
        self.assertEqual((state.asking, draft.g2.windows), ("courts_2h", [(840, 960)]))

    def test_keeping_overlapping_windows_is_allowed(self):
        state, _, draft = run(["后天 14-16 15-17 不用候选", "都保留"], ["overlap_2h"])
        self.assertEqual((state.asking, len(draft.g2.windows)), ("courts_2h", 2))

    def test_the_users_example_courts_apply_to_every_window_in_time_order(self):
        state, built, draft = run(["后天 14-16 和 18-20 不用候选 1号4号场 不要一小时"])
        self.assertEqual(state.phase, Phase.READY)
        self.assertEqual(entries(draft), [("1号场", "14:00", 120), ("4号场", "14:00", 120),
                                          ("1号场", "18:00", 120), ("4号场", "18:00", 120)])

    def test_a_weekday_that_could_mean_today_or_next_week_is_asked_again(self):
        # TODAY is a Sunday: "周日" is today or the 25th, so it must not be guessed.
        state, built, draft = run(["周日"])
        self.assertEqual((state.asking, built["target_date"].status), ("target_date", SlotStatus.AMBIGUOUS))
        self.assertEqual(draft.date_state, "ambiguous")
        state, built, _ = run(["周日", "下周日"], ["target_date"])
        self.assertEqual((state.asking, built["target_date"].display), ("windows_2h", "10月25日 周日"))

    def test_the_more_candidates_question_is_asked_at_most_twice(self):
        turns, asked = ["后天 14-16"], []
        for expected in ("more_2h", "more_2h", "courts_2h"):
            state, _, _ = run(turns, asked)
            self.assertEqual(state.asking, expected)
            asked.append(state.asking)
            turns.append("再想想")
        self.assertEqual(asked.count("more_2h"), 2)

    def test_the_one_hour_question_is_asked_at_most_twice(self):
        turns, asked = ["后天 14-16 不用候选 1号场"], []
        for _ in range(2):
            state, _, _ = run(turns, asked)
            self.assertEqual(state.asking, "want_1h")
            asked.append(state.asking)
            turns.append("再想想")
        state, _, draft = run(turns, asked)
        self.assertEqual(state.phase, Phase.READY)
        self.assertEqual({e[2] for e in entries(draft)}, {120})

    def test_a_spoken_length_governs_only_the_courts_that_follow_it(self):
        _, _, draft = run(["后天 14-16 15-16 2小时用1号4号场 1小时用3号场 不用候选"])
        self.assertEqual((draft.g2.courts, draft.g1.courts), ([1, 4], [3]))
        _, _, draft = run(["后天 14-16 15-16 不要一小时 1号4号场 不用候选"])
        self.assertEqual(draft.g2.courts, [1, 4])

    def test_one_hour_and_two_hour_queues_require_independent_court_choices(self):
        turns = ["后天 14-16 18-20 不用候选 1号4号场", "要", "15-16", "不用"]
        asked = ["want_1h", "windows_1h", "more_1h"]
        state, _, draft = run(turns, asked)
        self.assertEqual(state.asking, "courts_1h")
        self.assertEqual(draft.courts_of(60), [])
        self.assertEqual([e[2] for e in entries(draft)], [120] * 4)
        state, built, draft = run(turns + ["3号"], asked + ["courts_1h"])
        self.assertEqual(state.phase, Phase.READY)
        self.assertEqual(entries(draft), [("1号场", "14:00", 120), ("4号场", "14:00", 120),
                                          ("1号场", "18:00", 120), ("4号场", "18:00", 120),
                                          ("3号场", "15:00", 60)])
        self.assertNotIn("2小时", built["courts_1h"].display)

    def test_the_one_hour_queue_can_use_its_own_courts(self):
        state, _, draft = run(["后天 14-16 不用候选 1号4号场 要一小时 15-16 3号场 不用候选"])
        self.assertEqual(entries(draft)[-1], ("3号场", "15:00", 60))
        self.assertEqual(len(entries(draft)), 3)

    def test_hesitation_is_not_a_yes_and_refusals_are_not_a_yes(self):
        for answer in ("再想想", "不好", "不行", "算了"):
            _, _, draft = run(["后天 14-16 不用候选 1号场", answer], ["want_1h"])
            self.assertIsNot(draft.g1.wanted, True, answer)
        for answer in ("要", "需要", "好的", "可以"):
            _, _, draft = run(["后天 14-16 不用候选 1号场", answer], ["want_1h"])
            self.assertIs(draft.g1.wanted, True, answer)

    def test_declining_the_one_hour_queue_finishes(self):
        state, _, draft = run(["后天 14-16 不用候选 1号场", "不用"], ["want_1h"])
        self.assertEqual(state.phase, Phase.READY)
        self.assertEqual(len(entries(draft)), 1)

    def test_one_hour_only(self):
        state, _, draft = run(["后天 只要一小时 15-16 不用候选 3号场"])
        self.assertEqual(state.phase, Phase.READY)
        self.assertEqual(entries(draft), [("3号场", "15:00", 60)])

    def test_two_hour_questions_never_come_after_the_one_hour_ones(self):
        order = []
        asked, turns = [], ["后天"]
        for answer in ["14-16", "不用", "1号", "要", "15-16", "不用"]:
            state, _, _ = run(turns, asked)
            order.append(state.asking)
            asked.append(state.asking)
            turns.append(answer)
        self.assertEqual(order, ["windows_2h", "more_2h", "courts_2h", "want_1h", "windows_1h", "more_1h"])

    def test_the_owner_never_asks_about_a_venue(self):
        for text in ["我想订场", "后天", "后天 14-16"]:
            state, built, draft = run([text])
            self.assertNotIn("场馆", question(built, state.asking, draft, TODAY))

    def test_wording_never_shows_minutes(self):
        for turns, asked in [(["我想订场"], []), (["后天"], []), (["后天", "14-16"], ["target_date"]),
                             (["后天 14-16 15-17 不用"], []), (["后天 14-16 不用候选"], [])]:
            state, built, draft = run(turns, asked)
            if state.asking:
                self.assertNotIn("分钟", question(built, state.asking, draft, TODAY))

    def test_rule_breaking_input_is_explained_not_silently_fixed(self):
        _, built, draft = run(["后天 14-17"])
        self.assertIn("1 小时或 2 小时", question(built, "windows_2h", draft, TODAY))
        _, built, draft = run(["后天 21-23"])
        self.assertIn("09:00–22:00", question(built, "windows_2h", draft, TODAY))
        _, built, draft = run(["后天 14:30-16:30"])
        self.assertIn("整点", question(built, "windows_2h", draft, TODAY))
        _, built, draft = run(["后天 14-16 不用候选 11号场"])
        self.assertIn("1～10号场", question(built, "courts_2h", draft, TODAY))
        _, built, draft = run(["10月1日"])
        self.assertEqual(built["target_date"].status, SlotStatus.INVALID)
        self.assertIn("已经过了", question(built, "target_date", draft, TODAY))

    def test_a_later_good_answer_clears_the_problem(self):
        state, _, draft = run(["后天 14-17", "14-16"], ["windows_2h"])
        self.assertEqual((state.asking, draft.g2.windows), ("more_2h", [(840, 960)]))

    def test_too_many_candidates_ask_for_fewer_courts(self):
        state, built, draft = run(["后天 9-11 11-13 13-15 15-17 17-19 19-21 不用候选 都保留 1到10号场 不要一小时"], [])
        self.assertEqual(state.asking, "courts_2h")
        self.assertIn("最多 32 项", question(built, "courts_2h", draft, TODAY))
        state, _, draft = run(["后天 9-11 11-13 13-15 15-17 17-19 19-21 不用候选 都保留 1到10号场 不要一小时", "只要1号和2号"],
                              ["courts_2h"])
        self.assertEqual(state.phase, Phase.READY)
        self.assertEqual(len(entries(draft)), 12)

    def test_strip_follows_the_conversation(self):
        state, built, draft = run(["后天 14-16"], [])
        items = {i["id"]: (i["state"], i["display"]) for i in strip(draft, built, state.asking)}
        self.assertEqual(items["date"], ("done", "10月20日 周二"))
        self.assertEqual(items["windows"][0], "current")
        self.assertEqual(items["courts"][0], "empty")

    def test_two_other_users_words_do_not_leak_between_runs(self):
        a = run(["后天 14-16 不用候选 1号场 不要一小时"])[2]
        b = run(["下周六 10-12 不用候选 5号场 不要一小时"])[2]
        self.assertNotEqual(entries(a), entries(b))
        self.assertEqual(entries(a), entries(run(["后天 14-16 不用候选 1号场 不要一小时"])[2]))


class ReplayInvariants(unittest.TestCase):
    ANSWERS = ["后天", "14-16", "18-20", "15-17", "1号4号场", "3号", "不用", "要", "要一小时", "15-16", "都保留", "去掉15-17",
               "11号场", "14-17", "随便", "好的", "？", "下周六", "9点", "不要一小时", "只要两小时", "都行"]

    def play(self, rng):
        turns, asked, phases = [rng.choice(["想订场", "后天", "下周六 14-16", "后天 14-16 1号场"])], [], []
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

    def test_every_random_conversation_terminates_within_budget(self):
        rng = random.Random(7)
        for _ in range(600):
            state, draft, asked, phases = self.play(rng)
            self.assertLessEqual(len(asked), conv.MAX_ANSWERS)
            for earlier, later in itertools.pairwise(phases):
                self.assertTrue(can_follow(earlier, later))
            if state.phase is Phase.ESCALATED:
                self.assertIn(state.escalation, {"stalled", "turn_limit"})
            if state.phase is Phase.READY:
                self.assertTrue(build_entries(draft), "ready must produce at least one candidate")
                self.assertLessEqual(len(build_entries(draft)), 32)

    def test_no_field_is_asked_more_than_the_cap(self):
        rng = random.Random(11)
        for _ in range(600):
            _, _, asked, _ = self.play(rng)
            for field in set(asked):
                self.assertLessEqual(asked.count(field), conv.MAX_ASKS_PER_FIELD)

    def test_a_ready_queue_is_always_two_hour_first_and_unique(self):
        rng = random.Random(23)
        for _ in range(600):
            state, draft, _, _ = self.play(rng)
            if state.phase is not Phase.READY:
                continue
            built = [(e["duration_minutes"], e["start_time"], e["court_preference"]) for e in build_entries(draft)]
            self.assertEqual(len(set(built)), len(built))
            durations = [d for d, _, _ in built]
            self.assertEqual(durations, sorted(durations, reverse=True))
            for _, start, _ in built:
                self.assertTrue(start.endswith(":00") and "09:00" <= start <= "21:00")

    def test_the_question_asked_is_always_an_open_one(self):
        rng = random.Random(31)
        for _ in range(400):
            turns, asked = [rng.choice(["想订场", "后天 14-16"])], []
            for _ in range(8):
                draft = fold(turns, asked, TODAY)
                built = build_slots(draft, TODAY)
                state = decide(built, asked, len(turns) - 1)
                if state.phase in conv.TERMINAL:
                    break
                self.assertIn(state.asking, [s.field for s in conv.blocking_slots(built)])
                self.assertTrue(question(built, state.asking, draft, TODAY))
                asked.append(state.asking)
                turns.append(rng.choice(self.ANSWERS))


if __name__ == "__main__":
    unittest.main()
