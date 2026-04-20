from __future__ import annotations

import json
from types import SimpleNamespace

from main import (
    _append_monitor_log,
    _normalize_iso_date_input,
    _normalize_school_year_input,
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
