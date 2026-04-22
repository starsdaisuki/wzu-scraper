"""Tests for CMSScraper crawl logic."""

from __future__ import annotations

import httpx

from wzu_scraper.cms import CMSScraper, SITES


def test_crawl_max_pages_visits_newest_pages_first(tmp_path, monkeypatch):
    """max_pages should visit page 1,2,3 (newest) not total_pages,...,N (oldest).

    博达站群分页: 默认页 .htm = 最新; page/1.htm 次新; page/N.htm 最老.
    Regression test for a bug where max_pages sliced from the end of the
    descending range, so users asking for "last 5 pages" got the oldest 5.
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

    assert page_numbers == [1, 2, 3, 4, 5], (
        f"Expected newest pages [1,2,3,4,5], got {page_numbers}"
    )
