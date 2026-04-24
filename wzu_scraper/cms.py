"""Generic WZU CMS (博达站群) scraper with local full-text search.

Supports any WZU website built on the same CMS platform.
"""

import html as html_lib
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

from .cms_parsers import extract_article_content, parse_list_page


def _sanitize(text: str) -> str:
    """Decode HTML entities, collapse NBSP/whitespace."""
    if not text:
        return text
    return re.sub(r"\s+", " ", html_lib.unescape(text).replace("\xa0", " ")).strip()


class HttpClient(Protocol):
    """Minimal shape shared by ``httpx.Client`` and :class:`WebVPNClient`."""

    def get(self, url: str, **kwargs) -> httpx.Response: ...
    def close(self) -> None: ...


# Inter-fetch delay; tuned via WZU_REQUEST_DELAY env var (seconds).  The
# default 0.2s is gentle enough for the school servers but burns minutes on
# big crawls — power users can lower it.
REQUEST_DELAY = max(0.0, float(os.environ.get("WZU_REQUEST_DELAY", "0.2")))

# Number of attempts (incl. first) when fetching article bodies; transient
# network errors get retried with exponential backoff.
FETCH_ATTEMPTS = max(1, int(os.environ.get("WZU_FETCH_ATTEMPTS", "3")))


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}

DB_DIR = Path(__file__).parent.parent / "data"
logger = logging.getLogger(__name__)


@dataclass
class Article:
    id: str  # e.g. "1188/38224"
    title: str
    date: str  # e.g. "2026-01-16"
    category: str  # e.g. "教学新闻"
    url: str
    site: str = ""  # e.g. "jwc", "slxy"
    content: str = ""


@dataclass
class SiteConfig:
    key: str  # e.g. "jwc"
    name: str  # e.g. "教务处"
    base_url: str  # e.g. "https://jwc.wzu.edu.cn"
    # htm category: {path -> display name}  e.g. {"jxxw": "教学新闻"}
    categories: dict[str, str] = field(default_factory=dict)
    # JSP (联奕 xlist.jsp) category: {wbtreeid -> display name}.  JSP-only sites
    # (notably 教务处) require an on-campus IP to fetch, so these only resolve
    # through a WebVPN client.
    jsp_categories: dict[str, str] = field(default_factory=dict)


# Site definitions
SITES: dict[str, SiteConfig] = {
    "jwc": SiteConfig(
        key="jwc",
        name="教务处",
        base_url="https://jwc.wzu.edu.cn",
        categories={
            "jxxw": "教学新闻",
            "xxfw/xlzxsj": "校历/作息时间",
            "zcjd/zyyx": "政策解读",
        },
        # These JSP categories are IP-whitelisted — must crawl via WebVPN.
        jsp_categories={
            "1276": "学生公告",
            "1177": "教师公告",
            "1190": "信息服务",
        },
    ),
    "ai": SiteConfig(
        key="ai",
        name="计算机与人工智能学院",
        base_url="https://ai.wzu.edu.cn",
        categories={
            "xwzx/xydt": "学院动态",
            "xwzx/jsgg": "教师公告",
            "xwzx/xsgg": "学生公告",
            "xwzx/jzyg": "讲座预告",
            "xwzx/mtkxy": "媒体看学院",
        },
    ),
    "chem": SiteConfig(
        key="chem",
        name="化学与材料工程学院",
        base_url="https://chem.wzu.edu.cn",
        categories={
            "index/tzgg/xyxw": "学院新闻",
            "index/tzgg/jsgg": "教师公告",
            "index/tzgg/xsgg1": "学生公告",
            "kxyj/kydt/jzxx": "讲座信息",
        },
    ),
    "cace": SiteConfig(
        key="cace",
        name="建筑工程学院",
        base_url="https://cace.wzu.edu.cn",
        categories={
            "xyxw/xyxw": "学院新闻",
            "ywgk/xsgg": "学生公告",
            "xyxw/mtjg": "媒体聚焦",
        },
    ),
    "jdxy": SiteConfig(
        key="jdxy",
        name="机电工程学院",
        base_url="https://jdxy.wzu.edu.cn",
        categories={
            "xwkd": "新闻快递",
            "xstz": "学生通知",
            "xstd/tzgg": "通知公告",
            "xstd/txdt1": "团学动态",
            "xsjiang": "学术动态",
            "mtkjd": "媒体看机电",
        },
    ),
    "shxy": SiteConfig(
        key="shxy",
        name="生环学院",
        base_url="https://shxy.wzu.edu.cn",
        categories={
            "bkjy/tzgg": "本科教育通知",
            "yjsjy/tzgg": "研究生通知",
            "xsgz/txhd": "团学活动",
            "xsgz/xfjs": "学风建设",
            "xsgz/kjjs": "科技竞赛",
        },
    ),
    "slxy": SiteConfig(
        key="slxy",
        name="数理学院",
        base_url="https://slxy.wzu.edu.cn",
        categories={
            "xxzx/xydt": "学院动态",
            "xxzx/xsgg": "学生公告",
            "xxzx/jggg": "教工公告",
            "xxzx/jzxx": "讲座信息",
            "xxzx/mtsl": "媒体数理",
            "xstd/txdt": "团学动态",
            "xstd/kycx": "科研创新",
            "xstd/xfjs": "学风建设",
        },
    ),
}


