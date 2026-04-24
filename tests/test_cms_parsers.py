from __future__ import annotations

from wzu_scraper.cms_parsers import (
    extract_article_content,
    parse_list_page,
    parse_style_a,
    parse_style_b,
    parse_style_c,
    parse_style_d,
    parse_style_e,
    parse_style_f,
    parse_style_g,
    parse_style_jsp,
)

from .conftest import read_fixture


def test_parse_style_a() -> None:
    articles = parse_style_a(read_fixture("cms", "style_a.html"))
    assert articles[0].title == "教学新闻示例"
    assert articles[0].date == "2026-04-17"


def test_parse_style_b() -> None:
    articles = parse_style_b(read_fixture("cms", "style_b.html"))
    assert articles[0].title == "学生公告示例"
    assert articles[0].date == "2026-04-18"


def test_parse_style_c() -> None:
    articles = parse_style_c(read_fixture("cms", "style_c.html"))
    assert articles[0].title == "团学活动示例"
    assert articles[0].date == "2026-04-09"


def test_parse_style_d() -> None:
    articles = parse_style_d(read_fixture("cms", "style_d.html"))
    assert articles[0].title == "学院动态示例"
    assert articles[0].date == "2026-04-16"


def test_parse_style_e() -> None:
    articles = parse_style_e(read_fixture("cms", "style_e.html"))
    assert articles[0].title == "教师公告示例"
    assert articles[0].date == "2026-04-15"


def test_parse_style_f() -> None:
    articles = parse_style_f(read_fixture("cms", "style_f.html"))
    assert articles[0].title == "新闻快递示例"
    assert articles[0].date == "2026-04-14"


def test_parse_style_g() -> None:
    articles = parse_style_g(read_fixture("cms", "style_g.html"))
    assert articles[0].title == "媒体聚焦示例"
    assert articles[0].date == "2026-04-13"


def test_parse_style_jsp() -> None:
    """JSP list (xlist.jsp) parses wbtreeid/wbnewsid + 中文 date format."""
    articles = parse_style_jsp(read_fixture("cms", "style_jsp.html"))
    assert len(articles) == 2
    assert articles[0].category_id == "1276"
    assert articles[0].article_id == "39834"
    assert articles[0].title == "学生公告示例(JSP)"
    assert articles[0].date == "2026-04-24"
    # HTML entities (&amp;) in the URL must still match.
    assert articles[1].article_id == "39794"


def test_parse_list_page_routes_to_jsp_style() -> None:
    """The generic dispatcher must pick the JSP parser for JSP-style lists."""
    articles = parse_list_page(read_fixture("cms", "style_jsp.html"))
    assert len(articles) == 2
    assert articles[0].category_id == "1276"


def test_extract_article_content() -> None:
    content = extract_article_content(read_fixture("cms", "article_content.html"))
    assert content == "第一段内容。 第二段内容。"
