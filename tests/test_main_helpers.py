from __future__ import annotations

import json
from types import SimpleNamespace

from main import (
    _append_monitor_log,
    _compute_gpa_stats,
    _current_school_year_and_semester,
    _display_width,
    _normalize_iso_date_input,
    _normalize_school_year_input,
    _pad_display,
    _parse_index_selection,
    _prompt_choice,
    _prompt_float,
    _prompt_index,
    _prompt_int,
    _prompt_school_year,
    _prompt_semester,
    _prompt_yes_no,
    _resolve_export_output_path,
    should_run_tui,
)


def test_parse_index_selection_supports_comma_separated_indexes():
    items = ["a", "b", "c", "d"]

    selected = _parse_index_selection(items, "1, 3,4")

    assert selected == ["a", "c", "d"]


def test_append_monitor_log_writes_jsonl_record(tmp_path):
    path = tmp_path / "monitor.jsonl"
    tc = SimpleNamespace(
        kcmc="高级语言程序设计",
        jxbmc="01班",
        xm="张老师",
        jxb_id="JXB001",
        jxbrl="60",
        yxzrs="59",
    )

    _append_monitor_log(path, 3, tc, status="available", available=1, detail="剩余 1")

    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record["check"] == 3
    assert record["status"] == "available"
    assert record["course"] == "高级语言程序设计"
    assert record["available"] == 1
    assert record["detail"] == "剩余 1"


def test_should_run_tui_accepts_short_and_long_flags():
    assert should_run_tui(["main.py", "--tui"]) is True
    assert should_run_tui(["main.py", "-t"]) is True
    assert should_run_tui(["main.py"]) is False


def test_resolve_export_output_path_uses_default_name_for_directory(tmp_path):
    default_path = tmp_path / "exports" / "schedule-20260420-000000.csv"

    resolved = _resolve_export_output_path(str(tmp_path), default_path)

    assert resolved == tmp_path / default_path.name


def test_normalize_iso_date_input_accepts_unpadded_values():
    assert _normalize_iso_date_input("2026-1-1") == "2026-01-01"
    assert _normalize_iso_date_input(" 2026-04-20 ") == "2026-04-20"
    assert _normalize_iso_date_input("2026/04/20") is None


def test_normalize_school_year_input_accepts_short_and_full_forms():
    assert _normalize_school_year_input("2025") == "2025-2026"
    assert _normalize_school_year_input("2025-2026") == "2025-2026"
    assert _normalize_school_year_input("2025-2027") is None
    assert _normalize_school_year_input("2025/2026") is None


def test_prompt_choice_retries_until_valid(monkeypatch):
    answers = iter(["x", "2"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert _prompt_choice("Choice: ", {"1", "2"}) == "2"


def test_prompt_school_year_accepts_shorthand_after_invalid(monkeypatch):
    answers = iter(["2025/2026", "2025"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert _prompt_school_year("Year: ", default="2024-2025") == "2025-2026"


def test_prompt_semester_retries_until_1_or_2(monkeypatch):
    answers = iter(["3", "2"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert _prompt_semester("Semester: ", default="1") == "2"


def test_prompt_yes_no_retries_until_clear_answer(monkeypatch):
    answers = iter(["maybe", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert _prompt_yes_no("Confirm? ", default=False) is True


def test_prompt_int_retries_until_valid(monkeypatch):
    answers = iter(["abc", "0", "8"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert _prompt_int("Attempts: ", default=5, minimum=1) == 8


def test_prompt_float_retries_until_valid(monkeypatch):
    answers = iter(["oops", "-1", "0.5"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert _prompt_float("Interval: ", default=1.0, minimum=0.0) == 0.5


def test_prompt_index_retries_and_allows_cancel(monkeypatch):
    answers = iter(["9", "abc", "2"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert _prompt_index(["a", "b", "c"], "Pick: ") == 1


def test_compute_gpa_stats_excludes_pass_courses_from_denominator():
    """A pass/合格 course must not pull GPA average down."""
    grades = [
        {"name": "A", "credit": "3", "gpa_point": "4.0", "grade": "95"},
        {"name": "B", "credit": "2", "gpa_point": "", "grade": "合格"},
    ]
    stats = _compute_gpa_stats(grades)
    assert stats["gpa"] == 4.0
    assert stats["gpa_credit"] == 3.0
    assert stats["passed_non_gpa"] == 1
    assert stats["failed"] == 0
    assert stats["earned_credit"] == 5.0  # 3 @4.0 + 2 @pass


def test_compute_gpa_stats_counts_numeric_zero_as_fail():
    grades = [{"name": "F", "credit": "3", "gpa_point": "0", "grade": "55"}]
    stats = _compute_gpa_stats(grades)
    assert stats["failed"] == 1
    assert stats["passed_non_gpa"] == 0
    assert stats["gpa_rated"] == 1
    assert stats["earned_credit"] == 0.0


def test_compute_gpa_stats_treats_blank_grade_as_unscored():
    grades = [{"name": "U", "credit": "2", "gpa_point": "", "grade": "缓考"}]
    stats = _compute_gpa_stats(grades)
    assert stats["unscored"] == 1
    assert stats["failed"] == 0
    assert stats["gpa"] == 0.0


def test_compute_gpa_stats_handles_text_fail():
    grades = [{"name": "X", "credit": "1", "gpa_point": "", "grade": "不合格"}]
    assert _compute_gpa_stats(grades)["failed"] == 1


def test_current_school_year_and_semester():
    from datetime import date

    assert _current_school_year_and_semester(date(2026, 4, 24)) == ("2025-2026", "2")
    assert _current_school_year_and_semester(date(2025, 10, 1)) == ("2025-2026", "1")
    assert _current_school_year_and_semester(date(2026, 1, 5)) == ("2025-2026", "1")
    assert _current_school_year_and_semester(date(2026, 7, 15)) == ("2025-2026", "2")


def test_display_width_counts_cjk_as_two_columns():
    """CJK / full-width chars take 2 columns; ASCII 1; combining marks 0."""
    assert _display_width("hello") == 5
    assert _display_width("中文") == 4  # 2 chars × 2 cols
    assert _display_width("中a") == 3
    # Combining mark (e.g., COMBINING ACUTE ACCENT) doesn't add width.
    assert _display_width("é") == 1


def test_pad_display_pads_with_correct_spaces_for_cjk():
    # Target 10 columns, padded value should occupy exactly 10.
    out = _pad_display("中文", 10)
    # "中文" is 4 cols, so we expect 6 spaces appended.
    assert out == "中文" + " " * 6
    assert _display_width(out) == 10


def test_pad_display_truncates_with_ellipsis_when_overflowing():
    # 8-col budget; "高等数学A概论" needs more — must end with ellipsis,
    # and total width must not exceed 8.
    out = _pad_display("高等数学A概论", 8)
    assert out.endswith("…") or "…" in out
    assert _display_width(out) <= 8


def test_pad_display_right_align():
    out = _pad_display("12", 5, align="right")
    assert out == "   12"
    assert _display_width(out) == 5
