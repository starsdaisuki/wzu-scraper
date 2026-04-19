"""Export helpers for WZU Scraper data."""

from __future__ import annotations

import csv
import json
import re
import uuid
from datetime import UTC, datetime
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


def default_export_path(kind: str, fmt: str, export_dir: Path | None = None) -> Path:
    """Build a default export path under exports/."""
    export_root = export_dir or DEFAULT_EXPORT_DIR
    export_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return export_root / f"{kind}-{timestamp}.{fmt}"


def export_records(
    kind: str, records: list[dict[str, str]], fmt: str, path: Path
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


def _field_order_for_kind(kind: str, records: list[dict[str, str]]) -> list[str]:
    if kind == "schedule":
        return SCHEDULE_FIELDS
    if kind == "grades":
        return GRADES_FIELDS
    if kind == "exams":
        return EXAM_FIELDS
    if records:
        return list(records[0].keys())
    return []


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
