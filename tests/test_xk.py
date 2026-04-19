import httpx

from wzu_scraper.xk import (
    TeachingClass,
    XkConfig,
    get_xk_config,
    grab_course,
    query_courses,
    select_course,
)


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
    config = XkConfig("", "", "", "", "", "", is_open=False, is_valid=False, message="当前不属于选课阶段")

    assert query_courses(client, config, "高等数学") == []
    assert called is False


def test_select_course_rejects_invalid_config_without_request():
    called = False

    def handler(request):
        nonlocal called
        called = True
        return httpx.Response(500)

    client = _make_client(handler)
    config = XkConfig("", "", "", "", "", "", is_open=False, is_valid=False, message="当前不属于选课阶段")
    tc = TeachingClass("", "", "", "", "高等数学", "4", "", "", "", "", "0", "0", "1")

    ok, msg = select_course(client, config, tc)

    assert ok is False
    assert msg == "当前不属于选课阶段"
    assert called is False


def test_grab_course_rejects_invalid_config_without_attempts():
    config = XkConfig("", "", "", "", "", "", is_open=False, is_valid=False, message="当前不属于选课阶段")
    tc = TeachingClass("", "", "", "", "高等数学", "4", "", "", "", "", "0", "0", "1")
    client = _make_client(lambda request: httpx.Response(500))

    ok, msg, attempts = grab_course(client, config, tc)

    assert ok is False
    assert msg == "当前不属于选课阶段"
    assert attempts == 0
