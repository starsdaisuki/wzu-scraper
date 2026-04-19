"""Helpers for parsing JWXT responses and building request payloads."""

from __future__ import annotations

import html as html_lib
import re

SCHEDULE_XQM_MAP = {"1": "3", "2": "12", "3": "16"}
GRADES_XQM_MAP = {"1": "3", "2": "12", "3": "16", "": ""}


def school_year_to_xnm(school_year: str) -> str:
    """Convert a school year like 2025-2026 into the xnm parameter."""
    return school_year.split("-")[0] if school_year else ""


def build_schedule_payload(school_year: str, semester: str) -> dict[str, str]:
    """Build the form payload for the course schedule API."""
    return {
        "xnm": school_year_to_xnm(school_year),
        "xqm": SCHEDULE_XQM_MAP.get(semester, "12"),
    }


def build_grades_payload(school_year: str, semester: str) -> dict[str, str]:
    """Build the form payload for the grades API."""
    return {
        "xnm": school_year_to_xnm(school_year),
        "xqm": GRADES_XQM_MAP.get(semester, "12"),
        "queryModel.showCount": "100",
        "queryModel.currentPage": "1",
    }


def parse_student_info_html(html: str) -> dict[str, str | int]:
    """Extract the minimal student info exposed by the home page."""
    info: dict[str, str | int] = {}

    heading_match = re.search(
        r'<h4[^>]*class="media-heading"[^>]*>\s*(.*?)\s*</h4>',
        html,
        re.DOTALL,
    )
    if heading_match:
        heading = html_lib.unescape(
            re.sub(r"<[^>]+>", "", heading_match.group(1))
        ).strip()
        parts = [
            part.strip() for part in re.split(r"\s{2,}|\xa0+", heading) if part.strip()
        ]
        if parts:
            info["name"] = parts[0]
        if len(parts) > 1:
            info["role"] = parts[-1]

    profile_match = re.search(r"<p>\s*([^<]+?)\s*</p>", html)
    if profile_match:
        profile = html_lib.unescape(profile_match.group(1)).strip()
        if profile:
            info["profile"] = profile

    name_match = re.search(r"用户名[：:]\s*([^<\s]+)", html)
    if name_match and "name" not in info:
        info["name"] = name_match.group(1)

    return info


def parse_schedule_json(data: dict) -> list[dict[str, str]]:
    """Normalize the course schedule response into the public client shape."""
    return [
        {
            "name": item.get("kcmc", ""),
            "teacher": item.get("xm", ""),
            "location": item.get("cdmc", ""),
            "weekday": item.get("xqjmc", ""),
            "periods": item.get("jcor", ""),
            "weeks": item.get("zcd", ""),
            "credit": item.get("xf", ""),
        }
        for item in data.get("kbList", [])
    ]


def parse_grades_json(data: dict) -> list[dict[str, str]]:
    """Normalize the grades response into the public client shape."""
    return [
        {
            "name": item.get("kcmc", ""),
            "grade": item.get("cj", ""),
            "gpa_point": item.get("jd", ""),
            "credit": item.get("xf", ""),
            "category": item.get("kcxzmc", ""),
            "type": item.get("kcbj", ""),
        }
        for item in data.get("items", [])
    ]
