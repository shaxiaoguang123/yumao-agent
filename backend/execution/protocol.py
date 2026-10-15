from __future__ import annotations

import json
import time
import math
import unicodedata
from dataclasses import dataclass, field

from backend.credentials.service import CredentialService
from backend.credentials.types import CredentialOperationError
from backend.credentials.upstream import BoundedHttpResponse, UpstreamHttpTransport, UPSTREAM_GET_USER_INFO_ORIGIN
from backend.crypto import aes_cbc_encrypt_hex_upper


_API_ROOT = UPSTREAM_GET_USER_INFO_ORIGIN + "/service/appointment/appointment"
_BOOKING_NODE_LIST_BOOKTYPE = 2
_PAYWAY = "77"


@dataclass(frozen=True, slots=True)
class ProtocolReply:
    envelope: dict = field(repr=False)
    status_code: int
    server_date_header: str | None = field(default=None, repr=False)
    started_at_utc_ms: int = 0
    completed_at_utc_ms: int = 0
    elapsed_ms: int = 0


class UpstreamCallError(RuntimeError):
    def __init__(self, safe_code: str, outcome: str, *, started_at_utc_ms: int = 0,
                 completed_at_utc_ms: int = 0, elapsed_ms: int = 0):
        self.safe_code = safe_code
        self.outcome = outcome
        self.started_at_utc_ms = started_at_utc_ms
        self.completed_at_utc_ms = completed_at_utc_ms
        self.elapsed_ms = elapsed_ms
        super().__init__(safe_code)


