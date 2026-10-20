from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from typing import Callable

from backend.availability_matching.live_observation import (
    LiveAvailabilityObservationError,
    OfficialBookingByTimeObservationAdapter,
)
from backend.availability_matching.models import AvailabilityError
from backend.booking_window import BookingWindowPolicy
from backend.credentials.service import CredentialService
from backend.credentials.types import CredentialOperationError
from backend.credentials.upstream import (
    BoundedHttpResponse,
    UPSTREAM_GET_USER_INFO_ORIGIN,
    UpstreamHttpTransport,
)
from backend.crypto import aes_cbc_encrypt_hex_upper


_BOOKING_NODE_LIST_BOOKTYPE = "1"  # Exact read-only list value observed in the official client.
_MAX_REF_ENTRIES = 2048
_MAX_NODE_OPTIONS = 128
_MAX_NODE_ID_CHARS = 128
_MAX_LABEL_CHARS = 200
_DEFAULT_REF_TTL_SECONDS = 600


class LiveAvailabilityError(AvailabilityError):
    def __init__(self, code: str, status: int = 400, retry_after_seconds: int | None = None):
        self.http_status = status
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code, status)


@dataclass(frozen=True, slots=True)
class _ScopeReference:
    user_id: str
    credential_id: str
    session_fingerprint: bytes
    node_id: str = field(repr=False)
    label: str
    expires_at_monotonic: float


