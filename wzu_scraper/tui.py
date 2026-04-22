"""Terminal UI for WZU Scraper."""

from __future__ import annotations

import curses
import getpass
import json
import os
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .client import WZUClient
from .exporters import default_export_path, export_records


def _load_env_file() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def run_tui() -> None:
    _load_env_file()
    with WZUClient() as client:
        if not client.check_session():
            username = (
                os.environ.get("WZU_USERNAME") or input("Student ID (学号): ").strip()
            )
            password = os.environ.get("WZU_PASSWORD") or getpass.getpass(
                "Password (密码): "
            )
            if not client.login_cas(username, password):
                raise SystemExit("Login failed")
        curses.wrapper(lambda stdscr: WZUTUI(stdscr, client).run())


@dataclass
class TUIState:
    menu_index: int = 0
    school_year: str = "2025-2026"
    schedule_semester: str = "2"
    grades_semester: str = ""
    exams_semester: str = "1"
    search_keyword: str = ""
    message: str = (
        "↑↓ move  Enter/r refresh  / search  y year  s semester  "
        "j/k rows  e export  x select  d drop  m monitor  c check  a auto  q quit"
    )
    data: dict[str, object] = field(default_factory=dict)
    selected_row: dict[str, int] = field(default_factory=dict)
    monitor_courses: list[object] = field(default_factory=list)
    monitor_auto_grab: bool = False
    monitor_log_path: Path = field(
        default_factory=lambda: Path("exports") / "tui-monitor.jsonl"
    )


@dataclass
class SectionEntry:
    title: str
    subtitle: str = ""
    details: list[str] = field(default_factory=list)
    raw: object | None = None


MENU_ITEMS = [
    ("dashboard", "Dashboard"),
    ("schedule", "Course Schedule"),
    ("grades", "Grades"),
    ("exams", "Exams"),
    ("student", "Student Info"),
    ("selected", "Selected Courses"),
    ("search", "Search Courses"),
    ("monitor", "Course Monitor"),
    ("session", "Session Status"),
]


