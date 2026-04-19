from __future__ import annotations

import base64

from wzu_scraper.crypto import aes_encrypt


def test_aes_encrypt_returns_base64_text() -> None:
    key = b"0123456789abcdef"
    encrypted = aes_encrypt(key, "secret-password")

    decoded = base64.b64decode(encrypted)

    assert isinstance(encrypted, str)
    assert len(decoded) % 16 == 0
    assert decoded
