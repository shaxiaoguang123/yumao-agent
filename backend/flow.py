from __future__ import annotations

import json
import time
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .availability import build_availability_payload
from .client import ApiClient
from .config import AES_IV_ASCII, AES_KEY_ASCII, BASE_URL, DEFAULT_NODEID, PAY_PASSWORD, PAYWAY, TOKEN
from .crypto import aes_cbc_encrypt_hex_upper
from .logging_utils import setup_logging
from .plan_validation import PlanValidationError, load_plan_file
from .time_utils import booking_window_open, format_timestamp


LOGGER = setup_logging()

PAID_ORDER_STATUSES = {"1", "4", "8"}
PENDING_PAYMENT_STATUS = "5"
PAYMENT_VERIFY_MAX_ATTEMPTS = 15
PAYMENT_VERIFY_INTERVAL_MS = 3000


@dataclass
class FlowResult:
    success: bool
    message: str
    details: dict


def _make_headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": "https://bdtyg.cugb.edu.cn",
        "Referer": "https://bdtyg.cugb.edu.cn/",
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
            "MicroMessenger/8.0.47(0x18002f2f) NetType/WIFI Language/zh_CN "
            "miniProgram/appBrand"
        ),
        "token": token,
    }


def _encrypt_item(payload: dict) -> dict:
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return {
        "item": aes_cbc_encrypt_hex_upper(plaintext, AES_KEY_ASCII, AES_IV_ASCII),
    }


def _safe_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _format_ts(ts: datetime | None = None) -> str:
    return format_timestamp(ts)


def _sleep_between_queue_items(should_sleep: bool, interval_ms: int) -> None:
    if not should_sleep or interval_ms <= 0:
        return
    LOGGER.info("[sleep] queue_interval %dms", interval_ms)
    time.sleep(interval_ms / 1000)


def _sleep_for_stage(enabled: bool, delay_ms: int, stage_label: str) -> None:
    if not enabled or delay_ms <= 0:
        return
    LOGGER.info("[sleep] %s %dms", stage_label, delay_ms)
    time.sleep(delay_ms / 1000)


def _log_step(
    label: str,
    reserve_time: list[str],
    step: str,
    resp: dict,
    preselect: bool = False,
    attempt_start: str | None = None,
    attempt_end: str | None = None,
    elapsed_ms: float | None = None,
) -> None:
    success = bool(resp.get("success")) if isinstance(resp, dict) else False
    duration = round(elapsed_ms, 2) if elapsed_ms is not None else None
    LOGGER.info(
        "[run_flow] step=%s success=%s slot_count=%d elapsed_ms=%s",
        step,
        success,
        len(reserve_time),
        duration,
    )


def _parse_coord(coord: str) -> tuple[int, int] | None:
    parts = str(coord).split("-")
    if len(parts) != 2:
        return None
    try:
        court_idx = int(parts[0])
        time_idx = int(parts[1])
    except ValueError:
        return None
    if court_idx < 0 or time_idx < 0:
        return None
    return court_idx, time_idx


def _build_slot_context(reserve_time: list[str], availability: dict) -> list[dict]:
    time_list = availability.get("raw", {}).get("timeList") or []
    node_list = availability.get("raw", {}).get("nodeList") or []
    slot_map = {
        (slot.get("courtIndex"), slot.get("timeIndex")): slot
        for slot in availability.get("grid", [])
    }
    context: list[dict] = []
    for coord in reserve_time:
        parsed = _parse_coord(coord)
        if not parsed:
            context.append({"coord": coord, "error": "invalid coord"})
            continue
        court_idx, time_idx = parsed
        time_item = time_list[time_idx] if time_idx < len(time_list) else {}
        node_item = node_list[court_idx] if court_idx < len(node_list) else {}
        slot = slot_map.get((court_idx, time_idx)) or {}
        context.append(
            {
                "coord": coord,
                "timeIndex": time_idx,
                "courtIndex": court_idx,
                "time": time_item.get("time"),
                "timeStatus": time_item.get("status"),
                "court": node_item.get("sitename"),
                "available": slot.get("available"),
                "price": slot.get("price"),
                "conflictCodes": slot.get("conflictCodes"),
            }
        )
    return context


