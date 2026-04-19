"""WZU Scraper - 温州大学教务系统爬虫"""

import getpass
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from wzu_scraper.client import WZUClient
from wzu_scraper.cms import CMSScraper, SITES
from wzu_scraper.exporters import default_export_path, export_records
from wzu_scraper.notifier import build_notifier
from wzu_scraper.tui import run_tui

# Load .env file if present
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _show_article(art):
    """Display full article content."""
    print(f"\n{'=' * 60}")
    print(f"  {art.title}")
    print(
        f"  {art.date}  |  {art.category}  |  {SITES.get(art.site, art).name if art.site in SITES else art.site}"
    )
    print(f"  {art.url}")
    print(f"{'=' * 60}")
    if art.content:
        words = art.content
        while words:
            print(f"  {words[:70]}")
            words = words[70:]
    else:
        print("  (No content cached. Run crawl to fetch content.)")
    print()


def _show_article_list(articles, label=""):
    """Show numbered article list, allow selecting one to read."""
    if not articles:
        print("No articles found.")
        return

    if label:
        print(f"\n{label}\n")

    for i, art in enumerate(articles, 1):
        site_tag = f"[{SITES[art.site].name}]" if art.site in SITES else ""
        print(f"  {i:>3}. [{art.date}] {site_tag} {art.title}")

    print("\n  Enter number to read, or press Enter to go back")
    while True:
        sel = input("  > ").strip()
        if not sel:
            break
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(articles):
                _show_article(articles[idx])
            else:
                print("  Invalid number")
        except ValueError:
            break


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

        choice = input("\nChoice: ").strip()

        if choice == "1":
            keyword = input("Keyword: ").strip()
            if not keyword:
                continue
            results = scraper.search(keyword)
            _show_article_list(
                results, f"Found {len(results)} results for '{keyword}':"
            )

        elif choice == "2":
            articles = scraper.list_recent(limit=20)
            _show_article_list(articles, "Recent articles:")

        elif choice == "3":
            print("Sites:")
            site_keys = list(SITES.keys())
            for i, key in enumerate(site_keys, 1):
                count = scraper.stats().get(key, 0)
                print(f"  {i}. {SITES[key].name} ({count} articles)")
            idx = input("Which? ").strip()
            try:
                site_key = site_keys[int(idx) - 1]
                mp = input("Max pages per category [5]: ").strip()
                max_pages = int(mp) if mp else 5
                new = scraper.crawl(site_key, max_pages=max_pages)
                print(f"[+] Done! {new} new, {scraper.total_articles} total")
            except (ValueError, IndexError):
                print("Invalid choice")

        elif choice == "4":
            print("[*] Crawling all sites...")
            total_new = 0
            for site_key in SITES:
                total_new += scraper.crawl(site_key, max_pages=5)
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

        choice = input("\nChoice: ").strip()

        if choice == "1":
            if not config.is_valid:
                print(f"[!] {config.message or 'Selection config is invalid'}")
                continue
            if not config.is_open:
                print("[!] Selection is not open, query may return nothing")
            keyword = input("Keyword (课程名/课程号/教师): ").strip()
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
            idx = input("\nWhich class to select? (#): ").strip()
            try:
                tc = cached_courses[int(idx) - 1]
                print(f"[*] Selecting: {tc.kcmc} - {tc.jxbmc} ({tc.xm})")
                ok, msg = client.select_course(config, tc)
                print(f"[{'+' if ok else '!'}] {msg}")
            except (ValueError, IndexError):
                print("Invalid number")

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
            idx = input("\nWhich class to grab? (#): ").strip()
            try:
                tc = cached_courses[int(idx) - 1]
            except (ValueError, IndexError):
                print("Invalid number")
                continue

            attempts_str = input("Max attempts [50]: ").strip()
            try:
                max_attempts = int(attempts_str) if attempts_str else 50
            except ValueError:
                print("Invalid number, using default 50")
                max_attempts = 50
            interval_str = input("Interval seconds [0.3]: ").strip()
            try:
                interval = float(interval_str) if interval_str else 0.3
            except ValueError:
                print("Invalid number, using default 0.3")
                interval = 0.3
            jitter_str = input("Random jitter seconds [0.1]: ").strip()
            try:
                jitter = float(jitter_str) if jitter_str else 0.1
            except ValueError:
                print("Invalid number, using default 0.1")
                jitter = 0.1
            start_str = input("Start at HH:MM[:SS] [now]: ").strip()
            start_at = _parse_start_time_input(start_str)
            if start_str and start_at is None:
                print("Invalid time format, starting immediately")

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
            idx = input("\nWhich selected class to cancel? (#): ").strip()
            try:
                tc = cached_selected[int(idx) - 1]
                print(f"[*] Canceling: {tc.course_name} - {tc.class_name}")
                ok, msg = client.cancel_course(config, tc)
                print(f"[{'+' if ok else '!'}] {msg}")
            except (ValueError, IndexError):
                print("Invalid number")

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
    bell = input("Bell notification? (y/n) [y]: ").strip().lower()
    desktop = input("Desktop notification? (y/n) [y]: ").strip().lower()
    telegram = input("Telegram notification? (y/n) [n]: ").strip().lower()
    wants_telegram = telegram == "y"
    if wants_telegram and not (
        os.environ.get("WZU_TELEGRAM_BOT_TOKEN")
        and os.environ.get("WZU_TELEGRAM_CHAT_ID")
    ):
        print("[!] Telegram env vars missing, skipping Telegram notifier")
    notifier = build_notifier(
        bell=bell != "n",
        desktop=desktop != "n",
        telegram=wants_telegram,
    )
    return notifier


