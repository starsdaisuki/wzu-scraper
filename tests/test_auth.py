from __future__ import annotations

from wzu_scraper.auth import build_login_data, is_jwxt_url, parse_login_page

from .conftest import read_fixture


def test_parse_login_page_extracts_execution_and_croypto() -> None:
    page = parse_login_page(read_fixture("auth", "login_page.html"))

    assert page is not None
    assert page.execution == "fake-flow-key_H4sIAFAKE"
    assert page.server_croypto == "ZmFrZS1zZXJ2ZXItY3JveXB0bw=="


def test_build_login_data_contains_required_fields() -> None:
    data = build_login_data("student001", "safe-password", "flow-token")

    assert data["username"] == "student001"
    assert data["execution"] == "flow-token"
    assert data["type"] == "UsernamePassword"
    assert data["_eventId"] == "submit"
    assert data["geolocation"] == ""
    assert data["password"]
    assert data["croypto"]


def test_is_jwxt_url_checks_target_host_and_path() -> None:
    assert is_jwxt_url("https://jwxt.wzu.edu.cn/sso/zfiotlogin")
    assert is_jwxt_url("https://jwxt.wzu.edu.cn/jwglxt/xtgl/index_initMenu.html")
    assert not is_jwxt_url(
        "https://source.wzu.edu.cn/login?service=https://jwxt.wzu.edu.cn/sso/zfiotlogin"
    )
