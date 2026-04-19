"""JWC (教务处) website scraper with local full-text search."""

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

JWC_BASE = "https://jwc.wzu.edu.cn"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}

# Article database file
DB_FILE = Path(__file__).parent.parent / "jwc_articles.json"

# All known list pages with pagination
CATEGORIES = {
    "jxxw": {"name": "教学新闻", "cat_id": "1188"},
    "xxfw/xlzxsj": {"name": "校历/作息时间", "cat_id": "1192"},
    "zcjd/zyyx": {"name": "政策解读-专业遴选", "cat_id": "1817"},
}


@dataclass
class Article:
    id: str  # e.g. "1188/38224"
    title: str
    date: str  # e.g. "2026-01-16"
    category: str  # e.g. "教学新闻"
    url: str
    content: str = ""


class JWCScraper:
    """Scraper for JWC (教务处) website with local search."""

    def __init__(self):
        self._client = httpx.Client(
            headers=HEADERS,
            follow_redirects=True,
            timeout=15.0,
        )
        self._articles: dict[str, Article] = {}
        self._load_db()

    def _load_db(self):
        """Load article database from disk."""
        if DB_FILE.exists():
            try:
                data = json.loads(DB_FILE.read_text())
                for item in data:
                    art = Article(**item)
                    self._articles[art.id] = art
            except (json.JSONDecodeError, TypeError):
                pass

    def _save_db(self):
        """Save article database to disk."""
        data = [asdict(a) for a in self._articles.values()]
        DB_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _parse_list_page(self, html: str, category_name: str) -> list[Article]:
        """Extract articles from a list page."""
        articles = []
        # Pattern: <li id="line_..."><span class="w"><a href="info/CAT/ID.htm">TITLE</a></span><span class="time">DATE</span></li>
        items = re.findall(
            r'<li[^>]*>\s*<span[^>]*class="w"[^>]*>\s*<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*>(.*?)</a>\s*</span>\s*<span[^>]*class="time"[^>]*>(.*?)</span>',
            html,
            re.DOTALL,
        )
        for cat_id, art_id, title, date_str in items:
            title = re.sub(r"<[^>]+>", "", title).strip()
            # Normalize date: "2026年01月16日" → "2026-01-16"
            date_match = re.search(r"(\d{4})\D+(\d{2})\D+(\d{2})", date_str)
            date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}" if date_match else date_str.strip()

            articles.append(Article(
                id=f"{cat_id}/{art_id}",
                title=title,
                date=date,
                category=category_name,
                url=f"{JWC_BASE}/info/{cat_id}/{art_id}.htm",
            ))
        return articles

    def _fetch_article_content(self, article: Article) -> str:
        """Fetch the full text content of an article."""
        resp = self._client.get(article.url)
        if resp.status_code != 200:
            return ""

        # Extract from v_news_content div
        match = re.search(
            r'class="v_news_content"[^>]*>(.*?)</div>',
            resp.text,
            re.DOTALL,
        )
        if not match:
            return ""

        # Clean HTML tags, normalize whitespace
        content = re.sub(r"<[^>]+>", "", match.group(1))
        content = re.sub(r"\s+", " ", content).strip()
        return content

    def crawl_category(self, category_key: str, fetch_content: bool = True, max_pages: int = 0) -> int:
        """Crawl all articles from a category.

        Args:
            category_key: Key from CATEGORIES dict
            fetch_content: Whether to fetch full article content
            max_pages: Max pages to crawl (0 = all)

        Returns:
            Number of new articles found
        """
        cat = CATEGORIES[category_key]
        cat_name = cat["name"]
        print(f"[*] Crawling {cat_name}...")

        new_count = 0

        # First page is at {category_key}.htm, subsequent at {category_key}/{N}.htm
        # We need to discover the total pages first
        resp = self._client.get(f"{JWC_BASE}/{category_key}.htm")
        if resp.status_code != 200:
            print(f"[!] Failed to fetch {category_key}.htm: {resp.status_code}")
            return 0

        articles = self._parse_list_page(resp.text, cat_name)
        print(f"  Page (current): {len(articles)} articles")

        # Find total pages from pagination links
        page_nums = re.findall(
            rf'{category_key.split("/")[-1]}/(\d+)\.htm', resp.text
        )
        if page_nums:
            total_pages = max(int(p) for p in page_nums)
        else:
            total_pages = 0

        # Process first page articles
        for art in articles:
            if art.id not in self._articles:
                if fetch_content:
                    art.content = self._fetch_article_content(art)
                    time.sleep(0.3)  # Be nice to the server
                self._articles[art.id] = art
                new_count += 1

        # Crawl remaining pages (from newest to oldest: total_pages down to 1)
        pages_to_crawl = range(total_pages, 0, -1)
        if max_pages > 0:
            pages_to_crawl = list(pages_to_crawl)[:max_pages]

        for page_num in pages_to_crawl:
            page_name = category_key.split("/")[-1]
            url = f"{JWC_BASE}/{page_name}/{page_num}.htm"
            resp = self._client.get(url)
            if resp.status_code != 200:
                continue

            articles = self._parse_list_page(resp.text, cat_name)
            page_new = 0
            for art in articles:
                if art.id not in self._articles:
                    if fetch_content:
                        art.content = self._fetch_article_content(art)
                        time.sleep(0.3)
                    self._articles[art.id] = art
                    new_count += 1
                    page_new += 1

            print(f"  Page {page_num}: {len(articles)} articles ({page_new} new)")

        self._save_db()
        print(f"[+] {cat_name}: {new_count} new articles (total: {len(self._articles)})")
        return new_count

    def crawl_all(self, fetch_content: bool = True) -> int:
        """Crawl all categories."""
        total_new = 0
        for key in CATEGORIES:
            total_new += self.crawl_category(key, fetch_content)
        return total_new

    def search(self, keyword: str, limit: int = 20) -> list[Article]:
        """Search articles by keyword in title and content."""
        keyword_lower = keyword.lower()
        results = []
        for art in self._articles.values():
            if keyword_lower in art.title.lower() or keyword_lower in art.content.lower():
                results.append(art)

        # Sort by date descending
        results.sort(key=lambda a: a.date, reverse=True)
        return results[:limit]

    def list_recent(self, limit: int = 20) -> list[Article]:
        """List recent articles across all categories."""
        articles = sorted(self._articles.values(), key=lambda a: a.date, reverse=True)
        return articles[:limit]

    @property
    def total_articles(self) -> int:
        return len(self._articles)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
