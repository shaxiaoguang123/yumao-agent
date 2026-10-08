from __future__ import annotations

import json
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit

import requests

from backend.credentials.contracts import AdapterValidationResult, DispatchState, HttpStatusClass


UPSTREAM_GET_USER_INFO_ORIGIN = "https://bdtyg.cugb.edu.cn"
GET_USER_INFO_PATH = "/service/appointment/appointment/userAddress/getUserInfo"
IDENTITY_CONTRACT_VERSION = "getuserinfo-idserial-v1"
_MAX_RETRY_AFTER_HEADER_CHARS = 256
_MAX_IDENTITY_BYTES = 512
_STREAM_CHUNK_BYTES = 4096


@dataclass(frozen=True, slots=True)
class BoundedHttpResponse:
    status_code: int | None
    body: bytes | None = field(repr=False)
    retry_after_header: str | None = field(repr=False)
    error_code: str | None
    dispatch_state: DispatchState = "uncertain"


def _bounded_retry_after(headers) -> str | None:
    value = headers.get("Retry-After") if headers is not None else None
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > _MAX_RETRY_AFTER_HEADER_CHARS:
        return "!oversized!"
    value = value.strip()
    return value if value else None


def _status_class(status_code: int | None) -> HttpStatusClass | None:
    if status_code is None or not 100 <= status_code <= 599:
        return None
    return f"{status_code // 100}xx"  # type: ignore[return-value]


