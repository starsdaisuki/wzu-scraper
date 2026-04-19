from __future__ import annotations

import json
from types import SimpleNamespace

from main import _append_monitor_log, _parse_index_selection, should_run_tui


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