def _extract_booking_meta(booking_data: dict, reserve_date: str) -> dict:
    meta_keys = [
        "bookingstartdate",
        "bookingenddate",
        "bookingstarttime",
        "bookingendtime",
        "start",
        "end",
        "mintimeselect",
        "maxtimeselect",
        "maxAppointmentNodeNum",
        "isNew",
    ]
    meta = {key: booking_data.get(key) for key in meta_keys}
    start = meta.get("bookingstartdate")
    end = meta.get("bookingenddate")
    meta["reserveDateInRange"] = bool(start and end and start <= reserve_date <= end)
    return meta


def fetch_user_info(client: ApiClient, token: str) -> dict:
    headers = _make_headers(token)
    return client.post_json("/userAddress/getUserInfo", headers, {})


def fetch_children(client: ApiClient, token: str, nodeid: str) -> dict:
    headers = _make_headers(token)
    payload = _encrypt_item({"nodeid": nodeid})
    return client.post_json("/phone/getChildren", headers, payload)


def fetch_booking_by_time(client: ApiClient, token: str, nodeid: str, reserve_date: str) -> dict:
    headers = _make_headers(token)
    payload = _encrypt_item({"nodeid": nodeid, "selectdate": reserve_date})
    return client.post_json("/phone/bookingByTime", headers, payload)


def fetch_pay_price(
    client: ApiClient,
    token: str,
    nodeid: str,
    reserve_date: str,
    reserve_time: list[str],
    appointment_type: str,
    reservation_person: str,
    accompany_person: list[dict],
    time_list: list,
    node_list: list,
) -> dict:
    headers = _make_headers(token)
    payload = _encrypt_item(
        {
            "appointmentType": appointment_type,
            "reserveDate": reserve_date,
            "reserveTime": reserve_time,
            "timeList": time_list,
            "nodeList": node_list,
            "nodeid": nodeid,
            "reservationPerson": reservation_person,
            "accompanyPerson": accompany_person,
        }
    )
    return client.post_json("/phone/getPayPrice", headers, payload)


def fetch_orders(
    client: ApiClient,
    token: str,
    page_number: int = 1,
    page_size: int = 10,
    order_type: int = 1,
) -> dict:
    """
    Query user's appointment/payment orders.

    Captured request payload (decrypted from req logs) looks like:
      {"pageNumber":1,"pageSize":10,"ordertype":1}
    """
    headers = _make_headers(token)
    payload = _encrypt_item({"pageNumber": page_number, "pageSize": page_size, "ordertype": order_type})
    return client.post_json("/phone/payOrderForPhone", headers, payload)


def fetch_order_details(client: ApiClient, token: str, bookingno: str, order_id: str) -> dict:
    """
    Query order details by (bookingno, id).

    Captured request payload (decrypted from req logs) looks like:
      {"bookingno":"1489382","id":"1330335873690247168"}
    """
    headers = _make_headers(token)
    payload = _encrypt_item({"bookingno": bookingno, "id": order_id})
    return client.post_json("/phone/payOrderDetails", headers, payload)


def _build_error_response(exc: Exception) -> dict:
    return {
        "success": False,
        "message": str(exc),
        "resultData": {"errorType": exc.__class__.__name__},
    }


def _find_order_by_orderno(resp: dict, orderno: str) -> dict | None:
    content = ((resp or {}).get("resultData") or {}).get("content") or []
    for item in content:
        if _safe_str(item.get("orderno")) == orderno:
            return item
    return None


def _is_paid_order(detail: dict | None) -> bool:
    detail = detail or {}
    paytime = _safe_str(detail.get("paytime"))
    status = _safe_str(detail.get("status"))
    return bool(paytime) or status in PAID_ORDER_STATUSES


