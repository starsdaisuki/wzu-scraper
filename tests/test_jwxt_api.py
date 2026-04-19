from __future__ import annotations

import json

from wzu_scraper.jwxt_api import (
    build_grades_payload,
    build_schedule_payload,
    parse_grades_json,
    parse_schedule_json,
    parse_student_info_html,
)

from .conftest import read_fixture


def test_parse_student_info_html_extracts_name() -> None:
    info = parse_student_info_html(read_fixture("jwxt", "student_info.html"))

    assert info == {
        "name": "学生甲",
        "role": "学生",
        "profile": "数理学院 23统计1",
    }


def test_parse_schedule_json_normalizes_fields() -> None:
    payload = json.loads(read_fixture("jwxt", "schedule.json"))

    assert parse_schedule_json(payload) == [
        {
            "name": "高等数学A(一)",
            "teacher": "教师甲",
            "location": "南1-A101",
            "weekday": "星期一",
            "periods": "1-2",
            "weeks": "1-16周",
            "credit": "4.0",
        }
    ]


def test_parse_grades_json_normalizes_fields() -> None:
    payload = json.loads(read_fixture("jwxt", "grades.json"))

    assert parse_grades_json(payload) == [
        {
            "name": "大学英语(一)",
            "grade": "85",
            "gpa_point": "3.50",
            "credit": "4.0",
            "category": "必选课",
            "type": "",
        }
    ]


def test_request_payload_builders_match_expected_parameters() -> None:
    assert build_schedule_payload("2025-2026", "2") == {"xnm": "2025", "xqm": "12"}
    assert build_grades_payload("", "") == {
        "xnm": "",
        "xqm": "",
        "queryModel.showCount": "100",
        "queryModel.currentPage": "1",
    }
