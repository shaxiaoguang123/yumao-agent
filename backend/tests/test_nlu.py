import unittest
from datetime import date

from backend.ai.nlu import courts, cues, dates, times
from backend.ai.nlu.text import prep, to_int
from backend.ai.nlu.windows import label, resolve_start, scan_windows

TODAY = date(2026, 10, 10)  # a Saturday


def scan(text):
    return [(m.kind, [d.isoformat() for d in m.dates], m.ambiguous) for m in dates.scan_dates(courts.mask_courts(text), TODAY)]


class NumeralTests(unittest.TestCase):
    def test_arabic_and_chinese(self):
        for text, value in {"0": 0, "6": 6, "十": 10, "十二": 12, "二十": 20, "两": 2, "一百零五": 105, "零": 0}.items():
            self.assertEqual(to_int(text), value, text)
        for bad in ("", "abc", "二三"):
            self.assertIsNone(to_int(bad), bad)


class DateTests(unittest.TestCase):
    def test_absolute_forms(self):
        for text in ("10月20日", "10月20号", "2026-10-20", "2026年10月20日", "十月二十日"):
            found = scan(text)
            self.assertEqual([(dates_, amb) for _, dates_, amb in found], [(["2026-10-20"], False)], text)

    def test_relative_words_use_longest_match(self):
        self.assertEqual(scan("大后天")[0][1], ["2026-10-13"])
        self.assertEqual(scan("后天")[0][1], ["2026-10-12"])
        self.assertEqual(scan("明天")[0][1], ["2026-10-11"])

    def test_weeks_start_on_monday(self):
        self.assertEqual(scan("下周六")[0][1], ["2026-10-17"])
        self.assertEqual(scan("下周日")[0][1], ["2026-10-18"])
        self.assertEqual(scan("下下周日")[0][1], ["2026-10-25"])
        self.assertEqual(scan("本周一")[0][1], ["2026-10-05"])

    def test_same_weekday_and_weekend_are_ambiguous(self):
        self.assertEqual(scan("周六"), [("weekday", ["2026-10-10", "2026-10-17"], True)])
        self.assertTrue(scan("周末")[0][2])
        self.assertEqual(scan("周日")[0][1], ["2026-10-11"])

    def test_bare_day_and_impossible_dates_never_resolve(self):
        self.assertEqual(scan("10号"), [("bare_day", [], True)])
        self.assertEqual(scan("2月30日"), [("invalid_date", [], True)])

    def test_court_numbers_are_not_days(self):
        self.assertEqual(scan("6号场优先，5号和4号场备选"), [])

    def test_past_dates_are_reported_not_rolled_forward(self):
        self.assertEqual(scan("10月1日")[0][1], ["2026-10-01"])

    def test_latest_turn_wins_and_full_date_outranks_bare_day(self):
        state, found, _ = dates.settle(["预约10号", "10月20日"], TODAY, courts.mask_courts)
        self.assertEqual((state, found), ("resolved", (date(2026, 10, 20),)))
        state, found, _ = dates.settle(["下周六", "改成下周日"], TODAY, courts.mask_courts)
        self.assertEqual(found, (date(2026, 10, 18),))
        self.assertEqual(dates.settle(["预约10号"], TODAY, courts.mask_courts)[0], "ambiguous")
        self.assertEqual(dates.settle(["打球"], TODAY, courts.mask_courts)[0], "empty")


class CourtTests(unittest.TestCase):
    def numbers(self, text):
        return [(m.numbers, m.negated) for m in courts.scan_courts(text)]

    def test_forms(self):
        self.assertEqual(self.numbers("6号场优先，5号场备选"), [((6,), False), ((5,), False)])
        self.assertEqual(self.numbers("六号场"), [((6,), False)])
        self.assertEqual(self.numbers("6号和5号场"), [((6, 5), False)])
        self.assertEqual(self.numbers("1到3号场"), [((1, 2, 3), False)])
        self.assertEqual(self.numbers("10号场"), [((10,), False)])


class TimeTests(unittest.TestCase):
    def starts(self, text):
        return [(m.candidates, m.ambiguous, m.role) for m in times.scan_times(text)]

    def test_clock_forms(self):
        self.assertEqual(self.starts("18:00"), [(("18:00",), False, "start")])
        self.assertEqual(self.starts("晚上6点半"), [(("18:30",), False, "start")])
        self.assertEqual(self.starts("下午3点"), [(("15:00",), False, "start")])
        self.assertEqual(self.starts("十八点"), [(("18:00",), False, "start")])

    def test_bare_hour_uses_the_booking_window(self):
        self.assertEqual(self.starts("6点")[0][0], ("18:00",))
        self.assertEqual(self.starts("10点")[0][0], ("10:00",))
        self.assertTrue(self.starts("9点")[0][1])
        self.assertEqual(self.starts("09:00")[0], (("09:00",), False, "start"))

    def test_range_marks_the_end(self):
        self.assertEqual([m.role for m in times.scan_times("18:00-20:00")], ["start", "end"])
        self.assertEqual([m.role for m in times.scan_times("明天晚上6点打到8点")], ["start", "end"])

    def test_durations(self):
        cases = {"2小时": 120, "两个小时": 120, "两个半小时": 150, "一个半小时": 90, "1.5小时": 90, "90分钟": 90,
                 "半小时": 30, "1小时30分钟": 90}
        for text, minutes in cases.items():
            self.assertEqual(times.scan_durations(text), [minutes], text)



