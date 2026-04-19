"""CAS login helpers for WZU authentication."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .crypto import aes_encrypt, generate_aes_key


@dataclass(frozen=True)
class CASLoginPage:
    """Parsed fields required for a CAS login submission."""

    execution: str
    server_croypto: str | None = None


def parse_login_page(html: str) -> CASLoginPage | None:
    """Extract the execution token and server croypto value from the login page."""
    exec_match = re.search(r'id="login-page-flowkey"[^>]*>([^<]+)<', html)
    if not exec_match:
        return None

    croypto_match = re.search(r'id="login-croypto"[^>]*>([^<]+)<', html)
    server_croypto = croypto_match.group(1).strip() if croypto_match else None

    return CASLoginPage(
        execution=exec_match.group(1).strip(),
        server_croypto=server_croypto,
    )


def build_login_data(username: str, password: str, execution: str) -> dict[str, str]:
    """Build the CAS form payload using the same AES flow as the browser."""
    aes_key = generate_aes_key()
    croypto_b64 = base64.b64encode(aes_key).decode("ascii")
    encrypted_password = aes_encrypt(aes_key, password)

    return {
        "username": username,
        "type": "UsernamePassword",
        "_eventId": "submit",
        "geolocation": "",
        "execution": execution,
        "croypto": croypto_b64,
        "password": encrypted_password,
    }


def extract_login_error(html: str) -> str | None:
    """Extract a login error message from the response HTML if present."""
    err_match = re.search(r'class="[^"]*error[^"]*"[^>]*>([^<]+)<', html)
    if not err_match:
        return None
    return err_match.group(1).strip()


def is_jwxt_url(url: str) -> bool:
    """Return whether the current URL points at the JWXT application."""
    parsed = urlparse(url)
    if parsed.netloc != "jwxt.wzu.edu.cn":
        return False
    return parsed.path.startswith("/jwglxt") or parsed.path == "/sso/zfiotlogin"
