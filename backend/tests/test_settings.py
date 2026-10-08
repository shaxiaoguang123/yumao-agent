from __future__ import annotations

import base64
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.settings import AppSettings, load_settings
from support import credential_test_settings


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _settings_input() -> dict[str, str]:
    return credential_test_settings(Path("/tmp/credential-settings-test.sqlite3"))


class AppSettingsTests(unittest.TestCase):
    def test_explicit_values_override_process_environment_without_dotenv_loading(self) -> None:
        env = _settings_input()
        env.update({
            "DATABASE_PATH": "/injected.sqlite3",
            "LOGIN_USERNAME_ATTEMPT_LIMIT": "7",
            "LOGIN_USERNAME_WINDOW_SECONDS": "480",
            "LOGIN_IP_ATTEMPT_LIMIT": "41",
            "LOGIN_IP_WINDOW_SECONDS": "1200",
            "REGISTER_IP_ATTEMPT_LIMIT": "9",
            "REGISTER_IP_WINDOW_SECONDS": "1800",
        })
        with patch.dict(os.environ, {"DATABASE_PATH": "/process-env.sqlite3"}):
            settings = load_settings(env)

        self.assertEqual(settings.database_path, Path("/injected.sqlite3"))
        self.assertEqual(settings.login_username_attempt_limit, 7)
        self.assertEqual(settings.login_username_window_seconds, 480)
        self.assertEqual(settings.login_ip_attempt_limit, 41)
        self.assertEqual(settings.login_ip_window_seconds, 1200)
        self.assertEqual(settings.register_ip_attempt_limit, 9)
        self.assertEqual(settings.register_ip_window_seconds, 1800)

    def test_csrf_secret_decodes_to_bytes_and_is_excluded_from_repr(self) -> None:
        env = _settings_input()
        raw = bytes(range(32))
        settings = load_settings(env)

        self.assertIsInstance(settings, AppSettings)
        self.assertEqual(settings.csrf_hmac_secret, raw)
        self.assertNotIn(raw.hex(), repr(settings), "CSRF material entered AppSettings repr")

    def test_both_keyrings_decode_to_bytes_without_exposing_material_in_repr(self) -> None:
        env = _settings_input()
        encryption = bytes(range(32, 64))
        fingerprint = bytes(range(64, 96))
        settings = load_settings(env)

        self.assertEqual(settings.credential_encryption_keys, {"enc-v1": encryption})
        self.assertEqual(settings.credential_encryption_active_key_id, "enc-v1")
        self.assertEqual(settings.upstream_fingerprint_keys, {"fp-v1": fingerprint})
        self.assertEqual(settings.upstream_fingerprint_active_key_id, "fp-v1")
        rendered = repr(settings)
        self.assertNotIn(_encoded(encryption), rendered, "encryption key entered AppSettings repr")
        self.assertNotIn(_encoded(fingerprint), rendered, "fingerprint key entered AppSettings repr")
        self.assertNotIn(encryption.hex(), rendered, "encryption key entered AppSettings repr")
        self.assertNotIn(fingerprint.hex(), rendered, "fingerprint key entered AppSettings repr")

    def test_keyrings_reject_missing_empty_malformed_noncanonical_and_wrong_length_values(self) -> None:
        base = _settings_input()
        invalid_rings = (
            None,
            "{}",
            '{"enc-v1":"not base64!"}',
            json.dumps({"enc-v1": _encoded(b"short")}),
            json.dumps({"enc-v1": _encoded(bytes(range(32))) + "="}),
        )
        for ring in invalid_rings:
            with self.subTest(ring_kind="missing" if ring is None else "invalid"):
                env = dict(base)
                if ring is None:
                    env.pop("APP_CREDENTIAL_ENCRYPTION_KEYS")
                else:
                    env["APP_CREDENTIAL_ENCRYPTION_KEYS"] = ring
                with self.assertRaises(ValueError):
                    load_settings(env)

        env = dict(base)
        env.pop("APP_UPSTREAM_FINGERPRINT_KEYS")
        with self.assertRaises(ValueError):
            load_settings(env)

    def test_keyrings_reject_duplicate_ids_missing_active_id_and_invalid_key_ids(self) -> None:
        base = _settings_input()
        valid_value = _encoded(bytes(range(32, 64)))
        invalid = (
            ('{"enc-v1":"' + valid_value + '","enc-v1":"' + valid_value + '"}', "enc-v1"),
            (json.dumps({"enc-v1": valid_value}), "absent-v1"),
            (json.dumps({"bad key id": valid_value}), "bad key id"),
        )
        for ring, active_id in invalid:
            with self.subTest(active_id=active_id):
                env = dict(base)
                env["APP_CREDENTIAL_ENCRYPTION_KEYS"] = ring
                env["APP_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID"] = active_id
                with self.assertRaises(ValueError):
                    load_settings(env)

        env = dict(base)
        env.pop("APP_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID")
        with self.assertRaises(ValueError):
            load_settings(env)

    def test_key_material_cannot_be_reused_across_secret_domains(self) -> None:
        base = _settings_input()
        env = dict(base)
        env["APP_UPSTREAM_FINGERPRINT_KEYS"] = env["APP_CREDENTIAL_ENCRYPTION_KEYS"]
        env["APP_UPSTREAM_FINGERPRINT_ACTIVE_KEY_ID"] = "enc-v1"
        with self.assertRaises(ValueError):
            load_settings(env)

        env = dict(base)
        env["APP_CREDENTIAL_ENCRYPTION_KEYS"] = json.dumps(
            {"enc-v1": env["CSRF_HMAC_SECRET"]}
        )
        with self.assertRaises(ValueError):
            load_settings(env)

        env = dict(base)
        env["APP_UPSTREAM_FINGERPRINT_KEYS"] = json.dumps(
            {"fp-v1": env["CSRF_HMAC_SECRET"]}
        )
        with self.assertRaises(ValueError):
            load_settings(env)

    def test_printable_32_byte_key_material_is_not_rejected_by_entropy_heuristics(self) -> None:
        env = _settings_input()
        printable = _encoded(b"A" * 32)
        env["APP_CREDENTIAL_ENCRYPTION_KEYS"] = json.dumps({"enc-v1": printable})

        settings = load_settings(env)

        self.assertEqual(settings.credential_encryption_keys["enc-v1"], b"A" * 32)

    def test_timeout_limits_and_backoff_settings_are_validated(self) -> None:
        invalid = (
            {"UPSTREAM_CONNECT_TIMEOUT_SECONDS": "10", "UPSTREAM_TOTAL_DEADLINE_SECONDS": "10"},
            {"UPSTREAM_READ_TIMEOUT_SECONDS": "11", "UPSTREAM_TOTAL_DEADLINE_SECONDS": "10"},
            {"UPSTREAM_MAX_RESPONSE_BYTES": "0"},
            {"UPSTREAM_RETRY_AFTER_FALLBACK_SECONDS": "31", "MAX_UPSTREAM_BACKOFF_SECONDS": "30"},
            {"UPSTREAM_LEASE_SAFETY_MARGIN_SECONDS": "0"},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                env = {**_settings_input(), **overrides}
                with self.assertRaises(ValueError):
                    load_settings(env)

    def test_upstream_transport_and_backoff_settings_are_required(self) -> None:
        required = (
            "UPSTREAM_ORIGIN",
            "UPSTREAM_CONNECT_TIMEOUT_SECONDS",
            "UPSTREAM_READ_TIMEOUT_SECONDS",
            "UPSTREAM_TOTAL_DEADLINE_SECONDS",
            "UPSTREAM_MAX_RESPONSE_BYTES",
            "UPSTREAM_RETRY_AFTER_FALLBACK_SECONDS",
            "MAX_UPSTREAM_BACKOFF_SECONDS",
            "UPSTREAM_LEASE_SAFETY_MARGIN_SECONDS",
        )
        for name in required:
            with self.subTest(setting=name):
                env = _settings_input()
                env.pop(name)
                with self.assertRaises(ValueError):
                    load_settings(env)

    def test_missing_userinfo_interval_disables_validation_and_invalid_value_fails(self) -> None:
        env = _settings_input()
        settings = load_settings(env)
        self.assertIsNone(settings.upstream_get_user_info_min_interval_ms)

        env["UPSTREAM_GET_USER_INFO_MIN_INTERVAL_MS"] = "0"
        with self.assertRaises(ValueError):
            load_settings(env)

    def test_token_expiring_soon_window_defaults_to_seven_days_and_requires_positive_value(self) -> None:
        env = _settings_input()
        env.pop("TOKEN_EXPIRING_SOON_WINDOW_SECONDS")
        settings = load_settings(env)
        self.assertEqual(settings.token_expiring_soon_window_seconds, 604800)

        env["TOKEN_EXPIRING_SOON_WINDOW_SECONDS"] = "86400"
        self.assertEqual(load_settings(env).token_expiring_soon_window_seconds, 86400)

        env["TOKEN_EXPIRING_SOON_WINDOW_SECONDS"] = "0"
        with self.assertRaises(ValueError):
            load_settings(env)

    def test_upstream_origin_must_be_an_https_origin_without_path_or_userinfo(self) -> None:
        for origin in (
            "http://bdtyg.cugb.edu.cn",
            "https://bdtyg.cugb.edu.cn/path",
            "https://user@bdtyg.cugb.edu.cn",
        ):
            with self.subTest(origin=origin):
                env = {**_settings_input(), "UPSTREAM_ORIGIN": origin}
                with self.assertRaises(ValueError):
                    load_settings(env)

    def test_missing_malformed_noncanonical_short_and_weak_csrf_secrets_fail_fast(self) -> None:
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
                env = _settings_input()
                if value is None:
                    env.pop("CSRF_HMAC_SECRET")
                else:
                    env["CSRF_HMAC_SECRET"] = value
                with self.assertRaises(ValueError):
                    load_settings(env)

    def test_production_requires_explicit_allowed_origins(self) -> None:
        env = {**_settings_input(), "APP_ENV": "production", "APP_ALLOWED_ORIGINS": ""}
        with self.assertRaises(ValueError):
            load_settings(env)

    def test_optional_pair_bucket_can_be_disabled_with_zero(self) -> None:
        env = {**_settings_input(), "LOGIN_PAIR_ATTEMPT_LIMIT": "0"}
        settings = load_settings(env)
        self.assertEqual(settings.login_pair_attempt_limit, 0)

    def test_missing_upstream_transport_settings_fail_fast(self) -> None:
        required = (
            "UPSTREAM_ORIGIN",
            "UPSTREAM_CONNECT_TIMEOUT_SECONDS",
            "UPSTREAM_READ_TIMEOUT_SECONDS",
            "UPSTREAM_TOTAL_DEADLINE_SECONDS",
            "UPSTREAM_MAX_RESPONSE_BYTES",
            "UPSTREAM_RETRY_AFTER_FALLBACK_SECONDS",
            "MAX_UPSTREAM_BACKOFF_SECONDS",
            "UPSTREAM_LEASE_SAFETY_MARGIN_SECONDS",
        )
        for name in required:
            with self.subTest(setting=name):
                env = _settings_input()
                env.pop(name)
                with self.assertRaises(ValueError):
                    load_settings(env)


if __name__ == "__main__":
    unittest.main()
