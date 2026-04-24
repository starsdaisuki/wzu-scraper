"""Parser helpers for the different WZU CMS list page templates."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedArticle:
    """A normalized article parsed from a CMS list page."""

    category_id: str
    article_id: str
    title: str
    date: str


def _normalize_title(title: str) -> str:
    # Strip inner tags, decode HTML entities (&amp; → &, &nbsp; → ' '),
    # collapse stray whitespace including the non-breaking space '\xa0'.
    stripped = re.sub(r"<[^>]+>", "", title)
    decoded = html.unescape(stripped)
    # Replace any remaining NBSPs and collapse runs of whitespace.
    return re.sub(r"\s+", " ", decoded.replace("\xa0", " ")).strip()


def _normalize_date(date_str: str) -> str:
    date_match = re.search(r"(\d{4})\D+(\d{2})\D+(\d{2})", date_str)
    if not date_match:
        return date_str.strip()
    return f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"


def _build_articles(matches: list[tuple[str, str, str, str]]) -> list[ParsedArticle]:
    return [
        ParsedArticle(
            category_id=category_id,
            article_id=article_id,
            title=_normalize_title(title),
            date=_normalize_date(date_str),
        )
        for category_id, article_id, title, date_str in matches
    ]


def parse_style_a(html: str) -> list[ParsedArticle]:
    matches = re.findall(
        r'<li[^>]*>\s*<span[^>]*class="w"[^>]*>\s*<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*>(.*?)</a>\s*</span>\s*<span[^>]*class="time"[^>]*>(.*?)</span>',
        html,
        re.DOTALL,
    )
    return _build_articles(matches)


def parse_style_b(html: str) -> list[ParsedArticle]:
    matches = re.findall(
        r'<li[^>]*>\s*<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*title="([^"]*)"[^>]*>.*?</a>\s*<samp>(.*?)</samp>',
        html,
        re.DOTALL,
    )
    return _build_articles(matches)


def parse_style_c(html: str) -> list[ParsedArticle]:
    raw = re.findall(
        r'<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*title="([^"]*)"[^>]*>.*?<i>(\d+)</i>/\s*(\d{4}-\d{2})',
        html,
        re.DOTALL,
    )
    matches = [(c, a, t, f"{ym}-{d.zfill(2)}") for c, a, t, d, ym in raw]
    return _build_articles(matches)


def parse_style_d(html: str) -> list[ParsedArticle]:
    matches = re.findall(
        r'<li[^>]*>\s*<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*>([^<]+)</a>\s*<span[^>]*class="time"[^>]*>(.*?)</span>',
        html,
        re.DOTALL,
    )
    return _build_articles(matches)


def parse_style_e(html: str) -> list[ParsedArticle]:
    matches = re.findall(
        r'<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*>\s*<b[^>]*>(.*?)</b>\s*<span[^>]*>([\d-]+)</span>',
        html,
        re.DOTALL,
    )
    return _build_articles(matches)


def parse_style_f(html: str) -> list[ParsedArticle]:
    raw = re.findall(
        r'<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*>\s*<div[^>]*class="main_list_time"[^>]*>\s*([\d-]+)\s*</div>\s*<div[^>]*class="main_list_tit"[^>]*>\s*(.*?)\s*</div>',
        html,
        re.DOTALL,
    )
    matches = [(c, a, t.strip(), d.strip()) for c, a, d, t in raw]
    return _build_articles(matches)


def parse_style_g(html: str) -> list[ParsedArticle]:
    raw = re.findall(
        r'<a[^>]*href="(?:\.\./)*info/(\d+)/(\d+)\.htm"[^>]*>\s*<div[^>]*>(?:<div[^>]*></div>)?\s*<p>(.*?)</p>\s*<h4>([\d-]+)</h4>',
        html,
        re.DOTALL,
    )
    matches = [(c, a, t.strip(), d.strip()) for c, a, t, d in raw]
    return _build_articles(matches)


def parse_style_jsp(html: str) -> list[ParsedArticle]:
    """Parse 联奕 JSP-style news list (xlist.jsp output).

    Pattern::

        <li ...><span class="w"><a href="xdetails.jsp?urltype=news.NewsContentUrl
              &wbtreeid=<CAT>&wbnewsid=<ART>">TITLE</a></span>
          <span class="time">YYYY年MM月DD日</span></li>
    """
    matches = re.findall(
        r'<li[^>]*>\s*<span[^>]*class="w"[^>]*>\s*<a[^>]*href="[^"]*xdetails\.jsp\?'
        r"urltype=news\.NewsContentUrl&(?:amp;)?wbtreeid=(\d+)&(?:amp;)?wbnewsid=(\d+)[^\"]*"
        r'"[^>]*>(.*?)</a>\s*</span>\s*<span[^>]*class="time"[^>]*>(.*?)</span>',
        html,
        re.DOTALL,
    )
    return _build_articles(matches)


STYLE_PARSERS = [
    parse_style_a,
    parse_style_b,
    parse_style_c,
    parse_style_d,
    parse_style_e,
    parse_style_f,
    parse_style_g,
    parse_style_jsp,
]


def parse_list_page(html: str) -> list[ParsedArticle]:
    """Parse a CMS list page using the first matching style parser."""
    for parser in STYLE_PARSERS:
        articles = parser(html)
        if articles:
            return articles
    return []


def extract_article_content(html_text: str) -> str:
    """Extract and normalize the article content body.

    Works for both the traditional htm articles (``class="v_news_content"``)
    and 联奕 JSP articles (``class='v_news_content'`` with single quotes).
    HTML entities (``&nbsp;``, ``&amp;``, ``&quot;`` …) get decoded and any
    stray non-breaking spaces collapsed so the text is readable as-is.
    """
    match = re.search(
        r"class=(['\"])v_news_content\1[^>]*>(.*?)</div>",
        html_text,
        re.DOTALL,
    )
    if not match:
        return ""
    stripped = re.sub(r"<[^>]+>", "", match.group(2))
    decoded = html.unescape(stripped).replace("\xa0", " ")
    return re.sub(r"\s+", " ", decoded).strip()
