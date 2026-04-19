import httpx

from wzu_scraper.xk import (
    TeachingClass,
    XkConfig,
    get_xk_config,
    grab_course,
    parse_selected_classes_html,
    query_courses,
    select_course,
)

from .conftest import read_fixture


def _make_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


def test_get_xk_config_marks_closed_page_invalid():
    html = """
    <input type="hidden" name="iskxk" id="iskxk" value="0"/>
    <div class="nodata"><span>对不起，当前不属于选课阶段，如有需要，请与管理员联系！</span></div>
    """

    client = _make_client(lambda request: httpx.Response(200, text=html))
    config = get_xk_config(client)

    assert config is not None
    assert config.is_open is False
    assert config.is_valid is False
    assert config.message == "当前不属于选课阶段"


def test_get_xk_config_parses_valid_selection_page():
    html = """
    <input type="hidden" id="iskxk" value="1"/>
    <input type="hidden" id="firstXkkzId" value="xkkz-1"/>
    <input type="hidden" id="xkxnm" value="2025"/>
    <input type="hidden" id="xkxqm" value="12"/>
    <input type="hidden" id="firstKklxdm" value="01"/>
    <input type="hidden" id="firstNjdmId" value="2023"/>
    <input type="hidden" id="firstZyhId" value="stat"/>
    """

    client = _make_client(lambda request: httpx.Response(200, text=html))
    config = get_xk_config(client)

    assert config is not None
    assert config.is_open is True
    assert config.is_valid is True
    assert config.message == ""
    assert config.xkkz_id == "xkkz-1"
    assert config.xkxnm == "2025"
    assert config.xkxqm == "12"
    assert config.kklxdm == "01"
    assert config.njdm_id == "2023"
    assert config.zyh_id == "stat"


def test_query_courses_returns_empty_for_invalid_config_without_request():
    called = False

    def handler(request):
        nonlocal called
        called = True
        return httpx.Response(500)

    client = _make_client(handler)
    config = XkConfig(
        "",
        "",
        "",
        "",
        "",
        "",
        is_open=False,
        is_valid=False,
        message="当前不属于选课阶段",
    )

    assert query_courses(client, config, "高等数学") == []
    assert called is False


def test_select_course_rejects_invalid_config_without_request():
    called = False

    def handler(request):
        nonlocal called
        called = True
        return httpx.Response(500)

    client = _make_client(handler)
    config = XkConfig(
        "",
        "",
        "",
        "",
        "",
        "",
        is_open=False,
        is_valid=False,
        message="当前不属于选课阶段",
    )
    tc = TeachingClass("", "", "", "", "高等数学", "4", "", "", "", "", "0", "0", "1")

    ok, msg = select_course(client, config, tc)

    assert ok is False
    assert msg == "当前不属于选课阶段"
    assert called is False


def test_grab_course_rejects_invalid_config_without_attempts():
    config = XkConfig(
        "",
        "",
        "",
        "",
        "",
        "",
        is_open=False,
        is_valid=False,
        message="当前不属于选课阶段",
    )
    tc = TeachingClass("", "", "", "", "高等数学", "4", "", "", "", "", "0", "0", "1")
    client = _make_client(lambda request: httpx.Response(500))

    ok, msg, attempts = grab_course(client, config, tc)

    assert ok is False
    assert msg == "当前不属于选课阶段"
    assert attempts == 0


def test_parse_selected_classes_html_extracts_selected_courses():
    selected = parse_selected_classes_html(
        read_fixture("jwxt", "selected_courses.html")
    )

    assert [c.course_name for c in selected] == [
        "高级语言程序设计",
        "概率论与数理统计",
    ]
    assert selected[0].class_name == "01班"
    assert selected[0].teacher == "张老师"
    assert selected[0].do_jxb_id == "DO001"
    assert selected[1].credit == "4.0"
    assert selected[1].xkkz_id == "XKKZ002"


def test_grab_course_supports_start_time_and_jitter(monkeypatch):
    attempts = iter(
        [
            {"flag": "0", "msg": "课程已满"},
            {"flag": "1", "msg": "选课成功"},
        ]
    )

    def handler(request):
        return httpx.Response(200, json=next(attempts))

    sleep_calls = []

    monkeypatch.setattr("wzu_scraper.xk.time.time", lambda: 100.0)
    monkeypatch.setattr("wzu_scraper.xk.time.sleep", sleep_calls.append)
    monkeypatch.setattr("wzu_scraper.xk.random.uniform", lambda a, b: 0.2)

    client = _make_client(handler)
    config = XkConfig("xkkz", "2025", "12", "01", "2023", "stat", is_open=True)
    tc = TeachingClass(
        "jxb",
        "do",
        "kch",
        "KCH",
        "高等数学",
        "4",
        "01班",
        "教师",
        "",
        "",
        "0",
        "100",
        "1",
    )

    ok, msg, used = grab_course(
        client,
        config,
        tc,
        max_attempts=2,
        interval=0.3,
        jitter=0.2,
        start_at=101.0,
    )

    assert ok is True
    assert msg == "选课成功"
    assert used == 2
    assert sleep_calls == [1.0, 0.5]
