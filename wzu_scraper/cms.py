"""Generic WZU CMS (博达站群) scraper with local full-text search.

Supports any WZU website built on the same CMS platform.
"""

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}

DB_DIR = Path(__file__).parent.parent / "data"


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
    categories: dict[str, str]  # path -> display name, e.g. {"jxxw": "教学新闻"}


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
            "xstd/tzgg": "通知公告",
            "xstd/txdt1": "团学动态",
            "xsjiang": "学术动态",
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
    """Generic scraper for WZU CMS websites."""

    def __init__(self):
        self._client = httpx.Client(
            headers=HEADERS,
            follow_redirects=True,
            timeout=15.0,
        )
        self._articles: dict[str, Article] = {}
        DB_DIR.mkdir(exist_ok=True)
        self._load_all_dbs()

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
                    self._articles[f"{art.site}:{art.id}"] = art
            except (json.JSONDecodeError, TypeError):
                pass

    def _save_db(self, site_key: str):
        site_articles = [asdict(a) for a in self._articles.values() if a.site == site_key]
        self._db_path(site_key).write_text(
            json.dumps(site_articles, ensure_ascii=False, indent=2)
        )

    def _parse_list_page(self, html: str, category_name: str, site: SiteConfig) -> list[Article]:
        """Extract articles from a list page.

        Supports two CMS layouts:
        - JWC style: <span class="w"><a>TITLE</a></span><span class="time">DATE</span>
        - SLXY style: <a title="TITLE">TEXT</a><samp>DATE</samp>
        """
        articles = []
        # Try JWC style first
        items = re.findall(
            r'<li[^>]*>\s*<span[^>]*class="w"[^>]*>\s*<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*>(.*?)</a>\s*</span>\s*<span[^>]*class="time"[^>]*>(.*?)</span>',
            html,
            re.DOTALL,
        )
        if not items:
            # Style B (SLXY): <a title="TITLE">...</a><samp>DATE</samp>
            items = re.findall(
                r'<li[^>]*>\s*<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*title="([^"]*)"[^>]*>.*?</a>\s*<samp>(.*?)</samp>',
                html,
                re.DOTALL,
            )
        if not items:
            # Style C (SHXY): <a title="TITLE">...<i>DD</i>/ YYYY-MM...</a>
            raw = re.findall(
                r'<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*title="([^"]*)"[^>]*>.*?<i>(\d+)</i>/\s*(\d{4}-\d{2})',
                html,
                re.DOTALL,
            )
            items = [(c, a, t, f"{ym}-{d.zfill(2)}") for c, a, t, d, ym in raw]
        if not items:
            # Style D (AI/CACE): <a>TITLE</a><span class="time">DATE</span>
            items = re.findall(
                r'<li[^>]*>\s*<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*>([^<]+)</a>\s*<span[^>]*class="time"[^>]*>(.*?)</span>',
                html,
                re.DOTALL,
            )
        if not items:
            # Style E (CHEM): <a><b>TITLE</b><span>DATE</span></a>
            items = re.findall(
                r'<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*>\s*<b[^>]*>(.*?)</b>\s*<span[^>]*>([\d-]+)</span>',
                html,
                re.DOTALL,
            )
        if not items:
            # Style F (JDXY): <a><div class="main_list_time">DATE</div><div class="main_list_tit">TITLE</div></a>
            raw = re.findall(
                r'<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*>\s*<div[^>]*class="main_list_time"[^>]*>\s*([\d-]+)\s*</div>\s*<div[^>]*class="main_list_tit"[^>]*>\s*(.*?)\s*</div>',
                html,
                re.DOTALL,
            )
            items = [(c, a, t.strip(), d.strip()) for c, a, d, t in raw]
        if not items:
            # Style G (CACE): <a href="info/..."><div><p>TITLE</p><h4>DATE</h4></div></a>
            raw = re.findall(
                r'<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*>\s*<div[^>]*>(?:<div[^>]*></div>)?\s*<p>(.*?)</p>\s*<h4>([\d-]+)</h4>',
                html,
                re.DOTALL,
            )
            items = [(c, a, t.strip(), d.strip()) for c, a, t, d in raw]
        for cat_id, art_id, title, date_str in items:
            title = re.sub(r"<[^>]+>", "", title).strip()
            date_match = re.search(r"(\d{4})\D+(\d{2})\D+(\d{2})", date_str)
            date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}" if date_match else date_str.strip()
            articles.append(Article(
                id=f"{cat_id}/{art_id}",
                title=title,
                date=date,
                category=category_name,
                url=f"{site.base_url}/info/{cat_id}/{art_id}.htm",
                site=site.key,
            ))
        return articles

    def _fetch_content(self, url: str) -> str:
        resp = self._client.get(url)
        if resp.status_code != 200:
            return ""
        match = re.search(r'class="v_news_content"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
        if not match:
            return ""
        content = re.sub(r"<[^>]+>", "", match.group(1))
        return re.sub(r"\s+", " ", content).strip()

    def crawl(self, site_key: str, category_path: str | None = None,
              fetch_content: bool = True, max_pages: int = 0) -> int:
        """Crawl articles from a site.

        Args:
            site_key: e.g. "jwc" or "slxy"
            category_path: Specific category path, or None for all
            fetch_content: Whether to fetch full article text
            max_pages: Max pages per category (0 = all)
        """
        site = SITES[site_key]
        cats = {category_path: site.categories[category_path]} if category_path else site.categories
        total_new = 0

        for path, cat_name in cats.items():
            print(f"[*] {site.name} - {cat_name}...")
            new_count = 0

            resp = self._client.get(f"{site.base_url}/{path}.htm")
            if resp.status_code != 200:
                print(f"[!] Failed: {resp.status_code}")
                continue

            articles = self._parse_list_page(resp.text, cat_name, site)

            # Find total pages
            page_name = path.split("/")[-1]
            page_nums = re.findall(rf'{page_name}/(\d+)\.htm', resp.text)
            total_pages = max(int(p) for p in page_nums) if page_nums else 0

            # Process current page
            for art in articles:
                key = f"{art.site}:{art.id}"
                if key not in self._articles:
                    if fetch_content:
                        art.content = self._fetch_content(art.url)
                        time.sleep(0.2)
                    self._articles[key] = art
                    new_count += 1

            # Crawl remaining pages
            pages = range(total_pages, 0, -1)
            if max_pages > 0:
                pages = list(pages)[:max_pages]

            for page_num in pages:
                url = f"{site.base_url}/{page_name}/{page_num}.htm"
                resp = self._client.get(url)
                if resp.status_code != 200:
                    continue

                page_articles = self._parse_list_page(resp.text, cat_name, site)
                for art in page_articles:
                    key = f"{art.site}:{art.id}"
                    if key not in self._articles:
                        if fetch_content:
                            art.content = self._fetch_content(art.url)
                            time.sleep(0.2)
                        self._articles[key] = art
                        new_count += 1

            total_new += new_count
            print(f"  +{new_count} new")

        self._save_db(site_key)
        return total_new

    def search(self, keyword: str, site_key: str | None = None, limit: int = 20) -> list[Article]:
        """Search articles by keyword. Optionally filter by site."""
        kw = keyword.lower()
        results = []
        for art in self._articles.values():
            if site_key and art.site != site_key:
                continue
            if kw in art.title.lower() or kw in art.content.lower():
                results.append(art)
        results.sort(key=lambda a: a.date, reverse=True)
        return results[:limit]

    def list_recent(self, site_key: str | None = None, limit: int = 20) -> list[Article]:
        """List recent articles. Optionally filter by site."""
        arts = [a for a in self._articles.values() if not site_key or a.site == site_key]
        arts.sort(key=lambda a: a.date, reverse=True)
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
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