def _maybe_export_records(kind: str, records: list[dict[str, str]]) -> None:
    """Offer a simple export prompt after displaying structured data."""
    if not records:
        return

    allowed_formats = ["csv", "json"]
    if kind in {"exams", "schedule"}:
        allowed_formats.append("ics")

    choice = (
        input(f"Export {kind}? [{'/'.join(allowed_formats)}/Enter skip]: ")
        .strip()
        .lower()
    )
    if not choice:
        return
    if choice not in allowed_formats:
        print("Invalid format, skipping export")
        return

    default_path = default_export_path(kind, choice)
    path_input = input(f"Output path [{default_path}]: ").strip()
    output_path = Path(path_input) if path_input else default_path
    export_context = None
    if kind == "schedule" and choice == "ics":
        week1_monday = input("Week 1 Monday date [YYYY-MM-DD]: ").strip()
        try:
            datetime.strptime(week1_monday, "%Y-%m-%d")
        except ValueError:
            print("[!] Invalid date, skipping export")
            return
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
        export_records(kind, records, choice, output_path, context=export_context)
    except ValueError as exc:
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
    keyword = input("Keyword (课程名/课程号/教师): ").strip()
    courses = client.query_courses(config, keyword)
    if not courses:
        print("No courses found")
        return

    _print_course_list(courses)
    idx = input("\nWhich classes to monitor? (# or 1,3,5): ").strip()
    targets = _parse_index_selection(courses, idx)
    if not targets:
        print("Invalid selection")
        return

    interval_str = input("Check interval seconds [10]: ").strip()
    try:
        interval = float(interval_str) if interval_str else 10.0
    except ValueError:
        interval = 10.0

    auto_grab = input("Auto-grab when available? (y/n) [n]: ").strip().lower() == "y"
    notifier = _configure_monitor_notifier()
    log_path = default_export_path("course-monitor", "jsonl")
    log_choice = input(f"Write monitor log? (y/n) [y], path [{log_path}]: ").strip()
    if log_choice.lower() == "n":
        log_path = None
    else:
        custom_log = input("Log path override [Enter keep default]: ").strip()
        if custom_log:
            log_path = Path(custom_log)
    grab_attempts = 1
    grab_interval = 0.3
    grab_jitter = 0.1
    if auto_grab:
        attempts_str = input("Auto-grab attempts per vacancy [8]: ").strip()
        try:
            grab_attempts = int(attempts_str) if attempts_str else 8
        except ValueError:
            grab_attempts = 8
        retry_interval = input("Auto-grab retry interval [0.3]: ").strip()
        try:
            grab_interval = float(retry_interval) if retry_interval else 0.3
        except ValueError:
            grab_interval = 0.3
        jitter_str = input("Auto-grab jitter seconds [0.1]: ").strip()
        try:
            grab_jitter = float(jitter_str) if jitter_str else 0.1
        except ValueError:
            grab_jitter = 0.1

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
    zero_to_open_only = (
        input("Notify only on 0 -> vacancy transitions? (y/n) [y]: ").strip().lower()
        != "n"
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


def main():
    with WZUClient() as client:
        # Check if existing session works
        if client.check_session():
            print("[+] Existing session is valid, skipping login")
        else:
            print("[*] Need to login")
            username = (
                os.environ.get("WZU_USERNAME") or input("Student ID (学号): ").strip()
            )
            password = os.environ.get("WZU_PASSWORD") or getpass.getpass(
                "Password (密码): "
            )
            if not client.login_cas(username, password):
                print("[!] Login failed, exiting")
                sys.exit(1)

        scraper = CMSScraper()

        # Menu
        while True:
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

            choice = input("\nChoice: ").strip()

            if choice == "1":
                year = input("School year (e.g. 2025-2026): ").strip() or "2025-2026"
                sem = input("Semester (1=fall, 2=spring): ").strip() or "2"
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
                year = input("School year (e.g. 2025-2026, empty=all): ").strip() or ""
                sem = input("Semester (1=fall, 2=spring, empty=all): ").strip() or ""
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
                else:
                    print("No grades found")
                _maybe_export_records("grades", grades)

            elif choice == "3":
                year = input("School year (e.g. 2025-2026): ").strip() or "2025-2026"
                sem = input("Semester (1=fall, 2=spring): ").strip() or "1"
                exams = client.get_exams(year, sem)
                if exams:
                    print(f"\n  Found {len(exams)} exams:\n")
                    for i, e in enumerate(exams, 1):
                        print(f"  {i}. {e['name']}")
                        print(f"     Time:     {e['time']}")
                        print(f"     Location: {e['location']} ({e['campus']})")
                        print(f"     Seat:     {e['seat']}")
                        print(f"     Teacher:  {e['teacher']}")
                        print()
                else:
                    print("No exams found for this semester")
                _maybe_export_records("exams", exams)

            elif choice == "4":
                info = client.get_student_info()
                print(json.dumps(info, ensure_ascii=False, indent=2))

            elif choice == "5":
                cms_menu(scraper)

            elif choice == "6":
                xk_menu(client)

            elif choice == "7":
                monitor_menu(client)

            elif choice == "8":
                valid = client.check_session()
                print(f"Session valid: {valid}")

            elif choice == "0":
                scraper.close()
                break


def should_run_tui(argv: list[str]) -> bool:
    return any(arg in {"--tui", "-t"} for arg in argv[1:])


if __name__ == "__main__":
    if should_run_tui(sys.argv):
        run_tui()
    else:
        main()