class WZUTUI:
    def __init__(self, stdscr, client: WZUClient) -> None:
        self.stdscr = stdscr
        self.client = client
        self.state = TUIState()

    def run(self) -> None:
        curses.curs_set(0)
        self.stdscr.keypad(True)
        self.refresh_current()
        while True:
            self.render()
            key = self.stdscr.getch()
            if key in (ord("q"), 27):
                return
            if key == curses.KEY_UP:
                self.state.menu_index = (self.state.menu_index - 1) % len(MENU_ITEMS)
                continue
            if key == curses.KEY_DOWN:
                self.state.menu_index = (self.state.menu_index + 1) % len(MENU_ITEMS)
                continue
            if key in (curses.KEY_ENTER, 10, 13, ord("r")):
                self.refresh_current()
                continue
            if key == ord("/"):
                self.handle_search_prompt()
                continue
            if key == ord("y"):
                self.handle_year_prompt()
                continue
            if key == ord("s"):
                self.handle_semester_prompt()
                continue
            if key == ord("e"):
                self.handle_export()
                continue
            if key == ord("j"):
                self.move_row(1)
                continue
            if key == ord("k"):
                self.move_row(-1)
                continue
            if key == ord("x"):
                self.handle_select_course()
                continue
            if key == ord("d"):
                self.handle_cancel_course()
                continue
            if key == ord("m"):
                self.handle_add_monitor()
                continue
            if key == ord("u"):
                self.handle_remove_monitor()
                continue
            if key == ord("c"):
                self.handle_monitor_check()
                continue
            if key == ord("a"):
                self.handle_toggle_monitor_auto_grab()

    def refresh_current(self) -> None:
        section = self.current_section
        try:
            if section == "dashboard":
                self.state.data[section] = self.build_dashboard_data()
                self.state.message = "Dashboard refreshed"
            elif section == "schedule":
                self.state.data[section] = self.client.get_course_schedule(
                    self.state.school_year,
                    self.state.schedule_semester,
                )
                self.state.message = "Schedule refreshed"
            elif section == "grades":
                self.state.data[section] = self.client.get_grades(
                    self.state.school_year,
                    self.state.grades_semester,
                )
                self.state.message = "Grades refreshed"
            elif section == "exams":
                self.state.data[section] = self.client.get_exams(
                    self.state.school_year,
                    self.state.exams_semester,
                )
                self.state.message = "Exams refreshed"
            elif section == "student":
                self.state.data[section] = self.client.get_student_info() or {}
                self.state.message = "Student info refreshed"
            elif section == "selected":
                self.state.data[section] = self.client.get_selected_courses()
                self.state.message = "Selected courses refreshed"
            elif section == "search":
                self.state.data[section] = self.fetch_search_courses()
                self.state.message = "Course search refreshed"
            elif section == "monitor":
                self.state.data[section] = self.state.data.get(section, {})
                self.state.message = "Monitor view refreshed"
            elif section == "session":
                self.state.data[section] = {"valid": self.client.check_session()}
                self.state.message = "Session checked"
        except Exception as exc:  # pragma: no cover - live defensive path
            self.state.message = f"Error: {exc}"

    @property
    def current_section(self) -> str:
        return MENU_ITEMS[self.state.menu_index][0]

    def build_dashboard_data(self) -> dict[str, str]:
        return {
            "session": "valid" if self.client.check_session() else "expired",
            "school_year": self.state.school_year,
            "schedule_semester": self.state.schedule_semester,
            "grades_semester": self.state.grades_semester or "all",
            "exams_semester": self.state.exams_semester,
            "search_keyword": self.state.search_keyword or "(empty)",
        }

    def fetch_search_courses(self):
        config = self.client.get_xk_config()
        if not config:
            self.state.message = "Failed to load selection config"
            return []
        if not config.is_valid:
            self.state.message = config.message or "Selection config invalid"
            return []
        if not self.state.search_keyword:
            self.state.message = "Use / to enter search keyword"
            return []
        return self.client.query_courses(config, self.state.search_keyword)

    def handle_search_prompt(self) -> None:
        if self.current_section != "search":
            self.state.message = "Search prompt only works on Search Courses"
            return
        keyword = self.prompt("Course keyword", self.state.search_keyword)
        if keyword is None:
            return
        self.state.search_keyword = keyword
        self.refresh_current()

    def handle_year_prompt(self) -> None:
        value = self.prompt("School year", self.state.school_year)
        if value:
            self.state.school_year = value
            self.state.message = f"School year set to {value}"

    def handle_semester_prompt(self) -> None:
        section = self.current_section
        if section not in {"schedule", "grades", "exams"}:
            self.state.message = "Semester prompt works on schedule/grades/exams"
            return
        mapping = {
            "schedule": ("schedule_semester", self.state.schedule_semester),
            "grades": ("grades_semester", self.state.grades_semester),
            "exams": ("exams_semester", self.state.exams_semester),
        }
        attr, current = mapping[section]
        value = self.prompt("Semester (1/2/3 or empty)", current)
        if value is not None:
            setattr(self.state, attr, value)
            self.state.message = f"{section} semester updated"

    def handle_export(self) -> None:
        section = self.current_section
        payload = export_payload_for_section(section, self.state.data.get(section))
        if payload is None:
            self.state.message = "Nothing exportable on this screen"
            return

        kind, rows = payload
        allowed_formats = ["csv", "json"]
        if kind in {"schedule", "exams"}:
            allowed_formats.append("ics")
        fmt = self.prompt(
            f"Export format {'/'.join(allowed_formats)}",
            allowed_formats[0],
        )
        if not fmt or fmt not in allowed_formats:
            self.state.message = "Export cancelled"
            return

        context = None
        if kind == "schedule" and fmt == "ics":
            week1 = self.prompt("Week 1 Monday YYYY-MM-DD", "")
            if not week1:
                self.state.message = "Schedule ICS export cancelled"
                return
            prefix = self.prompt("Title prefix", "课表") or "课表"
            category = self.prompt("Category", "课程") or "课程"
            color = self.prompt("Calendar color #RRGGBB", "")
            context = {
                "week1_monday": week1,
                "summary_prefix": prefix,
                "category": category,
                "calendar_name": "WZU Schedule",
                "calendar_color": color or "",
            }
        path = default_export_path(kind, fmt)
        try:
            export_records(kind, rows, fmt, path, context=context)
            self.state.message = f"Exported to {path}"
        except ValueError as exc:
            self.state.message = f"Export failed: {exc}"

    def handle_select_course(self) -> None:
        if self.current_section != "search":
            self.state.message = "Select works on Search Courses"
            return
        courses = self.state.data.get("search")
        if not isinstance(courses, list) or not courses:
            self.state.message = "No searched courses to select"
            return
        config = self.client.get_xk_config()
        if not config or not config.is_valid or not config.is_open:
            self.state.message = "Selection is not currently open"
            return
        idx = self.current_row_index("search", len(courses))
        if idx < 0 or idx >= len(courses):
            self.state.message = "Invalid course index"
            return
        ok, msg = self.client.select_course(config, courses[idx])
        self.state.message = f"{'Selected' if ok else 'Select failed'}: {msg}"
        if ok:
            self.state.data["selected"] = self.client.get_selected_courses()

    def handle_cancel_course(self) -> None:
        if self.current_section != "selected":
            self.state.message = "Drop works on Selected Courses"
            return
        courses = self.state.data.get("selected")
        if not isinstance(courses, list) or not courses:
            self.state.message = "No selected courses to cancel"
            return
        config = self.client.get_xk_config()
        if not config or not config.is_valid or not config.is_open:
            self.state.message = "Selection is not currently open"
            return
        idx = self.current_row_index("selected", len(courses))
        if idx < 0 or idx >= len(courses):
            self.state.message = "Invalid selected-course index"
            return
        ok, msg = self.client.cancel_course(config, courses[idx])
        self.state.message = f"{'Cancelled' if ok else 'Cancel failed'}: {msg}"
        if ok:
            self.state.data["selected"] = self.client.get_selected_courses()

    def handle_add_monitor(self) -> None:
        if self.current_section != "search":
            self.state.message = "Add monitor works on Search Courses"
            return
        courses = self.state.data.get("search")
        if not isinstance(courses, list) or not courses:
            self.state.message = "No searched courses to monitor"
            return
        idx = self.current_row_index("search", len(courses))
        if idx < 0 or idx >= len(courses):
            self.state.message = "Invalid course index"
            return
        course = courses[idx]
        if any(
            getattr(existing, "jxb_id", "") == getattr(course, "jxb_id", "")
            for existing in self.state.monitor_courses
        ):
            self.state.message = "Course already in monitor list"
            return
        self.state.monitor_courses.append(course)
        self.state.message = f"Added to monitor: {getattr(course, 'kcmc', '')} - {getattr(course, 'jxbmc', '')}"

    def handle_remove_monitor(self) -> None:
        if self.current_section != "monitor":
            self.state.message = "Remove monitor works on Course Monitor"
            return
        if not self.state.monitor_courses:
            self.state.message = "Monitor list is empty"
            return
        idx = self.current_row_index("monitor", len(self.state.monitor_courses))
        course = self.state.monitor_courses.pop(idx)
        self.state.message = f"Removed monitor: {getattr(course, 'kcmc', '')} - {getattr(course, 'jxbmc', '')}"
        self.state.selected_row["monitor"] = max(0, idx - 1)

    def handle_toggle_monitor_auto_grab(self) -> None:
        if self.current_section != "monitor":
            self.state.message = "Auto-grab toggle works on Course Monitor"
            return
        self.state.monitor_auto_grab = not self.state.monitor_auto_grab
        self.state.message = f"Monitor auto-grab {'enabled' if self.state.monitor_auto_grab else 'disabled'}"

    def handle_monitor_check(self) -> None:
        if self.current_section != "monitor":
            self.state.message = "Check works on Course Monitor"
            return
        if not self.state.monitor_courses:
            self.state.message = "Monitor list is empty"
            return
        config = self.client.get_xk_config()
        if not config or not config.is_valid:
            self.state.message = "Selection config unavailable"
            return

        results: dict[str, dict[str, object]] = {}
        notifications = 0
        for course in self.state.monitor_courses:
            refreshed = self.client.query_courses(config, getattr(course, "kcmc", ""))
            match = next(
                (
                    item
                    for item in refreshed
                    if getattr(item, "jxb_id", "") == getattr(course, "jxb_id", "")
                ),
                None,
            )
            if not match:
                result = {
                    "status": "missing",
                    "available": None,
                    "message": "not found",
                }
                results[getattr(course, "jxb_id", "")] = result
                self.append_monitor_log(course, result)
                continue

            enrolled = (
                int(getattr(match, "yxzrs", "0"))
                if getattr(match, "yxzrs", "").isdigit()
                else 0
            )
            capacity = (
                int(getattr(match, "jxbrl", "0"))
                if getattr(match, "jxbrl", "").isdigit()
                else 0
            )
            available = capacity - enrolled
            result = {
                "status": "available" if available > 0 else "full",
                "available": available,
                "message": f"{enrolled}/{capacity}",
            }
            if available > 0 and self.state.monitor_auto_grab and config.is_open:
                ok, msg = self.client.select_course(config, match)
                result["status"] = "grab_success" if ok else "grab_failed"
                result["message"] = msg
            results[getattr(course, "jxb_id", "")] = result
            self.append_monitor_log(match, result)
            notifications += 1 if available > 0 else 0

        self.state.data["monitor"] = results
        self.state.message = f"Monitor checked: {notifications} course(s) with vacancy"

    def append_monitor_log(self, course: object, result: dict[str, object]) -> None:
        self.state.monitor_log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "course": getattr(course, "kcmc", ""),
            "class_name": getattr(course, "jxbmc", ""),
            "teacher": getattr(course, "xm", ""),
            "jxb_id": getattr(course, "jxb_id", ""),
            "status": result.get("status", ""),
            "available": result.get("available"),
            "message": result.get("message", ""),
        }
        with self.state.monitor_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def move_row(self, delta: int) -> None:
        entries = self.entries_for_current_section()
        if not entries:
            self.state.message = "Current page has no selectable rows"
            return
        section = self.current_section
        current = self.current_row_index(section, len(entries))
        self.state.selected_row[section] = (current + delta) % len(entries)

    def current_row_index(self, section: str, total: int) -> int:
        if total <= 0:
            return 0
        current = self.state.selected_row.get(section, 0)
        if current >= total:
            current = total - 1
        if current < 0:
            current = 0
        self.state.selected_row[section] = current
        return current

    def entries_for_current_section(self) -> list[SectionEntry]:
        return build_section_entries(
            self.current_section,
            self.state.data.get(self.current_section),
            self.state,
        )

    def prompt(self, label: str, default: str) -> str | None:
        height, width = self.stdscr.getmaxyx()
        win_width = max(20, width - 4)
        window = curses.newwin(3, win_width, max(0, height - 4), 2)
        window.border()
        header = f"{label} [{default}]: "
        # Truncate header if it would overflow the prompt window.
        if len(header) > win_width - 4:
            header = header[: max(0, win_width - 4)]
        window.addstr(1, 2, header)
        window.refresh()
        curses.echo()
        curses.curs_set(1)
        input_col = 2 + len(header)
        max_input = max(1, win_width - input_col - 2)
        raw = window.getstr(1, input_col, max_input)
        curses.noecho()
        curses.curs_set(0)
        value = raw.decode("utf-8").strip()
        return default if value == "" else value

    def render(self) -> None:
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        menu_width = min(24, max(18, width // 4))
        self.render_header(width)
        self.render_menu(2, 0, menu_width, height - 3)
        self.render_body(2, menu_width + 1, width - menu_width - 1, height - 3)
        self.render_footer(height - 1, width)
        self.stdscr.refresh()

    def render_header(self, width: int) -> None:
        title = "WZU Assistant TUI"
        section = MENU_ITEMS[self.state.menu_index][1]
        self.stdscr.addnstr(0, 1, f"{title}  |  {section}", width - 2, curses.A_BOLD)

    def render_menu(self, top: int, left: int, width: int, height: int) -> None:
        for idx, (_, label) in enumerate(MENU_ITEMS):
            attr = curses.A_REVERSE if idx == self.state.menu_index else curses.A_NORMAL
            self.stdscr.addnstr(top + idx, left + 1, label, width - 2, attr)

    def render_body(self, top: int, left: int, width: int, height: int) -> None:
        entries = self.entries_for_current_section()
        if entries:
            list_width = max(28, width // 2)
            detail_width = max(20, width - list_width - 1)
            current = self.current_row_index(self.current_section, len(entries))
            for idx, entry in enumerate(entries[: max(0, height - 1)]):
                attr = curses.A_REVERSE if idx == current else curses.A_NORMAL
                summary = entry.title
                if entry.subtitle:
                    summary = f"{summary} | {entry.subtitle}"
                self.stdscr.addnstr(top + idx, left + 1, summary, list_width - 2, attr)
            detail_lines = entries[current].details or [entries[current].title]
            detail_top = top
            detail_left = left + list_width
            for idx, line in enumerate(detail_lines[: max(0, height - 1)]):
                self.stdscr.addnstr(
                    detail_top + idx, detail_left + 1, line, detail_width - 2
                )
            return

        lines = render_section_lines(
            self.current_section,
            self.state.data.get(self.current_section),
            self.state,
            width - 2,
        )
        for idx, line in enumerate(lines[: max(0, height - 1)]):
            self.stdscr.addnstr(top + idx, left + 1, line, width - 2)

    def render_footer(self, row: int, width: int) -> None:
        self.stdscr.addnstr(row, 1, self.state.message, width - 2)


def render_section_lines(
    section: str,
    data: object,
    state: TUIState,
    width: int,
) -> list[str]:
    if section == "dashboard":
        dashboard = data if isinstance(data, dict) else {}
        return render_key_values(
            {
                "Session": dashboard.get("session", "unknown"),
                "School year": state.school_year,
                "Schedule semester": state.schedule_semester,
                "Grades semester": state.grades_semester or "all",
                "Exams semester": state.exams_semester,
                "Search keyword": state.search_keyword or "(empty)",
                "Help": "Enter/r refresh, / search courses, y/s edit filters, e export",
            },
            width,
        )
    if section == "student":
        if isinstance(data, dict):
            return render_key_values(data, width)
        return ["No student info loaded"]
    if section == "session":
        if isinstance(data, dict):
            return [f"Session valid: {data.get('valid', False)}"]
        return ["Session not checked"]
    if section == "schedule":
        return render_records(
            data or [],
            ("name", "teacher", "weekday", "periods", "location", "weeks"),
            width,
        )
    if section == "grades":
        return render_records(
            data or [],
            ("name", "grade", "gpa_point", "credit", "category"),
            width,
        )
    if section == "exams":
        return render_records(
            data or [],
            ("name", "time", "location", "seat", "teacher"),
            width,
        )
    if section == "selected":
        return render_selected_courses(data or [], width)
    if section == "search":
        header = [f"Keyword: {state.search_keyword or '(empty)'}", ""]
        return header + render_teaching_classes(data or [], width)
    if section == "monitor":
        return [
            f"Monitored courses: {len(state.monitor_courses)}",
            f"Auto-grab: {'on' if state.monitor_auto_grab else 'off'}",
            f"Log path: {state.monitor_log_path}",
            "Use m on Search Courses to add items here.",
        ]
    return ["No data"]


def render_key_values(values: dict, width: int) -> list[str]:
    lines: list[str] = []
    for key, value in values.items():
        wrapped = textwrap.wrap(f"{key}: {value}", width=width) or [f"{key}: {value}"]
        lines.extend(wrapped)
    return lines


def render_records(
    records: list[dict], fields: tuple[str, ...], width: int
) -> list[str]:
    if not records:
        return ["No data"]
    lines = [f"{len(records)} record(s)", ""]
    for idx, record in enumerate(records, 1):
        summary = " | ".join(
            str(record.get(field, "")) for field in fields if record.get(field, "")
        )
        wrapped = textwrap.wrap(f"{idx:>2}. {summary}", width=width) or [summary]
        lines.extend(wrapped)
    return lines


def render_selected_courses(courses: list[object], width: int) -> list[str]:
    if not courses:
        return ["No selected courses"]
    lines = [f"{len(courses)} selected course(s)", ""]
    for idx, course in enumerate(courses, 1):
        summary = " | ".join(
            part
            for part in [
                getattr(course, "course_name", ""),
                getattr(course, "class_name", ""),
                getattr(course, "teacher", ""),
                getattr(course, "credit", ""),
            ]
            if part
        )
        lines.extend(textwrap.wrap(f"{idx:>2}. {summary}", width=width) or [summary])
    return lines


def render_teaching_classes(courses: list[object], width: int) -> list[str]:
    if not courses:
        return ["No matching courses"]
    lines = [f"{len(courses)} teaching class(es)", ""]
    for idx, course in enumerate(courses, 1):
        capacity = f"{getattr(course, 'yxzrs', '?')}/{getattr(course, 'jxbrl', '?')}"
        summary = " | ".join(
            part
            for part in [
                getattr(course, "kcmc", ""),
                getattr(course, "jxbmc", ""),
                getattr(course, "xm", ""),
                capacity,
                getattr(course, "sksj", ""),
            ]
            if part
        )
        lines.extend(textwrap.wrap(f"{idx:>2}. {summary}", width=width) or [summary])
    return lines


def export_payload_for_section(
    section: str,
    data: object,
) -> tuple[str, list[dict[str, str]]] | None:
    if section in {"schedule", "grades", "exams"} and isinstance(data, list):
        return section, data
    if section == "selected" and isinstance(data, list):
        return "selected_courses", [
            {
                "course_name": getattr(item, "course_name", ""),
                "class_name": getattr(item, "class_name", ""),
                "teacher": getattr(item, "teacher", ""),
                "credit": getattr(item, "credit", ""),
                "jxb_id": getattr(item, "jxb_id", ""),
                "do_jxb_id": getattr(item, "do_jxb_id", ""),
                "kch_id": getattr(item, "kch_id", ""),
                "jxbzls": getattr(item, "jxbzls", ""),
                "xkkz_id": getattr(item, "xkkz_id", ""),
            }
            for item in data
        ]
    return None


def build_section_entries(
    section: str,
    data: object,
    state: TUIState,
) -> list[SectionEntry]:
    if section == "schedule" and isinstance(data, list):
        return [
            SectionEntry(
                title=item.get("name", "课程"),
                subtitle=" | ".join(
                    part
                    for part in [
                        item.get("teacher", ""),
                        item.get("weekday", ""),
                        item.get("periods", ""),
                    ]
                    if part
                ),
                details=[
                    f"Teacher: {item.get('teacher', '')}",
                    f"Location: {item.get('location', '')}",
                    f"Weekday: {item.get('weekday', '')}",
                    f"Periods: {item.get('periods', '')}",
                    f"Weeks: {item.get('weeks', '')}",
                    f"Credit: {item.get('credit', '')}",
                ],
                raw=item,
            )
            for item in data
        ]
    if section == "grades" and isinstance(data, list):
        return [
            SectionEntry(
                title=item.get("name", "成绩"),
                subtitle=" | ".join(
                    part
                    for part in [
                        item.get("grade", ""),
                        f"GPA {item.get('gpa_point', '')}"
                        if item.get("gpa_point", "")
                        else "",
                    ]
                    if part
                ),
                details=[
                    f"Grade: {item.get('grade', '')}",
                    f"GPA: {item.get('gpa_point', '')}",
                    f"Credit: {item.get('credit', '')}",
                    f"Category: {item.get('category', '')}",
                    f"Type: {item.get('type', '')}",
                ],
                raw=item,
            )
            for item in data
        ]
    if section == "exams" and isinstance(data, list):
        return [
            SectionEntry(
                title=item.get("name", "考试"),
                subtitle=item.get("time", ""),
                details=[
                    f"Time: {item.get('time', '')}",
                    f"Location: {item.get('campus', '')} {item.get('location', '')}".strip(),
                    f"Seat: {item.get('seat', '')}",
                    f"Teacher: {item.get('teacher', '')}",
                    f"Exam name: {item.get('exam_name', '')}",
                ],
                raw=item,
            )
            for item in data
        ]
    if section == "selected" and isinstance(data, list):
        return [
            SectionEntry(
                title=getattr(item, "course_name", "已选课程"),
                subtitle=" | ".join(
                    part
                    for part in [
                        getattr(item, "class_name", ""),
                        getattr(item, "teacher", ""),
                    ]
                    if part
                ),
                details=[
                    f"Class: {getattr(item, 'class_name', '')}",
                    f"Teacher: {getattr(item, 'teacher', '')}",
                    f"Credit: {getattr(item, 'credit', '')}",
                    f"JXB ID: {getattr(item, 'jxb_id', '')}",
                    f"DO JXB ID: {getattr(item, 'do_jxb_id', '')}",
                    f"Course ID: {getattr(item, 'kch_id', '')}",
                    f"XKKZ ID: {getattr(item, 'xkkz_id', '')}",
                ],
                raw=item,
            )
            for item in data
        ]
    if section == "search" and isinstance(data, list):
        return [
            SectionEntry(
                title=getattr(item, "kcmc", "课程"),
                subtitle=" | ".join(
                    part
                    for part in [
                        getattr(item, "jxbmc", ""),
                        getattr(item, "xm", ""),
                        f"{getattr(item, 'yxzrs', '?')}/{getattr(item, 'jxbrl', '?')}",
                    ]
                    if part
                ),
                details=[
                    f"Class: {getattr(item, 'jxbmc', '')}",
                    f"Teacher: {getattr(item, 'xm', '')}",
                    f"Time: {getattr(item, 'sksj', '')}",
                    f"Location: {getattr(item, 'jxdd', '')}",
                    f"Capacity: {getattr(item, 'yxzrs', '?')}/{getattr(item, 'jxbrl', '?')}",
                    f"Course ID: {getattr(item, 'kch_id', '')}",
                    f"JXB ID: {getattr(item, 'jxb_id', '')}",
                ],
                raw=item,
            )
            for item in data
        ]
    if section == "monitor":
        results = data if isinstance(data, dict) else {}
        return [
            SectionEntry(
                title=getattr(item, "kcmc", "监控课程"),
                subtitle=" | ".join(
                    part
                    for part in [
                        getattr(item, "jxbmc", ""),
                        getattr(item, "xm", ""),
                        str(
                            results.get(getattr(item, "jxb_id", ""), {}).get(
                                "status", "pending"
                            )
                        ),
                    ]
                    if part
                ),
                details=[
                    f"Class: {getattr(item, 'jxbmc', '')}",
                    f"Teacher: {getattr(item, 'xm', '')}",
                    f"Current capacity: {getattr(item, 'yxzrs', '?')}/{getattr(item, 'jxbrl', '?')}",
                    f"Last status: {results.get(getattr(item, 'jxb_id', ''), {}).get('status', 'pending')}",
                    f"Last message: {results.get(getattr(item, 'jxb_id', ''), {}).get('message', '')}",
                    f"Available: {results.get(getattr(item, 'jxb_id', ''), {}).get('available', '')}",
                    f"Auto-grab: {'on' if state.monitor_auto_grab else 'off'}",
                    f"Log path: {state.monitor_log_path}",
                ],
                raw=item,
            )
            for item in state.monitor_courses
        ]
    return []
