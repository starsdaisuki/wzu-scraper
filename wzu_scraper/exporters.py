"""Export helpers for WZU Scraper data."""

from __future__ import annotations

import csv
import json
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

DEFAULT_EXPORT_DIR = Path("exports")

SCHEDULE_FIELDS = [
    "name",
    "teacher",
    "location",
    "weekday",
    "periods",
    "weeks",
    "credit",
]
GRADES_FIELDS = ["name", "grade", "gpa_point", "credit", "category", "type"]
EXAM_FIELDS = [
    "name",
    "exam_name",
    "time",
    "location",
    "campus",
    "seat",
    "teacher",
    "credit",
]
SELECTED_COURSE_FIELDS = [
    "course_name",
    "class_name",
    "teacher",
    "credit",
    "jxb_id",
    "do_jxb_id",
    "kch_id",
    "jxbzls",
    "xkkz_id",
]
WEEKDAY_MAP = {
    "星期一": 0,
    "星期二": 1,
    "星期三": 2,
    "星期四": 3,
    "星期五": 4,
    "星期六": 5,
    "星期日": 6,
    "星期天": 6,
}
PERIOD_TIME_MAP = {
    1: ("08:00", "08:45"),
    2: ("08:55", "09:40"),
    3: ("10:10", "10:55"),
    4: ("11:05", "11:50"),
    5: ("14:00", "14:45"),
    6: ("14:55", "15:40"),
    7: ("16:00", "16:45"),
    8: ("16:55", "17:40"),
    9: ("19:00", "19:45"),
    10: ("19:55", "20:40"),
    11: ("20:50", "21:35"),
}


def default_export_path(kind: str, fmt: str, export_dir: Path | None = None) -> Path:
    """Build a default export path under exports/."""
    export_root = export_dir or DEFAULT_EXPORT_DIR
    export_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return export_root / f"{kind}-{timestamp}.{fmt}"


