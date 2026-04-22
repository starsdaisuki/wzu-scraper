from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from wzu_scraper.tui import (
    TUIState,
    WZUTUI,
    build_section_entries,
    export_payload_for_section,
    render_section_lines,
)


def test_prompt_survives_narrow_terminal():
    """Prompt width calculation must never produce negative args to curses."""
    stdscr = MagicMock()
    stdscr.getmaxyx.return_value = (10, 10)  # very narrow
    window = MagicMock()
    window.getstr.return_value = b""

    tui = WZUTUI(stdscr, MagicMock())
    with (
        patch("wzu_scraper.tui.curses.newwin", return_value=window) as new_win,
        patch("wzu_scraper.tui.curses.echo"),
        patch("wzu_scraper.tui.curses.noecho"),
        patch("wzu_scraper.tui.curses.curs_set"),
    ):
        tui.prompt("this is a very long label", "and a long default")

    # Window width must be at least 20 regardless of terminal size.
    args, _ = new_win.call_args
    _, win_width, _, _ = args
    assert win_width >= 20

    # getstr must receive non-negative coordinates and a positive length.
    (row, col, length), _ = window.getstr.call_args_list[0]
    assert row >= 0 and col >= 0 and length >= 1


def test_render_section_lines_for_schedule_contains_course_data():
    state = TUIState()
    lines = render_section_lines(
        "schedule",
        [
            {
                "name": "高等数学A(一)",
                "teacher": "教师甲",
                "weekday": "星期一",
                "periods": "1-2",
                "location": "南1-A101",
                "weeks": "1-16周",
            }
        ],
        state,
        80,
    )

    assert any("高等数学A(一)" in line for line in lines)
    assert any("星期一" in line for line in lines)


def test_export_payload_for_selected_section_normalizes_dataclass_like_objects():
    payload = export_payload_for_section(
        "selected",
        [
            SimpleNamespace(
                course_name="高级语言程序设计",
                class_name="01班",
                teacher="张老师",
                credit="3.0",
                jxb_id="JXB001",
                do_jxb_id="DO001",
                kch_id="KCH001",
                jxbzls="1",
                xkkz_id="XKKZ001",
            )
        ],
    )

    assert payload is not None
    kind, rows = payload
    assert kind == "selected_courses"
    assert rows[0]["course_name"] == "高级语言程序设计"
    assert rows[0]["do_jxb_id"] == "DO001"


def test_handle_select_course_updates_message_and_selected_cache():
    client = SimpleNamespace()
    course = SimpleNamespace(kcmc="高级语言程序设计", jxbmc="01班", xm="张老师")
    config = SimpleNamespace(is_valid=True, is_open=True)
    selected = [SimpleNamespace(course_name="高级语言程序设计")]

    client.get_xk_config = lambda: config
    client.select_course = lambda conf, tc: (True, "选课成功")
    client.get_selected_courses = lambda: selected

    tui = WZUTUI.__new__(WZUTUI)
    tui.client = client
    tui.state = TUIState()
    tui.state.menu_index = 6  # search
    tui.state.data = {"search": [course]}
    tui.prompt = lambda label, default: "1"

    tui.handle_select_course()

    assert tui.state.message == "Selected: 选课成功"
    assert tui.state.data["selected"] == selected


def test_handle_cancel_course_updates_message_and_selected_cache():
    client = SimpleNamespace()
    selected_course = SimpleNamespace(course_name="高级语言程序设计")
    config = SimpleNamespace(is_valid=True, is_open=True)

    client.get_xk_config = lambda: config
    client.cancel_course = lambda conf, tc: (True, "退课成功")
    client.get_selected_courses = lambda: []

    tui = WZUTUI.__new__(WZUTUI)
    tui.client = client
    tui.state = TUIState()
    tui.state.menu_index = 5  # selected
    tui.state.data = {"selected": [selected_course]}
    tui.prompt = lambda label, default: "1"

    tui.handle_cancel_course()

    assert tui.state.message == "Cancelled: 退课成功"
    assert tui.state.data["selected"] == []


def test_handle_add_monitor_appends_current_search_course():
    course = SimpleNamespace(
        kcmc="高级语言程序设计", jxbmc="01班", xm="张老师", jxb_id="JXB001"
    )

    tui = WZUTUI.__new__(WZUTUI)
    tui.client = SimpleNamespace()
    tui.state = TUIState()
    tui.state.menu_index = 6  # search
    tui.state.data = {"search": [course]}

    tui.handle_add_monitor()

    assert tui.state.monitor_courses == [course]
    assert "Added to monitor" in tui.state.message


def test_build_section_entries_for_monitor_uses_last_results():
    state = TUIState()
    state.monitor_auto_grab = True
    state.monitor_courses = [
        SimpleNamespace(
            kcmc="高级语言程序设计",
            jxbmc="01班",
            xm="张老师",
            yxzrs="59",
            jxbrl="60",
            jxb_id="JXB001",
        )
    ]
    data = {"JXB001": {"status": "available", "message": "59/60", "available": 1}}

    entries = build_section_entries("monitor", data, state)

    assert entries[0].title == "高级语言程序设计"
    assert any("available" in line for line in entries[0].details)
    assert any("Auto-grab: on" == line for line in entries[0].details)
