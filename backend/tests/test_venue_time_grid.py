import unittest

from backend.availability_matching.venue_time_grid import (
    AvailabilityGridProjector,
    VenueGridCell,
    VenueTimeGridError,
)
from backend.availability_matching.synthetic import SyntheticAvailabilitySource
from backend.availability_matching.matcher import AvailabilityMatcher


class SyntheticVenueTimeGridTests(unittest.TestCase):
    def setUp(self):
        self.source = AvailabilityGridProjector()

    def plan(self):
        return {
            "intent": {
                "target_date": "2026-10-20", "preferred_start_times": ["18:00", "19:00"],
                "duration_minutes": 120, "venue_preference": "人工输入的场馆",
                "court_preferences": ["6号场优先", "5号场备选"],
                "fallback_policy": {"allow_any_court_in_venue": False, "allow_time_shift": False,
                                    "allowed_start_time_range": None},
                "price_ceiling_minor": None,
            },
            "context": {"timezone_name": "Asia/Shanghai", "currency_code": "CNY",
                        "currency_minor_unit_exponent": 2},
        }

    def test_one_snapshot_drives_grid_and_matcher_for_the_same_occupied_slot(self):
        plan = self.plan()
        snapshot = SyntheticAvailabilitySource().snapshot(plan, "partially_occupied")
        first = self.source.project(snapshot, court_names=plan["intent"]["court_preferences"], duration_minutes=120)
        second = self.source.project(snapshot, court_names=plan["intent"]["court_preferences"], duration_minutes=120)

        self.assertEqual(first, second)
        self.assertTrue(first["simulation"])
        self.assertEqual(first["source"]["data_state"], "synthetic")
        self.assertEqual(first["atom_minutes"], 30)
        self.assertEqual(first["venue"]["verification"], "unverified_manual")
        states = {cell["state"] for row in first["rows"] for cell in row["cells"]}
        self.assertEqual(states, {"selectable", "reserved", "activity_occupied", "unbookable", "unknown"})
        self.assertTrue(all(not cell["selectable"] for row in first["rows"] for cell in row["cells"] if cell["state"] != "selectable"))
        occupied_row = next(row for row in first["rows"] if row["start_time"] == "18:30")
        self.assertEqual(occupied_row["cells"][0]["state"], "activity_occupied")
        self.assertFalse(occupied_row["cells"][0]["selectable"])
        matched = AvailabilityMatcher().match(plan, snapshot)
        self.assertFalse(any(item["court_name"] == "6号场优先" and item["start_time"] == "18:00"
                             for item in matched["candidates"]))
        serialized = str(first)
        for forbidden in ("nodeid", "coordinatesList", "courtIndex", "timeIndex", "price_minor"):
            self.assertNotIn(forbidden, serialized)
        for flag in ("can_query_upstream", "can_book", "can_pay", "can_create_job"):
            self.assertIs(first[flag], False)

    def test_projector_renders_absent_snapshot_rows_as_unknown(self):
        plan = self.plan(); snapshot = SyntheticAvailabilitySource().snapshot(plan, "time_gap")
        grid = self.source.project(snapshot, court_names=plan["intent"]["court_preferences"], duration_minutes=120)
        row = next(row for row in grid["rows"] if row["start_time"] == "18:30")
        self.assertTrue(all(cell["state"] == "unknown" and not cell["selectable"] for cell in row["cells"]))
        matched = AvailabilityMatcher().match(plan, snapshot)
        self.assertIn("time_discontinuous", {item["code"] for item in matched["reason_summary"]})

    def test_unknown_client_state_cannot_be_promoted_to_a_selectable_cell(self):
        with self.assertRaises(VenueTimeGridError):
            VenueGridCell("available-ish", "unverified_status")
        with self.assertRaises(VenueTimeGridError):
            VenueGridCell("unknown", "unverified_status", "活动占用")


if __name__ == "__main__":
    unittest.main()
