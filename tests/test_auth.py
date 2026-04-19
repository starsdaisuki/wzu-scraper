from __future__ import annotations

from wzu_scraper.auth import build_login_data, parse_login_page

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
