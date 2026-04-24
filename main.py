"""WZU Scraper - 温州大学教务系统爬虫"""

import getpass
import json
import os
import re
import shutil
import sys
import textwrap
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from wzu_scraper.client import WZUClient
from wzu_scraper.cms import CMSScraper, SITES
from wzu_scraper.exporters import default_export_path, export_records
from wzu_scraper.notifier import build_notifier
from wzu_scraper.tui import run_tui
from wzu_scraper.webvpn import WebVPNClient

# Load .env file if present
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _prompt_text(prompt: str, default: str | None = None) -> str:
    """Prompt for text with an optional default."""
    raw = input(prompt).strip()
    if raw:
        return raw
    return default or ""


def _prompt_choice(
    prompt: str,
    valid_choices: set[str],
    *,
    default: str | None = None,
    allow_blank: bool = False,
    invalid_message: str = "Invalid choice, try again.",
) -> str:
    """Prompt until the user enters a valid choice."""
    while True:
        value = input(prompt).strip().lower()
        if not value:
            if allow_blank:
                return ""
            if default is not None:
                return default
        elif value in valid_choices:
            return value
        print(invalid_message)


def _prompt_int(
    prompt: str,
    *,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Prompt for an integer with range validation."""
    while True:
        raw = input(prompt).strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print(
                f"Invalid number, using digits only. Press Enter for default {default}."
            )
            continue
        if minimum is not None and value < minimum:
            print(f"Value must be >= {minimum}.")
            continue
        if maximum is not None and value > maximum:
            print(f"Value must be <= {maximum}.")
            continue
        return value


def _prompt_float(
    prompt: str,
    *,
    default: float,
    minimum: float | None = None,
) -> float:
    """Prompt for a float with simple lower-bound validation."""
    while True:
        raw = input(prompt).strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            print(f"Invalid number, press Enter for default {default}.")
            continue
        if minimum is not None and value < minimum:
            print(f"Value must be >= {minimum}.")
            continue
        return value


def _prompt_yes_no(prompt: str, *, default: bool) -> bool:
    """Prompt for y/n and keep asking until the answer is clear."""
    default_hint = "y" if default else "n"
    while True:
        raw = input(prompt).strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print(f"Please enter y or n. Press Enter for default {default_hint}.")


def _normalize_school_year_input(raw: str) -> str | None:
    """Accept YYYY or YYYY-YYYY and normalize to academic-year format."""
    value = raw.strip()
    if not value:
        return None
    if re.fullmatch(r"\d{4}", value):
        start_year = int(value)
        return f"{start_year}-{start_year + 1}"
    if re.fullmatch(r"\d{4}-\d{4}", value):
        start_raw, end_raw = value.split("-", 1)
        start_year = int(start_raw)
        end_year = int(end_raw)
        if end_year - start_year == 1:
            return value
    return None


def _prompt_school_year(prompt: str, *, default: str | None = None) -> str:
    """Prompt for school year and allow shorthand like 2025 -> 2025-2026."""
    while True:
        raw = input(prompt).strip()
        if not raw:
            return default or ""
        normalized = _normalize_school_year_input(raw)
        if normalized:
            return normalized
        print("Invalid school year. Use YYYY or YYYY-YYYY, e.g. 2025 or 2025-2026.")


def _prompt_semester(
    prompt: str, *, default: str | None = None, allow_blank: bool = False
) -> str:
    """Prompt for semester code 1/2."""
    while True:
        raw = input(prompt).strip()
        if not raw:
            if allow_blank:
                return ""
            return default or ""
        if raw in {"1", "2"}:
            return raw
        print("Invalid semester. Enter 1 or 2.")


def _prompt_index(items, prompt: str) -> int | None:
    """Prompt for a 1-based list index; Enter cancels."""
    while True:
        raw = input(prompt).strip()
        if not raw:
            return None
        try:
            index = int(raw) - 1
        except ValueError:
            print("Invalid number, try again.")
            continue
        if 0 <= index < len(items):
            return index
        print(f"Please enter a number between 1 and {len(items)}.")


def _prompt_multi_indexes(items, prompt: str):
    """Prompt for one or more comma-separated list indexes; Enter cancels."""
    while True:
        raw = input(prompt).strip()
        if not raw:
            return []
        selected = _parse_index_selection(items, raw)
        if selected:
            return selected
        print("Invalid selection. Use numbers like 1 or 1,3,5.")


def _current_school_year_and_semester(today: date | None = None) -> tuple[str, str]:
    """Guess current academic year + semester from the calendar date.

    Fall (秋, sem=1): Sept~Jan -> academic year starts in Sept of current year
                     (Jan-Feb is still fall of previous academic year)
    Spring (春, sem=2): Feb~Aug -> academic year started previous Sept
    """
    today = today or date.today()
    if today.month >= 9:
        start_year = today.year
        semester = "1"
    elif today.month <= 1:
        start_year = today.year - 1
        semester = "1"
    else:
        start_year = today.year - 1
        semester = "2"
    return f"{start_year}-{start_year + 1}", semester


def _compute_gpa_stats(grades: list[dict]) -> dict:
    """Weighted GPA stats.

    正方 leaves ``gpa_point`` blank for Pass/Fail style courses (P/合格/不合格).
    Those MUST be excluded from both the numerator and the denominator of the
    weighted average, otherwise a P-course silently pulls GPA down.

    Categories:
    - ``gpa_rated``: row has a numeric gpa_point AND credit > 0. Goes into GPA.
    - ``passed_non_gpa``: row with blank gpa_point but grade text that looks
      like a pass (合格 / P / passed) — counts toward earned credit only.
    - ``failed``: numeric gpa_point == 0 OR grade text 不合格/F — explicit fail.
    - ``unscored``: all other rows (blank grade, 缓考, 补考 pending) — ignored.
    """
    weighted = 0.0
    gpa_credit = 0.0  # denominator for GPA average
    earned_credit = 0.0
    total_credit = 0.0
    gpa_rated = 0
    passed_non_gpa = 0
    failed = 0
    unscored = 0

    for g in grades:
        try:
            credit = float(g.get("credit") or 0)
        except (TypeError, ValueError):
            credit = 0.0
        if credit <= 0:
            unscored += 1
            continue

        raw_gpa = (g.get("gpa_point") or "").strip()
        grade_text = (g.get("grade") or "").strip()
        total_credit += credit

        # 1) Numeric GPA row.
        if raw_gpa:
            try:
                gpa = float(raw_gpa)
            except ValueError:
                gpa = None
            if gpa is not None:
                weighted += gpa * credit
                gpa_credit += credit
                gpa_rated += 1
                if gpa > 0:
                    earned_credit += credit
                else:
                    failed += 1
                continue

        # 2) Non-numeric grade: treat as pass/fail by the text.
        lowered = grade_text.lower()
        if grade_text in {"合格", "通过"} or lowered in {"p", "pass", "passed"}:
            passed_non_gpa += 1
            earned_credit += credit
        elif grade_text in {"不合格", "未通过"} or lowered in {"f", "fail", "failed"}:
            failed += 1
        else:
            unscored += 1

    avg_gpa = weighted / gpa_credit if gpa_credit > 0 else 0.0
    return {
        "gpa": avg_gpa,
        "total_credit": total_credit,
        "earned_credit": earned_credit,
        "gpa_credit": gpa_credit,
        "courses": gpa_rated + passed_non_gpa + failed + unscored,
        "gpa_rated": gpa_rated,
        "passed_non_gpa": passed_non_gpa,
        "failed": failed,
        "unscored": unscored,
    }


def _print_student_info(info: dict | None) -> None:
    """Human-friendly student info display."""
    if not info:
        print("  (No student info)")
        return
    labels = {
        "name": "姓名",
        "role": "身份",
        "profile": "简介",
        "raw_length": "Raw page length",
        "url": "URL",
    }
    for key, label in labels.items():
        if key in info and info[key]:
            print(f"  {label:<6}: {info[key]}")
    # Print any other keys we didn't label explicitly.
    for key, value in info.items():
        if key not in labels and value:
            print(f"  {key:<6}: {value}")


def _term_width(default: int = 80) -> int:
    """Best-effort terminal width, with a safe fallback for non-tty runs."""
    try:
        return max(40, shutil.get_terminal_size((default, 24)).columns)
    except OSError:
        return default


def _show_article(art, scraper=None):
    """Display full article content.

    If ``art.content`` is empty and a ``scraper`` is provided, try to fetch
    the body on demand (and persist it).  This covers JSP articles (only
    accessible via WebVPN) and any article indexed with ``fetch_content=False``.
    """
    width = _term_width()
    site_label = SITES.get(art.site, art).name if art.site in SITES else art.site
    print()
    print("=" * width)
    print(f"  {art.title}")
    print(f"  {art.date}  |  {art.category}  |  {site_label}")
    # URLs can be ~100 chars; show compactly on its own line prefixed so copy
    # is easy but it doesn't wrap into the body.
    print(f"  URL: {art.url}")
    print("=" * width)

    if not art.content and scraper is not None:
        print("  [*] Fetching content...")
        scraper.fetch_and_cache_content(art)

    if art.content:
        # Wrap at roughly half the terminal width counted as characters, since
        # CJK chars render 2 columns each — width=min(60, term/2+10) is a
        # pleasant compromise without a fancy east-asian-width library.
        wrap_width = max(40, min(80, width // 2 + 8))
        for paragraph in art.content.split("\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                print()
                continue
            wrapped = textwrap.wrap(
                paragraph,
                width=wrap_width,
                break_long_words=True,
                break_on_hyphens=False,
            )
            for line in wrapped or [paragraph]:
                print(f"  {line}")
    else:
        print("  (Content unavailable — JSP articles need WebVPN to fetch.)")
    print()
    print("-" * width)


def _show_article_list(articles, label="", page_size=20, scraper=None):
    """Show numbered article list with pagination.

    Commands:
      <number>   view article (1-based, global index)
      n          next page
      p          previous page
      g <page>   jump to page
      <Enter>    exit
    """
    if not articles:
        print("No articles found.")
        return

    if label:
        print(f"\n{label}")

    total = len(articles)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = 0  # 0-based

    width = _term_width()
    # Reserve space for index + date + site tag (~28 chars); title gets the rest.
    title_budget = max(20, width - 30)

    def render_page():
        start = page * page_size
        end = min(start + page_size, total)
        print(
            f"\n  Page {page + 1}/{total_pages}  (showing {start + 1}-{end} of {total})\n"
        )
        for i in range(start, end):
            art = articles[i]
            site_tag = f"[{SITES[art.site].name}]" if art.site in SITES else ""
            # Truncate long titles to keep list aligned on narrow terminals.
            title = art.title
            if len(title) > title_budget:
                title = title[: title_budget - 1].rstrip() + "…"
            cat = f"·{art.category}" if art.category else ""
            print(f"  {i + 1:>3}. [{art.date}] {site_tag}{cat} {title}")
        print("\n  <#>=read  n=next  p=prev  g<#>=goto page  <Enter>=back")

    render_page()
    while True:
        sel = input("  > ").strip().lower()
        if not sel:
            break
        if sel == "n":
            if page + 1 < total_pages:
                page += 1
                render_page()
            else:
                print("  Already on last page")
            continue
        if sel == "p":
            if page > 0:
                page -= 1
                render_page()
            else:
                print("  Already on first page")
            continue
        if sel.startswith("g"):
            arg = sel[1:].strip()
            try:
                target = int(arg) - 1
            except ValueError:
                print("  Usage: g <page number>")
                continue
            if 0 <= target < total_pages:
                page = target
                render_page()
            else:
                print(f"  Page must be 1-{total_pages}")
            continue
        try:
            idx = int(sel) - 1
            if 0 <= idx < total:
                _show_article(articles[idx], scraper=scraper)
                # Re-render the list so the user sees the current page again,
                # not just a lone prompt after the article body.
                render_page()
            else:
                print(f"  Invalid number (1-{total})")
        except ValueError:
            print("  Invalid input")


def _prompt_site_filter(scraper: CMSScraper, label: str) -> str | None:
    """Let the user pick a site to filter on, or all sites.

    Returns site_key string, or None for all sites.
    """
    site_keys = list(SITES.keys())
    print(f"\n{label}:")
    print("  0. All sites (全部)")
    for i, key in enumerate(site_keys, 1):
        count = scraper.stats().get(key, 0)
        print(f"  {i}. {SITES[key].name} ({count} articles)")
    valid = {"0"} | {str(i) for i in range(1, len(site_keys) + 1)}
    choice = _prompt_choice("Choice [0=all]: ", valid, default="0")
    if choice == "0":
        return None
    return site_keys[int(choice) - 1]


def cms_menu(scraper: CMSScraper):
    """CMS sites (教务处/数理学院) sub-menu."""
    stats = scraper.stats()
    total = scraper.total_articles
    detail = ", ".join(f"{SITES[k].name}:{v}" for k, v in stats.items() if k in SITES)
    print(f"[*] Database: {total} articles ({detail})")

    while True:
        print("\n--- WZU Websites ---")
        print("1. Search all sites (全站搜索)")
        print("2. Recent articles (最新文章)")
        print("3. Crawl specific site")
        print("4. Crawl all sites")
        print("0. Back")

        choice = _prompt_choice(
            "\nChoice: ",
            {"0", "1", "2", "3", "4"},
        )

        if choice == "1":
            keyword = _prompt_text("Keyword: ")
            if not keyword:
                continue
            site_key = _prompt_site_filter(scraper, "Filter by site")
            page_size = _prompt_int(
                "Page size [20]: ", default=20, minimum=1, maximum=200
            )
            # Pull a large limit so pagination has everything to work with.
            results = scraper.search(keyword, site_key=site_key, limit=10_000)
            scope = SITES[site_key].name if site_key else "all sites"
            _show_article_list(
                results,
                f"Found {len(results)} results for '{keyword}' in {scope}:",
                page_size=page_size,
                scraper=scraper,
            )

        elif choice == "2":
            site_key = _prompt_site_filter(scraper, "Which site")
            page_size = _prompt_int(
                "Page size [20]: ", default=20, minimum=1, maximum=200
            )
            articles = scraper.list_recent(site_key=site_key, limit=10_000)
            scope = SITES[site_key].name if site_key else "all sites"
            _show_article_list(
                articles,
                f"Recent articles ({scope}):",
                page_size=page_size,
                scraper=scraper,
            )

        elif choice == "3":
            print("Sites:")
            site_keys = list(SITES.keys())
            for i, key in enumerate(site_keys, 1):
                count = scraper.stats().get(key, 0)
                print(f"  {i}. {SITES[key].name} ({count} articles)")
            idx = _prompt_index(site_keys, "Which? [Enter cancel]: ")
            if idx is None:
                continue
            site_key = site_keys[idx]
            max_pages = _prompt_int(
                "Max pages per category [5]: ", default=5, minimum=1
            )
            new = scraper.crawl(site_key, max_pages=max_pages)
            print(f"[+] Done! {new} new, {scraper.total_articles} total")

        elif choice == "4":
            max_pages = _prompt_int(
                "Max pages per category [5]: ", default=5, minimum=1
            )
            total_sites = len(SITES)
            print(f"[*] Crawling {total_sites} sites (max {max_pages} pages each)...")
            total_new = 0
            try:
                for i, site_key in enumerate(SITES, 1):
                    print(
                        f"  [{i}/{total_sites}] {SITES[site_key].name}...",
                        end=" ",
                        flush=True,
                    )
                    added = scraper.crawl(site_key, max_pages=max_pages)
                    total_new += added
                    print(f"+{added}")
            except KeyboardInterrupt:
                print("\n[!] Interrupted. Partial results kept.")
            print(f"[+] Done! {total_new} new, {scraper.total_articles} total")

        elif choice == "0":
            break


def xk_menu(client: WZUClient):
    """Course selection (选课/抢课) sub-menu."""
    print("\n[*] Loading course selection config...")
    config = client.get_xk_config()
    if not config:
        print("[!] Failed to load selection config")
        return

    if not config.is_valid:
        print(f"[!] Selection config unavailable: {config.message or 'invalid config'}")
        print("    Try refresh later when selection opens.")
    elif config.is_open:
        print(f"[+] Selection is OPEN (xkkz_id={config.xkkz_id})")
    else:
        print("[!] Selection is NOT open (当前不属于选课阶段)")
        print("    Search/select will be blocked until selection opens.")

    # Cache for searched courses
    cached_courses: list = []
    cached_selected: list = []

    while True:
        print("\n--- Course Selection (选课) ---")
        print("1. Search courses (搜索课程)")
        print("2. Selected courses (我的已选课程)")
        print("3. Select a course (选课)")
        print("4. GRAB mode - auto retry (抢课模式)")
        print("5. Cancel a selected course (退课)")
        print("6. Refresh config (刷新状态)")
        print("0. Back")

        choice = _prompt_choice(
            "\nChoice: ",
            {"0", "1", "2", "3", "4", "5", "6"},
        )

        if choice == "1":
            if not config.is_valid:
                print(f"[!] {config.message or 'Selection config is invalid'}")
                continue
            if not config.is_open:
                print("[!] Selection is not open, query may return nothing")
            keyword = _prompt_text("Keyword (课程名/课程号/教师): ")
            courses = client.query_courses(config, keyword)
            if not courses:
                print("No courses found (selection may not be open)")
                continue

            cached_courses = courses
            print(f"\n  Found {len(courses)} teaching classes:\n")
            _print_course_list(courses)

        elif choice == "2":
            cached_selected = client.get_selected_courses()
            if not cached_selected:
                print("No selected courses found")
                continue
            print(f"\n  Selected {len(cached_selected)} teaching classes:\n")
            _print_selected_course_list(cached_selected)
            _maybe_export_records(
                "selected_courses",
                [_selected_course_to_dict(tc) for tc in cached_selected],
            )

        elif choice == "3":
            if not config.is_valid:
                print(f"[!] {config.message or 'Selection config is invalid'}")
                continue
            if not config.is_open:
                print("[!] Selection is not open, cannot select courses")
                continue
            if not cached_courses:
                print("Search for courses first (option 1)")
                continue
            _print_course_list(cached_courses)
            idx = _prompt_index(
                cached_courses, "\nWhich class to select? (#, Enter cancel): "
            )
            if idx is None:
                continue
            tc = cached_courses[idx]
            print(f"[*] Selecting: {tc.kcmc} - {tc.jxbmc} ({tc.xm})")
            ok, msg = client.select_course(config, tc)
            print(f"[{'+' if ok else '!'}] {msg}")

        elif choice == "4":
            if not config.is_valid:
                print(f"[!] {config.message or 'Selection config is invalid'}")
                continue
            if not config.is_open:
                print("[!] Selection is not open, cannot grab courses")
                continue
            if not cached_courses:
                print("Search for courses first (option 1)")
                continue
            _print_course_list(cached_courses)
            idx = _prompt_index(
                cached_courses, "\nWhich class to grab? (#, Enter cancel): "
            )
            if idx is None:
                continue
            tc = cached_courses[idx]

            max_attempts = _prompt_int("Max attempts [50]: ", default=50, minimum=1)
            interval = _prompt_float(
                "Interval seconds [0.3]: ", default=0.3, minimum=0.0
            )
            jitter = _prompt_float(
                "Random jitter seconds [0.1]: ", default=0.1, minimum=0.0
            )
            while True:
                start_str = _prompt_text("Start at HH:MM[:SS] [now]: ")
                start_at = _parse_start_time_input(start_str)
                if not start_str or start_at is not None:
                    break
                print(
                    "Invalid time format. Use HH:MM or HH:MM:SS, or press Enter for now."
                )

            print(f"\n[*] GRAB MODE: {tc.kcmc} - {tc.jxbmc}")
            print(
                f"    Max attempts: {max_attempts}, interval: {interval}s, jitter: {jitter}s"
            )
            if start_at is not None:
                print(
                    "    Scheduled start:"
                    f" {datetime.fromtimestamp(start_at).strftime('%Y-%m-%d %H:%M:%S')}"
                )
            print("    Press Ctrl+C to stop\n")

            def on_attempt(n, ok, msg):
                status = "OK" if ok else "FAIL"
                print(f"  [{n:>3}/{max_attempts}] {status}: {msg}")

            try:
                ok, msg, used = client.grab_course(
                    config,
                    tc,
                    max_attempts,
                    interval,
                    on_attempt,
                    jitter,
                    start_at,
                )
                if ok:
                    print(f"\n[+] SUCCESS after {used} attempts: {msg}")
                else:
                    print(f"\n[!] FAILED after {used} attempts: {msg}")
            except KeyboardInterrupt:
                print("\n[*] Stopped by user")

        elif choice == "5":
            if not config.is_valid:
                print(f"[!] {config.message or 'Selection config is invalid'}")
                continue
            if not config.is_open:
                print("[!] Selection is not open, cannot cancel courses")
                continue
            cached_selected = client.get_selected_courses()
            if not cached_selected:
                print("No selected courses found")
                continue
            _print_selected_course_list(cached_selected)
            idx = _prompt_index(
                cached_selected,
                "\nWhich selected class to cancel? (#, Enter cancel): ",
            )
            if idx is None:
                continue
            tc = cached_selected[idx]
            print(f"[*] Canceling: {tc.course_name} - {tc.class_name}")
            ok, msg = client.cancel_course(config, tc)
            print(f"[{'+' if ok else '!'}] {msg}")

        elif choice == "6":
            new_config = client.get_xk_config()
            if new_config:
                config = new_config
                if not config.is_valid:
                    print(
                        f"[!] Selection config unavailable: {config.message or 'invalid config'}"
                    )
                elif config.is_open:
                    print(f"[+] Selection is OPEN (xkkz_id={config.xkkz_id})")
                else:
                    print("[!] Selection is NOT open")
            else:
                print("[!] Failed to refresh config")

        elif choice == "0":
            break


def _print_course_list(courses):
    """Print a numbered list of teaching classes."""
    for i, tc in enumerate(courses, 1):
        capacity = f"{tc.yxzrs}/{tc.jxbrl}"
        print(
            f"  {i:>3}. {tc.kcmc:<20} {tc.xf}分  "
            f"{tc.jxbmc:<12} {tc.xm:<8} "
            f"[{capacity:>7}] {tc.sksj or ''}"
        )


def _print_selected_course_list(courses):
    """Print a numbered list of selected teaching classes."""
    for i, tc in enumerate(courses, 1):
        teacher = tc.teacher or "-"
        credit = f"{tc.credit}分" if tc.credit else ""
        print(
            f"  {i:>3}. {tc.course_name:<20} {credit:<6} {tc.class_name:<18} {teacher}"
        )


def _selected_course_to_dict(tc) -> dict[str, str]:
    return {
        "course_name": tc.course_name,
        "class_name": tc.class_name,
        "teacher": tc.teacher,
        "credit": tc.credit,
        "jxb_id": tc.jxb_id,
        "do_jxb_id": tc.do_jxb_id,
        "kch_id": tc.kch_id,
        "jxbzls": tc.jxbzls,
        "xkkz_id": tc.xkkz_id,
    }


def _parse_index_selection(items, raw: str):
    selected = []
    seen = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        try:
            idx = int(part) - 1
        except ValueError:
            return []
        if idx < 0 or idx >= len(items) or idx in seen:
            continue
        seen.add(idx)
        selected.append(items[idx])
    return selected


def _append_monitor_log(
    path: Path | None,
    check_num: int,
    tc,
    *,
    status: str,
    available: int | None,
    detail: str = "",
) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "check": check_num,
        "status": status,
        "course": getattr(tc, "kcmc", ""),
        "class_name": getattr(tc, "jxbmc", ""),
        "teacher": getattr(tc, "xm", ""),
        "jxb_id": getattr(tc, "jxb_id", ""),
        "capacity": getattr(tc, "jxbrl", ""),
        "enrolled": getattr(tc, "yxzrs", ""),
        "available": available,
        "detail": detail,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _parse_start_time_input(value: str) -> float | None:
    """Parse HH:MM or HH:MM:SS into a local timestamp."""
    if not value:
        return None

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(value, fmt)
            now = datetime.now()
            target = now.replace(
                hour=parsed.hour,
                minute=parsed.minute,
                second=parsed.second,
                microsecond=0,
            )
            if target <= now:
                target += timedelta(days=1)
            return target.timestamp()
        except ValueError:
            continue
    return None


def _configure_monitor_notifier():
    """Prompt for optional vacancy notification backends."""
    bell = _prompt_yes_no("Bell notification? (y/n) [y]: ", default=True)
    desktop = _prompt_yes_no("Desktop notification? (y/n) [y]: ", default=True)
    wants_telegram = _prompt_yes_no(
        "Telegram notification? (y/n) [n]: ",
        default=False,
    )
    if wants_telegram and not (
        os.environ.get("WZU_TELEGRAM_BOT_TOKEN")
        and os.environ.get("WZU_TELEGRAM_CHAT_ID")
    ):
        print("[!] Telegram env vars missing, skipping Telegram notifier")
    notifier = build_notifier(
        bell=bell,
        desktop=desktop,
        telegram=wants_telegram,
    )
    return notifier


def _resolve_export_output_path(path_input: str, default_path: Path) -> Path:
    """Resolve an export target, treating existing directories as output folders."""
    if not path_input:
        return default_path

    candidate = Path(path_input).expanduser()
    if candidate.exists() and candidate.is_dir():
        return candidate / default_path.name

    return candidate


def _normalize_iso_date_input(raw: str) -> str | None:
    """Accept YYYY-M-D or YYYY-MM-DD and normalize to ISO format."""
    match = re.fullmatch(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*", raw)
    if not match:
        return None

    try:
        return date(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        ).isoformat()
    except ValueError:
        return None


def _maybe_export_records(kind: str, records: list[dict[str, str]]) -> None:
    """Offer a simple export prompt after displaying structured data."""
    if not records:
        return

    allowed_formats = ["csv", "json"]
    if kind in {"exams", "schedule"}:
        allowed_formats.append("ics")

    choice = _prompt_choice(
        f"Export {kind}? [{'/'.join(allowed_formats)}/Enter skip]: ",
        set(allowed_formats),
        allow_blank=True,
        invalid_message=f"Invalid format. Choose one of: {', '.join(allowed_formats)}.",
    )
    if not choice:
        return

    default_path = default_export_path(kind, choice)
    path_input = input(f"Output path [{default_path}]: ").strip()
    output_path = _resolve_export_output_path(path_input, default_path)
    # Protect against accidental overwrite when the user typed a concrete path.
    if output_path.exists() and path_input:
        if not _prompt_yes_no(
            f"{output_path} already exists. Overwrite? (y/n) [n]: ",
            default=False,
        ):
            print("[*] Export cancelled")
            return
    export_context = None
    if kind == "schedule" and choice == "ics":
        while True:
            week1_monday = _normalize_iso_date_input(
                input("Week 1 Monday date [YYYY-MM-DD]: ").strip()
            )
            if week1_monday:
                break
            print("Invalid date. Use YYYY-MM-DD, e.g. 2026-02-23.")
        summary_prefix = input("Schedule title prefix [课表]: ").strip() or "课表"
        category = input("Calendar category tag [课程]: ").strip() or "课程"
        calendar_color = input("Calendar color hex [skip]: ").strip()
        export_context = {
            "week1_monday": week1_monday,
            "summary_prefix": summary_prefix,
            "category": category,
            "calendar_name": "WZU Schedule",
            "calendar_color": calendar_color,
        }

    try:
        output_path = export_records(
            kind,
            records,
            choice,
            output_path,
            context=export_context,
        )
    except (OSError, ValueError) as exc:
        print(f"[!] Export failed: {exc}")
        return

    print(f"[+] Exported to {output_path}")


def monitor_menu(client: WZUClient):
    """Course vacancy monitor (课程余量监控) sub-menu."""
    print("\n[*] Loading course selection config...")
    config = client.get_xk_config()
    if not config:
        print("[!] Failed to load selection config")
        return

    if not config.is_valid:
        print(f"[!] {config.message or 'Selection config is invalid'}")
        print("    Monitor requires selection to be open.")
        return

    if not config.is_open:
        print("[!] Selection is not open, monitor won't work")
        return

    print("[+] Selection is open, ready to monitor")
    print("\nFirst, search for the course you want to monitor.")
    keyword = _prompt_text("Keyword (课程名/课程号/教师): ")
    courses = client.query_courses(config, keyword)
    if not courses:
        print("No courses found")
        return

    _print_course_list(courses)
    targets = _prompt_multi_indexes(
        courses, "\nWhich classes to monitor? (# or 1,3,5, Enter cancel): "
    )
    if not targets:
        print("Monitor cancelled")
        return

    interval = _prompt_float("Check interval seconds [10]: ", default=10.0, minimum=0.1)

    auto_grab = _prompt_yes_no("Auto-grab when available? (y/n) [n]: ", default=False)
    notifier = _configure_monitor_notifier()
    log_path = default_export_path("course-monitor", "jsonl")
    wants_log = _prompt_yes_no(
        f"Write monitor log? (y/n) [y], path [{log_path}]: ",
        default=True,
    )
    if not wants_log:
        log_path = None
    else:
        custom_log = _prompt_text("Log path override [Enter keep default]: ")
        if custom_log:
            log_path = _resolve_export_output_path(custom_log, log_path)
    grab_attempts = 1
    grab_interval = 0.3
    grab_jitter = 0.1
    if auto_grab:
        grab_attempts = _prompt_int(
            "Auto-grab attempts per vacancy [8]: ",
            default=8,
            minimum=1,
        )
        grab_interval = _prompt_float(
            "Auto-grab retry interval [0.3]: ",
            default=0.3,
            minimum=0.0,
        )
        grab_jitter = _prompt_float(
            "Auto-grab jitter seconds [0.1]: ",
            default=0.1,
            minimum=0.0,
        )

    print(f"\n[*] Monitoring {len(targets)} class(es):")
    for tc in targets:
        print(f"    - {tc.kcmc} - {tc.jxbmc} [{tc.yxzrs}/{tc.jxbrl}]")
    print(f"    Interval: {interval}s, Auto-grab: {'yes' if auto_grab else 'no'}")
    if notifier:
        print("    Notification backends: enabled")
    if log_path:
        print(f"    Log file: {log_path}")
    print("    Press Ctrl+C to stop\n")

    check_num = 0
    last_available: dict[str, int | None] = {tc.jxb_id: None for tc in targets}
    zero_to_open_only = _prompt_yes_no(
        "Notify only on 0 -> vacancy transitions? (y/n) [y]: ",
        default=True,
    )
    try:
        while True:
            time.sleep(interval)
            check_num += 1

            for tc in targets:
                updated = client.query_courses(config, tc.kcmc)
                match = next((c for c in updated if c.jxb_id == tc.jxb_id), None)

                if not match:
                    print(f"  [{check_num}] Could not find {tc.kcmc} - {tc.jxbmc}")
                    _append_monitor_log(
                        log_path,
                        check_num,
                        tc,
                        status="missing",
                        available=None,
                    )
                    continue

                enrolled = int(match.yxzrs) if match.yxzrs.isdigit() else 0
                capacity = int(match.jxbrl) if match.jxbrl.isdigit() else 0
                available = capacity - enrolled
                previous_available = last_available[match.jxb_id]
                _append_monitor_log(
                    log_path,
                    check_num,
                    match,
                    status="available" if available > 0 else "full",
                    available=available,
                )

                if available > 0:
                    message = (
                        f"{match.kcmc} {match.jxbmc} 现在 {match.yxzrs}/{match.jxbrl}"
                        f"，剩余 {available} 个名额"
                    )
                    print(f"  [{check_num}] *** VACANCY! *** {message}")
                    should_notify = previous_available != available and (
                        not zero_to_open_only
                        or previous_available in (None, 0)
                        or available > previous_available
                    )
                    if notifier and should_notify:
                        notifier.notify("WZU 课程有空位", message)
                    last_available[match.jxb_id] = available
                    if auto_grab:
                        print(f"  [{check_num}] Auto-grabbing...")
                        ok, msg, used = client.grab_course(
                            config,
                            match,
                            grab_attempts,
                            grab_interval,
                            jitter=grab_jitter,
                        )
                        _append_monitor_log(
                            log_path,
                            check_num,
                            match,
                            status="grab_success" if ok else "grab_failed",
                            available=available,
                            detail=msg,
                        )
                        if ok:
                            success_message = (
                                f"{match.kcmc} - {match.jxbmc} 抢课成功"
                                f"（{used} 次尝试）: {msg}"
                            )
                            print(f"  [{check_num}] SUCCESS: {success_message}")
                            if notifier:
                                notifier.notify("WZU 抢课成功", success_message)
                            return
                        print(f"  [{check_num}] Failed: {msg}, will keep trying")
                else:
                    last_available[match.jxb_id] = 0
                    print(
                        f"  [{check_num}] Full: {match.kcmc} {match.jxbmc} {match.yxzrs}/{match.jxbrl}",
                        end="\r",
                    )
    except KeyboardInterrupt:
        print(f"\n[*] Stopped after {check_num} checks")


def _make_webvpn_client(
    username: str | None, password: str | None
) -> WebVPNClient | None:
    """Try to produce an authenticated WebVPNClient, return None on failure.

    WebVPN is optional: it unlocks campus-only JSP categories (教务处 学生公告,
    jdxy 教师通知, etc.) but is NOT required for the core features.
    """
    vpn = WebVPNClient()
    if vpn.check_session():
        return vpn
    if not username or not password:
        vpn.close()
        return None
    if vpn.login(username, password):
        return vpn
    vpn.close()
    return None


def main():
    with WZUClient() as client:
        creds_username = os.environ.get("WZU_USERNAME")
        creds_password = os.environ.get("WZU_PASSWORD")

        # Check if existing session works
        if client.check_session():
            print("[+] Existing session is valid, skipping login")
        else:
            print("[*] Need to login")
            creds_username = creds_username or _prompt_text("Student ID (学号): ")
            creds_password = creds_password or getpass.getpass("Password (密码): ")
            if not client.login_cas(creds_username, creds_password):
                print("[!] Login failed, exiting")
                sys.exit(1)

        # Optional WebVPN — unlocks on-campus JSP categories for the CMS crawler.
        print("[*] Initializing WebVPN (for on-campus-only pages)...")
        vpn = _make_webvpn_client(creds_username, creds_password)
        if vpn is None:
            print(
                "[!] WebVPN unavailable, campus-only categories (教务处 学生公告 etc.)"
                " will be skipped"
            )
            scraper = CMSScraper()
        else:
            print("[+] WebVPN ready, campus-only categories enabled")
            scraper = CMSScraper(client=vpn)

        # Menu. Catch Ctrl+C once per iteration so a stray keystroke during a
        # submenu/prompt returns to the main menu instead of nuking the session.
        consecutive_interrupts = 0
        while True:
            try:
                exit_now = _run_main_menu_iter(client, scraper, vpn)
                if exit_now:
                    break
                consecutive_interrupts = 0
            except KeyboardInterrupt:
                consecutive_interrupts += 1
                if consecutive_interrupts >= 2:
                    print("\n[*] Ctrl+C twice, exiting")
                    scraper.close()
                    if vpn is not None:
                        vpn.save()
                        vpn.close()
                    break
                print(
                    "\n[*] Cancelled. Use menu option 0 to quit, or Ctrl+C again to force exit"
                )
            except EOFError:
                print("\n[*] EOF (Ctrl+D), exiting")
                scraper.close()
                if vpn is not None:
                    vpn.save()
                    vpn.close()
                break


def _run_main_menu_iter(client, scraper, vpn) -> bool:
    """One iteration of the main menu.  Returns True when user requested exit."""
    print("\n--- WZU Scraper ---")
    print("1. Course schedule (课程表)")
    print("2. Grades (成绩)")
    print("3. Exams (考试安排)")
    print("4. Student info (个人信息)")
    print("5. Website search (网站搜索)")
    print("6. Course selection (选课/抢课)")
    print("7. Course monitor (课程余量监控)")
    print("8. Session status")
    print("0. Exit")

    choice = _prompt_choice(
        "\nChoice: ",
        {"0", "1", "2", "3", "4", "5", "6", "7", "8"},
    )

    if choice == "1":
        cur_year, cur_sem = _current_school_year_and_semester()
        year = _prompt_school_year(
            f"School year (e.g. 2025-2026 or 2025) [{cur_year}]: ",
            default=cur_year,
        )
        sem = _prompt_semester(
            f"Semester (1=fall, 2=spring) [{cur_sem}]: ",
            default=cur_sem,
        )
        courses = client.get_course_schedule(year, sem)
        if courses:
            print(
                f"\n{'Course':<30} {'Teacher':<10} {'Location':<15} {'Day':<6} {'Period':<8} {'Weeks':<15}"
            )
            print("-" * 90)
            for c in courses:
                print(
                    f"{c['name']:<30} {c['teacher']:<10} {c['location']:<15} {c['weekday']:<6} {c['periods']:<8} {c['weeks']:<15}"
                )
        else:
            print("No courses found")
        _maybe_export_records("schedule", courses)

    elif choice == "2":
        year = _prompt_school_year(
            "School year (e.g. 2025-2026 or 2025, Enter=all): ",
            default="",
        )
        sem = _prompt_semester(
            "Semester (1=fall, 2=spring, Enter=all): ",
            allow_blank=True,
        )
        grades = client.get_grades(year, sem)
        if grades:
            print(
                f"\n{'Course':<35} {'Grade':<8} {'GPA':<6} {'Credit':<8} {'Category':<15}"
            )
            print("-" * 80)
            for g in grades:
                print(
                    f"{g['name']:<35} {g['grade']:<8} {g['gpa_point']:<6} {g['credit']:<8} {g['category']:<15}"
                )
            stats = _compute_gpa_stats(grades)
            print("-" * 80)
            # Summary line: GPA with weighted-credit denominator made explicit.
            parts = [
                f"{stats['courses']} courses",
                (
                    f"GPA {stats['gpa']:.3f} (weighted over {stats['gpa_credit']:.1f} credits)"
                    if stats["gpa_credit"] > 0
                    else "GPA N/A"
                ),
                f"Earned {stats['earned_credit']:.1f}/{stats['total_credit']:.1f} credits",
            ]
            if stats["passed_non_gpa"]:
                parts.append(f"Pass/合格: {stats['passed_non_gpa']}")
            if stats["failed"]:
                parts.append(f"Failed: {stats['failed']}")
            if stats["unscored"]:
                parts.append(f"Unscored/缓考: {stats['unscored']}")
            print("  Summary: " + "  |  ".join(parts))
        else:
            print("No grades found")
        _maybe_export_records("grades", grades)

    elif choice == "3":
        cur_year, cur_sem = _current_school_year_and_semester()
        year = _prompt_school_year(
            f"School year (e.g. 2025-2026 or 2025) [{cur_year}]: ",
            default=cur_year,
        )
        sem = _prompt_semester(
            f"Semester (1=fall, 2=spring) [{cur_sem}]: ",
            default=cur_sem,
        )
        exams = client.get_exams(year, sem)
        if exams:
            print(f"\n  Found {len(exams)} exams:\n")
            for i, e in enumerate(exams, 1):
                print(f"  {i}. {e['name']}")
                print(f"     Time:     {e['time']}")
                # Don't repeat campus name if it's already a prefix of the location.
                loc = e["location"] or ""
                campus = e["campus"] or ""
                if campus and campus not in loc:
                    loc = f"{loc} ({campus})"
                print(f"     Location: {loc}")
                print(f"     Seat:     {e['seat']}")
                print(f"     Teacher:  {e['teacher']}")
                print()
        else:
            print("No exams found for this semester")
        _maybe_export_records("exams", exams)

    elif choice == "4":
        info = client.get_student_info()
        _print_student_info(info)

    elif choice == "5":
        cms_menu(scraper)

    elif choice == "6":
        xk_menu(client)

    elif choice == "7":
        monitor_menu(client)

    elif choice == "8":
        valid = client.check_session()
        print(f"\n  JWXT session: {'valid' if valid else 'EXPIRED'}")
        if valid:
            info = client.get_student_info() or {}
            if info.get("name"):
                print(
                    f"  Logged in as: {info['name']}"
                    + (f" ({info.get('role')})" if info.get("role") else "")
                )
            if info.get("profile"):
                print(f"  {info['profile']}")
        if vpn is not None:
            print(f"  WebVPN session: {'valid' if vpn.check_session() else 'EXPIRED'}")
        else:
            print("  WebVPN session: not initialised")

    elif choice == "0":
        scraper.close()
        if vpn is not None:
            vpn.save()
            vpn.close()
        return True
    return False


def should_run_tui(argv: list[str]) -> bool:
    return any(arg in {"--tui", "-t"} for arg in argv[1:])


if __name__ == "__main__":
    if should_run_tui(sys.argv):
        run_tui()
    else:
        main()
