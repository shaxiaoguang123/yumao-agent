from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.execution.reconciliation import candidate_coordinates, reconcile_queue


DATE = "2026-10-17"
ZONE = "Asia/Shanghai"


def at(hour, minute=0):
    return int(datetime(2026, 10, 17, hour, minute, tzinfo=ZoneInfo(ZONE)).timestamp() * 1000)


def envelope(*, courts=None, statuses=None, conflicts=None, opening="07:30"):
    times = [f"{hour:02d}:00" for hour in range(9, 14)]
    return {
        "success": True,
        "message": "CORE10008",
        "resultData": {
            "stepnumber": len(times),
            "nodeList": courts or [
                {"nodeid": "court-in-response-a", "sitename": "1号场"},
                {"nodeid": "court-in-response-b", "sitename": "2号场"},
            ],
            "timeList": [
                {"time": label, "status": (statuses or {}).get(index, "0")}
                for index, label in enumerate(times)
            ],
            "conflictList": conflicts or [],
            "priceList": [],
            "bookingstartdate": "2026-10-16",
            "bookingenddate": DATE,
            "bookingstarttime": opening,
            "bookingendtime": "22:00",
            "isNew": False,
        },
    }


def intent(court, start, duration, scope="羽毛球"):
    end_hour = int(start[:2]) + duration // 60
    return {
        "court_preferences": [court],
        "preferred_start_times": [start],
        "duration_minutes": duration,
        "query_scope_label": scope,
    }


class ExecutionReconciliationTests(unittest.TestCase):
    def test_preopening_filter_ignores_global_clock_gate_but_removes_explicit_blockers(self):
        raw = envelope(statuses={2: "1"}, conflicts=["0-1-7"])
        snapshot, summary = reconcile_queue(
            [
                intent("1号场", "09:00", 60),
                intent("1号场", "10:00", 120),
                intent("2号场", "11:00", 60),
                intent("1号场", "12:00", 60, None),
                intent("2号场", "12:00", 60, "未知类别"),
            ],
            {"羽毛球": (raw, at(0, 30))},
            target_date=DATE,
            timezone_name=ZONE,
        )
        self.assertEqual([(item["court_preference"], item["start_time"]) for item in snapshot], [("1号场", "09:00")])
        self.assertEqual(summary["discarded_candidate_counts"], {
            "explicit_conflict": 1,
            "time_row_not_selectable": 1,
            "scope_unbound": 1,
            "scope_query_missing": 1,
        })
        self.assertEqual(summary["availability_claim"], "none_pre_open; every candidate requires a fresh 07:30 query")

    def test_two_hour_candidates_require_exact_adjacent_hour_rows(self):
        raw = envelope()
        raw["resultData"]["timeList"][2]["time"] = "11:30"
        candidates, summary = reconcile_queue(
            [intent("1号场", "10:00", 120)],
            {"羽毛球": (raw, at(0, 30))},
            target_date=DATE,
            timezone_name=ZONE,
        )
        self.assertEqual(candidates, [])
        self.assertEqual(summary["discarded_candidate_counts"], {"time_interval_not_contiguous": 1})

    def test_fresh_opening_query_rebuilds_coordinates_from_current_response(self):
        candidate = {
            "scope_label": "羽毛球", "court_preference": "1号场", "start_time": "09:00",
            "end_time": "10:00", "duration_minutes": 60,
        }
        changed_order = envelope(courts=[
            {"nodeid": "new-response-court-x", "sitename": "2号场"},
            {"nodeid": "new-response-court-y", "sitename": "1号场"},
        ])
        coords, reason = candidate_coordinates(
            candidate, changed_order, target_date=DATE, timezone_name=ZONE,
            captured_at_utc_ms=at(7, 30),
        )
        self.assertEqual(coords, ["1-0"])
        self.assertIsNone(reason)
        coords, reason = candidate_coordinates(
            candidate, changed_order, target_date=DATE, timezone_name=ZONE,
            captured_at_utc_ms=at(7, 29),
        )
        self.assertIsNone(coords)
        self.assertEqual(reason, "booking_window_not_open")

    def test_unknown_target_window_metadata_fails_closed(self):
        raw = envelope()
        del raw["resultData"]["bookingstartdate"]
        with self.assertRaisesRegex(ValueError, "booking_window_metadata_unknown"):
            reconcile_queue([intent("1号场", "09:00", 60)], {"羽毛球": (raw, at(0, 30))},
                            target_date=DATE, timezone_name=ZONE)


if __name__ == "__main__":
    unittest.main()
