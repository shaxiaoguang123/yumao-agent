from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


_KEY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,31}\Z", re.ASCII)
_BASE64URL_RE = re.compile(r"\A[A-Za-z0-9_-]+\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class CredentialKeyring:
    keys: Mapping[str, bytes] = field(repr=False)
    active_key_id: str = field(repr=False)

    def key(self, key_id: str) -> bytes:
        try:
            return self.keys[key_id]
        except KeyError as exc:
            raise ValueError("credential key version is unavailable") from exc


def _reject_duplicate_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("credential keyring contains duplicate key IDs")
        result[key] = value
    return result


def _reject_json_constant(_value: str):
    raise ValueError("credential keyring must contain valid JSON")


def _decode_key(encoded: object) -> bytes:
    if not isinstance(encoded, str) or not _BASE64URL_RE.fullmatch(encoded):
        raise ValueError("credential key must be canonical unpadded base64url")
    try:
        padding = "=" * ((4 - len(encoded) % 4) % 4)
        decoded = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("credential key must be canonical unpadded base64url") from exc
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != encoded or len(decoded) != 32:
        raise ValueError("credential key must decode canonically to exactly 32 bytes")
    return decoded


def parse_credential_keyring(raw: object, active_key_id: object) -> CredentialKeyring:
    if not isinstance(raw, str) or not raw:
        raise ValueError("credential keyring is required")
    try:
        parsed = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_object_pairs,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("credential keyring must be a JSON object") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise ValueError("credential keyring must be a non-empty JSON object")

    keys: dict[str, bytes] = {}
    for key_id, encoded in parsed.items():
        if not isinstance(key_id, str) or not _KEY_ID_RE.fullmatch(key_id):
            raise ValueError("credential key ID is invalid")
        keys[key_id] = _decode_key(encoded)

    if not isinstance(active_key_id, str) or not _KEY_ID_RE.fullmatch(active_key_id):
        raise ValueError("credential active key ID is invalid")
    if active_key_id not in keys:
        raise ValueError("credential active key ID is not present in its keyring")

    return CredentialKeyring(MappingProxyType(keys), active_key_id)
