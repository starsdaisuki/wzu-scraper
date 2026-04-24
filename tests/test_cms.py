"""Tests for CMSScraper crawl logic."""

from __future__ import annotations

import httpx

from wzu_scraper.cms import CMSScraper, SITES
from wzu_scraper.webvpn import WebVPNClient


def test_crawl_max_pages_visits_newest_pages_first(tmp_path, monkeypatch):
    """max_pages should visit the newest numbered pages.

    博达站群分页: 默认页 .htm = 最新; page/N.htm (largest N) = 次新,
    走到 page/1.htm 才是最老一批. 所以 "last 5 pages" 是 [N, N-1, ..., N-4].
    """
    monkeypatch.setattr(CMSScraper, "_load_all_dbs", lambda self: None)
    monkeypatch.setattr(CMSScraper, "_save_db", lambda self, site_key: None)

    visited: list[str] = []

    site = SITES["jwc"]
    first_category_path = next(iter(site.categories))
    page_name = first_category_path.split("/")[-1]

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(request.url.path)
        if request.url.path.endswith(f"/{first_category_path}.htm"):
            # Pretend this category has 20 total pages.
            html = "".join(
                f'<a href="/{page_name}/{i}.htm">{i}</a>' for i in range(1, 21)
            )
            return httpx.Response(200, text=html)
        # Paginated pages: return empty list pages
        return httpx.Response(200, text="<html></html>")

    scraper = CMSScraper()
    scraper._client = httpx.Client(transport=httpx.MockTransport(handler))

    scraper.crawl(
        "jwc", category_path=first_category_path, fetch_content=False, max_pages=5
    )

    paginated = [p for p in visited if f"/{page_name}/" in p]
    page_numbers = [int(p.rsplit("/", 1)[1].removesuffix(".htm")) for p in paginated]

    assert page_numbers == [20, 19, 18, 17, 16], (
        f"Expected newest pages [20,19,18,17,16], got {page_numbers}"
    )


def test_supports_jsp_false_for_plain_httpx():
    """Without WebVPN, JSP categories must stay disabled."""
    scraper = CMSScraper()
    try:
        assert scraper.supports_jsp is False
    finally:
        scraper.close()


def test_supports_jsp_true_for_webvpn_client(tmp_path):
    """With a WebVPNClient injected, JSP support flips on."""
    vpn = WebVPNClient(cookie_file=tmp_path / ".webvpn.json")
    vpn._client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    scraper = CMSScraper(client=vpn)
    try:
        assert scraper.supports_jsp is True
    finally:
        scraper.close()
        vpn.close()


def test_jwc_has_jsp_categories_for_student_and_teacher_announcements():
    """Regression: ensure jwc config retains the webvpn-only categories."""
    jwc = SITES["jwc"]
    assert "1276" in jwc.jsp_categories
    assert jwc.jsp_categories["1276"] == "学生公告"
    assert "1177" in jwc.jsp_categories
    assert jwc.jsp_categories["1177"] == "教师公告"


def test_crawl_skips_jsp_without_webvpn(tmp_path, monkeypatch):
    """crawl() must not hit jsp endpoints when client lacks WebVPN support."""
    monkeypatch.setattr(CMSScraper, "_load_all_dbs", lambda self: None)
    monkeypatch.setattr(CMSScraper, "_save_db", lambda self, site_key: None)

    visited: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(request.url.path)
        return httpx.Response(200, text="<html></html>")

    scraper = CMSScraper()
    scraper._client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper.crawl("jwc", fetch_content=False, max_pages=1)

    # Without webvpn, we should never request any JSP paths.
    assert not any("xlist.jsp" in p for p in visited)
    scraper.close()


def test_jsp_crawl_parses_and_ingests(tmp_path, monkeypatch):
    """With a WebVPNClient, jsp categories fetch xlist.jsp and ingest articles."""
    monkeypatch.setattr(CMSScraper, "_load_all_dbs", lambda self: None)
    monkeypatch.setattr(CMSScraper, "_save_db", lambda self, site_key: None)

    sample_list = """
<ul>
  <li><span class="w"><a href="xdetails.jsp?urltype=news.NewsContentUrl&wbtreeid=1276&wbnewsid=39834">标题 A</a></span><span class="time">2026年04月24日</span></li>
  <li><span class="w"><a href="xdetails.jsp?urltype=news.NewsContentUrl&wbtreeid=1276&wbnewsid=39794">标题 B</a></span><span class="time">2026年04月23日</span></li>
</ul>
<!-- totalpage=1/1 meaning single page -->
<script>_simple_list_gotopage_fun(1,'x')</script>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if "xlist.jsp" in request.url.path:
            return httpx.Response(200, text=sample_list)
        # htm category requests return an empty page — we're only testing jsp here.
        return httpx.Response(200, text="<html></html>")

    vpn = WebVPNClient(cookie_file=tmp_path / ".webvpn.json")
    vpn._client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = CMSScraper(client=vpn)
    try:
        new = scraper.crawl("jwc", fetch_content=False, max_pages=1)
    finally:
        scraper.close()
        vpn.close()

    assert new >= 2
    jsp_keys = [k for k in scraper._articles if k.startswith("jwc:jsp/1276/")]
    assert "jwc:jsp/1276/39834" in jsp_keys
    # Database content should include the normalised date + title.
    art = scraper._articles["jwc:jsp/1276/39834"]
    assert art.title == "标题 A"
    assert art.date == "2026-04-24"
    assert art.category == "学生公告"
    assert art.url.endswith("wbnewsid=39834")
