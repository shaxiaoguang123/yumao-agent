import unittest

from backend.availability_matching.models import AvailabilityError
from backend.availability_matching.official_history import OfficialBookingByTimeHistoryAdapter


def response(**changes):
    result = {
        "stepnumber": "2",
        "nodeList": [
            {"nodeid": "synthetic-node-secret-a", "sitename": "合成场地甲"},
            {"nodeid": "synthetic-node-secret-b", "sitename": "合成场地乙"},
        ],
        "timeList": [{"time": "18:00", "status": "1"}, {"time": "18:30", "status": "0"}],
        "conflictList": ["1-0", "0-1-3", "1-1-7"],
        "priceList": [{"x": "0", "y": "1", "price": "synthetic-price-secret"}],
    }
    result.update(changes)
    return {"success": True, "message": "synthetic success", "resultData": result}


class OfficialBookingByTimeHistoryAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = OfficialBookingByTimeHistoryAdapter()

    def test_maps_observed_display_states_to_a_strict_historical_read_only_grid(self):
        grid = self.adapter.preview(response())
        self.assertEqual(grid["grid_version"], "official-history-grid-v1")
        self.assertEqual(grid["source"]["data_state"], "historical_unverified")
        self.assertEqual(grid["source"]["freshness_state"], "unknown")
        self.assertIsNone(grid["target_date"])
        self.assertIsNone(grid["source"]["captured_at_utc_ms"])
        self.assertEqual([court["display_name"] for court in grid["courts"]], ["合成场地甲", "合成场地乙"])
        self.assertEqual(grid["rows"][0]["cells"][0]["state"], "historical_selectable")
        self.assertEqual(grid["rows"][0]["cells"][1]["state"], "historical_reserved")
        self.assertEqual(grid["rows"][1]["cells"][0]["state"], "historical_activity_occupied")
        self.assertEqual(grid["rows"][1]["cells"][1]["state"], "historical_unbookable")
        self.assertTrue(all(cell["selectable"] is False for row in grid["rows"] for cell in row["cells"]))
        self.assertEqual(grid["rows"][0]["time_label"], "18:00")
        self.assertEqual(grid["rows"][0]["time_status"]["state"], "recognized_unverified")
        self.assertEqual(grid["price_state"], "omitted_unit_unverified")
        self.assertFalse(grid["can_match"])
        for forbidden in ("synthetic-node-secret", "synthetic-price-secret", "nodeid", "coordinatesList"):
            self.assertNotIn(forbidden, str(grid))

    def test_conflicting_duplicate_coordinates_become_unknown_instead_of_last_write_wins(self):
        grid = self.adapter.preview(response(conflictList=["1-0", "1-0-2"]))
        cell = grid["rows"][0]["cells"][1]
        self.assertEqual(cell["state"], "historical_unknown")
        self.assertFalse(cell["selectable"])

    def test_unknown_row_status_or_conflict_type_stays_unknown(self):
        payload = response()
        payload["resultData"]["timeList"][0]["status"] = "unrecognized"
        payload["resultData"]["conflictList"] = ["1-0-8"]
        grid = self.adapter.preview(payload)
        self.assertTrue(all(cell["state"] == "historical_unknown" for cell in grid["rows"][0]["cells"]))
        self.assertEqual(grid["rows"][0]["time_status"]["state"], "unknown")

    def test_rejects_failed_or_malformed_response_shapes_without_echoing_input(self):
        for payload in (
            {"success": False, "message": "private error text", "resultData": {}},
            {"success": True, "resultData": {**response()["resultData"], "stepnumber": "9"}},
            {"success": True, "resultData": {**response()["resultData"], "conflictList": ["99-0"]}},
        ):
            with self.subTest(payload=payload), self.assertRaises(AvailabilityError) as failure:
                self.adapter.preview(payload)
            self.assertEqual(str(failure.exception), "invalid_official_history_response")


if __name__ == "__main__":
    unittest.main()
