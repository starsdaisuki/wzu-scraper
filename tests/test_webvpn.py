"""Tests for the WebVPN client: URL rewriting + session detection."""

from __future__ import annotations

import httpx

from wzu_scraper.webvpn import WebVPNClient, rewrite_url


def test_rewrite_url_standard_https() -> None:
    """Canonical campus https URL gets -443.webvpn.wzu.edu.cn suffix."""
    assert (
        rewrite_url("https://jwc.wzu.edu.cn/path.htm")
        == "https://jwc-443.webvpn.wzu.edu.cn/path.htm"
    )


def test_rewrite_url_preserves_query_and_fragment() -> None:
    original = (
        "https://jwc.wzu.edu.cn/new2021/xlist.jsp"
        "?urltype=tree.TreeTempUrl&wbtreeid=1276#top"
    )
    rewritten = rewrite_url(original)
    assert rewritten == (
        "https://jwc-443.webvpn.wzu.edu.cn/new2021/xlist.jsp"
        "?urltype=tree.TreeTempUrl&wbtreeid=1276#top"
    )


def test_rewrite_url_leaves_webvpn_host_unchanged() -> None:
    url = "https://jwc-443.webvpn.wzu.edu.cn/x.htm"
    assert rewrite_url(url) == url


def test_rewrite_url_leaves_external_host_unchanged() -> None:
    assert rewrite_url("https://example.com/foo") == "https://example.com/foo"
    assert rewrite_url("https://jsjyxy.example.cn/x") == "https://jsjyxy.example.cn/x"


def test_rewrite_url_leaves_non_http_unchanged() -> None:
    assert rewrite_url("mailto:a@b.wzu.edu.cn") == "mailto:a@b.wzu.edu.cn"


def test_rewrite_url_flattens_multi_label_subdomain() -> None:
    # Hypothetical nested subdomain still routes correctly.
    assert (
        rewrite_url("https://api.jwxt.wzu.edu.cn/x")
        == "https://api-jwxt-443.webvpn.wzu.edu.cn/x"
    )


def test_webvpn_client_get_rewrites_url_before_dispatch(tmp_path) -> None:
    """WebVPNClient.get must request the rewritten URL, not the original."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, text="ok")

    client = WebVPNClient(cookie_file=tmp_path / ".webvpn.json")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    resp = client.get("https://jwc.wzu.edu.cn/path.htm")

    assert resp.status_code == 200
    assert requested == ["https://jwc-443.webvpn.wzu.edu.cn/path.htm"]


def test_webvpn_check_session_recognises_authenticated_response(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="home page")

    client = WebVPNClient(cookie_file=tmp_path / ".webvpn.json")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    assert client.check_session() is True


def test_webvpn_check_session_recognises_signin_redirect(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"location": "https://webvpn.wzu.edu.cn/users/sign_in"}
        )

    client = WebVPNClient(cookie_file=tmp_path / ".webvpn.json")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    assert client.check_session() is False


def test_webvpn_login_retries_transient_network_errors(tmp_path, monkeypatch) -> None:
    """A flaky network must not blow up login on the first connect failure."""
    monkeypatch.setattr("wzu_scraper.webvpn.time.sleep", lambda s: None)

    calls = {"n": 0}
    monkeypatch.setattr(
        WebVPNClient,
        "_do_login_once",
        lambda self, u, p: _flaky_login(calls),
    )

    client = WebVPNClient(cookie_file=tmp_path / ".webvpn.json")
    try:
        ok = client.login("user", "pw", attempts=3)
    finally:
        client.close()
    assert ok is True
    assert calls["n"] == 2  # 1 failure + 1 success


def _flaky_login(calls):
    calls["n"] += 1
    if calls["n"] < 2:
        raise httpx.ConnectError("boom")
    return True


def test_webvpn_login_does_not_retry_bad_credentials(tmp_path, monkeypatch) -> None:
    """If CAS rejects the password, retrying is pointless — bail immediately."""
    monkeypatch.setattr("wzu_scraper.webvpn.time.sleep", lambda s: None)

    calls = {"n": 0}

    def handler(self, u, p):
        calls["n"] += 1
        return False  # simulates "got back to sign_in"

    monkeypatch.setattr(WebVPNClient, "_do_login_once", handler)

    client = WebVPNClient(cookie_file=tmp_path / ".webvpn.json")
    try:
        ok = client.login("user", "wrong", attempts=5)
    finally:
        client.close()
    assert ok is False
    assert calls["n"] == 1