def _verify_payment_result(
    client: ApiClient,
    token: str,
    orderno: str,
    reserve_date: str,
    max_attempts: int = PAYMENT_VERIFY_MAX_ATTEMPTS,
    start_delay_ms: int = 0,
    interval_ms: int = PAYMENT_VERIFY_INTERVAL_MS,
) -> dict:
    last_orders_resp: dict | None = None
    last_order: dict | None = None
    last_detail_resp: dict | None = None
    last_detail: dict | None = None

    if start_delay_ms > 0:
        LOGGER.info("[sleep] paymentVerifyStartDelay %dms", start_delay_ms)
        time.sleep(start_delay_ms / 1000)

    for attempt in range(1, max_attempts + 1):
        LOGGER.info("[payment_verify] attempt %d/%d", attempt, max_attempts)
        try:
            orders_resp = fetch_orders(client, token, page_number=1, page_size=20, order_type=1)
        except Exception as exc:
            orders_resp = _build_error_response(exc)
        last_orders_resp = orders_resp
        order = _find_order_by_orderno(orders_resp, orderno) if orders_resp.get("success") else None
        if order:
            last_order = order
            bookingno = _safe_str(order.get("bookingno"))
            order_id = _safe_str(order.get("id"))
            order_status = _safe_str(order.get("status"))
            LOGGER.info("[payment_verify] matching order found")
            if bookingno and order_id:
                try:
                    detail_resp = fetch_order_details(client, token, bookingno, order_id)
                except Exception as exc:
                    detail_resp = _build_error_response(exc)
                last_detail_resp = detail_resp
                if detail_resp.get("success"):
                    detail = detail_resp.get("resultData") or {}
                    last_detail = detail
                    LOGGER.info("[payment_verify] order details checked")
                    if _is_paid_order(detail):
                        return {
                            "success": True,
                            "message": "payment verified via payOrderDetails",
                            "verifiedBy": "payOrderDetails",
                            "order": order,
                            "orderDetails": detail,
                            "verificationAttempts": attempt,
                        }
            if order_status in PAID_ORDER_STATUSES:
                return {
                    "success": True,
                    "message": "payment verified via payOrderForPhone",
                    "verifiedBy": "payOrderForPhone",
                    "order": order,
                    "orderDetails": last_detail,
                    "verificationAttempts": attempt,
                }

        if attempt < max_attempts:
            time.sleep(interval_ms / 1000)

    final_message = "payment result unverified after order creation"
    final_status = _safe_str((last_detail or {}).get("status")) or _safe_str((last_order or {}).get("status"))
    if final_status == PENDING_PAYMENT_STATUS:
        final_message = "order created but still pending payment"

    return {
        "success": False,
        "message": final_message,
        "verifiedBy": None,
        "order": last_order,
        "orderDetails": last_detail,
        "ordersResponse": last_orders_resp,
        "detailsResponse": last_detail_resp,
        "verificationAttempts": max_attempts,
    }


def create_booking_by_time(
    client: ApiClient,
    token: str,
    nodeid: str,
    reserve_date: str,
    reserve_time: list[str],
    txamt: str,
    time_list: list,
    node_list: list,
    is_last_day: bool,
    childrennum: str,
) -> dict:
    headers = _make_headers(token)
    payload = _encrypt_item(
        {
            "appointmentDate": reserve_date,
            "booktype": 2,
            "childrennum": childrennum,
            "coordinatesList": reserve_time,
            "followList": [],
            "isLastDay": is_last_day,
            "nodeList": node_list,
            "nodeid": nodeid,
            "payprice": txamt,
            "payway": PAYWAY,
            "timeList": time_list,
            "txamt": txamt,
        }
    )
    return client.post_json("/phone/createBookingBytime", headers, payload)


def open_platform_pay_order(
    client: ApiClient,
    token: str,
    orderno: str,
    txamt: str,
    password: str,
) -> dict:
    headers = _make_headers(token)
    payload = _encrypt_item(
        {
            "orderno": orderno,
            "payway": PAYWAY,
            "password": password,
            "txamt": txamt or "",
        }
    )
    return client.post_json("/mobile/pay/openPlatFormPayOrder", headers, payload)


def _iter_queue(queue: Iterable[Iterable[str] | dict]) -> list[dict]:
    cleaned: list[dict] = []
    for entry in queue:
        preselect = False
        coords: Iterable[str] | None = None
        if isinstance(entry, dict):
            coords = entry.get("coords") or entry.get("reserveTime")
            preselect = bool(entry.get("preselect"))
        elif isinstance(entry, Iterable) and not isinstance(entry, (str, bytes)):
            coords = entry
        if coords is None:
            continue
        entry_list = [str(item) for item in coords if str(item)]
        if entry_list:
            cleaned.append({"coords": entry_list, "preselect": preselect})
    return cleaned