class CMSScraper:
    """Generic scraper for WZU CMS websites.

    By default builds a plain :class:`httpx.Client`; callers that need to
    access on-campus JSP categories (교务处 学生公告, 等) can pass a
    :class:`wzu_scraper.webvpn.WebVPNClient` via ``client=``.  Any object
    conforming to :class:`HttpClient` works.
    """

    def __init__(self, client: HttpClient | None = None) -> None:
        self._owns_client = client is None
        self._client: HttpClient = client or httpx.Client(
            headers=HEADERS,
            follow_redirects=True,
            timeout=15.0,
        )
        self._articles: dict[str, Article] = {}
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self._load_all_dbs()

    @property
    def supports_jsp(self) -> bool:
        """Whether the underlying client can reach IP-restricted JSP pages.

        JSP categories are IP-whitelisted; only a WebVPN-backed client can
        fetch them.  The plain ``httpx.Client`` default cannot.
        """
        # Avoid importing WebVPNClient at module load time; detect by class name.
        return type(self._client).__name__ == "WebVPNClient"

    def _db_path(self, site_key: str) -> Path:
        return DB_DIR / f"{site_key}_articles.json"

    def _load_all_dbs(self):
        """Load all site databases."""
        for site_key in SITES:
            self._load_db(site_key)

    def _load_db(self, site_key: str):
        path = self._db_path(site_key)
        if path.exists():
            try:
                for item in json.loads(path.read_text()):
                    art = Article(**item)
                    # Repair any HTML entities baked into older DBs.
                    art.title = _sanitize(art.title)
                    art.content = _sanitize(art.content)
                    self._articles[f"{art.site}:{art.id}"] = art
            except (json.JSONDecodeError, TypeError):
                pass

    def _save_db(self, site_key: str):
        """Atomic write: serialize to a temp file then rename into place.

        A crash mid-write used to corrupt the JSON (truncated file ⇒ next
        startup treats DB as empty).  Writing to a sibling ``.tmp`` and
        ``os.replace``-ing is atomic on POSIX.
        """
        site_articles = [
            asdict(a) for a in self._articles.values() if a.site == site_key
        ]
        target = self._db_path(site_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=target.name + ".",
            suffix=".tmp",
            dir=target.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(site_articles, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, target)
        except Exception:
            # Clean up stray tmp file on failure and re-raise.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _parse_list_page(
        self, html: str, category_name: str, site: SiteConfig
    ) -> list[Article]:
        """Extract articles from a list page."""
        return [
            Article(
                id=f"{item.category_id}/{item.article_id}",
                title=item.title,
                date=item.date,
                category=category_name,
                url=f"{site.base_url}/info/{item.category_id}/{item.article_id}.htm",
                site=site.key,
            )
            for item in parse_list_page(html)
        ]

    def _fetch_content(self, url: str) -> str:
        """Fetch article body with retry/backoff on transient failures.

        404/403 are treated as permanent (stop early); other non-200 codes
        and HTTP errors get up to ``FETCH_ATTEMPTS`` total attempts with an
        exponential 0.5/1.0/2.0s backoff.
        """
        last_error = ""
        for attempt in range(FETCH_ATTEMPTS):
            try:
                resp = self._client.get(url)
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
                logger.debug(
                    "fetch_content network error",
                    extra={"url": url, "attempt": attempt + 1, "error": last_error},
                )
            else:
                if resp.status_code == 200:
                    return extract_article_content(resp.text)
                # Permanent failures: don't waste retries.
                if resp.status_code in (403, 404, 410):
                    logger.warning(
                        "fetch_content permanent failure",
                        extra={"url": url, "status": resp.status_code},
                    )
                    return ""
                last_error = f"HTTP {resp.status_code}"
            if attempt + 1 < FETCH_ATTEMPTS:
                time.sleep(0.5 * (2**attempt))
        logger.warning(
            "fetch_content gave up after retries",
            extra={"url": url, "attempts": FETCH_ATTEMPTS, "last_error": last_error},
        )
        return ""

    def fetch_and_cache_content(self, article: Article) -> str:
        """Fetch article body on demand and persist to disk.

        Called from the reader when an article's ``content`` is empty, e.g.
        because an earlier crawl ran with ``fetch_content=False`` or predated
        the category being enabled.  Returns the resulting content (may be
        empty if the fetch failed, e.g. JSP article with no WebVPN).
        """
        if article.content:
            return article.content
        content = self._fetch_content(article.url)
        if content:
            article.content = content
            # Make sure the in-memory copy in self._articles reflects this too.
            key = f"{article.site}:{article.id}"
            if key in self._articles:
                self._articles[key].content = content
            self._save_db(article.site)
        return content

    def crawl(
        self,
        site_key: str,
        category_path: str | None = None,
        fetch_content: bool = True,
        max_pages: int = 0,
        include_jsp: bool = True,
    ) -> int:
        """Crawl articles from a site.

        Args:
            site_key: e.g. "jwc" or "slxy"
            category_path: Specific htm category path, or None for all
            fetch_content: Whether to fetch full article text
            max_pages: Max pages per category (0 = all)
            include_jsp: Also crawl ``jsp_categories`` when the client supports
                it.  Ignored without WebVPN since those pages are IP-blocked.
        """
        site = SITES[site_key]
        cats = (
            {category_path: site.categories[category_path]}
            if category_path
            else site.categories
        )
        total_new = 0

        # Save after EACH category so a Ctrl+C between categories preserves
        # everything fetched so far.  The atomic write means partial saves
        # during a single category are still safe.
        try:
            for path, cat_name in cats.items():
                added = self._crawl_htm_category(
                    site, path, cat_name, fetch_content, max_pages
                )
                total_new += added
                if added:
                    self._save_db(site_key)

            if include_jsp and site.jsp_categories and category_path is None:
                if not self.supports_jsp:
                    logger.info(
                        "Skipping JSP categories; client does not support WebVPN",
                        extra={"site": site.name},
                    )
                else:
                    for wbtreeid, cat_name in site.jsp_categories.items():
                        added = self._crawl_jsp_category(
                            site, wbtreeid, cat_name, fetch_content, max_pages
                        )
                        total_new += added
                        if added:
                            self._save_db(site_key)
        finally:
            # Always write a final consolidated copy on the way out (even if
            # an exception or KeyboardInterrupt is propagating).
            self._save_db(site_key)
        return total_new

    def _crawl_htm_category(
        self,
        site: SiteConfig,
        path: str,
        cat_name: str,
        fetch_content: bool,
        max_pages: int,
    ) -> int:
        """Crawl a single .htm-style category across its paginated pages."""
        logger.info(
            "Crawling CMS category", extra={"site": site.name, "category": cat_name}
        )
        new_count = 0

        resp = self._client.get(f"{site.base_url}/{path}.htm")
        if resp.status_code != 200:
            logger.warning(
                "Failed to fetch CMS list page",
                extra={
                    "site": site.name,
                    "category": cat_name,
                    "status_code": resp.status_code,
                },
            )
            return 0

        new_count += self._ingest_htm_list_page(
            resp.text, cat_name, site, fetch_content
        )

        page_name = path.split("/")[-1]
        page_nums = re.findall(rf"{page_name}/(\d+)\.htm", resp.text)
        total_pages = max(int(p) for p in page_nums) if page_nums else 0

        # 博达站群 pagination is REVERSE: default .htm shows newest;
        # page/N.htm (highest N) is the next newest batch; page/1.htm is
        # the oldest.  Walk from total_pages down for "crawl newest first".
        pages = range(total_pages, 0, -1)
        if max_pages > 0:
            pages = list(pages)[:max_pages]

        for page_num in pages:
            url = f"{site.base_url}/{page_name}/{page_num}.htm"
            resp = self._client.get(url)
            if resp.status_code != 200:
                continue
            new_count += self._ingest_htm_list_page(
                resp.text, cat_name, site, fetch_content
            )

        logger.info(
            "Finished CMS category crawl",
            extra={"site": site.name, "category": cat_name, "new_count": new_count},
        )
        return new_count

    def _ingest_htm_list_page(
        self,
        html: str,
        cat_name: str,
        site: SiteConfig,
        fetch_content: bool,
    ) -> int:
        """Parse one htm list page and ingest any new articles; return new count."""
        new_count = 0
        for art in self._parse_list_page(html, cat_name, site):
            key = f"{art.site}:{art.id}"
            if key in self._articles:
                continue
            if fetch_content:
                art.content = self._fetch_content(art.url)
                time.sleep(REQUEST_DELAY)
            self._articles[key] = art
            new_count += 1
        return new_count

    def _crawl_jsp_category(
        self,
        site: SiteConfig,
        wbtreeid: str,
        cat_name: str,
        fetch_content: bool,
        max_pages: int,
    ) -> int:
        """Crawl a single JSP-style category (xlist.jsp?wbtreeid=...)."""
        logger.info(
            "Crawling CMS JSP category",
            extra={"site": site.name, "category": cat_name, "wbtreeid": wbtreeid},
        )
        new_count = 0

        base_list_url = f"{site.base_url}/new2021/xlist.jsp"
        resp = self._client.get(
            base_list_url,
            params={"urltype": "tree.TreeTempUrl", "wbtreeid": wbtreeid},
        )
        if resp.status_code != 200:
            logger.warning(
                "Failed to fetch JSP list page",
                extra={
                    "site": site.name,
                    "category": cat_name,
                    "status_code": resp.status_code,
                },
            )
            return 0

        new_count += self._ingest_jsp_list_page(
            resp.text, cat_name, site, fetch_content
        )

        # Find total page count from "totalpage=N" or "1/N" pattern in html.
        total_pages = 0
        m = re.search(r"totalpage=(\d+)", resp.text)
        if m:
            total_pages = int(m.group(1))
        else:
            m = re.search(r"1/(\d+)", resp.text)
            if m:
                total_pages = int(m.group(1))

        # JSP paging: PAGENUM=1 is the page we already fetched.  Newer items
        # are on lower page numbers, so walk 2, 3, ... forwards.
        pages = range(2, total_pages + 1)
        if max_pages > 0:
            pages = list(pages)[: max(0, max_pages - 1)]

        for page_num in pages:
            resp = self._client.get(
                base_list_url,
                params={
                    "totalpage": str(total_pages),
                    "PAGENUM": str(page_num),
                    "urltype": "tree.TreeTempUrl",
                    "wbtreeid": wbtreeid,
                },
            )
            if resp.status_code != 200:
                continue
            new_count += self._ingest_jsp_list_page(
                resp.text, cat_name, site, fetch_content
            )

        logger.info(
            "Finished CMS JSP category crawl",
            extra={"site": site.name, "category": cat_name, "new_count": new_count},
        )
        return new_count

    def _ingest_jsp_list_page(
        self,
        html: str,
        cat_name: str,
        site: SiteConfig,
        fetch_content: bool,
    ) -> int:
        """Parse one JSP list page and ingest new articles."""
        new_count = 0
        for item in parse_list_page(html):
            # JSP items come back with (category_id=wbtreeid, article_id=wbnewsid)
            # from parse_style_jsp.  Namespace the DB key with ``jsp/`` so we
            # cannot collide with legacy ``info/{category_id}/{article_id}`` keys.
            art_id = f"jsp/{item.category_id}/{item.article_id}"
            key = f"{site.key}:{art_id}"
            if key in self._articles:
                continue
            art = Article(
                id=art_id,
                title=item.title,
                date=item.date,
                category=cat_name,
                url=(
                    f"{site.base_url}/new2021/xdetails.jsp"
                    f"?urltype=news.NewsContentUrl"
                    f"&wbtreeid={item.category_id}"
                    f"&wbnewsid={item.article_id}"
                ),
                site=site.key,
            )
            if fetch_content:
                art.content = self._fetch_content(art.url)
                time.sleep(REQUEST_DELAY)
            self._articles[key] = art
            new_count += 1
        return new_count

    def search(
        self, keyword: str, site_key: str | None = None, limit: int = 20
    ) -> list[Article]:
        """Search articles by keyword. Optionally filter by site.

        An empty keyword matches nothing (rather than everything — ``"" in s``
        is trivially True, which would dump the whole DB).
        """
        kw = keyword.strip().lower()
        if not kw:
            return []
        results = []
        for art in self._articles.values():
            if site_key and art.site != site_key:
                continue
            if kw in art.title.lower() or kw in art.content.lower():
                results.append(art)
        results.sort(key=lambda a: (a.date, a.id), reverse=True)
        return results[:limit]

    def list_recent(
        self, site_key: str | None = None, limit: int = 20
    ) -> list[Article]:
        """List recent articles. Optionally filter by site."""
        arts = [
            a for a in self._articles.values() if not site_key or a.site == site_key
        ]
        arts.sort(key=lambda a: (a.date, a.id), reverse=True)
        return arts[:limit]

    def stats(self) -> dict[str, int]:
        """Article counts per site."""
        counts: dict[str, int] = {}
        for art in self._articles.values():
            counts[art.site] = counts.get(art.site, 0) + 1
        return counts

    @property
    def total_articles(self) -> int:
        return len(self._articles)

    def close(self):
        # Only tear down the client we created ourselves; when one is
        # injected, the caller owns its lifetime.
        if self._owns_client:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
