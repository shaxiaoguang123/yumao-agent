from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from backend.credentials.contracts import AdapterValidationResult
from backend.credentials.request_gate import GateOperationContext
from backend.db import connect_database
from backend.migrate import migrate_database
from support import credential_test_settings


BUSY_TIMEOUT_MS = 5000
ORIGIN = "http://localhost:5173"
NOW = 1_800_000_000_000


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _token(marker: str = "api-test") -> str:
    header = _b64url(b'{"alg":"none","typ":"JWT"}')
    payload = _b64url(json.dumps({"exp": NOW // 1000 + 30 * 86_400, "marker": marker}).encode())
    return f"{header}.{payload}.signature"


class FakeAdapter:
    def __init__(self) -> None:
        self.results: list[AdapterValidationResult] = []
        self.calls: list[str] = []

    def validate_token(self, token: str) -> AdapterValidationResult:
        self.calls.append(token)
        if self.results:
            return self.results.pop(0)
        return AdapterValidationResult(
            "success",
            "get_user_info_success",
            b"synthetic-account-a",
            "getuserinfo-idserial-v1",
            "2xx",
            None,
            "complete",
            200,
        )


class CredentialApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="credential-api-")
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "credentials.sqlite3"
        migrate_database(self.database_path, BUSY_TIMEOUT_MS)
        self.app = __import__("backend.app", fromlist=["*"]).create_app(
            {
                **credential_test_settings(self.database_path),
                "TESTING": True,
                "APP_ALLOWED_ORIGINS": ORIGIN,
            }
        )
        self.app.testing = True
        self.service = self.app.extensions["credential_service"]
        self.gate = self.app.extensions["upstream_request_gate"]
        self.gate.minimum_interval_ms = 1
        self.adapter = FakeAdapter()
        self.service.adapter = self.adapter
        self.client_a = self.app.test_client()
        self.client_b = self.app.test_client()
        self._insert_user("user-a", "Alice")
        self._insert_user("user-b", "Bob")
        self.csrf_a = self._authenticate(self.client_a, "user-a")
        self.csrf_b = self._authenticate(self.client_b, "user-b")

    def _insert_user(self, user_id: str, username: str) -> None:
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            connection.execute(
                """INSERT INTO users
                   (user_id, username, normalized_username, password_hash, role, status,
                    created_at_utc_ms, updated_at_utc_ms)
                   VALUES (?, ?, ?, 'synthetic-hash', 'user', 'active', ?, ?)""",
                (user_id, username, username.casefold(), NOW, NOW),
            )

    def _authenticate(self, client, user_id: str) -> str:
        session_id, csrf = self.app.extensions["session_service"].create(user_id, NOW)
        client.set_cookie("yumao_session", session_id)
        return csrf

    def _headers(self, csrf: str | None = None, *, origin: str = ORIGIN) -> dict[str, str]:
        headers = {"Origin": origin}
        if csrf is not None:
            headers["X-CSRF-Token"] = csrf
        return headers

    def _clear_gate_spacing(self) -> None:
        with closing(connect_database(self.database_path, BUSY_TIMEOUT_MS)) as connection:
            connection.execute(
                """UPDATE upstream_request_gate
                   SET next_allowed_at_utc_ms=NULL, upstream_backoff_until_utc_ms=NULL
                   WHERE endpoint_key='getUserInfo'"""
            )

    def _seed_credential(self, user_id: str = "user-a", marker: str = "seed"):
        return self.service.create(user_id, "Seed credential", _token(marker), time.time_ns() // 1_000_000)

    def _body(self, response):
        value = response.get_json()
        self.assertIsInstance(value, dict)
        return value

    def test_credential_routes_require_an_application_session(self) -> None:
        anonymous = self.app.test_client()
        response = anonymous.get("/api/credentials")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self._body(response), {"error": "session_invalid"})

    def test_mutation_routes_require_csrf_and_trusted_origin(self) -> None:
        credential = self._seed_credential()
        requests = (
            ("post", "/api/credentials", {"label": "New", "token": _token()}),
            ("post", f"/api/credentials/{credential.credential_id}/validate", {
                "expected_credential_version": credential.credential_version,
                "expected_current_token_revision_id": credential.current_token_revision_id,
            }),
            ("post", f"/api/credentials/{credential.credential_id}/rotate-token", {
                "token": _token("rotate"),
                "expected_credential_version": credential.credential_version,
                "expected_current_token_revision_id": credential.current_token_revision_id,
            }),
            ("patch", f"/api/credentials/{credential.credential_id}", {
                "expected_credential_version": credential.credential_version, "label": "Renamed",
            }),
            ("delete", f"/api/credentials/{credential.credential_id}", {
                "expected_credential_version": credential.credential_version,
            }),
        )
        calls_before = len(self.adapter.calls)
        for method, path, body in requests:
            with self.subTest(method=method, path=path):
                response = getattr(self.client_a, method)(path, json=body, headers=self._headers())
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self._body(response)["error"], "csrf_invalid")
        response = self.client_a.post(
            "/api/credentials", json={"label": "New", "token": _token()},
            headers=self._headers(self.csrf_a, origin="https://attacker.invalid"),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._body(response)["error"], "origin_not_allowed")
        self.assertEqual(len(self.adapter.calls), calls_before)

    def test_create_rejects_oversized_and_unknown_json_fields(self) -> None:
        oversized = b'{"label":"x","token":"' + (b"a" * (64 * 1024)) + b'"}'
        response = self.client_a.post(
            "/api/credentials", data=oversized, content_type="application/json",
            headers=self._headers(self.csrf_a),
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self._body(response)["error"], "request_too_large")

        response = self.client_a.post(
            "/api/credentials",
            json={"label": "Known", "token": _token(), "role": "admin"},
            headers=self._headers(self.csrf_a),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._body(response)["error"], "invalid_request")
        self.assertEqual(self.adapter.calls, [])

    def test_create_maps_json_integer_and_nesting_parser_limits_to_invalid_request(self) -> None:
        oversized_integer = (
            '{"label":"Home","token":"synthetic-token","extra":'
            + ("9" * 5000)
            + "}"
        )
        deeply_nested = (
            '{"label":"Home","token":"synthetic-token","extra":'
            + ("{" * 1400)
            + '"end":true'
            + ("}" * 1400)
            + "}"
        )
        calls_before = len(self.adapter.calls)

        for body in (oversized_integer, deeply_nested):
            with self.subTest(body_bytes=len(body)):
                response = self.client_a.post(
                    "/api/credentials",
                    data=body,
                    content_type="application/json",
                    headers=self._headers(self.csrf_a),
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self._body(response), {"error": "invalid_request"})

        self.assertEqual(len(self.adapter.calls), calls_before)

    def test_create_returns_exact_safe_dto_and_never_echoes_token_or_identity(self) -> None:
        token = _token("never-echo-this")

        response = self.client_a.post(
            "/api/credentials", json={"label": "Home", "token": token},
            headers=self._headers(self.csrf_a),
        )

        self.assertEqual(response.status_code, 201)
        body = self._body(response)
        self.assertEqual(set(body), {"credential"})
        credential = body["credential"]
        self.assertEqual(
            set(credential),
            {
                "credential_id", "label", "credential_version", "current_token_revision_id",
                "enabled", "account_binding_state", "requires_revalidation", "expiry_state",
                "token_expires_at_utc", "last_confirmed_validation_state",
                "last_successful_validation_at_utc", "latest_requested_validation_attempt",
            },
        )
        self.assertEqual(credential["account_binding_state"], "confirmed")
        self.assertEqual(credential["label"], "Home")
        self.assertTrue(credential["token_expires_at_utc"].endswith("Z"))
        attempt = credential["latest_requested_validation_attempt"]
        self.assertEqual(
            set(attempt),
            {
                "validation_attempt_id", "operation_kind", "current_token_revision_snapshot_id",
                "token_revision_id", "started_at_utc", "completed_at_utc", "attempt_result",
                "account_binding_outcome", "apply_state",
            },
        )
        self.assertTrue(attempt["started_at_utc"].endswith("Z"))
        self.assertNotIn(token, response.get_data(as_text=True))
        self.assertNotIn("synthetic-account-a", response.get_data(as_text=True))
        self.assertNotIn("fingerprint", response.get_data(as_text=True))
        self.assertEqual(response.headers.get("Set-Cookie"), None)

    def test_list_and_mutations_are_owner_scoped(self) -> None:
        credential_a = self._seed_credential("user-a", "a")
        self._clear_gate_spacing()
        credential_b = self._seed_credential("user-b", "b")
        self._clear_gate_spacing()

        listed = self.client_a.get("/api/credentials")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["credential_id"] for item in self._body(listed)["credentials"]], [credential_a.credential_id])

        response = self.client_a.patch(
            f"/api/credentials/{credential_a.credential_id}",
            json={"expected_credential_version": credential_a.credential_version, "label": "Edited"},
            headers=self._headers(self.csrf_a),
        )
        self.assertEqual(response.status_code, 200)
        updated = self._body(response)["credential"]
        self.assertEqual(updated["label"], "Edited")
        self.assertEqual(updated["account_binding_state"], "confirmed")
        self.assertEqual(self.service.get_for_user("user-b", credential_b.credential_id).label, "Seed credential")

        response = self.client_a.patch(
            f"/api/credentials/{credential_a.credential_id}",
            json={"expected_credential_version": updated["credential_version"], "enabled": False},
            headers=self._headers(self.csrf_a),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self._body(response)["credential"]["enabled"])
        self.assertEqual(self._body(response)["credential"]["account_binding_state"], "confirmed")

        response = self.client_a.delete(
            f"/api/credentials/{credential_a.credential_id}",
            json={"expected_credential_version": self._body(response)["credential"]["credential_version"]},
            headers=self._headers(self.csrf_a),
        )
        self.assertEqual(response.status_code, 204)
        remaining = self.client_a.get("/api/credentials")
        self.assertEqual(self._body(remaining)["credentials"], [])
        self.assertIsNotNone(self.service.get_for_user("user-b", credential_b.credential_id))

    def test_cross_user_ids_are_the_same_non_disclosing_404_as_missing_ids(self) -> None:
        credential_b = self._seed_credential("user-b", "b")
        self._clear_gate_spacing()
        missing_id = "does-not-exist"
        operations = (
            ("post", "validate", {"expected_credential_version": credential_b.credential_version,
                                   "expected_current_token_revision_id": credential_b.current_token_revision_id}),
            ("post", "rotate-token", {"token": _token("rot"),
                                        "expected_credential_version": credential_b.credential_version,
                                        "expected_current_token_revision_id": credential_b.current_token_revision_id}),
            ("patch", "", {"expected_credential_version": credential_b.credential_version, "label": "x"}),
            ("delete", "", {"expected_credential_version": credential_b.credential_version}),
        )
        for method, suffix, body in operations:
            with self.subTest(method=method, suffix=suffix):
                path = f"/api/credentials/{credential_b.credential_id}/{suffix}".rstrip("/")
                cross_user = getattr(self.client_a, method)(path, json=body, headers=self._headers(self.csrf_a))
                missing_path = f"/api/credentials/{missing_id}/{suffix}".rstrip("/")
                missing = getattr(self.client_a, method)(missing_path, json=body, headers=self._headers(self.csrf_a))
                self.assertEqual(cross_user.status_code, 404)
                self.assertEqual(missing.status_code, 404)
                self.assertEqual(self._body(cross_user), {"error": "credential_not_found"})
                self.assertEqual(self._body(missing), {"error": "credential_not_found"})

    def test_validate_and_rotate_map_safe_results_and_preserve_app_session(self) -> None:
        credential = self._seed_credential()
        self._clear_gate_spacing()
        self.adapter.results = [AdapterValidationResult(
            "explicit_invalid", "synthetic-invalid", None, None, "4xx", None, "complete", 401
        )]
        response = self.client_a.post(
            f"/api/credentials/{credential.credential_id}/validate",
            json={"expected_credential_version": credential.credential_version,
                  "expected_current_token_revision_id": credential.current_token_revision_id},
            headers=self._headers(self.csrf_a),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self._body(response)["error"], "credential_token_invalid")
        self.assertNotEqual(response.status_code, 401)
        session = self.client_a.get("/api/auth/session")
        self.assertEqual(session.status_code, 200)
        self.assertTrue(self._body(session)["authenticated"])

        self.adapter.results = [AdapterValidationResult(
            "success", "get_user_info_success", b"synthetic-account-a",
            "getuserinfo-idserial-v1", "2xx", None, "complete", 200,
        )]
        current = self.service.get_for_user("user-a", credential.credential_id)
        response = self.client_a.post(
            f"/api/credentials/{credential.credential_id}/rotate-token",
            json={"token": _token("replacement"),
                  "expected_credential_version": current.credential_version,
                  "expected_current_token_revision_id": current.current_token_revision_id},
            headers=self._headers(self.csrf_a),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._body(response)["result"], "token_rotated")
        self.assertNotIn(_token("replacement"), response.get_data(as_text=True))

    def test_not_configured_gate_returns_503_without_persisting_token(self) -> None:
        self.gate.minimum_interval_ms = None
        token = _token("must-not-persist")

        response = self.client_a.post(
            "/api/credentials", json={"label": "No gate", "token": token},
            headers=self._headers(self.csrf_a),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self._body(response), {"error": "validation_not_configured"})
        self.assertEqual(self.service.list_for_user("user-a"), [])
        self.assertEqual(self.adapter.calls, [])

    def test_gate_rate_limit_returns_retry_after_header_and_json(self) -> None:
        active = self.gate.acquire(
            GateOperationContext(user_id="user-b", credential_id=None, operation_kind="create_candidate"),
            time.time_ns() // 1_000_000,
            lambda _connection, _context: None,
        )
        self.assertTrue(active.allowed)
        token = _token("rate-limited")

        response = self.client_a.post(
            "/api/credentials", json={"label": "Busy", "token": token},
            headers=self._headers(self.csrf_a),
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(self._body(response)["error"], "validation_rate_limited")
        self.assertGreaterEqual(self._body(response)["retry_after_seconds"], 1)
        self.assertEqual(response.headers["Retry-After"], str(self._body(response)["retry_after_seconds"]))
        self.assertEqual(self.service.list_for_user("user-a"), [])
        self.assertEqual(self.adapter.calls, [])

    def test_upstream_rate_limit_uses_shared_backoff_retry_metadata(self) -> None:
        self.adapter.results = [AdapterValidationResult(
            "rate_limited", "upstream_rate_limited", None, None, "4xx", "17", "complete", 429
        )]

        response = self.client_a.post(
            "/api/credentials", json={"label": "Limited", "token": _token()},
            headers=self._headers(self.csrf_a),
        )

        self.assertEqual(response.status_code, 429)
        body = self._body(response)
        self.assertEqual(body["error"], "upstream_rate_limited")
        self.assertGreaterEqual(body["retry_after_seconds"], 17)
        self.assertEqual(response.headers["Retry-After"], str(body["retry_after_seconds"]))
        self.assertEqual(self.service.list_for_user("user-a"), [])

    def test_uncertain_upstream_rate_limit_preserves_longer_retry_after(self) -> None:
        credential = self._seed_credential()
        self._clear_gate_spacing()
        self.adapter.results = [AdapterValidationResult(
            "rate_limited", "upstream_rate_limited", None, None, "4xx", "120", "uncertain", 429
        )]

        response = self.client_a.post(
            f"/api/credentials/{credential.credential_id}/validate",
            json={"expected_credential_version": credential.credential_version,
                  "expected_current_token_revision_id": credential.current_token_revision_id},
            headers=self._headers(self.csrf_a),
        )

        self.assertEqual(response.status_code, 429)
        body = self._body(response)
        self.assertEqual(body["error"], "upstream_rate_limited")
        self.assertGreaterEqual(body["retry_after_seconds"], 120)
        self.assertEqual(response.headers["Retry-After"], str(body["retry_after_seconds"]))

    def test_unclassified_upstream_error_does_not_become_app_401_or_clear_session(self) -> None:
        self.adapter.results = [AdapterValidationResult(
            "validation_unknown", "safe-unknown", None, None, "4xx", None, "complete", 401
        )]

        response = self.client_a.post(
            "/api/credentials", json={"label": "Unknown", "token": _token()},
            headers=self._headers(self.csrf_a),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(self._body(response), {"error": "upstream_validation_unknown"})
        session = self.client_a.get("/api/auth/session")
        self.assertEqual(session.status_code, 200)
        self.assertTrue(self._body(session)["authenticated"])

    def test_unknown_methods_remain_405(self) -> None:
        response = self.client_a.put(
            "/api/credentials", json={}, headers=self._headers(self.csrf_a)
        )
        self.assertEqual(response.status_code, 405)


if __name__ == "__main__":
    unittest.main()
