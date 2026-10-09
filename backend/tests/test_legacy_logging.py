from __future__ import annotations

import importlib
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


_LEGACY_ROOT = tempfile.TemporaryDirectory(prefix="yumao-legacy-log-test-")
_PREVIOUS_APP_ROOT = os.environ.get("APP_ROOT_DIR")
_PREVIOUS_DOTENV_DISABLED = os.environ.get("PYTHON_DOTENV_DISABLED")
os.environ["APP_ROOT_DIR"] = _LEGACY_ROOT.name
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
client_module = importlib.import_module("backend.client")
flow_module = importlib.import_module("backend.flow")
legacy_module = importlib.import_module("backend.legacy_app")
legacy_module.app.config["LEGACY_SINGLE_USER_RUNTIME_ENABLED"] = False
if _PREVIOUS_APP_ROOT is None:
    os.environ.pop("APP_ROOT_DIR", None)
else:
    os.environ["APP_ROOT_DIR"] = _PREVIOUS_APP_ROOT
if _PREVIOUS_DOTENV_DISABLED is None:
    os.environ.pop("PYTHON_DOTENV_DISABLED", None)
else:
    os.environ["PYTHON_DOTENV_DISABLED"] = _PREVIOUS_DOTENV_DISABLED


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self.content = json.dumps(payload).encode("utf-8")
        self.apparent_encoding = "utf-8"
        self.text = self.content.decode("utf-8")


class _FakeSession:
    def __init__(self, response):
        self.response = response

    def post(self, *args, **kwargs):
        return self.response


