from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.credentials.types import CredentialOperationError
from backend.orders.status import ORDER_STATUSES, order_is_confirmed, order_status


class OrderQueryError(ValueError):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


def _identifier(value: object) -> str:
    if type(value) not in {str, int} or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(value)):
        raise OrderQueryError("order_response_invalid", 502)
    return str(value)


def _text(value: object, limit: int = 256) -> str | None:
    if (type(value) is not str or not value.strip() or len(value) > limit
            or any(unicodedata.category(char) in {"Cc", "Cs"} for char in value)):
        return None
    return value.strip()


def _count(value: object) -> int:
    if type(value) is int and 0 <= value <= 2**53 - 1:
        return value
    if type(value) is str and re.fullmatch(r"[0-9]{1,16}", value) and int(value) <= 2**53 - 1:
        return int(value)
    raise OrderQueryError("order_response_invalid", 502)


def _amount(value: object) -> str | None:
    if type(value) not in {str, int} or not re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,2})?", str(value)):
        return None
    try:
        amount = Decimal(str(value))
        return format(amount / 100, ".2f") if amount == amount.to_integral_value() else None
    except InvalidOperation:
        return None


def _projection(raw: dict, *, detail: bool = False) -> dict:
    if type(raw) is not dict:
        raise OrderQueryError("order_response_invalid", 502)
    code = order_status(raw.get("status"))
    return {
        "order_number": _text(raw.get("orderno"), 128),
        "appointment_date": _text(raw.get("appointmentdate"), 32),
        "booking_time": _text(raw.get("bookingtime"), 1000),
        "venue_name": _text(raw.get("nodename"), 256),
        "created_at": _text(raw.get("createdate"), 32),
        "status": code,
        "status_label": ORDER_STATUSES.get(code, "未知状态"),
        "reservation_confirmed": order_is_confirmed(raw),
        "amount_display": _amount(raw.get("payallamt") if detail else raw.get("totaltxamt", raw.get("txamt"))),
        "paid_at": _text(raw.get("paytime"), 32) if order_is_confirmed(raw) else None,
        "use_expires_at": _text(raw.get("expirationTime"), 32) if detail else None,
    }


class OrderQueryService:
    """Read owned Token orders; signed references bind detail reads to a listed order."""

    def __init__(self, *, credential_service, protocol, reference_secret: bytes, enabled: bool):
        self.credentials, self.protocol, self.enabled = credential_service, protocol, enabled
        self.references = URLSafeTimedSerializer(reference_secret, salt="yumao-order-query-v1")

    def _credential(self, user_id: str, credential_id: object):
        if not self.enabled:
            raise OrderQueryError("order_query_unavailable", 503)
        if type(credential_id) is not str or not 1 <= len(credential_id) <= 128:
            raise OrderQueryError("invalid_order_query")
        credential = self.credentials.get_for_user(user_id, credential_id)
        if credential is None:
            raise CredentialOperationError("credential_not_found", 404)
        return credential

    @staticmethod
    def _scope(user_id: str, session_id: str, credential) -> list:
        return [user_id, hashlib.sha256(session_id.encode()).hexdigest(), credential.credential_id,
                credential.credential_version, credential.current_token_revision_id]

    def list(self, user_id: str, session_id: str, credential_id: object, *,
             page: object = 1, page_size: object = 10, status: object = "") -> dict:
        if (type(page) is not int or not 1 <= page <= 10000
                or type(page_size) is not int or not 1 <= page_size <= 50
                or type(status) is not str or (status and status not in ORDER_STATUSES)):
            raise OrderQueryError("invalid_order_query")
        credential = self._credential(user_id, credential_id)
        reply = self.protocol.list_orders(page_number=page, page_size=page_size, status=status,
                                          read_user=(user_id, credential_id))
        data = reply.envelope.get("resultData")
        if reply.envelope.get("success") is not True:
            raise OrderQueryError("order_query_rejected", 502)
        if type(data) is not dict or type(data.get("content")) is not list or len(data["content"]) > 50:
            raise OrderQueryError("order_response_invalid", 502)
        current = self._credential(user_id, credential_id)
        if self._scope(user_id, session_id, current) != self._scope(user_id, session_id, credential):
            raise OrderQueryError("order_reference_expired", 409)
        number, size = _count(data.get("number")), _count(data.get("size"))
        total, pages = _count(data.get("totalElements")), _count(data.get("totalPages"))
        if number != page - 1 or size != page_size or len(data["content"]) > size:
            raise OrderQueryError("order_response_invalid", 502)
        orders = []
        for raw in data["content"]:
            item = _projection(raw)
            booking_no, order_id = _identifier(raw.get("bookingno")), _identifier(raw.get("id"))
            item["reference"] = self.references.dumps({
                "scope": self._scope(user_id, session_id, current),
                "bookingno": booking_no, "id": order_id, "orderno": item["order_number"],
            })
            orders.append(item)
        return {"orders": orders, "page": page, "page_size": size, "total": total,
                "total_pages": pages, "has_next": page < pages,
                "status_options": [{"code": code, "label": label} for code, label in ORDER_STATUSES.items()],
                "queried_at_utc_ms": reply.completed_at_utc_ms}

    def detail(self, user_id: str, session_id: str, credential_id: object, reference: object) -> dict:
        credential = self._credential(user_id, credential_id)
        if type(reference) is not str or not 1 <= len(reference) <= 4096:
            raise OrderQueryError("invalid_order_query")
        try:
            signed = self.references.loads(reference, max_age=600)
        except SignatureExpired:
            raise OrderQueryError("order_reference_expired", 409) from None
        except BadSignature:
            raise OrderQueryError("order_not_found", 404) from None
        if type(signed) is not dict or signed.get("scope") != self._scope(user_id, session_id, credential):
            raise OrderQueryError("order_not_found", 404)
        reply = self.protocol.order_details(booking_no=_identifier(signed.get("bookingno")),
                                            order_id=_identifier(signed.get("id")),
                                            read_user=(user_id, credential_id))
        raw = reply.envelope.get("resultData")
        if reply.envelope.get("success") is not True:
            raise OrderQueryError("order_query_rejected", 502)
        if (type(raw) is not dict or str(raw.get("bookingno") or "") != signed["bookingno"]
                or (signed.get("orderno") and raw.get("orderno") != signed["orderno"])):
            raise OrderQueryError("order_response_invalid", 502)
        if self._scope(user_id, session_id, self._credential(user_id, credential_id)) != signed["scope"]:
            raise OrderQueryError("order_reference_expired", 409)
        return {"order": _projection(raw, detail=True), "queried_at_utc_ms": reply.completed_at_utc_ms}