class _ScopeReferenceRegistry:
    """Short-lived, process-local mapping; upstream node IDs never reach the browser."""

    def __init__(self, *, ttl_seconds: int = _DEFAULT_REF_TTL_SECONDS, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._items: dict[str, _ScopeReference] = {}

    @staticmethod
    def _fingerprint(session_id: str) -> bytes:
        return sha256(session_id.encode("utf-8", errors="strict")).digest()

    def issue(self, user_id: str, session_id: str, credential_id: str, node_id: str, label: str) -> str:
        now = self._clock()
        with self._lock:
            self._expire(now)
            if len(self._items) >= _MAX_REF_ENTRIES:
                oldest = min(self._items, key=lambda key: self._items[key].expires_at_monotonic)
                self._items.pop(oldest, None)
            reference = secrets.token_urlsafe(24)
            self._items[reference] = _ScopeReference(
                user_id=user_id,
                credential_id=credential_id,
                session_fingerprint=self._fingerprint(session_id),
                node_id=node_id,
                label=label,
                expires_at_monotonic=now + self._ttl,
            )
            return reference

    def resolve(self, reference: str, user_id: str, session_id: str, credential_id: str) -> _ScopeReference:
        now = self._clock()
        with self._lock:
            self._expire(now)
            item = self._items.get(reference)
            if (item is None or item.user_id != user_id or item.credential_id != credential_id
                    or item.session_fingerprint != self._fingerprint(session_id)):
                raise LiveAvailabilityError("live_query_scope_expired", 409)
            return item

    def _expire(self, now: float) -> None:
        expired = [key for key, item in self._items.items() if item.expires_at_monotonic <= now]
        for key in expired:
            self._items.pop(key, None)


class OfficialReadOnlyAvailabilityService:
    """Read official option/grid endpoints and expose only a display-only projection."""

    def __init__(
        self,
        *,
        credential_service: CredentialService,
        transport: UpstreamHttpTransport,
        booking_window_policy: BookingWindowPolicy,
        item_aes_key_ascii: str | None,
        item_aes_iv_ascii: str | None,
        enabled: bool,
        timezone_name: str,
        clock_utc_ms: Callable[[], int] | None = None,
    ):
        if (item_aes_key_ascii is None) != (item_aes_iv_ascii is None):
            raise ValueError("official request cipher key and IV must be configured together")
        if item_aes_key_ascii is not None and (
            len(item_aes_key_ascii.encode("utf-8")) != 16
            or len(item_aes_iv_ascii.encode("utf-8")) != 16
        ):
            raise ValueError("official request cipher key and IV must be 16 bytes")
        self._credentials = credential_service
        self._transport = transport
        self._window = booking_window_policy
        self._key = item_aes_key_ascii
        self._iv = item_aes_iv_ascii
        self._feature_enabled = bool(enabled)
        self._cipher_configured = bool(item_aes_key_ascii and item_aes_iv_ascii)
        self._enabled = self._feature_enabled and self._cipher_configured
        self._timezone_name = timezone_name
        self._clock = clock_utc_ms or (lambda: time.time_ns() // 1_000_000)
        self._references = _ScopeReferenceRegistry()
        self._adapter = OfficialBookingByTimeObservationAdapter()

    def options(self) -> dict:
        return {
            "enabled": self._enabled,
            "disabled_reason": (
                None if self._enabled else
                "request_cipher_missing" if self._feature_enabled else
                "feature_disabled"
            ),
            "min_read_interval_ms": self._credentials.gate.minimum_interval_ms,
            "source": "official_read_only",
            "physical_venue_catalog_configured": False,
            "can_bind_venue": False,
            "can_select_inventory": False,
            "can_select_intent": self._enabled,
            "can_match": False,
            "can_book": False,
            "can_pay": False,
            "can_create_job": False,
        }

    @staticmethod
    def _check_enabled(enabled: bool) -> None:
        if not enabled:
            raise LiveAvailabilityError("live_availability_disabled", 404)

    def _encode_payload(self, payload: dict) -> dict:
        if not self._key or not self._iv:
            raise LiveAvailabilityError("live_availability_disabled", 404)
        try:
            plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            encrypted = aes_cbc_encrypt_hex_upper(plaintext, self._key, self._iv)
        except (TypeError, ValueError, UnicodeError):
            raise LiveAvailabilityError("upstream_request_invalid", 400) from None
        return {"item": encrypted}

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

    def _post(self, path: str, payload: dict, token: str) -> BoundedHttpResponse:
        if path not in {"/phone/getBookingNode", "/phone/bookingByTime"}:
            raise LiveAvailabilityError("upstream_route_not_allowed", 400)
        return self._transport.post_json(
            UPSTREAM_GET_USER_INFO_ORIGIN + "/service/appointment/appointment" + path,
            headers=self._headers(token),
            json_body=self._encode_payload(payload),
        )

    @staticmethod
    def _decode_response(response: BoundedHttpResponse) -> dict:
        if response.error_code is not None:
            if response.status_code == 429:
                raise LiveAvailabilityError("upstream_rate_limited", 429)
            if response.status_code in {401, 403}:
                raise LiveAvailabilityError("upstream_authentication_unknown", 502)
            raise LiveAvailabilityError("upstream_read_failed", 502)
        if response.status_code != 200 or type(response.body) is not bytes:
            raise LiveAvailabilityError("upstream_read_failed", 502)
        try:
            value = json.loads(response.body.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise LiveAvailabilityError("upstream_response_invalid", 502) from None
        if type(value) is not dict:
            raise LiveAvailabilityError("upstream_response_invalid", 502)
        return value

    @staticmethod
    def _node_options(envelope: dict) -> list[dict]:
        nodes = envelope.get("resultData")
        if envelope.get("success") is not True or type(nodes) is not list or not 1 <= len(nodes) <= _MAX_NODE_OPTIONS:
            raise LiveAvailabilityError("upstream_booking_categories_unavailable", 502)
        seen_ids: set[str] = set()
        seen_labels: set[str] = set()
        result = []
        for item in nodes:
            if type(item) is not dict:
                raise LiveAvailabilityError("upstream_response_invalid", 502)
            raw_id = item.get("id")
            if type(raw_id) is str:
                node_id = raw_id
            elif type(raw_id) is int and type(raw_id) is not bool:
                node_id = str(raw_id)
            else:
                raise LiveAvailabilityError("upstream_response_invalid", 502)
            label = item.get("nodename")
            if (not 1 <= len(node_id) <= _MAX_NODE_ID_CHARS
                    or type(label) is not str or not 1 <= len(label.strip()) <= _MAX_LABEL_CHARS
                    or label != label.strip() or any(ord(char) < 32 for char in label)):
                raise LiveAvailabilityError("upstream_response_invalid", 502)
            if node_id in seen_ids or label in seen_labels:
                raise LiveAvailabilityError("upstream_response_invalid", 502)
            seen_ids.add(node_id)
            seen_labels.add(label)
            result.append({"node_id": node_id, "label": label})
        return result

    def list_booking_categories(self, *, user_id: str, session_id: str, credential_id: str) -> dict:
        self._check_enabled(self._enabled)
        try:
            response = self._credentials.with_availability_read_token(
                user_id,
                credential_id,
                lambda token: self._post(
                    "/phone/getBookingNode",
                    {"booktype": _BOOKING_NODE_LIST_BOOKTYPE},
                    token,
                ),
            )
        except CredentialOperationError as exc:
            raise self._credential_error(exc) from None
        envelope = self._decode_response(response)
        nodes = self._node_options(envelope)
        options = []
        for node in nodes:
            reference = self._references.issue(user_id, session_id, credential_id, node["node_id"], node["label"])
            options.append({
                "reference": reference,
                "label": node["label"],
                "kind": "booking_category",
                "physical_venue_verified": False,
            })
        return {
            "source": "official_read_only",
            "data_state": "live_observed_unverified",
            "options": options,
            "notice": "这些是官方预约类别/查询范围，不是已核验的实体场馆目录。",
        }

    def query_grid(
        self,
        *,
        user_id: str,
        session_id: str,
        credential_id: str,
        scope_reference: str,
        target_date: str,
    ) -> dict:
        self._check_enabled(self._enabled)
        if type(scope_reference) is not str or not 16 <= len(scope_reference) <= 128:
            raise LiveAvailabilityError("live_query_scope_expired", 409)
        try:
            requested_date = date.fromisoformat(target_date)
        except (TypeError, ValueError):
            raise LiveAvailabilityError("invalid_target_date", 400) from None
        if requested_date.isoformat() != target_date:
            raise LiveAvailabilityError("invalid_target_date", 400)
        now = self._clock()
        try:
            window = self._window.describe(requested_date, now)
        except (ValueError, OverflowError):
            raise LiveAvailabilityError("invalid_target_date", 400) from None
        if requested_date not in window.queryable_target_dates or not window.can_query:
            raise LiveAvailabilityError("booking_window_closed", 422)
        scope = self._references.resolve(scope_reference, user_id, session_id, credential_id)
        try:
            response = self._credentials.with_availability_read_token(
                user_id,
                credential_id,
                lambda token: self._post(
                    "/phone/bookingByTime",
                    {"nodeid": scope.node_id, "selectdate": target_date},
                    token,
                ),
            )
        except CredentialOperationError as exc:
            raise self._credential_error(exc) from None
        envelope = self._decode_response(response)
        captured_at = self._clock()
        try:
            return self._adapter.adapt(
                envelope,
                target_date=target_date,
                timezone_name=window.business_timezone_name,
                query_scope_label=scope.label,
                captured_at_utc_ms=captured_at,
            )
        except LiveAvailabilityObservationError as exc:
            raise LiveAvailabilityError(exc.code, exc.status) from None

    @staticmethod
    def _credential_error(error: CredentialOperationError) -> LiveAvailabilityError:
        code = error.code
        if code in {"upstream_read_rate_limited", "validation_rate_limited"}:
            return LiveAvailabilityError("upstream_rate_limited", 429, error.retry_after_seconds)
        if code in {"credential_token_expired", "credential_token_invalid"}:
            return LiveAvailabilityError("credential_requires_validation", 409)
        if code in {"credential_not_found", "credential_disabled"}:
            return LiveAvailabilityError("credential_unavailable", 409)
        if code in {"credential_account_binding_unresolved", "credential_account_reconfirmation_required"}:
            return LiveAvailabilityError("credential_account_unverified", 409)
        if code == "upstream_read_not_configured":
            return LiveAvailabilityError("upstream_read_not_configured", 503)
        if code == "upstream_read_failed":
            return LiveAvailabilityError("upstream_read_failed", 502)
        if code == "credential_version_conflict":
            return LiveAvailabilityError("credential_changed", 409)
        return LiveAvailabilityError("credential_requires_validation", 409)
