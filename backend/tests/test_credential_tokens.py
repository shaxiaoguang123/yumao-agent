from __future__ import annotations

import base64
import hashlib
import hmac
import json
import unittest

from backend.credentials.keyring import parse_credential_keyring
from backend.credentials.tokens import (
    account_fingerprint,
    parse_token_exp,
    token_fingerprint,
)


def _jwt(payload: object) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode("ascii")
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), allow_nan=True).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    return f"{header}.{encoded_payload}.synthetic-signature"


def _keyring() -> tuple[object, bytes]:
    key = bytes(range(32))
    rotated_key = bytes(range(32, 64))
    encoded = base64.urlsafe_b64encode(key).rstrip(b"=").decode("ascii")
    encoded_rotated = base64.urlsafe_b64encode(rotated_key).rstrip(b"=").decode("ascii")
    ring = parse_credential_keyring(
        json.dumps({"fp-v1": encoded, "fp-v2": encoded_rotated}), "fp-v2"
    )
    return ring, key


class TokenExpiryTests(unittest.TestCase):
    def test_parses_exp_without_retaining_payload(self) -> None:
        result = parse_token_exp(_jwt({"exp": 1_800_000_000, "private": "must-not-return"}), 1_700_000_000_000)

        self.assertEqual(result.expires_at_utc_ms, 1_800_000_000_000)
        self.assertEqual(result.expiry_state, "expiry_ok")
        self.assertNotIn("private", repr(result))

    def test_missing_or_malformed_token_has_unknown_expiry(self) -> None:
        for token in ("", "not-a-jwt", "a.b", "a.***.c", "a.e30.c"):
            with self.subTest(token_shape=len(token)):
                result = parse_token_exp(token, 1_700_000_000_000)
                self.assertEqual(result.expires_at_utc_ms, None)
                self.assertEqual(result.expiry_state, "expiry_unknown")

    def test_boolean_nan_infinity_and_non_json_numeric_values_are_unknown(self) -> None:
        malformed_payloads = (
            '{"exp":true}',
            '{"exp":NaN}',
            '{"exp":Infinity}',
            '{"exp":-Infinity}',
        )
        for payload in malformed_payloads:
            token = "e30." + base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode() + ".sig"
            with self.subTest(payload=payload):
                self.assertEqual(
                    parse_token_exp(token, 1_700_000_000_000).expiry_state,
                    "expiry_unknown",
                )

    def test_out_of_range_and_submillisecond_values_are_unknown(self) -> None:
        values = ("-0.001", "253402300800", "1.0001")
        for value in values:
            payload = '{"exp":' + value + '}'
            token = "e30." + base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode() + ".sig"
            with self.subTest(exp=value):
                self.assertEqual(
                    parse_token_exp(token, 0).expiry_state,
                    "expiry_unknown",
                )

    def test_expiry_at_now_is_expired(self) -> None:
        result = parse_token_exp(_jwt({"exp": 1_700_000_000}), 1_700_000_000_000)

        self.assertEqual(result.expires_at_utc_ms, 1_700_000_000_000)
        self.assertEqual(result.expiry_state, "expired")

    def test_expiring_soon_window_includes_the_exact_seven_day_boundary(self) -> None:
        now_utc_ms = 1_700_000_000_000
        boundary = now_utc_ms + 604_800_000
        result = parse_token_exp(_jwt({"exp": boundary // 1000}), now_utc_ms)

        self.assertEqual(result.expiry_state, "expiring_soon")

    def test_expiring_soon_window_is_configurable(self) -> None:
        now_utc_ms = 1_700_000_000_000
        result = parse_token_exp(
            _jwt({"exp": (now_utc_ms + 3_600_000) // 1000}),
            now_utc_ms,
            expiring_soon_window_seconds=3600,
        )

        self.assertEqual(result.expiry_state, "expiring_soon")


class FingerprintTests(unittest.TestCase):
    def test_fingerprint_is_key_versioned_and_deterministic(self) -> None:
        ring, _key = _keyring()

        first = token_fingerprint("header.payload.signature", ring)
        second = token_fingerprint("header.payload.signature", ring)
        historical = token_fingerprint(
            "header.payload.signature", ring, key_version="fp-v1"
        )

        self.assertEqual(first, second)
        self.assertEqual(first.key_version, "fp-v2")
        self.assertEqual(historical.key_version, "fp-v1")
        self.assertNotEqual(first.value, historical.value)
        self.assertRegex(first.value, r"\A[0-9a-f]{64}\Z")
        self.assertNotIn("header.payload.signature", repr(first))

    def test_account_and_token_fingerprints_use_separate_domains(self) -> None:
        ring, key = _keyring()
        identical_bytes = b"same-input-domain-check"

        account = account_fingerprint(identical_bytes, ring, key_version="fp-v1")
        token = token_fingerprint(identical_bytes.decode(), ring, key_version="fp-v1")
        expected_account = hmac.new(
            key,
            b"upstream-account-v1\0"
            + len(identical_bytes).to_bytes(8, "big")
            + identical_bytes,
            hashlib.sha256,
        ).hexdigest()
        expected_token = hmac.new(
            key,
            b"credential-token-v1\0"
            + len(identical_bytes).to_bytes(8, "big")
            + identical_bytes,
            hashlib.sha256,
        ).hexdigest()

        self.assertEqual(account.value, expected_account)
        self.assertEqual(token.value, expected_token)
        self.assertNotEqual(account.value, token.value)

    def test_account_identity_is_exact_and_empty_or_wrong_type_is_rejected(self) -> None:
        ring, _key = _keyring()
        self.assertNotEqual(
            account_fingerprint("idserial".encode(), ring).value,
            account_fingerprint(" IDSerial ".encode(), ring).value,
        )
        for identity in (b"", "not-bytes", None):
            with self.subTest(identity_type=type(identity).__name__):
                with self.assertRaises(ValueError):
                    account_fingerprint(identity, ring)


if __name__ == "__main__":
    unittest.main()