def export_records(
    kind: str,
    records: list[dict[str, str]],
    fmt: str,
    path: Path,
    *,
    context: dict[str, str] | None = None,
) -> Path:
    """Export normalized records in the requested format."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2))
        return path

    if fmt == "csv":
        fieldnames = _field_order_for_kind(kind, records)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)
        return path

    if fmt == "ics" and kind == "exams":
        path.write_text(build_exams_ics(records), encoding="utf-8")
        return path

    if fmt == "ics" and kind == "schedule":
        if not context or not context.get("week1_monday"):
            raise ValueError("Schedule ICS export requires week1_monday")
        week1_monday = date.fromisoformat(context["week1_monday"])
        path.write_text(
            build_schedule_ics(
                records,
                week1_monday,
                summary_prefix=context.get("summary_prefix", "") if context else "",
                category=context.get("category", "") if context else "",
                calendar_name=context.get("calendar_name", "WZU Schedule")
                if context
                else "WZU Schedule",
                calendar_color=context.get("calendar_color", "") if context else "",
            ),
            encoding="utf-8",
        )
        return path

    raise ValueError(f"Unsupported export format for {kind}: {fmt}")


def build_exams_ics(exams: list[dict[str, str]]) -> str:
    """Convert normalized exams into a simple ICS calendar."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WZU Scraper//Exam Export//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:WZU Exams",
    ]

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for exam in exams:
        parsed = _parse_exam_time_range(exam.get("time", ""))
        if not parsed:
            continue

        start_dt, end_dt = parsed
        summary = _ics_escape(exam.get("name", "考试"))
        description = _ics_escape(
            "\n".join(
                part
                for part in [
                    f"考试名称: {exam.get('exam_name', '')}".strip(),
                    f"教师: {exam.get('teacher', '')}".strip(),
                    f"座位号: {exam.get('seat', '')}".strip(),
                ]
                if part.split(": ", 1)[-1]
            )
        )
        location = _ics_escape(
            " ".join(
                part
                for part in [exam.get("campus", ""), exam.get("location", "")]
                if part
            )
        )
        uid = f"{uuid.uuid4()}@wzu-scraper"

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:{summary}",
                f"LOCATION:{location}",
                f"DESCRIPTION:{description}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def build_schedule_ics(
    courses: list[dict[str, str]],
    week1_monday: date,
    *,
    summary_prefix: str = "",
    category: str = "",
    calendar_name: str = "WZU Schedule",
    calendar_color: str = "",
) -> str:
    """Convert normalized schedule rows into concrete weekly ICS events."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WZU Scraper//Schedule Export//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(calendar_name)}",
    ]
    if calendar_color:
        lines.append(f"X-APPLE-CALENDAR-COLOR:{calendar_color}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for course in courses:
        weekday = WEEKDAY_MAP.get(course.get("weekday", ""))
        start_end = _period_range_to_times(course.get("periods", ""))
        week_numbers = _parse_weeks(course.get("weeks", ""))
        if weekday is None or start_end is None or not week_numbers:
            continue

        start_time, end_time = start_end
        for week in week_numbers:
            event_date = week1_monday + timedelta(weeks=week - 1, days=weekday)
            start_dt = datetime.combine(event_date, start_time)
            end_dt = datetime.combine(event_date, end_time)
            uid = f"{uuid.uuid4()}@wzu-scraper"
            summary_text = course.get("name", "课程")
            if summary_prefix:
                summary_text = f"{summary_prefix} {summary_text}"
            summary = _ics_escape(summary_text)
            description = _ics_escape(
                "\n".join(
                    part
                    for part in [
                        f"教师: {course.get('teacher', '')}".strip(),
                        f"周次: {course.get('weeks', '')}".strip(),
                        f"节次: {course.get('periods', '')}".strip(),
                        f"学分: {course.get('credit', '')}".strip(),
                    ]
                    if part.split(": ", 1)[-1]
                )
            )
            location = _ics_escape(course.get("location", ""))
            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"DTSTAMP:{stamp}",
                    f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}",
                    f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}",
                    f"SUMMARY:{summary}",
                    f"LOCATION:{location}",
                    f"DESCRIPTION:{description}",
                    *([f"CATEGORIES:{_ics_escape(category)}"] if category else []),
                    "END:VEVENT",
                ]
            )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _field_order_for_kind(kind: str, records: list[dict[str, str]]) -> list[str]:
    if kind == "schedule":
        return SCHEDULE_FIELDS
    if kind == "grades":
        return GRADES_FIELDS
    if kind == "exams":
        return EXAM_FIELDS
    if kind == "selected_courses":
        return SELECTED_COURSE_FIELDS
    if records:
        return list(records[0].keys())
    return []


def _parse_weeks(raw: str) -> list[int]:
    week_text = raw.replace("，", ",").replace(" ", "")
    if not week_text:
        return []

    weeks: set[int] = set()
    for part in filter(None, week_text.split(",")):
        step = 1
        if "(单)" in part:
            step = 2
        if "(双)" in part:
            step = 2
        cleaned = (
            part.replace("周", "")
            .replace("(单)", "")
            .replace("(双)", "")
            .replace("单周", "")
            .replace("双周", "")
        )
        if "-" in cleaned:
            start_raw, end_raw = cleaned.split("-", 1)
            start = int(start_raw)
            end = int(end_raw)
            if "(双)" in part and start % 2 != 0:
                start += 1
            if "(单)" in part and start % 2 == 0:
                start += 1
            weeks.update(range(start, end + 1, step))
        elif cleaned.isdigit():
            value = int(cleaned)
            if "(单)" in part and value % 2 == 0:
                continue
            if "(双)" in part and value % 2 != 0:
                continue
            weeks.add(value)
    return sorted(weeks)


def _period_range_to_times(raw: str) -> tuple[time, time] | None:
    numbers = [int(token) for token in re.findall(r"\d+", raw)]
    if not numbers:
        return None
    start_period = min(numbers)
    end_period = max(numbers)
    start_values = PERIOD_TIME_MAP.get(start_period)
    end_values = PERIOD_TIME_MAP.get(end_period)
    if not start_values or not end_values:
        return None
    return _parse_clock(start_values[0]), _parse_clock(end_values[1])


def _parse_clock(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def _parse_exam_time_range(raw: str) -> tuple[datetime, datetime] | None:
    match = re.match(
        r"(?P<date>\d{4}-\d{2}-\d{2})\((?P<start>\d{2}:\d{2})-(?P<end>\d{2}:\d{2})\)",
        raw,
    )
    if not match:
        return None

    start_dt = datetime.strptime(
        f"{match.group('date')} {match.group('start')}", "%Y-%m-%d %H:%M"
    )
    end_dt = datetime.strptime(
        f"{match.group('date')} {match.group('end')}", "%Y-%m-%d %H:%M"
    )
    return start_dt, end_dt


def _ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )
