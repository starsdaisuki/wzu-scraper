"""WZU WebVPN client.

WebVPN (Astraeus) at ``webvpn.wzu.edu.cn`` wraps any campus domain via a
hostname rewrite:

    https://<host>:<port>/<path>  →  https://<host>-<port>.webvpn.wzu.edu.cn/<path>

Access requires a CAS-authenticated session persisted across requests as the
``_astraeus_session`` / ``_webvpn_key`` cookies.  This module handles the full
login flow, URL rewriting, and cookie persistence so that the rest of the
crawler can treat a :class:`WebVPNClient` as a drop-in replacement for
``httpx.Client`` when on-campus pages are needed.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx

from .auth import build_login_data, parse_login_page

logger = logging.getLogger(__name__)

WEBVPN_HOST = "webvpn.wzu.edu.cn"
WEBVPN_BASE = f"https://{WEBVPN_HOST}"
CAS_BASE = "https://source.wzu.edu.cn"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

DEFAULT_COOKIE_FILE = Path(__file__).parent.parent / ".webvpn-cookies.json"


WZU_DOMAIN_SUFFIX = ".wzu.edu.cn"


def rewrite_url(url: str) -> str:
    """Rewrite a ``*.wzu.edu.cn`` URL so it routes through WebVPN.

    ``https://jwc.wzu.edu.cn/xxx.htm`` → ``https://jwc-443.webvpn.wzu.edu.cn/xxx.htm``.

    URLs that are not http(s), already on ``webvpn.wzu.edu.cn``, or whose host
    is outside ``*.wzu.edu.cn`` (including external domains and bare IPs) are
    returned unchanged.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return url
    host = parsed.hostname or ""
    if not host or host == WEBVPN_HOST or host.endswith(f".{WEBVPN_HOST}"):
        return url
    # Only rewrite campus subdomains.  host must end with ``.wzu.edu.cn`` and
    # have at least one label before it.
    if not host.endswith(WZU_DOMAIN_SUFFIX):
        return url
    subdomain = host[: -len(WZU_DOMAIN_SUFFIX)]
    if not subdomain:
        return url

    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    # Dots inside a multi-label subdomain get flattened into dashes.
    new_host = f"{subdomain.replace('.', '-')}-{port}.{WEBVPN_HOST}"

    return urlunparse(
        ("https", new_host, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


class WebVPNClient:
    """HTTP client that routes every request through WZU WebVPN.

    Public API mirrors a tiny subset of :class:`httpx.Client` (``get``,
    ``post``, ``close``, context manager).  Every URL passed in is transparently
    rewritten via :func:`rewrite_url` before dispatching.
    """

    def __init__(self, cookie_file: Path | None = None) -> None:
        self._client = httpx.Client(
            headers=HEADERS,
            follow_redirects=True,
            timeout=30.0,
        )
        self._cookie_file = cookie_file or DEFAULT_COOKIE_FILE
        self._logged_in = False
        self._load_cookies()

    # --- cookie persistence ---

    def _save_cookies(self) -> None:
        cookie_list = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self._client.cookies.jar
        ]
        self._cookie_file.write_text(
            json.dumps(cookie_list, ensure_ascii=False, indent=2)
        )

    def _load_cookies(self) -> None:
        if not self._cookie_file.exists():
            return
        try:
            cookie_list = json.loads(self._cookie_file.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for c in cookie_list:
            try:
                self._client.cookies.set(
                    c["name"],
                    c["value"],
                    domain=c.get("domain", ""),
                    path=c.get("path", "/"),
                )
            except KeyError:
                continue

    # --- auth ---

    def check_session(self) -> bool:
        """Return True when the persisted WebVPN cookies still authorise us.

        Hits the WebVPN root with redirects disabled.  An unauthenticated
        client receives ``302`` pointing at ``/users/sign_in``; an
        authenticated one receives ``200``.
        """
        try:
            resp = self._client.get(
                WEBVPN_BASE + "/",
                follow_redirects=False,
                timeout=10.0,
            )
        except httpx.HTTPError:
            return False
        if resp.status_code == 200:
            return True
        if resp.status_code in (301, 302):
            location = resp.headers.get("location") or ""
            return "sign_in" not in location
        return False

    def login(self, username: str, password: str, attempts: int = 3) -> bool:
        """Log in to WebVPN via CAS, retrying on transient network errors.

        Reuses :mod:`wzu_scraper.auth` helpers to parse the CAS login page
        and build the encrypted form payload.  Wrong credentials are NOT
        retried (they'd fail every time); only HTTP/network failures get
        a second chance.
        """
        last_error: Exception | None = None
        for attempt in range(max(1, attempts)):
            try:
                if self._do_login_once(username, password):
                    return True
                # Reached the final URL but not logged in — credentials wrong
                # or CAS denied us.  No point retrying.
                return False
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                last_error = exc
                logger.warning(
                    "WebVPN login network error",
                    extra={
                        "attempt": attempt + 1,
                        "of": attempts,
                        "error": type(exc).__name__,
                    },
                )
                if attempt + 1 < attempts:
                    time.sleep(1.0 * (2**attempt))
        logger.warning(
            "WebVPN login gave up",
            extra={
                "attempts": attempts,
                "last_error": type(last_error).__name__ if last_error else None,
            },
        )
        return False

    def _do_login_once(self, username: str, password: str) -> bool:
        """Single login attempt — may raise on network errors."""
        logger.info("Starting WebVPN login via CAS")
        # 1) Visit webvpn home, follow redirects.  If already authenticated
        #    this lands back on webvpn itself; otherwise it lands on the CAS
        #    login page (source.wzu.edu.cn).
        resp = self._client.get(WEBVPN_BASE + "/")
        resp.raise_for_status()
        if self._is_webvpn_host(str(resp.url)):
            self._logged_in = True
            logger.info("WebVPN session already valid, skipping login")
            return True

        login_page = parse_login_page(resp.text)
        if login_page is None:
            logger.warning("Failed to parse WebVPN CAS login page")
            return False

        cas_url = str(resp.url)
        post_resp = self._client.post(
            f"{CAS_BASE}/login",
            data=build_login_data(username, password, login_page.execution),
            headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": CAS_BASE,
                "Referer": cas_url,
            },
        )
        final_url = str(post_resp.url)
        if self._is_webvpn_host(final_url):
            self._logged_in = True
            self._save_cookies()
            logger.info("WebVPN login succeeded")
            return True

        logger.warning(
            "WebVPN login did not redirect back to webvpn",
            extra={"final_url": final_url, "status": post_resp.status_code},
        )
        return False

    @staticmethod
    def _is_webvpn_host(url: str) -> bool:
        """True if ``url``'s *hostname* is exactly webvpn.wzu.edu.cn."""
        try:
            host = urlparse(url).hostname
        except ValueError:
            return False
        return host == WEBVPN_HOST

    # --- HTTP ---

    def get(self, url: str, **kwargs) -> httpx.Response:
        resp = self._client.get(rewrite_url(url), **kwargs)
        self._warn_if_ipauth(resp)
        return resp

    def post(self, url: str, **kwargs) -> httpx.Response:
        resp = self._client.post(rewrite_url(url), **kwargs)
        self._warn_if_ipauth(resp)
        return resp

    @staticmethod
    def _warn_if_ipauth(resp: httpx.Response) -> None:
        """Log when WebVPN silently returns the ipauth stub.

        A valid WebVPN session forwards the request and returns real content.
        If the session expires mid-crawl the server responds 200 OK with the
        tiny ``window.location.href='/system/resource/code/auth/ipauth.htm'``
        redirect stub instead — the caller would otherwise just see "empty
        list" and have no idea why.  Emitting a warning at least surfaces it.
        """
        if resp.status_code == 200 and len(resp.text) < 500 and "ipauth" in resp.text:
            logger.warning(
                "WebVPN returned ipauth redirect — session may be expired",
                extra={"url": str(resp.url)},
            )

    # --- housekeeping ---

    def save(self) -> None:
        self._save_cookies()

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