def _load_plan(plan_path: Path) -> dict:
    return load_plan_file(plan_path)


def _add_attempt(
    details: dict,
    label: str,
    reserve_time: list[str],
    step: str,
    resp: dict,
    payload: dict | None = None,
    preselect: bool = False,
    attempt_start: str | None = None,
    attempt_end: str | None = None,
    elapsed_ms: float | None = None,
) -> None:
    entry = {
        "ts": _format_ts(),
        "queue": label,
        "reserveTime": reserve_time,
        "step": step,
        "message": resp.get("message") if isinstance(resp, dict) else str(resp),
        "success": bool(resp.get("success")) if isinstance(resp, dict) else False,
        "response": resp,
        "preselect": preselect,
    }
    if attempt_start:
        entry["attemptStart"] = attempt_start
    if attempt_end:
        entry["attemptEnd"] = attempt_end
    if elapsed_ms is not None:
        entry["elapsedMs"] = round(elapsed_ms, 2)
    if payload is not None:
        entry["payload"] = payload
    details.setdefault("attempts", []).append(entry)


def run_plan(plan_path: Path, auto_run: bool = False) -> FlowResult:
    if not TOKEN:
        return FlowResult(False, "TOKEN missing in new/.env", {})
    if not PAY_PASSWORD:
        return FlowResult(False, "PAY_PASSWORD missing in new/.env", {})

    client = ApiClient(BASE_URL)
    try:
        plan = _load_plan(plan_path)
    except FileNotFoundError as exc:
        LOGGER.error("[run_plan] plan file not found")
        return FlowResult(False, str(exc), {"errorType": "FileNotFoundError"})
    except PlanValidationError as exc:
        LOGGER.error("[run_plan] plan validation error")
        details = {"errorType": "PlanValidationError"}
        details.update(exc.details)
        return FlowResult(False, str(exc), details)
    except Exception as exc:
        LOGGER.error("[run_plan] load plan failed (%s)", exc.__class__.__name__)
        return FlowResult(False, f"load plan failed: {exc}", {"errorType": exc.__class__.__name__})

    reserve_date = str(plan.get("reserveDate") or "")
    nodeid = str(plan.get("nodeid") or DEFAULT_NODEID)
    appointment_type = str(plan.get("appointmentType") or "2")
    two_hour_queue = _iter_queue(plan.get("twoHourQueue") or [])
    one_hour_queue = _iter_queue(plan.get("oneHourQueue") or [])
    booking_by_time_delay_enabled = bool(plan.get("bookingByTimeDelayEnabled"))
    booking_by_time_delay_ms = _safe_int(plan.get("bookingByTimeDelayMs"))
    get_pay_price_delay_enabled = bool(plan.get("getPayPriceDelayEnabled"))
    get_pay_price_delay_ms = _safe_int(plan.get("getPayPriceDelayMs"))
    create_booking_request_delay_enabled = bool(plan.get("createBookingRequestDelayEnabled"))
    create_booking_request_delay_ms = _safe_int(plan.get("createBookingRequestDelayMs"))
    open_platform_pay_order_delay_enabled = bool(plan.get("openPlatformPayOrderDelayEnabled"))
    open_platform_pay_order_delay_ms = _safe_int(plan.get("openPlatformPayOrderDelayMs"))
    payment_verify_start_delay_enabled = bool(plan.get("paymentVerifyStartDelayEnabled"))
    payment_verify_start_delay_ms = _safe_int(plan.get("paymentVerifyStartDelayMs"))
    payment_verify_interval_enabled = bool(plan.get("paymentVerifyIntervalEnabled"))
    payment_verify_interval_ms = _safe_int(plan.get("paymentVerifyIntervalMs"), PAYMENT_VERIFY_INTERVAL_MS)
    queue_interval_enabled = auto_run and bool(plan.get("autoRunQueueIntervalEnabled"))
    queue_interval_ms = _safe_int(plan.get("autoRunQueueIntervalMs"))

    LOGGER.info(
        "[run_plan] plan loaded: two_hour_entries=%d one_hour_entries=%d",
        len(two_hour_queue),
        len(one_hour_queue),
    )

    details: dict[str, Any] = {
        "reserveDate": reserve_date,
        "nodeid": nodeid,
        "twoHourCount": len(two_hour_queue),
        "oneHourCount": len(one_hour_queue),
        "bookingByTimeDelayEnabled": booking_by_time_delay_enabled,
        "bookingByTimeDelayMs": booking_by_time_delay_ms,
        "getPayPriceDelayEnabled": get_pay_price_delay_enabled,
        "getPayPriceDelayMs": get_pay_price_delay_ms,
        "createBookingRequestDelayEnabled": create_booking_request_delay_enabled,
        "createBookingRequestDelayMs": create_booking_request_delay_ms,
        "openPlatformPayOrderDelayEnabled": open_platform_pay_order_delay_enabled,
        "openPlatformPayOrderDelayMs": open_platform_pay_order_delay_ms,
        "paymentVerifyStartDelayEnabled": payment_verify_start_delay_enabled,
        "paymentVerifyStartDelayMs": payment_verify_start_delay_ms,
        "paymentVerifyIntervalEnabled": payment_verify_interval_enabled,
        "paymentVerifyIntervalMs": payment_verify_interval_ms,
        "autoRunQueueIntervalEnabled": queue_interval_enabled,
        "autoRunQueueIntervalMs": queue_interval_ms,
        "autoRun": auto_run,
    }

    if not reserve_date:
        return FlowResult(False, "reserveDate missing in plan", details)
    if not two_hour_queue and not one_hour_queue:
        return FlowResult(False, "queue is empty", details)

    user_info = fetch_user_info(client, TOKEN)
    if not user_info.get("success"):
        details["userInfo"] = user_info
        return FlowResult(False, "getUserInfo failed", details)
    reservation_person = str((user_info.get("resultData") or {}).get("idserial") or "")
    LOGGER.info("[run_plan] getUserInfo completed")
    if not reservation_person:
        details["userInfo"] = user_info
        return FlowResult(False, "reservationPerson missing", details)

    children_resp = fetch_children(client, TOKEN, nodeid)
    if children_resp.get("success"):
        childrennum = str((children_resp.get("resultData") or {}).get("childrennum") or "1")
    else:
        childrennum = "1"
        details["children"] = children_resp
    details["childrennum"] = childrennum
    LOGGER.info("[run_plan] child metadata loaded")

    max_rounds = 3
    details["maxRounds"] = max_rounds
    total_attempts = max_rounds * (len(two_hour_queue) + len(one_hour_queue))
    details["totalAttempts"] = total_attempts
    attempt_index = 0
    for round_idx in range(1, max_rounds + 1):
        details["round"] = round_idx
        LOGGER.info("[round %d/%d] starting, %d queue entries", round_idx, max_rounds, len(two_hour_queue) + len(one_hour_queue))
        for label, queue in (("twoHourQueue", two_hour_queue), ("oneHourQueue", one_hour_queue)):
            for entry in queue:
                attempt_index += 1
                sleep_after_attempt = queue_interval_enabled and queue_interval_ms > 0 and attempt_index < total_attempts
                reserve_time = entry["coords"]
                preselect = entry["preselect"]
                attempt_start_ts = _format_ts()
                attempt_start = time.perf_counter()
                LOGGER.info("[attempt %d/%d] queue=%s", attempt_index, total_attempts, label)
                _sleep_for_stage(booking_by_time_delay_enabled, booking_by_time_delay_ms, "bookingByTimeDelay")
                booking = fetch_booking_by_time(client, TOKEN, nodeid, reserve_date)
                if not booking.get("success"):
                    attempt_end_ts = _format_ts()
                    elapsed_ms = (time.perf_counter() - attempt_start) * 1000
                    _log_step(
                        label,
                        reserve_time,
                        "bookingByTime",
                        booking,
                        preselect,
                        attempt_start=attempt_start_ts,
                        attempt_end=attempt_end_ts,
                        elapsed_ms=elapsed_ms,
                    )
                    _add_attempt(
                        details,
                        label,
                        reserve_time,
                        "bookingByTime",
                        booking,
                        preselect=preselect,
                        attempt_start=attempt_start_ts,
                        attempt_end=attempt_end_ts,
                        elapsed_ms=elapsed_ms,
                    )
                    _sleep_between_queue_items(sleep_after_attempt, queue_interval_ms)
                    continue

                booking_data = booking.get("resultData") or {}
                booking_meta = _extract_booking_meta(booking_data, reserve_date)
                window_open = booking_window_open(booking_meta, reserve_date)
                LOGGER.info("[step] bookingByTime completed, window_open=%s", window_open)
                if not window_open:
                    resp = {
                        "success": False,
                        "message": "booking window closed",
                        "resultData": {
                            "bookingWindowOpen": False,
                            "bookingMeta": booking_meta,
                        },
                    }
                    attempt_end_ts = _format_ts()
                    elapsed_ms = (time.perf_counter() - attempt_start) * 1000
                    _log_step(
                        label,
                        reserve_time,
                        "booking_window_check",
                        resp,
                        preselect,
                        attempt_start=attempt_start_ts,
                        attempt_end=attempt_end_ts,
                        elapsed_ms=elapsed_ms,
                    )
                    _add_attempt(
                        details,
                        label,
                        reserve_time,
                        "booking_window_check",
                        resp,
                        {"bookingMeta": booking_meta},
                        preselect,
                        attempt_start=attempt_start_ts,
                        attempt_end=attempt_end_ts,
                        elapsed_ms=elapsed_ms,
                    )
                    details["bookingMeta"] = booking_meta
                    details["bookingWindowOpen"] = False
                    return FlowResult(False, "booking window closed", details)

                availability = build_availability_payload(booking)
                time_list = availability["raw"]["timeList"]
                node_list = availability["raw"]["nodeList"]

                available_map = {
                    (slot["courtIndex"], slot["timeIndex"]): slot["available"]
                    for slot in availability["grid"]
                }
                invalid_coords = []
                unavailable_coords = []
                for coord in reserve_time:
                    parsed = _parse_coord(coord)
                    if not parsed:
                        invalid_coords.append(coord)
                        continue
                    if not available_map.get(parsed, False):
                        unavailable_coords.append(coord)

                if invalid_coords or unavailable_coords:
                    msg = "invalid coords" if invalid_coords else "unavailable coords"
                    resp = {
                        "success": False,
                        "message": msg,
                        "resultData": {"invalid": invalid_coords, "unavailable": unavailable_coords},
                    }
                    attempt_end_ts = _format_ts()
                    elapsed_ms = (time.perf_counter() - attempt_start) * 1000
                    _log_step(
                        label,
                        reserve_time,
                        "availability_check",
                        resp,
                        preselect,
                        attempt_start=attempt_start_ts,
                        attempt_end=attempt_end_ts,
                        elapsed_ms=elapsed_ms,
                    )
                    _add_attempt(
                        details,
                        label,
                        reserve_time,
                        "availability_check",
                        resp,
                        preselect=preselect,
                        attempt_start=attempt_start_ts,
                        attempt_end=attempt_end_ts,
                        elapsed_ms=elapsed_ms,
                    )
                    _sleep_between_queue_items(sleep_after_attempt, queue_interval_ms)
                    continue
                LOGGER.info("[step] availability check succeeded, slot_count=%d", len(reserve_time))
                slot_context = _build_slot_context(reserve_time, availability)

                pay_payload = {
                    "appointmentType": appointment_type,
                    "reserveDate": reserve_date,
                    "reserveTime": reserve_time,
                    "nodeid": nodeid,
                    "reservationPerson": reservation_person,
                    "timeListLen": len(time_list),
                    "nodeListLen": len(node_list),
                    "bookingMeta": booking_meta,
                    "slotContext": slot_context,
                }
                _sleep_for_stage(get_pay_price_delay_enabled, get_pay_price_delay_ms, "getPayPriceDelay")
                pay_price = fetch_pay_price(
                    client,
                    TOKEN,
                    nodeid,
                    reserve_date,
                    reserve_time,
                    appointment_type,
                    reservation_person,
                    [],
                    time_list,
                    node_list,
                )
                if not pay_price.get("success"):
                    attempt_end_ts = _format_ts()
                    elapsed_ms = (time.perf_counter() - attempt_start) * 1000
                    _log_step(
                        label,
                        reserve_time,
                        "getPayPrice",
                        pay_price,
                        preselect,
                        attempt_start=attempt_start_ts,
                        attempt_end=attempt_end_ts,
                        elapsed_ms=elapsed_ms,
                    )
                    _add_attempt(
                        details,
                        label,
                        reserve_time,
                        "getPayPrice",
                        pay_price,
                        pay_payload,
                        preselect,
                        attempt_start=attempt_start_ts,
                        attempt_end=attempt_end_ts,
                        elapsed_ms=elapsed_ms,
                    )
                    _sleep_between_queue_items(sleep_after_attempt, queue_interval_ms)
                    continue

                price_data = pay_price.get("resultData") or {}
                txamt = str(price_data.get("txamt") or "")
                is_last_day = bool(booking_data.get("bookingenddate") == reserve_date)
                LOGGER.info("[step] getPayPrice completed")

                order_payload = {
                    "appointmentDate": reserve_date,
                    "booktype": 2,
                    "childrennum": childrennum,
                    "coordinatesList": reserve_time,
                    "isLastDay": is_last_day,
                    "nodeid": nodeid,
                    "payprice": txamt,
                    "payway": PAYWAY,
                    "txamt": txamt,
                    "timeListLen": len(time_list),
                    "nodeListLen": len(node_list),
                    "bookingMeta": booking_meta,
                    "slotContext": slot_context,
                    "appointmentType": appointment_type,
                    "reservationPerson": reservation_person,
                }

                _sleep_for_stage(
                    create_booking_request_delay_enabled,
                    create_booking_request_delay_ms,
                    "createBookingRequestDelay",
                )
                order = create_booking_by_time(
                    client,
                    TOKEN,
                    nodeid,
                    reserve_date,
                    reserve_time,
                    txamt,
                    time_list,
                    node_list,
                    is_last_day,
                    childrennum,
                )
                if not order.get("success"):
                    attempt_end_ts = _format_ts()
                    elapsed_ms = (time.perf_counter() - attempt_start) * 1000
                    _log_step(
                        label,
                        reserve_time,
                        "createBookingBytime",
                        order,
                        preselect,
                        attempt_start=attempt_start_ts,
                        attempt_end=attempt_end_ts,
                        elapsed_ms=elapsed_ms,
                    )
                    _add_attempt(
                        details,
                        label,
                        reserve_time,
                        "createBookingBytime",
                        order,
                        order_payload,
                        preselect,
                        attempt_start=attempt_start_ts,
                        attempt_end=attempt_end_ts,
                        elapsed_ms=elapsed_ms,
                    )
                    _sleep_between_queue_items(sleep_after_attempt, queue_interval_ms)
                    continue

                orderno = str((order.get("resultData") or {}).get("orderno") or "")
                LOGGER.info("[step] createBookingBytime completed")
                details["createdOrder"] = {
                    "queue": label,
                    "reserveTime": reserve_time,
                    "orderno": orderno,
                    "preselect": preselect,
                }
                if not orderno:
                    attempt_end_ts = _format_ts()
                    elapsed_ms = (time.perf_counter() - attempt_start) * 1000
                    _add_attempt(
                        details,
                        label,
                        reserve_time,
                        "orderno missing",
                        order,
                        order_payload,
                        preselect,
                        attempt_start=attempt_start_ts,
                        attempt_end=attempt_end_ts,
                        elapsed_ms=elapsed_ms,
                    )
                    _sleep_between_queue_items(sleep_after_attempt, queue_interval_ms)
                    continue

                _sleep_for_stage(
                    open_platform_pay_order_delay_enabled,
                    open_platform_pay_order_delay_ms,
                    "openPlatformPayOrderDelay",
                )

                try:
                    pay_resp = open_platform_pay_order(client, TOKEN, orderno, txamt, PAY_PASSWORD)
                except Exception as exc:
                    pay_resp = _build_error_response(exc)
                if pay_resp.get("success"):
                    attempt_end_ts = _format_ts()
                    elapsed_ms = (time.perf_counter() - attempt_start) * 1000
                    _log_step(
                        label,
                        reserve_time,
                        "openPlatFormPayOrder",
                        pay_resp,
                        preselect,
                        attempt_start=attempt_start_ts,
                        attempt_end=attempt_end_ts,
                        elapsed_ms=elapsed_ms,
                    )
                    _add_attempt(
                        details,
                        label,
                        reserve_time,
                        "openPlatFormPayOrder",
                        pay_resp,
                        {"orderno": orderno, "txamt": txamt},
                        preselect,
                        attempt_start=attempt_start_ts,
                        attempt_end=attempt_end_ts,
                        elapsed_ms=elapsed_ms,
                    )
                    details["success"] = {
                        "queue": label,
                        "reserveTime": reserve_time,
                        "orderno": orderno,
                        "preselect": preselect,
                    }
                    return FlowResult(True, f"success via {label}", details)

                attempt_end_ts = _format_ts()
                elapsed_ms = (time.perf_counter() - attempt_start) * 1000
                _log_step(
                    label,
                    reserve_time,
                    "openPlatFormPayOrder",
                    pay_resp,
                    preselect,
                    attempt_start=attempt_start_ts,
                    attempt_end=attempt_end_ts,
                    elapsed_ms=elapsed_ms,
                )
                _add_attempt(
                    details,
                    label,
                    reserve_time,
                    "openPlatFormPayOrder",
                    pay_resp,
                    preselect=preselect,
                    attempt_start=attempt_start_ts,
                    attempt_end=attempt_end_ts,
                    elapsed_ms=elapsed_ms,
                )
                payment_verify = _verify_payment_result(
                    client,
                    TOKEN,
                    orderno,
                    reserve_date,
                    start_delay_ms=(
                        payment_verify_start_delay_ms if payment_verify_start_delay_enabled else 0
                    ),
                    interval_ms=(
                        payment_verify_interval_ms
                        if payment_verify_interval_enabled and payment_verify_interval_ms > 0
                        else PAYMENT_VERIFY_INTERVAL_MS
                    ),
                )
                verify_attempt_end_ts = _format_ts()
                verify_elapsed_ms = (time.perf_counter() - attempt_start) * 1000
                verify_resp = {
                    "success": bool(payment_verify.get("success")),
                    "message": payment_verify.get("message"),
                    "resultData": {
                        "verifiedBy": payment_verify.get("verifiedBy"),
                        "verificationAttempts": payment_verify.get("verificationAttempts"),
                        "order": payment_verify.get("order"),
                        "orderDetails": payment_verify.get("orderDetails"),
                    },
                }
                _log_step(
                    label,
                    reserve_time,
                    "paymentVerification",
                    verify_resp,
                    preselect,
                    attempt_start=attempt_start_ts,
                    attempt_end=verify_attempt_end_ts,
                    elapsed_ms=verify_elapsed_ms,
                )
                _add_attempt(
                    details,
                    label,
                    reserve_time,
                    "paymentVerification",
                    verify_resp,
                    {"orderno": orderno},
                    preselect,
                    attempt_start=attempt_start_ts,
                    attempt_end=verify_attempt_end_ts,
                    elapsed_ms=verify_elapsed_ms,
                )
                details["paymentVerification"] = payment_verify
                if payment_verify.get("success"):
                    verified_order = payment_verify.get("order") or {}
                    verified_detail = payment_verify.get("orderDetails") or {}
                    details["success"] = {
                        "queue": label,
                        "reserveTime": reserve_time,
                        "orderno": orderno,
                        "preselect": preselect,
                        "bookingno": _safe_str(verified_order.get("bookingno")),
                        "id": _safe_str(verified_order.get("id")),
                        "verifiedBy": payment_verify.get("verifiedBy"),
                        "paytime": _safe_str(verified_detail.get("paytime")),
                        "status": _safe_str(verified_detail.get("status") or verified_order.get("status")),
                    }
                    return FlowResult(True, f"success via {label} (verified)", details)

                return FlowResult(False, payment_verify.get("message") or "payment result unverified", details)

    LOGGER.warning("[run_plan] all %d attempts exhausted across %d rounds", total_attempts, max_rounds)
    return FlowResult(False, "all queue attempts failed", details)
