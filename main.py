"""WZU Scraper - 温州大学教务系统爬虫"""

import getpass
import json
import os
import sys
import time

from wzu_scraper.client import WZUClient
from wzu_scraper.cms import CMSScraper, SITES

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
        print("    You can still browse the menu, but selecting will fail.")

    # Cache for searched courses
    cached_courses: list = []

    while True:
        print("\n--- Course Selection (选课) ---")
        print("1. Search courses (搜索课程)")
        print("2. Select a course (选课)")
        print("3. GRAB mode - auto retry (抢课模式)")
        print("4. Cancel a course (退课)")
        print("5. Refresh config (刷新状态)")
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

        elif choice == "3":
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

            print(f"\n[*] GRAB MODE: {tc.kcmc} - {tc.jxbmc}")
            print(f"    Max attempts: {max_attempts}, interval: {interval}s")
            print("    Press Ctrl+C to stop\n")

            def on_attempt(n, ok, msg):
                status = "OK" if ok else "FAIL"
                print(f"  [{n:>3}/{max_attempts}] {status}: {msg}")

            try:
                ok, msg, used = client.grab_course(
                    config, tc, max_attempts, interval, on_attempt
                )
                if ok:
                    print(f"\n[+] SUCCESS after {used} attempts: {msg}")
                else:
                    print(f"\n[!] FAILED after {used} attempts: {msg}")
            except KeyboardInterrupt:
                print("\n[*] Stopped by user")

        elif choice == "4":
            if not config.is_valid:
                print(f"[!] {config.message or 'Selection config is invalid'}")
                continue
            if not config.is_open:
                print("[!] Selection is not open, cannot cancel courses")
                continue
            if not cached_courses:
                print("Search for courses first (option 1)")
                continue
            _print_course_list(cached_courses)
            idx = input("\nWhich class to cancel? (#): ").strip()
            try:
                tc = cached_courses[int(idx) - 1]
                print(f"[*] Canceling: {tc.kcmc} - {tc.jxbmc}")
                ok, msg = client.cancel_course(config, tc)
                print(f"[{'+' if ok else '!'}] {msg}")
            except (ValueError, IndexError):
                print("Invalid number")

        elif choice == "5":
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
    idx = input("\nWhich class to monitor? (#): ").strip()
    try:
        tc = courses[int(idx) - 1]
    except (ValueError, IndexError):
        print("Invalid number")
        return

    interval_str = input("Check interval seconds [10]: ").strip()
    try:
        interval = float(interval_str) if interval_str else 10.0
    except ValueError:
        interval = 10.0

    auto_grab = input("Auto-grab when available? (y/n) [n]: ").strip().lower() == "y"

    print(f"\n[*] Monitoring: {tc.kcmc} - {tc.jxbmc}")
    print(f"    Current: {tc.yxzrs}/{tc.jxbrl}")
    print(f"    Interval: {interval}s, Auto-grab: {'yes' if auto_grab else 'no'}")
    print("    Press Ctrl+C to stop\n")

    check_num = 0
    try:
        while True:
            time.sleep(interval)
            check_num += 1

            # Re-query to get updated capacity
            updated = client.query_courses(config, tc.kcmc)
            match = None
            for c in updated:
                if c.jxb_id == tc.jxb_id:
                    match = c
                    break

            if not match:
                print(f"  [{check_num}] Could not find class in results")
                continue

            enrolled = int(match.yxzrs) if match.yxzrs.isdigit() else 0
            capacity = int(match.jxbrl) if match.jxbrl.isdigit() else 0
            available = capacity - enrolled

            if available > 0:
                print(
                    f"  [{check_num}] *** VACANCY! *** "
                    f"{match.yxzrs}/{match.jxbrl} "
                    f"({available} spots open)"
                )
                if auto_grab:
                    print(f"  [{check_num}] Auto-grabbing...")
                    ok, msg = client.select_course(config, match)
                    if ok:
                        print(f"  [{check_num}] SUCCESS: {msg}")
                        break
                    else:
                        print(f"  [{check_num}] Failed: {msg}, will keep trying")
            else:
                print(
                    f"  [{check_num}] Full: {match.yxzrs}/{match.jxbrl}",
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


if __name__ == "__main__":
    main()