class LegacyLoggingTests(unittest.TestCase):
    def test_legacy_http_runtime_is_disabled_by_default(self) -> None:
        client = legacy_module.app.test_client()
        with patch.object(
            legacy_module,
            "run_plan",
            return_value=flow_module.FlowResult(False, "synthetic", {}),
        ) as run_plan:
            response = client.post("/api/run", json={"autoRun": True})

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.get_json(), {"error": "legacy_app_disabled"})
        run_plan.assert_not_called()

    def test_opted_in_legacy_runtime_rejects_non_loopback_clients(self) -> None:
        legacy_module.app.config["LEGACY_SINGLE_USER_RUNTIME_ENABLED"] = True
        client = legacy_module.app.test_client()
        try:
            with patch.object(
                legacy_module,
                "run_plan",
                return_value=flow_module.FlowResult(False, "synthetic", {}),
            ) as run_plan:
                response = client.post(
                    "/api/run",
                    json={"autoRun": True},
                    environ_overrides={"REMOTE_ADDR": "198.51.100.10"},
                )
        finally:
            legacy_module.app.config["LEGACY_SINGLE_USER_RUNTIME_ENABLED"] = False

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"error": "legacy_app_loopback_only"})
        run_plan.assert_not_called()

    def test_opted_in_legacy_runtime_rejects_cross_origin_execution(self) -> None:
        legacy_module.app.config["LEGACY_SINGLE_USER_RUNTIME_ENABLED"] = True
        client = legacy_module.app.test_client()
        try:
            with patch.object(
                legacy_module,
                "run_plan",
                return_value=flow_module.FlowResult(True, "synthetic", {}),
            ) as run_plan:
                response = client.post(
                    "/api/run",
                    json={"autoRun": True},
                    base_url="http://localhost:5175",
                    headers={"Origin": "https://attacker.invalid"},
                )
        finally:
            legacy_module.app.config["LEGACY_SINGLE_USER_RUNTIME_ENABLED"] = False

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"error": "legacy_origin_not_allowed"})
        run_plan.assert_not_called()

    def test_opted_in_legacy_runtime_allows_same_origin_without_wildcard_cors(self) -> None:
        legacy_module.app.config["LEGACY_SINGLE_USER_RUNTIME_ENABLED"] = True
        client = legacy_module.app.test_client()
        try:
            with patch.object(
                legacy_module,
                "run_plan",
                return_value=flow_module.FlowResult(True, "synthetic", {}),
            ) as run_plan:
                response = client.post(
                    "/api/run",
                    json={"autoRun": True},
                    base_url="http://localhost:5175",
                    headers={"Origin": "http://localhost:5175"},
                )
        finally:
            legacy_module.app.config["LEGACY_SINGLE_USER_RUNTIME_ENABLED"] = False

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
        run_plan.assert_called_once()

    def test_legacy_log_endpoints_never_expose_or_clear_historical_logs(self) -> None:
        legacy_module.app.config["LEGACY_SINGLE_USER_RUNTIME_ENABLED"] = True
        client = legacy_module.app.test_client()
        log_path = legacy_module.LOG_DIR / "run_flow.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        historical_log = b"synthetic-historical-token-value\n"
        log_path.write_bytes(historical_log)
        headers = {"Origin": "http://localhost:5175"}

        try:
            with patch.object(legacy_module.API_LOG, "info"):
                listed = client.get(
                    "/api/logs?source=run_flow",
                    base_url="http://localhost:5175",
                    headers=headers,
                )
                cleared = client.delete(
                    "/api/logs?source=run_flow",
                    base_url="http://localhost:5175",
                    headers=headers,
                )
        finally:
            legacy_module.app.config["LEGACY_SINGLE_USER_RUNTIME_ENABLED"] = False

        self.assertEqual(listed.status_code, 410)
        self.assertEqual(cleared.status_code, 410)
        self.assertNotIn("synthetic-historical-token-value", listed.get_data(as_text=True))
        self.assertEqual(log_path.read_bytes(), historical_log)

    def test_http_success_logs_omit_request_payload_and_upstream_response(self) -> None:
        token = "synthetic-token-that-must-not-be-logged"
        identity = "synthetic-idserial-that-must-not-be-logged"
        response = _FakeResponse(200, {"success": True, "resultData": {"idserial": identity}})

        with patch.object(client_module.requests, "Session", return_value=_FakeSession(response)):
            with patch.object(client_module.HTTP_LOG, "info") as log_info:
                result = client_module.ApiClient("https://example.invalid").post_json(
                    "/getUserInfo",
                    {"token": token},
                    {"reservationPerson": identity},
                )

        self.assertTrue(result["success"])
        rendered_logs = repr(log_info.call_args_list)
        self.assertNotIn(token, rendered_logs)
        self.assertNotIn(identity, rendered_logs)

    def test_http_logs_omit_query_parameters_from_endpoint_path(self) -> None:
        query_secret = "synthetic-query-token"
        response = _FakeResponse(200, {"success": True})

        with patch.object(client_module.requests, "Session", return_value=_FakeSession(response)):
            with patch.object(client_module.HTTP_LOG, "info") as log_info:
                client_module.ApiClient("https://example.invalid").post_json(
                    f"/getUserInfo?token={query_secret}", {}, {}
                )

        self.assertNotIn(query_secret, repr(log_info.call_args_list))

    def test_http_error_logs_and_safe_error_omit_upstream_body(self) -> None:
        sensitive_value = "synthetic-private-upstream-detail"
        response = _FakeResponse(500, {"message": sensitive_value})

        with patch.object(client_module.requests, "Session", return_value=_FakeSession(response)):
            with patch.object(client_module.HTTP_LOG, "info"), patch.object(
                client_module.HTTP_LOG, "error"
            ) as log_error:
                with self.assertRaises(RuntimeError) as raised:
                    client_module.ApiClient("https://example.invalid").post_json(
                        "/getUserInfo", {"token": "synthetic-token"}, {}
                    )

        self.assertNotIn(sensitive_value, repr(log_error.call_args_list))
        self.assertNotIn(sensitive_value, str(raised.exception))

    def test_flow_step_log_omits_coordinates_and_free_text_response(self) -> None:
        sensitive_value = "synthetic-order-number"
        coordinates = ["court-4-time-7"]

        with patch.object(flow_module.LOGGER, "info") as log_info:
            flow_module._log_step(
                "twoHourQueue",
                coordinates,
                "createBookingBytime",
                {"success": True, "message": sensitive_value},
            )

        rendered_logs = repr(log_info.call_args_list)
        self.assertNotIn(sensitive_value, rendered_logs)
        self.assertNotIn(coordinates[0], rendered_logs)

    def test_legacy_request_and_frontend_logs_omit_query_and_body(self) -> None:
        query_secret = "synthetic-query-secret"
        body_secret = "synthetic-body-secret"
        client = legacy_module.app.test_client()
        legacy_module.app.config["LEGACY_SINGLE_USER_RUNTIME_ENABLED"] = True

        try:
            with patch.object(legacy_module.API_LOG, "info") as api_log:
                response = client.post(
                    f"/api/save_plan?token={query_secret}",
                    json={"token": body_secret},
                    base_url="http://localhost:5175",
                    headers={"Origin": "http://localhost:5175"},
                )

            self.assertIn(response.status_code, (400, 500))
            logged_request = repr(api_log.call_args_list)
            self.assertNotIn(query_secret, logged_request)
            self.assertNotIn(body_secret, logged_request)

            detail_secret = "synthetic-frontend-detail-secret"
            with patch.object(legacy_module.FE_LOG, "info") as frontend_log:
                client.post(
                    "/api/frontend-log",
                    json={"level": "info", "action": "save-plan", "detail": detail_secret},
                    base_url="http://localhost:5175",
                    headers={"Origin": "http://localhost:5175"},
                )

            self.assertNotIn(detail_secret, repr(frontend_log.call_args_list))
        finally:
            legacy_module.app.config["LEGACY_SINGLE_USER_RUNTIME_ENABLED"] = False


def tearDownModule() -> None:
    for name in ("http_client", "run_flow", "api_server", "frontend"):
        logger = logging.getLogger(name)
        for handler in tuple(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
    _LEGACY_ROOT.cleanup()


if __name__ == "__main__":
    unittest.main()
