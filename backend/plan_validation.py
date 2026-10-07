from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import DEFAULT_NODEID


class PlanValidationError(ValueError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


def _error(message: str, field: str | None = None, value: Any = None) -> PlanValidationError:
    details: dict[str, Any] = {}
    if field:
        details["field"] = field
    if value is not None:
        details["value"] = value
    return PlanValidationError(message, details)


def _as_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _error(f"{field} must be an object", field, value)
    return value


def _as_text(value: Any, field: str, default: str = "", *, required: bool = False) -> str:
    if value is None:
        text = default
    else:
        text = str(value).strip()
    if required and not text:
        raise _error(f"{field} is required", field, value)
    return text or default


def _as_bool(value: Any, field: str, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in {0, 1}:
            return bool(value)
        raise _error(f"{field} must be a boolean", field, value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise _error(f"{field} must be a boolean", field, value)


def _as_optional_bool(value: Any, field: str) -> bool | None:
    if value is None or value == "":
        return None
    return _as_bool(value, field)


def _as_int(value: Any, field: str, default: int = 0, *, minimum: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise _error(f"{field} must be an integer", field, value)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _error(f"{field} must be an integer", field, value) from exc
    if parsed < minimum:
        raise _error(f"{field} must be >= {minimum}", field, value)
    return parsed


def _as_optional_int(value: Any, field: str, *, minimum: int = 0) -> int | None:
    if value is None or value == "":
        return None
    return _as_int(value, field, minimum=minimum)


def _duration_ms(
    value: Any,
    legacy_seconds_value: Any,
    field: str,
    *,
    default: int,
    minimum: int = 0,
) -> int:
    if value is not None and value != "":
        return _as_int(value, field, default, minimum=minimum)
    if legacy_seconds_value is not None and legacy_seconds_value != "":
        legacy_seconds = _as_int(
            legacy_seconds_value,
            f"{field.replace('Ms', 'Seconds')}",
            0,
            minimum=minimum,
        )
        return legacy_seconds * 1000
    return default


def _normalize_coord(value: Any, field: str) -> str:
    text = str(value).strip()
    parts = text.split("-")
    if len(parts) != 2:
        raise _error(f"{field} must use courtIndex-timeIndex format", field, value)
    try:
        court_index = int(parts[0])
        time_index = int(parts[1])
    except ValueError as exc:
        raise _error(f"{field} must use integer indices", field, value) from exc
    if court_index < 0 or time_index < 0:
        raise _error(f"{field} indices must be >= 0", field, value)
    return f"{court_index}-{time_index}"


def _normalize_queue_entry(value: Any, field: str) -> dict[str, Any]:
    if isinstance(value, dict):
        coords = value.get("coords")
        if coords is None:
            coords = value.get("reserveTime")
        preselect = _as_bool(value.get("preselect"), f"{field}.preselect", False)
    else:
        coords = value
        preselect = False
    if not isinstance(coords, list):
        raise _error(f"{field}.coords must be an array", f"{field}.coords", coords)
    cleaned = [_normalize_coord(coord, f"{field}.coords") for coord in coords]
    if not cleaned:
        raise _error(f"{field}.coords must not be empty", f"{field}.coords", coords)
    return {"coords": cleaned, "preselect": preselect}


def _normalize_queue(value: Any, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _error(f"{field} must be an array", field, value)
    return [_normalize_queue_entry(entry, f"{field}[{index}]") for index, entry in enumerate(value)]


def _normalize_timing_snapshot(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    snapshot = _as_object(value, "lastTimingSnapshot")
    return {
        "reserveDate": _as_text(snapshot.get("reserveDate"), "lastTimingSnapshot.reserveDate"),
        "timezone": _as_text(snapshot.get("timezone"), "lastTimingSnapshot.timezone"),
        "serverNowIso": _as_text(snapshot.get("serverNowIso"), "lastTimingSnapshot.serverNowIso"),
        "serverNowEpochMs": _as_optional_int(
            snapshot.get("serverNowEpochMs"),
            "lastTimingSnapshot.serverNowEpochMs",
            minimum=0,
        ),
        "openAtIso": _as_text(snapshot.get("openAtIso"), "lastTimingSnapshot.openAtIso"),
        "openAtEpochMs": _as_optional_int(
            snapshot.get("openAtEpochMs"),
            "lastTimingSnapshot.openAtEpochMs",
            minimum=0,
        ),
        "bookingWindowOpen": _as_optional_bool(
            snapshot.get("bookingWindowOpen"),
            "lastTimingSnapshot.bookingWindowOpen",
        ),
        "bookingWindowCheckEnforced": _as_optional_bool(
            snapshot.get("bookingWindowCheckEnforced"),
            "lastTimingSnapshot.bookingWindowCheckEnforced",
        ),
        "fetchedAtIso": _as_text(snapshot.get("fetchedAtIso"), "lastTimingSnapshot.fetchedAtIso"),
        "fetchedAtEpochMs": _as_optional_int(
            snapshot.get("fetchedAtEpochMs"),
            "lastTimingSnapshot.fetchedAtEpochMs",
            minimum=0,
        ),
    }


def normalize_plan_payload(value: Any) -> dict[str, Any]:
    plan = _as_object(value, "plan")
    booking_by_time_delay_ms = _as_int(
        plan.get("bookingByTimeDelayMs"),
        "bookingByTimeDelayMs",
        0,
        minimum=0,
    )
    get_pay_price_delay_ms = _as_int(
        plan.get("getPayPriceDelayMs"),
        "getPayPriceDelayMs",
        0,
        minimum=0,
    )
    create_booking_request_delay_source = plan.get("createBookingRequestDelayMs")
    if create_booking_request_delay_source is None or create_booking_request_delay_source == "":
        create_booking_request_delay_source = plan.get("payPriceDelayMs")
    create_booking_request_delay_ms = _as_int(
        create_booking_request_delay_source,
        "createBookingRequestDelayMs",
        0,
        minimum=0,
    )
    open_platform_pay_order_delay_source = plan.get("openPlatformPayOrderDelayMs")
    if open_platform_pay_order_delay_source is None or open_platform_pay_order_delay_source == "":
        open_platform_pay_order_delay_source = plan.get("createBookingDelayMs")
    open_platform_pay_order_delay_ms = _as_int(
        open_platform_pay_order_delay_source,
        "openPlatformPayOrderDelayMs",
        0,
        minimum=0,
    )
    payment_verify_start_delay_ms = _as_int(
        plan.get("paymentVerifyStartDelayMs"),
        "paymentVerifyStartDelayMs",
        0,
        minimum=0,
    )
    payment_verify_interval_ms = _as_int(
        plan.get("paymentVerifyIntervalMs"),
        "paymentVerifyIntervalMs",
        3000,
        minimum=1,
    )
    auto_run_lead_ms = _duration_ms(
        plan.get("autoRunLeadMs"),
        plan.get("autoRunLeadSeconds"),
        "autoRunLeadMs",
        default=100,
        minimum=0,
    )
    auto_run_delay_ms = _duration_ms(
        plan.get("autoRunDelayMs"),
        plan.get("autoRunDelaySeconds"),
        "autoRunDelayMs",
        default=0,
        minimum=0,
    )
    auto_run_queue_interval_ms = _as_int(
        plan.get("autoRunQueueIntervalMs"),
        "autoRunQueueIntervalMs",
        0,
        minimum=0,
    )
    auto_run_poll_ms = _as_int(plan.get("autoRunPollMs"), "autoRunPollMs", 100, minimum=1)
    return {
        "reserveDate": _as_text(plan.get("reserveDate"), "reserveDate", required=True),
        "nodeid": _as_text(plan.get("nodeid"), "nodeid", DEFAULT_NODEID, required=True),
        "appointmentType": _as_text(plan.get("appointmentType"), "appointmentType", "2", required=True),
        "preselectMode": _as_bool(plan.get("preselectMode"), "preselectMode", False),
        "autoSaveEnabled": _as_bool(plan.get("autoSaveEnabled"), "autoSaveEnabled", False),
        "bookingByTimeDelayEnabled": _as_bool(
            plan.get("bookingByTimeDelayEnabled"),
            "bookingByTimeDelayEnabled",
            booking_by_time_delay_ms > 0,
        ),
        "bookingByTimeDelayMs": booking_by_time_delay_ms,
        "getPayPriceDelayEnabled": _as_bool(
            plan.get("getPayPriceDelayEnabled"),
            "getPayPriceDelayEnabled",
            get_pay_price_delay_ms > 0,
        ),
        "getPayPriceDelayMs": get_pay_price_delay_ms,
        "createBookingRequestDelayEnabled": _as_bool(
            plan.get("createBookingRequestDelayEnabled"),
            "createBookingRequestDelayEnabled",
            create_booking_request_delay_ms > 0,
        ),
        "createBookingRequestDelayMs": create_booking_request_delay_ms,
        "openPlatformPayOrderDelayEnabled": _as_bool(
            plan.get("openPlatformPayOrderDelayEnabled"),
            "openPlatformPayOrderDelayEnabled",
            open_platform_pay_order_delay_ms > 0,
        ),
        "openPlatformPayOrderDelayMs": open_platform_pay_order_delay_ms,
        "paymentVerifyStartDelayEnabled": _as_bool(
            plan.get("paymentVerifyStartDelayEnabled"),
            "paymentVerifyStartDelayEnabled",
            payment_verify_start_delay_ms > 0,
        ),
        "paymentVerifyStartDelayMs": payment_verify_start_delay_ms,
        "paymentVerifyIntervalEnabled": _as_bool(
            plan.get("paymentVerifyIntervalEnabled"),
            "paymentVerifyIntervalEnabled",
            False,
        ),
        "paymentVerifyIntervalMs": payment_verify_interval_ms,
        "autoRunEnabled": _as_bool(plan.get("autoRunEnabled"), "autoRunEnabled", False),
        "autoRunLeadEnabled": _as_bool(
            plan.get("autoRunLeadEnabled"),
            "autoRunLeadEnabled",
            auto_run_lead_ms > 0,
        ),
        "autoRunLeadMs": auto_run_lead_ms,
        "autoRunDelayEnabled": _as_bool(
            plan.get("autoRunDelayEnabled"),
            "autoRunDelayEnabled",
            auto_run_delay_ms > 0,
        ),
        "autoRunDelayMs": auto_run_delay_ms,
        "autoRunQueueIntervalEnabled": _as_bool(
            plan.get("autoRunQueueIntervalEnabled"),
            "autoRunQueueIntervalEnabled",
            auto_run_queue_interval_ms > 0,
        ),
        "autoRunQueueIntervalMs": auto_run_queue_interval_ms,
        "autoRunPollMs": auto_run_poll_ms,
        "lastTimingSnapshot": _normalize_timing_snapshot(plan.get("lastTimingSnapshot")),
        "twoHourQueue": _normalize_queue(plan.get("twoHourQueue"), "twoHourQueue"),
        "oneHourQueue": _normalize_queue(plan.get("oneHourQueue"), "oneHourQueue"),
    }


def load_plan_file(plan_path: Path) -> dict[str, Any]:
    if not plan_path.exists():
        raise FileNotFoundError(f"Plan not found: {plan_path}")
    try:
        raw = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise PlanValidationError(f"invalid plan json: {exc.msg}", {"line": exc.lineno, "column": exc.colno}) from exc
    return normalize_plan_payload(raw)
