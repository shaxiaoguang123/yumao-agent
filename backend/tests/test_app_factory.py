from __future__ import annotations

import base64
import importlib
import importlib.util
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


# Importing the recovered legacy app at the red phase must not inspect the
# developer's project root. Give any legacy import a clean synthetic root.
_TEST_ROOT = tempfile.TemporaryDirectory(prefix="yumao-app-factory-")
os.environ["APP_ROOT_DIR"] = _TEST_ROOT.name
os.environ["PYTHON_DOTENV_DISABLED"] = "1"


def _settings_module():
    spec = importlib.util.find_spec("backend.settings")
    if spec is None:
        raise AssertionError("backend.settings must provide the V1 settings API")
    return importlib.import_module("backend.settings")


def _app_factory():
    module = importlib.import_module("backend.app")
    factory = getattr(module, "create_app", None)
    if not callable(factory):
        raise AssertionError("backend.app must expose create_app")
    return factory


def _valid_secret() -> str:
    return base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode("ascii")


class SettingsTests(unittest.TestCase):
    def test_explicit_environment_values_override_process_environment(self) -> None:
        load_settings = _settings_module().load_settings
        with patch.dict(os.environ, {"DATABASE_PATH": "/process-env.sqlite3"}):
            settings = load_settings({
                "DATABASE_PATH": "/injected.sqlite3",
                "CSRF_HMAC_SECRET": _valid_secret(),
                "LOGIN_USERNAME_ATTEMPT_LIMIT": "7",
                "LOGIN_IP_ATTEMPT_LIMIT": "41",
            })
        self.assertEqual(settings.database_path, Path("/injected.sqlite3"))
        self.assertEqual(settings.login_username_attempt_limit, 7)
        self.assertEqual(settings.login_ip_attempt_limit, 41)

    def test_csrf_secret_is_strictly_decoded_and_excluded_from_repr(self) -> None:
        secret_bytes = bytes(range(32))
        settings = _settings_module().load_settings({
            "CSRF_HMAC_SECRET": base64.urlsafe_b64encode(secret_bytes).rstrip(b"=").decode("ascii"),
        })
        self.assertEqual(settings.csrf_hmac_secret, secret_bytes)
        self.assertNotIn(settings.csrf_hmac_secret.hex(), repr(settings))

    def test_missing_or_malformed_csrf_secret_fails_fast(self) -> None:
        load_settings = _settings_module().load_settings
        invalid_values = [None, "", "not base64!", "YWJj=", "c2hvcnQ", "A" * 43, "changeme"]
        for value in invalid_values:
            with self.subTest(value=value):
                env = {} if value is None else {"CSRF_HMAC_SECRET": value}
                with self.assertRaises(ValueError):
                    load_settings(env)

    def test_production_requires_allowed_origins(self) -> None:
        load_settings = _settings_module().load_settings
        with self.assertRaises(ValueError):
            load_settings({"APP_ENV": "production", "CSRF_HMAC_SECRET": _valid_secret()})


class AppFactoryTests(unittest.TestCase):
    def test_create_app_uses_injected_database_path(self) -> None:
        factory = _app_factory()
        database_path = Path(_TEST_ROOT.name) / "identity-test.sqlite3"
        app = factory({
            "TESTING": True,
            "DATABASE_PATH": str(database_path),
            "CSRF_HMAC_SECRET": _valid_secret(),
        })
        self.assertEqual(app.config["DATABASE_PATH"], database_path)

    def test_health_endpoint_is_public_and_minimal(self) -> None:
        app = _app_factory()({
            "TESTING": True,
            "DATABASE_PATH": str(Path(_TEST_ROOT.name) / "health.sqlite3"),
            "CSRF_HMAC_SECRET": _valid_secret(),
        })
        response = app.test_client().get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_v1_app_does_not_register_legacy_mutation_routes(self) -> None:
        app = _app_factory()({
            "TESTING": True,
            "DATABASE_PATH": str(Path(_TEST_ROOT.name) / "routes.sqlite3"),
            "CSRF_HMAC_SECRET": _valid_secret(),
        })
        routes = {rule.rule for rule in app.url_map.iter_rules()}
        self.assertNotIn("/api/run", routes)
        self.assertNotIn("/api/save_plan", routes)


def tearDownModule() -> None:
    logging.shutdown()
    _TEST_ROOT.cleanup()
