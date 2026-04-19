"""WZU Scraper - 温州大学教务系统爬虫"""

import getpass
import json
import os
import sys

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
            print("3. Student info (个人信息)")
            print("4. Website search (网站搜索)")
            print("5. Session status")
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
                info = client.get_student_info()
                print(json.dumps(info, ensure_ascii=False, indent=2))

            elif choice == "4":
                cms_menu(scraper)

            elif choice == "5":
                valid = client.check_session()
                print(f"Session valid: {valid}")

            elif choice == "0":
                scraper.close()
                break


if __name__ == "__main__":
    main()
