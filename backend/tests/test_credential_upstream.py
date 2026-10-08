from __future__ import annotations

import json
import inspect
import unittest
import requests

from backend.credentials.contracts import AdapterValidationResult
from backend.credentials.upstream import (
    GET_USER_INFO_PATH,
    IDENTITY_CONTRACT_VERSION,
    UPSTREAM_GET_USER_INFO_ORIGIN,
    UpstreamContractAdapter,
    UpstreamHttpTransport,
)


def _success_body(identity: str | None = "synthetic-id") -> bytes:
    result_data = {"tel": "synthetic-phone", "username": "synthetic-user"}
    if identity is not None:
        result_data["idserial"] = identity
    return json.dumps(
        {"success": True, "message": "CORE10008", "resultData": result_data},
        separators=(",", ":"),
    ).encode("utf-8")


class FakeResponse:
    def __init__(self, status_code: int, chunks: list[bytes], headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size: int):
        assert chunk_size > 0
        yield from self.chunks

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []
        self.trust_env = True
        self.cookies = {}
        self.auth = None
        self.proxies = {}
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response

    def close(self):
        self.closed = True


def _transport(session, *, clock=None, max_response_bytes=65536, total_deadline=10):
    return UpstreamHttpTransport(
        session_factory=lambda: session,
        connect_timeout_seconds=3,
        read_timeout_seconds=5,
        total_deadline_seconds=total_deadline,
        max_response_bytes=max_response_bytes,
        clock=clock,
    )


def _adapter(session, **kwargs):
    return UpstreamContractAdapter(
        transport=_transport(
            session,
            clock=kwargs.get("clock"),
            max_response_bytes=kwargs.get("max_response_bytes", 65536),
            total_deadline=kwargs.get("total_deadline", 10),
        ),
        upstream_origin=UPSTREAM_GET_USER_INFO_ORIGIN,
        account_continuity_capability=True,
    )


