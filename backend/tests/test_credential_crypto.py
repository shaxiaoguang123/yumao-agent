from __future__ import annotations

import base64
import json
import unittest

from backend.credentials.crypto import (
    CredentialTokenCipher,
    TokenCipherIntegrityError,
    TokenCipherKeyUnavailable,
)
from backend.credentials.keyring import parse_credential_keyring


def _keyring(key_id: str = "enc-v1", material: bytes = bytes(range(32))):
    encoded = base64.urlsafe_b64encode(material).rstrip(b"=").decode("ascii")
    return parse_credential_keyring(json.dumps({key_id: encoded}), key_id)


class CredentialTokenCipherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cipher = CredentialTokenCipher(_keyring())
        self.context = {
            "user_id": "user-1",
            "credential_id": "credential-1",
            "revision_id": "revision-1",
            "key_id": "enc-v1",
        }

    def test_encrypt_decrypt_round_trip_uses_expected_nonce_and_tag_sizes(self) -> None:
        plaintext = b"synthetic.jwt.token"

        envelope = self.cipher.encrypt(plaintext, **self.context)

        self.assertEqual(len(envelope.nonce), 12)
        self.assertEqual(len(envelope.tag), 16)
        self.assertEqual(self.cipher.decrypt(envelope, **self.context), plaintext)
        self.assertNotIn(plaintext.decode(), repr(envelope))

    def test_each_encryption_uses_a_fresh_nonce(self) -> None:
        first = self.cipher.encrypt(b"same plaintext", **self.context)
        second = self.cipher.encrypt(b"same plaintext", **self.context)

        self.assertNotEqual(first.nonce, second.nonce)
        self.assertNotEqual(first.ciphertext, second.ciphertext)

    def test_ciphertext_is_bound_to_user_credential_revision_and_key_context(self) -> None:
        envelope = self.cipher.encrypt(b"synthetic.jwt.token", **self.context)
        changed_contexts = (
            {**self.context, "user_id": "user-2"},
            {**self.context, "credential_id": "credential-2"},
            {**self.context, "revision_id": "revision-2"},
            {**self.context, "key_id": "enc-v2"},
        )
        for context in changed_contexts:
            with self.subTest(context=context):
                with self.assertRaises(TokenCipherIntegrityError):
                    self.cipher.decrypt(envelope, **context)

    def test_ciphertext_and_authentication_tag_tampering_are_rejected(self) -> None:
        envelope = self.cipher.encrypt(b"synthetic.jwt.token", **self.context)
        changed_ciphertext = type(envelope)(
            ciphertext=bytes([envelope.ciphertext[0] ^ 1]) + envelope.ciphertext[1:],
            nonce=envelope.nonce,
            tag=envelope.tag,
            key_id=envelope.key_id,
        )
        changed_tag = type(envelope)(
            ciphertext=envelope.ciphertext,
            nonce=envelope.nonce,
            tag=bytes([envelope.tag[0] ^ 1]) + envelope.tag[1:],
            key_id=envelope.key_id,
        )
        for changed in (changed_ciphertext, changed_tag):
            with self.assertRaises(TokenCipherIntegrityError):
                self.cipher.decrypt(changed, **self.context)

    def test_missing_encryption_key_fails_with_safe_error(self) -> None:
        envelope = self.cipher.encrypt(b"synthetic.jwt.token", **self.context)
        cipher_without_key = CredentialTokenCipher(_keyring("enc-v2", bytes(range(32, 64))))

        with self.assertRaises(TokenCipherKeyUnavailable) as raised:
            cipher_without_key.decrypt(envelope, **self.context)

        self.assertNotIn("synthetic.jwt.token", str(raised.exception))
        self.assertNotIn(envelope.ciphertext.hex(), str(raised.exception))


if __name__ == "__main__":
    unittest.main()
