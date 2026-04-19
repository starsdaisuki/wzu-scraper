from __future__ import annotations

import json

from wzu_scraper.exporters import build_exams_ics, default_export_path, export_records


def test_default_export_path_uses_exports_dir_and_extension(tmp_path) -> None:
    path = default_export_path("grades", "csv", export_dir=tmp_path)

    assert path.parent == tmp_path
    assert path.name.startswith("grades-")
    assert path.suffix == ".csv"


def test_export_records_writes_csv(tmp_path) -> None:
    path = tmp_path / "grades.csv"
    rows = [
        {
            "name": "大学英语(一)",
            "grade": "85",
            "gpa_point": "3.50",
            "credit": "4.0",
            "category": "必选课",
            "type": "",
        }
    ]

    export_records("grades", rows, "csv", path)

    text = path.read_text(encoding="utf-8")
    assert "大学英语(一)" in text
    assert "grade" in text


def test_export_records_writes_json(tmp_path) -> None:
    path = tmp_path / "schedule.json"
    rows = [{"name": "高等数学A(一)", "teacher": "教师甲"}]

    export_records("schedule", rows, "json", path)

    assert json.loads(path.read_text(encoding="utf-8")) == rows


def test_build_exams_ics_contains_exam_event() -> None:
    exams = [
        {
            "name": "大学英语(一)",
            "time": "2026-01-19(09:00-11:00)",
            "location": "南11-A202",
            "campus": "南校区",
            "seat": "2",
            "exam_name": "2025-2026-1全校公共课期末考试",
            "teacher": "教师甲",
            "credit": "4.0",
        }
    ]

    ics = build_exams_ics(exams)

    assert "BEGIN:VCALENDAR" in ics
    assert "SUMMARY:大学英语(一)" in ics
    assert "DTSTART:20260119T090000" in ics
    assert "DTEND:20260119T110000" in ics
    assert "LOCATION:南校区 南11-A202" in ics


def test_export_records_writes_exam_ics(tmp_path) -> None:
    path = tmp_path / "exams.ics"
    exams = [
        {
            "name": "大学英语(一)",
            "time": "2026-01-19(09:00-11:00)",
            "location": "南11-A202",
            "campus": "南校区",
            "seat": "2",
            "exam_name": "2025-2026-1全校公共课期末考试",
            "teacher": "教师甲",
            "credit": "4.0",
        }
    ]

    export_records("exams", exams, "ics", path)

    assert "BEGIN:VEVENT" in path.read_text(encoding="utf-8")
