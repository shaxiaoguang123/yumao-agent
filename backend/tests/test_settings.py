from __future__ import annotations

import base64
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.settings import AppSettings, load_settings


def _valid_secret() -> tuple[str, bytes]:
    raw = bytes(range(32))
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return encoded, raw


class AppSettingsTests(unittest.TestCase):
    def test_explicit_values_override_process_environment_without_dotenv_loading(self) -> None:
        encoded, _raw = _valid_secret()
        with patch.dict(os.environ, {"DATABASE_PATH": "/process-env.sqlite3"}):
            settings = load_settings({
                "DATABASE_PATH": "/injected.sqlite3",
                "CSRF_HMAC_SECRET": encoded,
                "LOGIN_USERNAME_ATTEMPT_LIMIT": "7",
                "LOGIN_USERNAME_WINDOW_SECONDS": "480",
                "LOGIN_IP_ATTEMPT_LIMIT": "41",
                "LOGIN_IP_WINDOW_SECONDS": "1200",
                "REGISTER_IP_ATTEMPT_LIMIT": "9",
                "REGISTER_IP_WINDOW_SECONDS": "1800",
            })

        self.assertEqual(settings.database_path, Path("/injected.sqlite3"))
        self.assertEqual(settings.login_username_attempt_limit, 7)
        self.assertEqual(settings.login_username_window_seconds, 480)
        self.assertEqual(settings.login_ip_attempt_limit, 41)
        self.assertEqual(settings.login_ip_window_seconds, 1200)
        self.assertEqual(settings.register_ip_attempt_limit, 9)
        self.assertEqual(settings.register_ip_window_seconds, 1800)

    def test_csrf_secret_decodes_to_bytes_and_is_excluded_from_repr(self) -> None:
        encoded, raw = _valid_secret()
        settings = load_settings({"CSRF_HMAC_SECRET": encoded})

        self.assertIsInstance(settings, AppSettings)
        self.assertEqual(settings.csrf_hmac_secret, raw)
        self.assertNotIn(raw.hex(), repr(settings))

    def test_missing_malformed_noncanonical_short_and_weak_secrets_fail_fast(self) -> None:
        readable_password = base64.urlsafe_b64encode(
            b"ordinaryhumanpasswordtextlongenoughtodecodeasasecret123456789"
        ).rstrip(b"=").decode("ascii")
        invalid_values = (
            None,
            "",
            "not base64!",
            "YWJj=",
            "c2hvcnQ",
            "A" * 43,
            "changeme",
            "default",
            readable_password,
        )
        for value in invalid_values:
            with self.subTest(value_type=type(value).__name__):
                env = {} if value is None else {"CSRF_HMAC_SECRET": value}
                with self.assertRaises(ValueError):
                    load_settings(env)

    def test_production_requires_explicit_allowed_origins(self) -> None:
        encoded, _raw = _valid_secret()
        with self.assertRaises(ValueError):
            load_settings({"APP_ENV": "production", "CSRF_HMAC_SECRET": encoded})

    def test_optional_pair_bucket_can_be_disabled_with_zero(self) -> None:
        encoded, _raw = _valid_secret()
        settings = load_settings({
            "CSRF_HMAC_SECRET": encoded,
            "LOGIN_PAIR_ATTEMPT_LIMIT": "0",
        })
        self.assertEqual(settings.login_pair_attempt_limit, 0)


if __name__ == "__main__":
    unittest.main()
