from __future__ import annotations

from dataclasses import dataclass

from wzu_scraper.client import WZUClient

from .conftest import read_fixture


@dataclass
class FakeResponse:
    url: str
    text: str = ""
    status_code: int = 200

    def raise_for_status(self) -> None:
        return None


class FakeCookieJar:
    def __iter__(self):
        return iter(())


class FakeCookies:
    jar = FakeCookieJar()

    def set(self, *_args, **_kwargs) -> None:
        return None


class FakeClient:
    def __init__(self, session_valid: bool):
        self.cookies = FakeCookies()
        self._session_valid = session_valid

    def get(self, url: str, params: dict | None = None):
        if "index_cxYhxxIndex.html" in url:
            if self._session_valid:
                return FakeResponse(
                    url="https://jwxt.wzu.edu.cn/jwglxt/xtgl/index_cxYhxxIndex.html",
                    text="<html>ok</html>",
                )
            return FakeResponse(
                url="https://source.wzu.edu.cn/login",
                text="<html>login</html>",
            )

        return FakeResponse(
            url="https://source.wzu.edu.cn/login?service=https://jwxt.wzu.edu.cn/sso/zfiotlogin",
            text=read_fixture("auth", "login_page.html"),
        )

    def post(self, url: str, data: dict | None = None, headers: dict | None = None):
        return FakeResponse(
            url="https://source.wzu.edu.cn/interstitial",
            text="<html>interstitial</html>",
            status_code=200,
        )

    def close(self) -> None:
        return None


def _make_client(session_valid: bool) -> WZUClient:
    client = WZUClient()
    client._client = FakeClient(session_valid)  # noqa: SLF001
    client._save_cookies = lambda: None  # noqa: SLF001
    return client


def test_login_cas_fails_when_redirect_does_not_produce_valid_session() -> None:
    client = _make_client(session_valid=False)

    assert client.login_cas("student001", "password") is False


def test_login_cas_accepts_verified_session_after_unexpected_redirect() -> None:
    client = _make_client(session_valid=True)

    assert client.login_cas("student001", "password") is True
