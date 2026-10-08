from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal

from backend.credentials.keyring import CredentialKeyring


_BASE64URL_SEGMENT_RE = re.compile(r"\A[A-Za-z0-9_-]+\Z", re.ASCII)
_MAX_TOKEN_BYTES = 16 * 1024
_MAX_NUMERIC_DATE_MS = 253_402_300_799_999


@dataclass(frozen=True, slots=True)
class TokenExpiry:
    expires_at_utc_ms: int | None
    expiry_state: Literal["expiry_unknown", "expiry_ok", "expiring_soon", "expired"]


@dataclass(frozen=True, slots=True)
class VersionedFingerprint:
    value: str = field(repr=False)
    key_version: str


def _reject_constant(_value: str):
    raise ValueError("non-finite JSON number")


def _decode_segment(segment: str) -> bytes:
    if not segment or not _BASE64URL_SEGMENT_RE.fullmatch(segment):
        raise ValueError("invalid JWT base64url segment")
    padding = "=" * ((4 - len(segment) % 4) % 4)
    decoded = base64.b64decode(segment + padding, altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != segment:
        raise ValueError("non-canonical JWT base64url segment")
    return decoded


def _expiry_unknown() -> TokenExpiry:
    return TokenExpiry(None, "expiry_unknown")


def parse_token_exp(
    token: str,
    now_utc_ms: int,
    expiring_soon_window_seconds: int = 604_800,
) -> TokenExpiry:
    """Extract only a bounded JWT NumericDate; this does not validate a signature."""
    if isinstance(now_utc_ms, bool) or not isinstance(now_utc_ms, int) or now_utc_ms < 0:
        raise ValueError("now_utc_ms must be a non-negative integer")
    if (
        isinstance(expiring_soon_window_seconds, bool)
        or not isinstance(expiring_soon_window_seconds, int)
        or expiring_soon_window_seconds <= 0
    ):
        raise ValueError("expiring_soon_window_seconds must be a positive integer")
    if not isinstance(token, str) or not token or token != token.strip():
        return _expiry_unknown()
    try:
        encoded_token = token.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return _expiry_unknown()
    if len(encoded_token) > _MAX_TOKEN_BYTES or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in token):
        return _expiry_unknown()

    parts = token.split(".")
    if len(parts) != 3:
        return _expiry_unknown()
    try:
        header_bytes = _decode_segment(parts[0])
        payload_bytes = _decode_segment(parts[1])
        if parts[2] and not _BASE64URL_SEGMENT_RE.fullmatch(parts[2]):
            return _expiry_unknown()
        header = json.loads(header_bytes.decode("utf-8", errors="strict"))
        payload = json.loads(
            payload_bytes.decode("utf-8", errors="strict"),
            parse_int=Decimal,
            parse_float=Decimal,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, InvalidOperation, ValueError, binascii.Error):
        return _expiry_unknown()

    if not isinstance(header, dict) or not isinstance(payload, dict) or "exp" not in payload:
        return _expiry_unknown()
    raw_exp = payload["exp"]
    if isinstance(raw_exp, bool) or not isinstance(raw_exp, Decimal) or not raw_exp.is_finite():
        return _expiry_unknown()
    if raw_exp < 0 or raw_exp > Decimal("253402300799.999"):
        return _expiry_unknown()
    try:
        milliseconds = raw_exp * Decimal(1000)
        integral_ms = milliseconds.to_integral_value()
        if milliseconds != integral_ms:
            return _expiry_unknown()
        expires_at_utc_ms = int(integral_ms)
    except (InvalidOperation, OverflowError, ValueError):
        return _expiry_unknown()
    if not 0 <= expires_at_utc_ms <= _MAX_NUMERIC_DATE_MS:
        return _expiry_unknown()

    if expires_at_utc_ms <= now_utc_ms:
        state: Literal["expiry_unknown", "expiry_ok", "expiring_soon", "expired"] = "expired"
    elif expires_at_utc_ms <= now_utc_ms + expiring_soon_window_seconds * 1000:
        state = "expiring_soon"
    else:
        state = "expiry_ok"
    return TokenExpiry(expires_at_utc_ms, state)


def _fingerprint(
    domain: bytes,
    value: bytes,
    keyring: CredentialKeyring,
    key_version: str | None = None,
) -> VersionedFingerprint:
    if not isinstance(value, bytes) or not value:
        raise ValueError("fingerprint input must be non-empty bytes")
    selected_key_version = keyring.active_key_id if key_version is None else key_version
    key = keyring.key(selected_key_version)
    message = domain + b"\0" + len(value).to_bytes(8, "big") + value
    digest = hmac.new(key, message, hashlib.sha256).hexdigest()
    return VersionedFingerprint(digest, selected_key_version)


def token_fingerprint(
    token: str,
    keyring: CredentialKeyring,
    key_version: str | None = None,
) -> VersionedFingerprint:
    if not isinstance(token, str) or not token:
        raise ValueError("Token fingerprint input must be a non-empty string")
    try:
        encoded = token.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("Token fingerprint input is not valid UTF-8") from exc
    if len(encoded) > _MAX_TOKEN_BYTES:
        raise ValueError("Token fingerprint input is too large")
    return _fingerprint(b"credential-token-v1", encoded, keyring, key_version)


def account_fingerprint(
    identity_bytes: bytes,
    keyring: CredentialKeyring,
    key_version: str | None = None,
) -> VersionedFingerprint:
    if not isinstance(identity_bytes, bytes) or not identity_bytes:
        raise ValueError("account identity must be non-empty UTF-8 bytes")
    try:
        identity_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("account identity must be UTF-8") from exc
    return _fingerprint(b"upstream-account-v1", identity_bytes, keyring, key_version)