class UpstreamHttpTransport:
    """Narrow, testable transport for the fixed read-only upstream endpoint."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], object] = requests.Session,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        total_deadline_seconds: float,
        max_response_bytes: int,
        clock: Callable[[], float] = time.monotonic,
    ):
        values = (
            connect_timeout_seconds,
            read_timeout_seconds,
            total_deadline_seconds,
        )
        if any(value <= 0 for value in values):
            raise ValueError("upstream timeouts must be positive")
        if connect_timeout_seconds >= total_deadline_seconds:
            raise ValueError("connect timeout must be less than the total deadline")
        if read_timeout_seconds >= total_deadline_seconds:
            raise ValueError("read timeout must be less than the total deadline")
        if isinstance(max_response_bytes, bool) or max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._session_factory = session_factory
        self._connect_timeout = float(connect_timeout_seconds)
        self._read_timeout = float(read_timeout_seconds)
        self._total_deadline = float(total_deadline_seconds)
        self._max_response_bytes = int(max_response_bytes)
        self._clock = time.monotonic if clock is None else clock

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict,
    ) -> BoundedHttpResponse:
        started_at = self._clock()
        session = None
        response = None
        try:
            session = self._session_factory()
            # A validation attempt must not inherit a cookie, netrc auth, proxy, or
            # other mutable Requests state from an earlier Credential operation.
            session.trust_env = False
            session.cookies.clear()
            session.auth = None
            session.proxies.clear()
            response = session.post(
                url,
                json=json_body,
                headers=headers,
                timeout=(self._connect_timeout, self._read_timeout),
                allow_redirects=False,
                verify=True,
                stream=True,
            )
            status_code = int(response.status_code)
            retry_after = _bounded_retry_after(getattr(response, "headers", None))
            if self._clock() - started_at >= self._total_deadline:
                return BoundedHttpResponse(
                    None, None, retry_after, "upstream_total_deadline_exceeded", "uncertain"
                )

            headers_received = getattr(response, "headers", {})
            content_length = headers_received.get("Content-Length")
            if isinstance(content_length, str) and content_length.isdecimal():
                if int(content_length) > self._max_response_bytes:
                    return BoundedHttpResponse(
                        status_code, None, retry_after, "upstream_response_too_large", "uncertain"
                    )

            body = bytearray()
            chunks = iter(response.iter_content(chunk_size=_STREAM_CHUNK_BYTES))
            received_bytes = 0
            while True:
                if self._clock() - started_at >= self._total_deadline:
                    return BoundedHttpResponse(
                        status_code, None, retry_after, "upstream_total_deadline_exceeded", "uncertain"
                    )
                try:
                    chunk = next(chunks)
                except StopIteration:
                    break
                if not isinstance(chunk, bytes):
                    return BoundedHttpResponse(
                        status_code, None, retry_after, "upstream_invalid_stream", "uncertain"
                    )
                if not chunk:
                    continue
                if received_bytes + len(chunk) > self._max_response_bytes:
                    return BoundedHttpResponse(
                        status_code, None, retry_after, "upstream_response_too_large", "uncertain"
                    )
                received_bytes += len(chunk)
                if status_code == 200:
                    body.extend(chunk)
                if self._clock() - started_at >= self._total_deadline:
                    return BoundedHttpResponse(
                        status_code, None, retry_after, "upstream_total_deadline_exceeded", "uncertain"
                    )
            return BoundedHttpResponse(
                status_code,
                bytes(body) if status_code == 200 else None,
                retry_after,
                None,
                "complete",
            )
        except (requests.RequestException, OSError, TimeoutError, ValueError):
            return BoundedHttpResponse(None, None, None, "upstream_transport_error", "uncertain")
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass


class UpstreamContractAdapter:
    def __init__(
        self,
        *,
        transport: UpstreamHttpTransport,
        upstream_origin: str,
        account_continuity_capability: bool,
    ):
        parsed = urlsplit(upstream_origin)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("upstream origin is not the approved HTTPS origin") from exc
        authority = parsed.hostname.lower() if parsed.hostname else ""
        if port is not None:
            authority = f"{authority}:{port}"
        normalized = f"{parsed.scheme.lower()}://{authority}"
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or normalized != UPSTREAM_GET_USER_INFO_ORIGIN
        ):
            raise ValueError("upstream origin is not the approved HTTPS origin")
        self._transport = transport
        self._origin = normalized
        self._account_continuity_capability = bool(account_continuity_capability)

    @staticmethod
    def _result(
        outcome: str,
        safe_code: str,
        *,
        status_code: int | None = None,
        dispatch_state: DispatchState = "not_dispatched",
        identity_bytes: bytes | None = None,
        identity_contract_version: str | None = None,
        retry_after_header: str | None = None,
    ) -> AdapterValidationResult:
        return AdapterValidationResult(
            token_outcome=outcome,  # type: ignore[arg-type]
            safe_code=safe_code,
            identity_bytes=identity_bytes,
            identity_contract_version=identity_contract_version,
            http_status_class=_status_class(status_code),
            retry_after_header=retry_after_header,
            dispatch_state=dispatch_state,
            http_status_code=status_code,
        )

    def validate_token(self, token: str) -> AdapterValidationResult:
        if not isinstance(token, str) or not token:
            return self._result("validation_unknown", "invalid_token_input")

        response = self._transport.post_json(
            self._origin + GET_USER_INFO_PATH,
            headers={
                "Accept": "*/*",
                "Origin": self._origin,
                "Referer": self._origin + "/",
                "token": token,
            },
            json_body={},
        )
        status = response.status_code
        dispatch_state = response.dispatch_state
        if response.error_code is not None:
            outcome = "contract_drift" if response.error_code in {
                "upstream_response_too_large",
                "upstream_invalid_stream",
            } else "network_error"
            return self._result(
                outcome, response.error_code, status_code=status, dispatch_state=dispatch_state
            )
        if status is None:
            return self._result(
                "network_error", "upstream_transport_error", dispatch_state=dispatch_state
            )
        if status != 200:
            if status == 429:
                return self._result(
                    "rate_limited",
                    "upstream_rate_limited",
                    status_code=status,
                    retry_after_header=response.retry_after_header,
                    dispatch_state=dispatch_state,
                )
            if status == 408 or 500 <= status <= 599:
                return self._result(
                    "network_error",
                    "upstream_transient_error",
                    status_code=status,
                    retry_after_header=response.retry_after_header,
                    dispatch_state=dispatch_state,
                )
            if 300 <= status <= 399:
                return self._result(
                    "contract_drift", "upstream_redirect_rejected", status_code=status,
                    dispatch_state=dispatch_state,
                )
            return self._result(
                "validation_unknown", "upstream_validation_unknown", status_code=status,
                dispatch_state=dispatch_state,
            )

        try:
            payload = json.loads(response.body.decode("utf-8", errors="strict"))
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
            return self._result("contract_drift", "upstream_invalid_json", status_code=status,
                                dispatch_state=dispatch_state)
        if not isinstance(payload, dict) or set(payload) != {"success", "message", "resultData"}:
            return self._result("contract_drift", "upstream_response_shape_changed", status_code=status,
                                dispatch_state=dispatch_state)
        if type(payload["success"]) is not bool:
            return self._result("contract_drift", "upstream_response_shape_changed", status_code=status,
                                dispatch_state=dispatch_state)
        if payload["success"] is not True:
            # The captures do not establish an invalid-Token mapping.
            return self._result("validation_unknown", "upstream_validation_unknown", status_code=status,
                                dispatch_state=dispatch_state)
        if payload["message"] != "CORE10008" or not isinstance(payload["resultData"], dict):
            return self._result("contract_drift", "upstream_response_shape_changed", status_code=status,
                                dispatch_state=dispatch_state)

        identity_bytes = None
        identity_contract_version = None
        if self._account_continuity_capability:
            identity_contract_version = IDENTITY_CONTRACT_VERSION
            identity = payload["resultData"].get("idserial")
            if isinstance(identity, str) and identity:
                try:
                    encoded_identity = identity.encode("utf-8", errors="strict")
                except UnicodeEncodeError:
                    encoded_identity = b""
                if encoded_identity and len(encoded_identity) <= _MAX_IDENTITY_BYTES:
                    if not any(unicodedata.category(character).startswith("C") for character in identity):
                        identity_bytes = encoded_identity

        return self._result(
            "success",
            "get_user_info_success",
            status_code=status,
            identity_bytes=identity_bytes,
            identity_contract_version=identity_contract_version,
            retry_after_header=response.retry_after_header,
            dispatch_state=dispatch_state,
        )
