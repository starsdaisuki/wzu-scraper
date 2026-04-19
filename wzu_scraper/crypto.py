"""AES-ECB encryption matching the CAS login page's CryptoJS implementation."""

import base64
import os

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


def generate_aes_key() -> bytes:
    """Generate a random 16-byte AES key."""
    return os.urandom(16)


def aes_encrypt(key: bytes, plaintext: str) -> str:
    """Encrypt plaintext with AES-ECB-PKCS7, return base64 string.

    This mirrors the JS: CryptoJS.AES.encrypt(plaintext, key, {mode: ECB, padding: Pkcs7})
    """
    cipher = AES.new(key, AES.MODE_ECB)
    padded = pad(plaintext.encode("utf-8"), AES.block_size)
    encrypted = cipher.encrypt(padded)
    return base64.b64encode(encrypted).decode("ascii")
