from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from Crypto.Cipher import AES

from backend.credentials.upstream import BoundedHttpResponse
from backend.execution.protocol import OfficialBookingProtocol
from backend.execution.clock import ClockCalibrationError, sample_upstream_clock


KEY = "1234567890abcdef"
IV = "fedcba0987654321"


def unpad(value: bytes) -> bytes:
    size = value[-1]
    return value[:-size]


def decrypt_item(value: str) -> dict:
    cipher = AES.new(KEY.encode(), AES.MODE_CBC, iv=IV.encode())
    plain = unpad(cipher.decrypt(bytes.fromhex(value)))
    return json.loads(plain.decode())


class FakeTransport:
    def __init__(self):
        self.calls = []

    def post_json(self, url, *, headers, json_body):
        self.calls.append((url, headers, json_body))
        path = url.split("/service/appointment/appointment", 1)[-1]
        if path == "/phone/getBookingNode":
            result = [{"id": "category-node", "nodename": "羽毛球"}]
        elif path == "/userAddress/getUserInfo":
            result = {"idserial": "reservation-person"}
        elif path == "/phone/getChildren":
            result = {"childrennum": "1"}
        elif path == "/phone/getPayPrice":
            result = {"txamt": "20.00"}
        elif path == "/phone/createBookingBytime":
            result = {"orderno": "order-a"}
        elif path == "/phone/payOrderForPhone":
            result = {"content": []}
        elif path == "/phone/payOrderDetails":
            result = {"status": "1"}
        else:
            result = {}
        body = json.dumps({"success": True, "message": "CORE10008", "resultData": result}).encode()
        return BoundedHttpResponse(200, body, None, None, "complete", "Thu, 15 Oct 2026 16:30:00 GMT")


class FakeCredentialService:
    def __init__(self):
        self.tokens = []
        self.gate = type("Gate", (), {"minimum_interval_ms": None})()

    def with_availability_read_token(self, user_id, credential_id, callback):
        self.tokens.append((user_id, credential_id))
        return callback("synthetic-token")


class BookingProtocolTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.credentials = FakeCredentialService()
        self.protocol = OfficialBookingProtocol(
            credential_service=self.credentials, transport=self.transport,
            item_aes_key_ascii=KEY, item_aes_iv_ascii=IV,
        )

    def test_reads_selected_real_category_and_grid_through_the_credential_gate(self):
        categories, category_reply = self.protocol.read_categories("user-a", "credential-a", "ignored")
        self.assertEqual(categories, [{"node_id": "category-node", "label": "羽毛球"}])
        request = self.transport.calls[0]
        self.assertEqual(request[0].rsplit("/", 1)[-1], "getBookingNode")
        self.assertEqual(decrypt_item(request[2]["item"]), {"booktype": 2})
        reply = self.protocol.read_grid("user-a", "credential-a", "ignored", "category-node", "2026-10-17")
        request = self.transport.calls[1]
        self.assertEqual(decrypt_item(request[2]["item"]), {"nodeid": "category-node", "selectdate": "2026-10-17"})
        self.assertEqual(reply.envelope["success"], True)
        self.assertEqual(self.credentials.tokens, [("user-a", "credential-a"), ("user-a", "credential-a")])
        self.assertEqual(reply.server_date_header, "Thu, 15 Oct 2026 16:30:00 GMT")

    def test_order_price_booking_and_payment_payloads_match_the_legacy_python_flow(self):
        user = self.protocol.get_user_info("user-a", "credential-a", "synthetic-token")
        self.assertEqual(self.transport.calls[-1][2], {})
        children = self.protocol.get_children("synthetic-token", "category-node")
        self.assertEqual(decrypt_item(self.transport.calls[-1][2]["item"]), {"nodeid": "category-node"})
        time_list = [{"time": "09:00", "status": "0"}]
        node_list = [{"nodeid": "court-id-from-this-query", "sitename": "6号场"}]
        coordinates = ["0-0"]
        self.protocol.get_pay_price("synthetic-token", node_id="category-node", target_date="2026-10-17",
                                    coordinates=coordinates, appointment_type="2", reservation_person="person",
                                    time_list=time_list, node_list=node_list)
        quote = decrypt_item(self.transport.calls[-1][2]["item"])
        self.assertEqual(set(quote), {"appointmentType", "reserveDate", "reserveTime", "timeList", "nodeList", "nodeid", "reservationPerson", "accompanyPerson"})
        self.assertEqual(quote["coordinatesList"] if "coordinatesList" in quote else quote["reserveTime"], coordinates)
        self.protocol.create_booking("synthetic-token", node_id="category-node", target_date="2026-10-17",
                                     coordinates=coordinates, txamt="20.00", time_list=time_list,
                                     node_list=node_list, is_last_day=True, childrennum="1")
        booking = decrypt_item(self.transport.calls[-1][2]["item"])
        self.assertEqual(booking["coordinatesList"], coordinates)
        self.assertEqual(booking["nodeList"], node_list)
        self.protocol.pay_order("synthetic-token", order_no="order-a", txamt="20.00", password="synthetic-pay-pass")
        payment = decrypt_item(self.transport.calls[-1][2]["item"])
        self.assertEqual(payment, {"orderno": "order-a", "payway": "77", "password": "synthetic-pay-pass", "txamt": "20.00"})
        self.assertNotIn("synthetic-pay-pass", self.transport.calls[-1][2]["item"])
        self.assertEqual(user.envelope["resultData"]["idserial"], "reservation-person")
        self.assertEqual(children.envelope["resultData"]["childrennum"], "1")
        self.assertTrue(all("captcha" not in call[0].lower() for call in self.transport.calls))

    def test_payment_status_read_endpoints_are_present_and_clock_sample_is_bounded(self):
        self.protocol.list_orders("synthetic-token")
        self.assertEqual(decrypt_item(self.transport.calls[-1][2]["item"]), {"pageNumber": 1, "pageSize": 20, "ordertype": 1})
        self.protocol.order_details("synthetic-token", booking_no="booking-a", order_id="id-a")
        self.assertEqual(decrypt_item(self.transport.calls[-1][2]["item"]), {"bookingno": "booking-a", "id": "id-a"})
        local_ms = int(datetime(2026, 10, 15, 16, 30, tzinfo=timezone.utc).timestamp() * 1000)
        sample = sample_upstream_clock("Thu, 15 Oct 2026 16:30:00 GMT", local_ms, local_ms + 100)
        self.assertLessEqual(sample.uncertainty_ms, 2500)
        with self.assertRaises(ClockCalibrationError):
            sample_upstream_clock(None, 1, 2)


if __name__ == "__main__":
    unittest.main()
