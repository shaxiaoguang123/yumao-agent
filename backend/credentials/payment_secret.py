from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from Crypto.Cipher import AES

from backend.credentials.keyring import CredentialKeyring


class PaymentSecretError(RuntimeError):
    """Safe error for the separately encrypted payment password envelope."""


@dataclass(frozen=True, slots=True)
class EncryptedPaymentSecret:
    ciphertext: bytes = field(repr=False)
    nonce: bytes = field(repr=False)
    tag: bytes = field(repr=False)
    key_id: str = field(repr=False)


def _part(value: str) -> bytes:
    encoded = value.encode("utf-8", errors="strict")
    if not encoded or len(encoded) > 65535:
        raise ValueError("payment secret context is invalid")
    return len(encoded).to_bytes(4, "big") + encoded


def _aad(*, user_id: str, credential_id: str, revision: int, key_id: str) -> bytes:
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("payment secret revision is invalid")
    return (b"credential-payment-secret-v1\0" + _part(user_id) + _part(credential_id)
            + _part(str(revision)) + _part(key_id))


class CredentialPaymentSecretCipher:
    """AES-GCM envelope with a purpose-specific AAD domain, independent of Token ciphertext."""

    def __init__(self, keyring: CredentialKeyring):
        self._keyring = keyring

    def encrypt(self, plaintext: bytes, *, user_id: str, credential_id: str,
                revision: int, key_id: str) -> EncryptedPaymentSecret:
        if not isinstance(plaintext, bytes) or not plaintext:
            raise TypeError("payment secret plaintext must be non-empty bytes")
        try:
            key = self._keyring.key(key_id)
        except ValueError as exc:
            raise PaymentSecretError("payment secret encryption key is unavailable") from exc
        nonce = secrets.token_bytes(12)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=16)
        cipher.update(_aad(user_id=user_id, credential_id=credential_id, revision=revision, key_id=key_id))
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)
        return EncryptedPaymentSecret(ciphertext, nonce, tag, key_id)

    def decrypt(self, envelope: EncryptedPaymentSecret, *, user_id: str, credential_id: str,
                revision: int, key_id: str) -> bytes:
        if (not isinstance(envelope, EncryptedPaymentSecret) or envelope.key_id != key_id
                or len(envelope.nonce) != 12 or len(envelope.tag) != 16):
            raise PaymentSecretError("payment secret envelope is invalid")
        try:
            key = self._keyring.key(key_id)
        except ValueError as exc:
            raise PaymentSecretError("payment secret encryption key is unavailable") from exc
        try:
            cipher = AES.new(key, AES.MODE_GCM, nonce=envelope.nonce, mac_len=16)
            cipher.update(_aad(user_id=user_id, credential_id=credential_id, revision=revision, key_id=key_id))
            return cipher.decrypt_and_verify(envelope.ciphertext, envelope.tag)
        except (ValueError, TypeError) as exc:
            raise PaymentSecretError("payment secret envelope authentication failed") from exc
