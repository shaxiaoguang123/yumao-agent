from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from backend.booking_window import BookingWindowPolicy
from backend.settings import load_settings
from support import credential_test_settings


UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _utc_ms(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("test instant must be timezone-aware")
    return (value.astimezone(UTC) - EPOCH) // timedelta(milliseconds=1)


def _policy(timezone_name: str = "Asia/Shanghai") -> BookingWindowPolicy:
    settings_env = credential_test_settings()
    settings_env["BOOKING_TIMEZONE"] = timezone_name
    settings = load_settings(settings_env)
    return BookingWindowPolicy(settings.booking_timezone_name)


class BookingWindowPolicyTests(unittest.TestCase):
    def test_business_date_and_window_use_configured_timezone_not_host_timezone(self) -> None:
        policy = _policy("America/New_York")
        instant = _utc_ms(datetime(2026, 1, 2, 0, 30, tzinfo=UTC))

        self.assertEqual(policy.business_date_at_utc(instant), date(2026, 1, 1))
        self.assertEqual(
            policy.queryable_target_dates(instant),
            (date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)),
        )

    def test_window_calendar_arithmetic_handles_month_year_and_leap_day(self) -> None:
        policy = _policy()
        cases = (
            (
                datetime(2024, 2, 28, 16, 0, tzinfo=UTC),
                (date(2024, 2, 29), date(2024, 3, 1), date(2024, 3, 2)),
            ),
            (
                datetime(2025, 12, 31, 16, 0, tzinfo=UTC),
                (date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)),
            ),
            (
                datetime(2026, 1, 31, 16, 0, tzinfo=UTC),
                (date(2026, 2, 1), date(2026, 2, 2), date(2026, 2, 3)),
            ),
        )
        for now, expected in cases:
            with self.subTest(now=now):
                self.assertEqual(policy.queryable_target_dates(_utc_ms(now)), expected)

    def test_only_current_business_day_and_next_two_days_are_queryable(self) -> None:
        policy = _policy()
        now = _utc_ms(datetime(2026, 10, 9, 0, 0, tzinfo=UTC))
        dates = policy.queryable_target_dates(now)

        states = [policy.describe(target_date, now) for target_date in dates]
        self.assertTrue(all(state.can_query for state in states))
        self.assertEqual(states[0].default_target_date, date(2026, 10, 11))
        self.assertTrue(all(not state.can_book and not state.can_pay for state in states))

        distant = policy.describe(date(2099, 1, 1), now)
        self.assertFalse(distant.can_query)
        self.assertEqual(distant.reason_code, "target_outside_query_window")

    def test_t_minus_two_midnight_boundary_is_exact(self) -> None:
        policy = _policy()
        target = date(2026, 11, 1)
        opens_at = _utc_ms(datetime(2026, 10, 29, 16, 0, tzinfo=UTC))

        before = policy.describe(target, opens_at - 1)
        at = policy.describe(target, opens_at)
        after = policy.describe(target, opens_at + 1)

        self.assertEqual(before.query_open_at_utc_ms, opens_at)
        self.assertFalse(before.can_query)
        self.assertEqual(at.query_open_at_utc_ms, opens_at)
        self.assertTrue(at.can_query)
        self.assertTrue(after.can_query)

    def test_estimated_open_is_display_only_and_never_authorizes_booking_or_payment(self) -> None:
        policy = _policy()
        now = _utc_ms(datetime(2026, 10, 30, 0, 0, tzinfo=UTC))
        state = policy.describe(date(2026, 11, 1), now)

        self.assertEqual(state.estimated_open_at_local, "2026-10-30T07:30:00")
        self.assertFalse(state.estimated_open_is_confirmed)
        self.assertIsNone(state.resolved_official_open_at_utc_ms)
        self.assertEqual(state.contract_status, "not_checked")
        self.assertFalse(state.can_book)
        self.assertFalse(state.can_pay)

    def test_timezone_snapshot_mismatch_blocks_query_without_reinterpreting_intent(self) -> None:
        policy = _policy("Asia/Shanghai")
        now = _utc_ms(datetime(2026, 10, 9, 0, 0, tzinfo=UTC))
        target = date(2026, 10, 11)

        state = policy.describe(target, now, intent_timezone_snapshot="America/New_York")

        self.assertFalse(state.can_query)
        self.assertEqual(state.reason_code, "timezone_context_mismatch")
        self.assertEqual(state.target_date, target)
        self.assertEqual(state.business_timezone_name, "Asia/Shanghai")
        self.assertFalse(state.can_book)
        self.assertFalse(state.can_pay)

    def test_spring_dst_boundary_uses_local_calendar_and_zone_rules(self) -> None:
        policy = _policy("America/New_York")
        before_jump = _utc_ms(datetime(2024, 3, 10, 6, 59, tzinfo=UTC))
        after_jump = _utc_ms(datetime(2024, 3, 10, 7, 0, tzinfo=UTC))

        self.assertEqual(policy.business_date_at_utc(before_jump), date(2024, 3, 10))
        self.assertEqual(policy.business_date_at_utc(after_jump), date(2024, 3, 10))
        self.assertEqual(
            policy.queryable_target_dates(after_jump),
            (date(2024, 3, 10), date(2024, 3, 11), date(2024, 3, 12)),
        )
        state = policy.describe(date(2024, 3, 12), after_jump)
        self.assertEqual(state.query_open_at_utc_ms, _utc_ms(datetime(2024, 3, 10, 5, 0, tzinfo=UTC)))
        self.assertTrue(state.can_query)

    def test_fall_dst_repeated_hour_does_not_change_the_business_date(self) -> None:
        policy = _policy("America/New_York")
        first_one_thirty = _utc_ms(datetime(2024, 11, 3, 5, 30, tzinfo=UTC))
        second_one_thirty = _utc_ms(datetime(2024, 11, 3, 6, 30, tzinfo=UTC))

        self.assertEqual(policy.business_date_at_utc(first_one_thirty), date(2024, 11, 3))
        self.assertEqual(policy.business_date_at_utc(second_one_thirty), date(2024, 11, 3))
        self.assertEqual(
            policy.queryable_target_dates(first_one_thirty),
            policy.queryable_target_dates(second_one_thirty),
        )
        state = policy.describe(date(2024, 11, 5), second_one_thirty)
        self.assertEqual(state.query_open_at_utc_ms, _utc_ms(datetime(2024, 11, 3, 4, 0, tzinfo=UTC)))
        self.assertTrue(state.can_query)

    def test_ambiguous_midnight_uses_its_first_occurrence(self) -> None:
        policy = _policy("America/Havana")
        now = _utc_ms(datetime(2020, 11, 1, 6, 0, tzinfo=UTC))
        state = policy.describe(date(2020, 11, 3), now)

        self.assertEqual(state.query_open_at_utc_ms, _utc_ms(datetime(2020, 11, 1, 4, 0, tzinfo=UTC)))
        self.assertTrue(state.can_query)

    def test_nonexistent_midnight_uses_first_valid_instant_on_same_date(self) -> None:
        policy = _policy("America/Santiago")
        now = _utc_ms(datetime(2019, 9, 8, 4, 0, tzinfo=UTC))
        state = policy.describe(date(2019, 9, 10), now)

        self.assertEqual(state.query_open_at_utc_ms, _utc_ms(datetime(2019, 9, 8, 4, 0, tzinfo=UTC)))
        self.assertTrue(state.can_query)

    def test_wholly_skipped_local_date_fails_closed(self) -> None:
        policy = _policy("Pacific/Apia")
        now = _utc_ms(datetime(2011, 12, 31, 22, 0, tzinfo=UTC))
        state = policy.describe(date(2012, 1, 1), now)

        self.assertIsNone(state.query_open_at_utc_ms)
        self.assertFalse(state.can_query)
        self.assertEqual(state.reason_code, "query_open_local_date_unavailable")
        self.assertFalse(state.can_book)
        self.assertFalse(state.can_pay)

    def test_non_integer_utc_instants_and_datetime_targets_are_rejected(self) -> None:
        policy = _policy()
        with self.assertRaises(TypeError):
            policy.business_date_at_utc(True)
        with self.assertRaises(TypeError):
            policy.describe(datetime(2026, 10, 9), _utc_ms(datetime(2026, 10, 9, tzinfo=UTC)))


if __name__ == "__main__":
    unittest.main()
