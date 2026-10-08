from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from Crypto.Cipher import AES

from backend.credentials.keyring import CredentialKeyring


class TokenCipherError(RuntimeError):
    """Safe base error for Token envelope operations."""


class TokenCipherKeyUnavailable(TokenCipherError):
    """An envelope's encryption key version is not configured."""


class TokenCipherIntegrityError(TokenCipherError):
    """An envelope failed its authenticated context or integrity check."""


@dataclass(frozen=True, slots=True)
class EncryptedTokenEnvelope:
    ciphertext: bytes = field(repr=False)
    nonce: bytes = field(repr=False)
    tag: bytes = field(repr=False)
    key_id: str = field(repr=False)


def _aad_part(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("Token envelope context values must be non-empty strings")
    encoded = value.encode("utf-8", errors="strict")
    if len(encoded) > 65535:
        raise ValueError("Token envelope context value is too long")
    return len(encoded).to_bytes(4, "big") + encoded


def _aad(*, user_id: str, credential_id: str, revision_id: str, key_id: str) -> bytes:
    return (
        b"credential-token-envelope-v1\0"
        + _aad_part(user_id)
        + _aad_part(credential_id)
        + _aad_part(revision_id)
        + _aad_part(key_id)
    )


class CredentialTokenCipher:
    def __init__(self, keyring: CredentialKeyring):
        self._keyring = keyring

    def encrypt(
        self,
        plaintext: bytes,
        *,
        user_id: str,
        credential_id: str,
        revision_id: str,
        key_id: str,
    ) -> EncryptedTokenEnvelope:
        if not isinstance(plaintext, bytes):
            raise TypeError("Token plaintext must be bytes")
        try:
            key = self._keyring.key(key_id)
        except ValueError as exc:
            raise TokenCipherKeyUnavailable("Token encryption key version is unavailable") from exc
        nonce = secrets.token_bytes(12)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=16)
        cipher.update(_aad(
            user_id=user_id,
            credential_id=credential_id,
            revision_id=revision_id,
            key_id=key_id,
        ))
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)
        return EncryptedTokenEnvelope(ciphertext, nonce, tag, key_id)

    def decrypt(
        self,
        envelope: EncryptedTokenEnvelope,
        *,
        user_id: str,
        credential_id: str,
        revision_id: str,
        key_id: str,
    ) -> bytes:
        if not isinstance(envelope, EncryptedTokenEnvelope):
            raise TypeError("Token envelope has an unsupported type")
        if envelope.key_id != key_id or len(envelope.nonce) != 12 or len(envelope.tag) != 16:
            raise TokenCipherIntegrityError("Token envelope authentication failed")
        try:
            key = self._keyring.key(key_id)
        except ValueError as exc:
            raise TokenCipherKeyUnavailable("Token encryption key version is unavailable") from exc
        try:
            cipher = AES.new(key, AES.MODE_GCM, nonce=envelope.nonce, mac_len=16)
            cipher.update(_aad(
                user_id=user_id,
                credential_id=credential_id,
                revision_id=revision_id,
                key_id=key_id,
            ))
            return cipher.decrypt_and_verify(envelope.ciphertext, envelope.tag)
        except (ValueError, TypeError) as exc:
            raise TokenCipherIntegrityError("Token envelope authentication failed") from exc
