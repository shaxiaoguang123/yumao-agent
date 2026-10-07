from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets


_N = 32768
_R = 8
_P = 1
_DKLEN = 64
_MAXMEM = 64 * 1024 * 1024
_SALT_BYTES = 16
_PREFIX = "scrypt$v1$n=32768$r=8$p=1$dklen=64$maxmem=67108864"


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    if not value or any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for char in value
    ):
        raise ValueError("invalid base64url")
    padding = "=" * ((4 - len(value) % 4) % 4)
    decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    if _b64url_encode(decoded) != value:
        raise ValueError("non-canonical base64url")
    return decoded


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError("password length must be between 12 and 1024 Unicode code points")


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_N,
        r=_R,
        p=_P,
        dklen=_DKLEN,
        maxmem=_MAXMEM,
    )


def hash_password(password: str) -> str:
    _validate_password(password)
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = _derive(password, salt)
    return _PREFIX + "$" + _b64url_encode(salt) + "$" + _b64url_encode(derived)


def verify_password(password: str, stored_hash: str) -> bool:
    if not isinstance(password, str) or not isinstance(stored_hash, str):
        return False
    try:
        _validate_password(password)
        parts = stored_hash.split("$")
        if len(parts) != 9 or "$".join(parts[:7]) != _PREFIX:
            return False
        salt = _b64url_decode(parts[7])
        expected = _b64url_decode(parts[8])
        if len(salt) != _SALT_BYTES or len(expected) != _DKLEN:
            return False
        actual = _derive(password, salt)
        return hmac.compare_digest(actual, expected)
    except (binascii.Error, ValueError, TypeError, OverflowError):
        return False
