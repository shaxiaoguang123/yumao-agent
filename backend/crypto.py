from __future__ import annotations

from Crypto.Cipher import AES


def pkcs7_pad(data: bytes) -> bytes:
    pad_len = 16 - (len(data) % 16)
    return data + bytes([pad_len] * pad_len)


def aes_cbc_encrypt_hex_upper(plaintext: str, key_ascii: str, iv_ascii: str) -> str:
    key = key_ascii.encode("utf-8")
    iv = iv_ascii.encode("utf-8")
    data = plaintext.encode("utf-8")
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    return cipher.encrypt(pkcs7_pad(data)).hex().upper()