class OfficialBookingProtocol:
    """Narrow adapter for endpoints already used by the previous Python flow.

    It deliberately has no CAPTCHA path and uses the current response's raw
    nodeList/timeList only for the request assembled from that same response.
    """

    _ALLOWED = {
        "/phone/getBookingNode",
        "/phone/bookingByTime",
        "/userAddress/getUserInfo",
        "/phone/getChildren",
        "/phone/getPayPrice",
        "/phone/createBookingBytime",
        "/mobile/pay/openPlatFormPayOrder",
        "/phone/payOrderForPhone",
        "/phone/payOrderDetails",
    }

    def __init__(self, *, credential_service: CredentialService,
                 transport: UpstreamHttpTransport, item_aes_key_ascii: str | None,
                 item_aes_iv_ascii: str | None):
        self.credentials = credential_service
        self.transport = transport
        self._key = item_aes_key_ascii
        self._iv = item_aes_iv_ascii

    def _encrypted(self, payload: dict) -> dict:
        if not isinstance(self._key, str) or not isinstance(self._iv, str):
            raise UpstreamCallError("official_request_cipher_unavailable", "failed")
        try:
            plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            return {"item": aes_cbc_encrypt_hex_upper(plain, self._key, self._iv)}
        except (TypeError, ValueError, UnicodeError):
            raise UpstreamCallError("official_request_payload_invalid", "failed") from None

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Origin": UPSTREAM_GET_USER_INFO_ORIGIN,
            "Referer": UPSTREAM_GET_USER_INFO_ORIGIN + "/",
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
                "MicroMessenger/8.0.47 miniProgram/appBrand"
            ),
            "token": token,
        }

    @staticmethod
    def _now_ms() -> int:
        return time.time_ns() // 1_000_000

    def _call(self, *, path: str, payload: dict, token: str,
              encrypt: bool = True, read_user: tuple[str, str] | None = None) -> ProtocolReply:
        if path not in self._ALLOWED:
            raise UpstreamCallError("official_route_not_allowed", "failed")
        wire_payload = self._encrypted(payload) if encrypt else payload
        observed: dict[str, object] = {}

        def send(active_token: str):
            observed["started_at"] = self._now_ms()
            started = time.monotonic_ns()
            response = self.transport.post_json(
                _API_ROOT + path,
                headers=self._headers(active_token),
                json_body=wire_payload,
            )
            observed["completed_at"] = self._now_ms()
            observed["elapsed_ms"] = max(0, (time.monotonic_ns() - started) // 1_000_000)
            return response

        response = None
        for retry in range(4):
            try:
                if read_user is not None:
                    user_id, credential_id = read_user
                    response = self.credentials.with_availability_read_token(
                        user_id, credential_id, send,
                    )
                else:
                    response = send(token)
                break
            except CredentialOperationError as exc:
                if exc.code in {"upstream_read_rate_limited", "validation_rate_limited"} and retry < 3:
                    wait = exc.retry_after_seconds
                    if wait is None:
                        interval = self.credentials.gate.minimum_interval_ms
                        wait = math.ceil(interval / 1000) if interval else 1
                    if 0 < wait <= 10:
                        time.sleep(wait)
                        continue
                raise UpstreamCallError(
                    exc.code,
                    "rejected",
                    started_at_utc_ms=int(observed.get("started_at", 0)),
                    completed_at_utc_ms=int(observed.get("completed_at", self._now_ms())),
                    elapsed_ms=int(observed.get("elapsed_ms", 0)),
                ) from None
        if not isinstance(response, BoundedHttpResponse):
            raise UpstreamCallError(
                "upstream_transport_invalid",
                "uncertain",
                started_at_utc_ms=int(observed.get("started_at", 0)),
                completed_at_utc_ms=int(observed.get("completed_at", self._now_ms())),
                elapsed_ms=int(observed.get("elapsed_ms", 0)),
            )
        started_at = int(observed.get("started_at", 0))
        completed_at = int(observed.get("completed_at", self._now_ms()))
        elapsed_ms = int(observed.get("elapsed_ms", 0))
        if response.error_code is not None:
            status = response.status_code
            uncertain = response.dispatch_state == "uncertain" or status is None or status >= 500
            safe_code = response.error_code if response.error_code.isascii() else "upstream_request_failed"
            raise UpstreamCallError(
                safe_code,
                "uncertain" if uncertain else "rejected",
                started_at_utc_ms=started_at,
                completed_at_utc_ms=completed_at,
                elapsed_ms=elapsed_ms,
            )
        if response.status_code != 200 or type(response.body) is not bytes:
            status = response.status_code
            raise UpstreamCallError(
                f"upstream_http_{status or 0}",
                "uncertain" if status is None or status >= 500 or status < 200 else "rejected",
                started_at_utc_ms=started_at,
                completed_at_utc_ms=completed_at,
                elapsed_ms=elapsed_ms,
            )
        try:
            envelope = json.loads(response.body.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise UpstreamCallError(
                "upstream_response_invalid",
                "uncertain" if path in {"/phone/createBookingBytime", "/mobile/pay/openPlatFormPayOrder"} else "rejected",
                started_at_utc_ms=started_at,
                completed_at_utc_ms=completed_at,
                elapsed_ms=elapsed_ms,
            ) from None
        if type(envelope) is not dict or type(envelope.get("success")) is not bool or "resultData" not in envelope:
            raise UpstreamCallError(
                "upstream_response_invalid",
                "uncertain" if path in {"/phone/createBookingBytime", "/mobile/pay/openPlatFormPayOrder"} else "rejected",
                started_at_utc_ms=started_at,
                completed_at_utc_ms=completed_at,
                elapsed_ms=elapsed_ms,
            )
        return ProtocolReply(
            envelope=envelope,
            status_code=response.status_code,
            server_date_header=response.server_date_header,
            started_at_utc_ms=started_at,
            completed_at_utc_ms=completed_at,
            elapsed_ms=elapsed_ms,
        )

    def read_categories(self, user_id: str, credential_id: str, token: str) -> tuple[list[dict], ProtocolReply]:
        reply = self._call(
            path="/phone/getBookingNode", payload={"booktype": _BOOKING_NODE_LIST_BOOKTYPE},
            token=token, read_user=(user_id, credential_id),
        )
        values = reply.envelope.get("resultData")
        if reply.envelope.get("success") is not True or type(values) is not list or not 1 <= len(values) <= 256:
            raise UpstreamCallError("booking_categories_unavailable", "rejected",
                                    started_at_utc_ms=reply.started_at_utc_ms,
                                    completed_at_utc_ms=reply.completed_at_utc_ms,
                                    elapsed_ms=reply.elapsed_ms)
        seen_ids, seen_labels, options = set(), set(), []
        for item in values:
            if type(item) is not dict:
                raise UpstreamCallError("booking_category_contract_invalid", "rejected")
            raw_id, label = item.get("id"), item.get("nodename")
            if type(raw_id) not in {str, int} or type(raw_id) is bool or type(label) is not str:
                raise UpstreamCallError("booking_category_contract_invalid", "rejected")
            node_id = str(raw_id)
            if (not node_id or len(node_id) > 128 or not label.strip() or label != label.strip()
                    or len(label) > 100 or any(unicodedata.category(char) in {"Cc", "Cs"} for char in label)
                    or node_id in seen_ids or label in seen_labels):
                raise UpstreamCallError("booking_category_contract_invalid", "rejected")
            seen_ids.add(node_id)
            seen_labels.add(label)
            options.append({"node_id": node_id, "label": label})
        return options, reply

    def read_grid(self, user_id: str, credential_id: str, token: str,
                  node_id: str, target_date: str) -> ProtocolReply:
        return self._call(
            path="/phone/bookingByTime",
            payload={"nodeid": node_id, "selectdate": target_date},
            token=token,
            read_user=(user_id, credential_id),
        )

    def get_user_info(self, user_id: str, credential_id: str, token: str) -> ProtocolReply:
        return self._call(path="/userAddress/getUserInfo", payload={}, token=token,
                          encrypt=False, read_user=(user_id, credential_id))

    def get_children(self, token: str, node_id: str) -> ProtocolReply:
        return self._call(path="/phone/getChildren", payload={"nodeid": node_id}, token=token)

    def get_pay_price(self, token: str, *, node_id: str, target_date: str, coordinates: list[str],
                      appointment_type: str, reservation_person: str, time_list: list, node_list: list) -> ProtocolReply:
        return self._call(
            path="/phone/getPayPrice",
            payload={"appointmentType": appointment_type, "reserveDate": target_date,
                     "reserveTime": coordinates, "timeList": time_list, "nodeList": node_list,
                     "nodeid": node_id, "reservationPerson": reservation_person, "accompanyPerson": []},
            token=token,
        )

    def create_booking(self, token: str, *, node_id: str, target_date: str, coordinates: list[str],
                       txamt: str, time_list: list, node_list: list,
                       is_last_day: bool, childrennum: str) -> ProtocolReply:
        return self._call(
            path="/phone/createBookingBytime",
            payload={"appointmentDate": target_date, "booktype": 2, "childrennum": childrennum,
                     "coordinatesList": coordinates, "followList": [], "isLastDay": is_last_day,
                     "nodeList": node_list, "nodeid": node_id, "payprice": txamt,
                     "payway": _PAYWAY, "timeList": time_list, "txamt": txamt},
            token=token,
        )

    def pay_order(self, token: str, *, order_no: str, txamt: str, password: str) -> ProtocolReply:
        return self._call(
            path="/mobile/pay/openPlatFormPayOrder",
            payload={"orderno": order_no, "payway": _PAYWAY, "password": password, "txamt": txamt or ""},
            token=token,
        )

    def list_orders(self, token: str) -> ProtocolReply:
        return self._call(path="/phone/payOrderForPhone",
                          payload={"pageNumber": 1, "pageSize": 20, "ordertype": 1}, token=token)

    def order_details(self, token: str, *, booking_no: str, order_id: str) -> ProtocolReply:
        return self._call(path="/phone/payOrderDetails", payload={"bookingno": booking_no, "id": order_id}, token=token)

