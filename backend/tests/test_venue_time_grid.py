import unittest

from backend.availability_matching.venue_time_grid import (
    SyntheticVenueTimeGridSource,
    VenueGridCell,
    VenueTimeGridError,
)


class SyntheticVenueTimeGridTests(unittest.TestCase):
    def setUp(self):
        self.source = SyntheticVenueTimeGridSource()

    def build(self, **changes):
        values = {
            "target_date": "2026-10-20",
            "timezone_name": "Asia/Shanghai",
            "venue_preference": "人工输入的场馆",
            "court_preferences": ["6号场优先", "5号场备选"],
            "duration_minutes": 120,
        }
        values.update(changes)
        return self.source.preview(**values)

    def test_fixture_is_stable_labeled_and_has_distinct_display_states(self):
        first = self.build()
        second = self.build()

        self.assertEqual(first, second)
        self.assertTrue(first["simulation"])
        self.assertEqual(first["source"]["data_state"], "synthetic")
        self.assertEqual(first["atom_minutes"], 30)
        self.assertEqual(first["venue"]["verification"], "unverified_manual")
        states = {cell["state"] for row in first["rows"] for cell in row["cells"]}
        self.assertEqual(states, {"selectable", "reserved", "activity_occupied", "unbookable", "unknown"})
        self.assertTrue(all(not cell["selectable"] for row in first["rows"] for cell in row["cells"] if cell["state"] != "selectable"))
        serialized = str(first)
        for forbidden in ("nodeid", "coordinatesList", "courtIndex", "timeIndex", "price_minor"):
            self.assertNotIn(forbidden, serialized)
        for flag in ("can_query_upstream", "can_book", "can_pay", "can_create_job"):
            self.assertIs(first[flag], False)

    def test_invalid_intent_dimensions_fail_closed(self):
        for changes in (
            {"target_date": "not-a-date"},
            {"target_date": "9999-12-31"},
            {"duration_minutes": 45},
            {"court_preferences": []},
            {"court_preferences": ["重复", "重复"]},
            {"venue_preference": "   "},
        ):
            with self.subTest(changes=changes), self.assertRaises(VenueTimeGridError):
                self.build(**changes)

    def test_unknown_client_state_cannot_be_promoted_to_a_selectable_cell(self):
        with self.assertRaises(VenueTimeGridError):
            VenueGridCell("available-ish", "unverified_status")
        with self.assertRaises(VenueTimeGridError):
            VenueGridCell("unknown", "unverified_status", "活动占用")


if __name__ == "__main__":
    unittest.main()