class ExecutionTests(unittest.TestCase):
    def test_commands_are_unsupported(self):
        for text in ("帮我直接预约并付款", "立即下单", "帮我付款", "马上订场"):
            self.assertTrue(cues.classify_execution([text])[0], text)

    def test_negation_and_plain_requests_are_fine(self):
        for text in ("不要自动付款，周六18:00打2小时", "帮我预约下周六18:00打两个小时", "别直接付款"):
            self.assertEqual(cues.classify_execution([text]), (False, []), text)

    def test_scheduled_wishes_are_recorded_not_refused(self):
        has_command, notes = cues.classify_execution(["周六18:00打2小时，到点自动预约"])
        self.assertFalse(has_command)
        self.assertEqual(notes, [cues.SCHEDULE_NOTE])

    def test_an_earlier_negation_does_not_hide_a_later_command(self):
        self.assertTrue(cues.classify_execution(["1号场，不用候选 然后立即下单"])[0])
        self.assertFalse(cues.classify_execution(["别直接付款"])[0])

    def test_every_turn_is_checked_independently(self):
        self.assertTrue(cues.classify_execution(["下周六18:00打2小时", "然后直接付款"])[0])


def windows(text):
    return [(m.kind, label(m.start, m.end) if m.start is not None and m.end is not None else None, m.issue) for m in scan_windows(text).mentions]


class WindowTests(unittest.TestCase):
    def test_plain_ranges(self):
        self.assertEqual(windows("14-16、18-20"), [("range", "14-16", None), ("range", "18-20", None)])
        self.assertEqual(windows("14:00-16:00,18:00-20:00"), [("range", "14-16", None), ("range", "18-20", None)])
        self.assertEqual(windows("14到16点"), [("range", "14-16", None)])

    def test_period_words_and_inherited_period(self):
        self.assertEqual(windows("下午2点到4点"), [("range", "14-16", None)])
        self.assertEqual(windows("晚上6点到8点"), [("range", "18-20", None)])
        self.assertEqual(windows("明天晚上6点打到8点"), [("range", "18-20", None)])

    def test_bare_hours_pick_the_only_sensible_reading(self):
        for text, expected in {"3-5": "15-17", "9-11": "9-11", "10-12": "10-12", "12-14": "12-14", "7-9": "19-21"}.items():
            self.assertEqual(windows(text), [("range", expected, None)], text)

    def test_genuinely_ambiguous_ranges_stay_ambiguous(self):
        self.assertEqual(windows("9-10")[0][2], "ambiguous")

    def test_bad_windows_get_a_reason(self):
        self.assertEqual(windows("14-17")[0][2], "bad_length")
        self.assertEqual(windows("14:30-16:30")[0][2], "unaligned")
        self.assertEqual(windows("20-22")[0][2], None)
        self.assertEqual(windows("21-23")[0][2], "outside_hours")
        self.assertEqual(windows("16-14")[0][2], "bad_order")

    def test_a_date_or_court_list_is_never_read_as_a_window(self):
        self.assertEqual(windows("2026-10-24 14-16"), [("range", "14-16", None)])
        self.assertEqual(windows("1-4号场 14-16"), [("range", "14-16", None)])
        self.assertEqual(windows("10月24日"), [])
        self.assertEqual(windows("一到两个小时"), [])
        self.assertEqual(windows("6号和5号场"), [])

    def test_lone_starts_wait_for_a_length(self):
        mention = scan_windows("晚上7点打2小时").mentions[0]
        self.assertEqual((mention.kind, scan_windows("晚上7点打2小时").durations), ("start", (120,)))
        self.assertEqual(resolve_start(mention, 120), (1140, 1260, None))
        self.assertEqual(resolve_start(scan_windows("9点").mentions[0], 120)[:2], (540, 660))
        self.assertEqual(resolve_start(scan_windows("21点").mentions[0], 120)[2], "outside_hours")
        self.assertEqual(resolve_start(scan_windows("14:30").mentions[0], 60)[2], "unaligned")

    def test_several_lone_starts_keep_the_users_order(self):
        self.assertEqual([m.text for m in scan_windows("14点和18点各打两小时").mentions], ["14点", "18点"])

    def test_positions_allow_cue_lookups(self):
        text = scan_windows("去掉14-16").text
        mention = scan_windows("去掉14-16").mentions[0]
        self.assertEqual(text[mention.pos:mention.stop], "14-16")


class CourtListTests(unittest.TestCase):
    def numbers(self, text):
        return [m.numbers for m in courts.scan_courts(text)]

    def test_run_together_and_spaced_lists(self):
        self.assertEqual(self.numbers("1号4号场"), [(1, 4)])
        self.assertEqual(self.numbers("14-16 1号4号场"), [(1, 4)])
        self.assertEqual(self.numbers("14-16 1 4号场"), [(1, 4)])
        self.assertEqual(self.numbers("1、4、6号场"), [(1, 4, 6)])

    def test_prep_only_separates_digits(self):
        self.assertEqual(prep("14-16 1号"), "14-16,1号")
        self.assertEqual(prep("2 小时"), "2小时")