class UpstreamContractAdapterTests(unittest.TestCase):
    def test_success_uses_only_the_confirmed_request_shape_and_returns_ephemeral_identity(self) -> None:
        response = FakeResponse(200, [_success_body()])
        session = FakeSession(response)
        adapter = _adapter(session)

        result = adapter.validate_token("synthetic.jwt.token")

        self.assertIsInstance(result, AdapterValidationResult)
        self.assertEqual(result.token_outcome, "success")
        self.assertEqual(result.safe_code, "get_user_info_success")
        self.assertEqual(result.identity_bytes, b"synthetic-id")
        self.assertEqual(result.identity_contract_version, IDENTITY_CONTRACT_VERSION)
        self.assertEqual(result.http_status_class, "2xx")
        self.assertNotIn("synthetic-id", repr(result))
        self.assertNotIn("synthetic-phone", repr(result))
        self.assertTrue(response.closed)

        url, options = session.calls[0]
        self.assertEqual(url, UPSTREAM_GET_USER_INFO_ORIGIN + GET_USER_INFO_PATH)
        self.assertEqual(options["json"], {})
        self.assertEqual(options["headers"]["token"], "synthetic.jwt.token")
        self.assertEqual(options["headers"]["Accept"], "*/*")
        self.assertEqual(options["headers"]["Origin"], UPSTREAM_GET_USER_INFO_ORIGIN)
        self.assertEqual(options["headers"]["Referer"], UPSTREAM_GET_USER_INFO_ORIGIN + "/")
        self.assertNotIn("authorization", {key.lower() for key in options["headers"]})
        self.assertEqual(options["allow_redirects"], False)
        self.assertTrue(options["verify"])
        self.assertTrue(options["stream"])
        self.assertEqual(options["timeout"], (3.0, 5.0))
        self.assertEqual(getattr(result, "dispatch_state", None), "complete")

    def test_each_validation_uses_a_fresh_non_environment_session(self) -> None:
        self.assertIn("session_factory", inspect.signature(UpstreamHttpTransport).parameters)
        sessions = []

        def make_session():
            session = FakeSession(FakeResponse(200, [_success_body()]))
            sessions.append(session)
            return session

        transport = UpstreamHttpTransport(
            session_factory=make_session,
            connect_timeout_seconds=3,
            read_timeout_seconds=5,
            total_deadline_seconds=10,
            max_response_bytes=65536,
        )
        adapter = UpstreamContractAdapter(
            transport=transport,
            upstream_origin=UPSTREAM_GET_USER_INFO_ORIGIN,
            account_continuity_capability=True,
        )

        adapter.validate_token("synthetic.one")
        adapter.validate_token("synthetic.two")

        self.assertEqual(len(sessions), 2)
        self.assertIsNot(sessions[0], sessions[1])
        for session in sessions:
            self.assertFalse(session.trust_env)
            self.assertFalse(session.cookies)
            self.assertIsNone(session.auth)
            self.assertEqual(session.proxies, {})
            self.assertTrue(session.closed)

    def test_incomplete_response_is_uncertain_and_does_not_claim_dispatch_completion(self) -> None:
        self.assertIn("session_factory", inspect.signature(UpstreamHttpTransport).parameters)
        class IncompleteResponse(FakeResponse):
            def iter_content(self, chunk_size: int):
                yield b'{"success":'
                raise requests.ConnectionError("synthetic disconnect")

        session = FakeSession(IncompleteResponse(200, []))
        transport = UpstreamHttpTransport(
            session_factory=lambda: session,
            connect_timeout_seconds=3,
            read_timeout_seconds=5,
            total_deadline_seconds=10,
            max_response_bytes=65536,
        )
        result = UpstreamContractAdapter(
            transport=transport,
            upstream_origin=UPSTREAM_GET_USER_INFO_ORIGIN,
            account_continuity_capability=True,
        ).validate_token("synthetic.jwt")

        self.assertEqual(result.token_outcome, "network_error")
        self.assertEqual(result.dispatch_state, "uncertain")

    def test_missing_identity_keeps_token_valid_but_does_not_create_identity(self) -> None:
        adapter = _adapter(FakeSession(FakeResponse(200, [_success_body(identity=None)])))

        result = adapter.validate_token("synthetic.jwt.token")

        self.assertEqual(result.token_outcome, "success")
        self.assertIsNone(result.identity_bytes)
        self.assertEqual(result.identity_contract_version, IDENTITY_CONTRACT_VERSION)

    def test_unapproved_identity_capability_discards_identity_even_when_present(self) -> None:
        adapter = UpstreamContractAdapter(
            transport=_transport(FakeSession(FakeResponse(200, [_success_body()]))),
            upstream_origin=UPSTREAM_GET_USER_INFO_ORIGIN,
            account_continuity_capability=False,
        )

        result = adapter.validate_token("synthetic.jwt.token")

        self.assertEqual(result.token_outcome, "success")
        self.assertIsNone(result.identity_bytes)
        self.assertIsNone(result.identity_contract_version)

    def test_unknown_success_code_and_business_failure_do_not_validate_token(self) -> None:
        cases = (
            ({"success": True, "message": "CORE99999", "resultData": {"idserial": "id"}}, "contract_drift"),
            ({"success": False, "message": "CORE10008", "resultData": {}}, "validation_unknown"),
        )
        for body, expected_outcome in cases:
            with self.subTest(success=body["success"], message=body["message"]):
                adapter = _adapter(FakeSession(FakeResponse(200, [json.dumps(body).encode()])))
                result = adapter.validate_token("synthetic.jwt.token")
                self.assertEqual(result.token_outcome, expected_outcome)
                self.assertIsNone(result.identity_bytes)

    def test_changed_envelope_and_non_object_result_data_are_contract_drift(self) -> None:
        bodies = (
            {"success": True, "message": "CORE10008", "resultData": {}, "extra": 1},
            {"success": True, "message": "CORE10008", "resultData": []},
            {"success": True, "message": "CORE10008"},
            ["not", "an", "object"],
        )
        for body in bodies:
            with self.subTest(body_type=type(body).__name__):
                adapter = _adapter(FakeSession(FakeResponse(200, [json.dumps(body).encode()])))
                result = adapter.validate_token("synthetic.jwt.token")
                self.assertEqual(result.token_outcome, "contract_drift")
                self.assertIsNone(result.identity_bytes)

    def test_http_statuses_are_safely_classified_without_parsing_error_body(self) -> None:
        cases = (
            (302, "contract_drift", None, "https://elsewhere.invalid/"),
            (401, "validation_unknown", None, None),
            (429, "rate_limited", "17", None),
            (503, "network_error", "31", None),
        )
        for status, outcome, retry_after, location in cases:
            headers = {"Retry-After": retry_after} if retry_after else {}
            if location:
                headers["Location"] = location
            response = FakeResponse(status, [b"untrusted upstream error body"], headers)
            adapter = _adapter(FakeSession(response))

            result = adapter.validate_token("synthetic.jwt.token")

            self.assertEqual(result.token_outcome, outcome)
            self.assertEqual(getattr(result, "http_status_code", None), status)
            self.assertEqual(result.retry_after_header, retry_after)
            self.assertIsNone(result.identity_bytes)
            self.assertNotIn("untrusted upstream", repr(result))
            self.assertTrue(response.closed)

    def test_oversized_response_is_stopped_and_closed(self) -> None:
        response = FakeResponse(200, [b"12345", b"67890"])
        adapter = _adapter(FakeSession(response), max_response_bytes=8)

        result = adapter.validate_token("synthetic.jwt.token")

        self.assertEqual(result.token_outcome, "contract_drift")
        self.assertEqual(result.safe_code, "upstream_response_too_large")
        self.assertTrue(response.closed)

    def test_total_deadline_is_checked_between_streamed_chunks_and_response_is_closed(self) -> None:
        response = FakeResponse(200, [_success_body()])
        session = FakeSession(response)
        clock_values = iter((0.0, 0.0, 0.0, 11.0))
        transport = _transport(session, clock=lambda: next(clock_values), total_deadline=10)
        adapter = UpstreamContractAdapter(
            transport=transport,
            upstream_origin=UPSTREAM_GET_USER_INFO_ORIGIN,
            account_continuity_capability=True,
        )

        result = adapter.validate_token("synthetic.jwt.token")

        self.assertEqual(result.token_outcome, "network_error")
        self.assertEqual(result.safe_code, "upstream_total_deadline_exceeded")
        self.assertTrue(response.closed)

    def test_network_errors_are_safe_and_do_not_include_request_material(self) -> None:
        session = FakeSession(error=TimeoutError("synthetic private request data"))
        result = _adapter(session).validate_token("synthetic.jwt.token")

        self.assertEqual(result.token_outcome, "network_error")
        self.assertEqual(result.safe_code, "upstream_transport_error")
        self.assertNotIn("private request data", repr(result))
        self.assertNotIn("synthetic.jwt.token", repr(result))

    def test_adapter_rejects_any_origin_outside_the_capture_allowlist(self) -> None:
        with self.assertRaises(ValueError):
            UpstreamContractAdapter(
                transport=_transport(FakeSession()),
                upstream_origin="https://other.example.invalid",
                account_continuity_capability=True,
            )

    def test_retry_after_header_is_bounded_before_returning_to_gate(self) -> None:
        response = FakeResponse(429, [], {"Retry-After": "1" * 300})
        result = _adapter(FakeSession(response)).validate_token("synthetic.jwt.token")

        self.assertEqual(result.token_outcome, "rate_limited")
        self.assertEqual(result.retry_after_header, "!oversized!")


if __name__ == "__main__":
    unittest.main()
