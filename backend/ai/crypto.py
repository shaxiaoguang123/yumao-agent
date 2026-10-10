from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import HKDF
from Crypto.Hash import SHA256

from backend.credentials.keyring import CredentialKeyring


@dataclass(frozen=True, slots=True)
class EncryptedProviderKey:
    ciphertext: bytes = field(repr=False)
    nonce: bytes = field(repr=False)
    tag: bytes = field(repr=False)
    key_id: str = field(repr=False)


def _aad(user_id: str, model_id: str, revision: str, key_id: str) -> bytes:
    parts = (user_id, model_id, revision, key_id)
    if any(not isinstance(v, str) or not v or len(v.encode("utf-8")) > 65535 for v in parts):
        raise ValueError("invalid provider key context")
    return b"ai-provider-secret-v1\0" + b"".join(
        len(v.encode("utf-8")).to_bytes(4, "big") + v.encode("utf-8") for v in parts
    )


class ProviderKeyCipher:
    """AES-GCM with an HKDF-derived purpose-specific subkey and tenant/model binding."""

    def __init__(self, keyring: CredentialKeyring):
        self.keyring = keyring

    def _key(self, key_id: str, user_id: str, model_id: str) -> bytes:
        material = self.keyring.key(key_id)
        salt = (user_id + "\0" + model_id).encode("utf-8")
        return HKDF(material, 32, salt, SHA256, context=b"ai-provider-secret-v1")

    def encrypt(self, plaintext: bytes, *, user_id: str, model_id: str, revision: str, key_id: str) -> EncryptedProviderKey:
        if not isinstance(plaintext, bytes) or not plaintext:
            raise ValueError("provider key must be non-empty bytes")
        nonce = secrets.token_bytes(12)
        cipher = AES.new(self._key(key_id, user_id, model_id), AES.MODE_GCM, nonce=nonce, mac_len=16)
        cipher.update(_aad(user_id, model_id, revision, key_id))
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)
        return EncryptedProviderKey(ciphertext, nonce, tag, key_id)

    def decrypt(self, envelope: EncryptedProviderKey, *, user_id: str, model_id: str, revision: str) -> bytes:
        if len(envelope.nonce) != 12 or len(envelope.tag) != 16:
            raise ValueError("provider key authentication failed")
        cipher = AES.new(self._key(envelope.key_id, user_id, model_id), AES.MODE_GCM, nonce=envelope.nonce, mac_len=16)
        cipher.update(_aad(user_id, model_id, revision, envelope.key_id))
        try:
            return cipher.decrypt_and_verify(envelope.ciphertext, envelope.tag)
        except (ValueError, TypeError) as exc:
            raise ValueError("provider key authentication failed") from exc
