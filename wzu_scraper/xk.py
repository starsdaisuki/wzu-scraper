"""Course selection (选课/抢课) module for WZU 正方教务系统.

Reverse-engineered from /js/comp/jwglxt/xkgl/xsxk/zzxkYzb.js (N253512).
"""

import html as html_lib
import logging
import random
import re
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

JWXT_BASE = "https://jwxt.wzu.edu.cn"
XK_GNMKDM = "N253512"

XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


@dataclass
class XkConfig:
    """Selection period config extracted from the index page."""

    xkkz_id: str  # 选课控制 ID
    xkxnm: str  # 学年
    xkxqm: str  # 学期
    kklxdm: str  # 开课类型代码
    njdm_id: str  # 年级代码
    zyh_id: str  # 专业号
    is_open: bool  # 是否在选课时间内
    is_valid: bool = True  # 关键隐藏字段是否提取完整
    message: str = ""  # 无效时的人类可读提示


@dataclass
class TeachingClass:
    """A teaching class (教学班) for a course."""

    jxb_id: str  # 教学班 ID
    do_jxb_id: str  # 教学班操作 ID (用于选课/退课请求)
    kch_id: str  # 课程号
    kch: str  # 课程号(显示)
    kcmc: str  # 课程名称
    xf: str  # 学分
    jxbmc: str  # 教学班名称
    xm: str  # 教师姓名
    sksj: str  # 上课时间
    jxdd: str  # 教学地点
    yxzrs: str  # 已选人数
    jxbrl: str  # 教学班容量
    jxbzls: str  # 教学班组类数


@dataclass
class SelectedClass:
    """A selected teaching class parsed from the choosed panel HTML."""

    jxb_id: str
    do_jxb_id: str
    kch_id: str
    jxbzls: str
    xkkz_id: str
    course_name: str
    class_name: str
    teacher: str = ""
    credit: str = ""


def get_xk_config(client: httpx.Client) -> XkConfig | None:
    """Fetch course selection index page and extract config.

    Returns None if the page can't be loaded.
    """
    resp = client.get(
        f"{JWXT_BASE}/jwglxt/xsxk/zzxkyzb_cxZzxkYzbIndex.html",
        params={"gnmkdm": XK_GNMKDM},
    )
    if resp.status_code != 200:
        return None

    html = resp.text
    is_open = _extract_hidden(html, "iskxk") == "1"
    xkkz_id = _extract_hidden(html, "firstXkkzId") or _extract_hidden(html, "xkkz_id")
    xkxnm = _extract_hidden(html, "xkxnm")
    xkxqm = _extract_hidden(html, "xkxqm")
    kklxdm = _extract_hidden(html, "firstKklxdm") or _extract_hidden(html, "kklxdm")
    njdm_id = _extract_hidden(html, "firstNjdmId") or _extract_hidden(html, "njdm_id")
    zyh_id = _extract_hidden(html, "firstZyhId") or _extract_hidden(html, "zyh_id")

    is_valid = all([xkkz_id, xkxnm, xkxqm, kklxdm, njdm_id, zyh_id])
    message = ""
    if not is_valid:
        if "当前不属于选课阶段" in html:
            message = "当前不属于选课阶段"
        else:
            message = "选课配置不完整"

    return XkConfig(
        xkkz_id=xkkz_id,
        xkxnm=xkxnm,
        xkxqm=xkxqm,
        kklxdm=kklxdm,
        njdm_id=njdm_id,
        zyh_id=zyh_id,
        is_open=is_open,
        is_valid=is_valid,
        message=message,
    )


def get_selected_classes(client: httpx.Client) -> list[SelectedClass]:
    """Fetch the selected teaching classes shown in the right-side panel."""
    resp = client.get(f"{JWXT_BASE}/jwglxt/xsxk/zzxkyzb_cxZzxkYzbChoosed.html")
    if resp.status_code != 200:
        logger.warning(
            "Failed to load selected classes panel",
            extra={"status": resp.status_code},
        )
        return []

    return parse_selected_classes_html(resp.text)


def query_courses(
    client: httpx.Client,
    config: XkConfig,
    keyword: str = "",
    page: int = 0,
) -> list[TeachingClass]:
    """Query available teaching classes.

    Args:
        client: Authenticated httpx client
        config: Selection period config
        keyword: Optional search keyword (course name/code/teacher)
        page: Page number (0-based, each page ~10 items)
    """
    error = _get_config_error(config)
    if error:
        logger.warning("Refusing to query courses with invalid config")
        return []

    data = {
        "xkkz_id": config.xkkz_id,
        "kklxdm": config.kklxdm,
        "njdm_id": config.njdm_id,
        "zyh_id": config.zyh_id,
        "xqh_id": "",
        "kspage": str(page * 10),
        "jspage": str(10),
    }
    if keyword:
        data["filter_list[0]"] = keyword

    resp = client.post(
        f"{JWXT_BASE}/jwglxt/xsxk/zzxkyzbjk_cxJxbWithKchZzxkYzb.html",
        params={"gnmkdm": XK_GNMKDM},
        data=data,
        headers=XHR_HEADERS,
    )

    if resp.status_code != 200:
        logger.warning("Query courses failed", extra={"status": resp.status_code})
        return []

    try:
        result = resp.json()
    except Exception:
        # Returns "0" when selection is closed
        return []

    if not isinstance(result, list):
        return []

    classes = []
    for item in result:
        classes.append(
            TeachingClass(
                jxb_id=item.get("jxb_id", ""),
                do_jxb_id=item.get("do_jxb_id", ""),
                kch_id=item.get("kch_id", ""),
                kch=item.get("kch", ""),
                kcmc=item.get("kcmc", ""),
                xf=item.get("xf", ""),
                jxbmc=item.get("jxbmc", ""),
                xm=item.get("xm", ""),
                sksj=item.get("sksj", ""),
                jxdd=item.get("jxdd", ""),
                yxzrs=item.get("yxzrs", "0"),
                jxbrl=item.get("jxbrl", "0"),
                jxbzls=item.get("jxbzls", "1"),
            )
        )
    return classes


def select_course(
    client: httpx.Client,
    config: XkConfig,
    tc: TeachingClass,
) -> tuple[bool, str]:
    """Submit a course selection request.

    Returns (success, message).
    """
    error = _get_config_error(config)
    if error:
        return False, error

    data = {
        "jxb_ids": tc.do_jxb_id or tc.jxb_id,
        "kch_id": tc.kch_id,
        "xkkz_id": config.xkkz_id,
        "njdm_id": config.njdm_id,
        "zyh_id": config.zyh_id,
        "kklxdm": config.kklxdm,
        "rwlx": "2",
        "rlkz": "0",
        "rlzlkz": "1",
        "sxbj": "1",
        "xxkbj": "0",
        "cxbj": "0",
        "qz": "0",
        "xkxnm": config.xkxnm,
        "xkxqm": config.xkxqm,
        "jxbzls": tc.jxbzls,
    }

    resp = client.post(
        f"{JWXT_BASE}/jwglxt/xsxk/zzxkyzb_xkBcZzxkYzb.html",
        params={"gnmkdm": XK_GNMKDM},
        data=data,
        headers=XHR_HEADERS,
    )

    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}"

    try:
        result = resp.json()
    except Exception:
        return False, resp.text[:200]

    if isinstance(result, dict):
        flag = result.get("flag")
        msg = result.get("msg", "")
        if flag == "1":
            return True, msg or "选课成功"
        return False, msg or f"选课失败 (flag={flag})"

    return False, str(result)[:200]


def cancel_course(
    client: httpx.Client,
    config: XkConfig,
    tc: TeachingClass | SelectedClass,
) -> tuple[bool, str]:
    """Cancel a selected course.

    Returns (success, message).
    """
    error = _get_config_error(config)
    if error:
        return False, error

    data = {
        "jxb_ids": tc.do_jxb_id or tc.jxb_id,
        "kch_id": tc.kch_id,
        "xkkz_id": config.xkkz_id,
        "njdm_id": config.njdm_id,
        "zyh_id": config.zyh_id,
        "kklxdm": config.kklxdm,
        "xkxnm": config.xkxnm,
        "xkxqm": config.xkxqm,
    }

    resp = client.post(
        f"{JWXT_BASE}/jwglxt/xsxk/zzxkyzb_tuikBcZzxkYzb.html",
        params={"gnmkdm": XK_GNMKDM},
        data=data,
        headers=XHR_HEADERS,
    )

    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}"

    try:
        result = resp.json()
    except Exception:
        return False, resp.text[:200]

    if isinstance(result, dict):
        flag = result.get("flag")
        msg = result.get("msg", "")
        if flag == "1":
            return True, msg or "退课成功"
        return False, msg or f"退课失败 (flag={flag})"

    return False, str(result)[:200]


def grab_course(
    client: httpx.Client,
    config: XkConfig,
    tc: TeachingClass,
    max_attempts: int = 50,
    interval: float = 0.3,
    on_attempt: callable = None,
    jitter: float = 0.0,
    start_at: float | None = None,
) -> tuple[bool, str, int]:
    """Repeatedly try to select a course until success or max attempts.

    Args:
        client: Authenticated httpx client
        config: Selection period config
        tc: Teaching class to select
        max_attempts: Maximum number of attempts
        interval: Seconds between attempts (0.1 ~ 1.0 recommended)
        on_attempt: Optional callback(attempt_num, success, message)
        jitter: Extra random delay added to each retry interval
        start_at: Optional unix timestamp to start grabbing at

    Returns (success, message, attempts_used).
    """
    error = _get_config_error(config)
    if error:
        return False, error, 0

    if start_at is not None:
        delay = start_at - time.time()
        if delay > 0:
            time.sleep(delay)

    for attempt in range(1, max_attempts + 1):
        success, msg = select_course(client, config, tc)
        classification = _classify_select_result(success, msg)

        if on_attempt:
            on_attempt(attempt, success, msg)

        if classification == "success":
            return True, msg, attempt

        if classification == "equivalent_success":
            return True, msg, attempt

        if classification == "permanent_error":
            return False, msg, attempt

        if attempt < max_attempts:
            sleep_for = max(0.0, interval)
            if jitter > 0:
                sleep_for += random.uniform(0.0, jitter)
            time.sleep(sleep_for)

    return False, f"达到最大尝试次数 ({max_attempts})", max_attempts


def parse_selected_classes_html(html: str) -> list[SelectedClass]:
    """Parse the selected-course panel HTML into a flat list."""
    starts = [
        match.start()
        for match in re.finditer(
            r'<div[^>]*class=["\'][^"\']*outer_xkxx_list[^"\']*["\'][^>]*>', html
        )
    ]
    if not starts:
        return []

    blocks: list[str] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(html)
        blocks.append(html[start:end])

    selected: list[SelectedClass] = []
    for block in blocks:
        course_name = _extract_html_text(block, "kcmc")
        credit = _extract_input_value(block, "right_xf")
        class_parts = re.split(r'<input[^>]*name=["\']right_jxb_id["\']', block)
        if len(class_parts) <= 1:
            continue

        for part in class_parts[1:]:
            value_match = re.search(r'value=["\']([^"\']+)["\']', part)
            if not value_match:
                continue
            jxb_id = value_match.group(1)
            cancel_match = re.search(
                rf"cancelCourseZzxk\('leftpage','{re.escape(jxb_id)}','([^']*)','([^']*)','([^']*)','([^']*)'\)",
                part,
            )
            if not cancel_match:
                continue

            selected.append(
                SelectedClass(
                    jxb_id=jxb_id,
                    do_jxb_id=cancel_match.group(1),
                    kch_id=cancel_match.group(2),
                    jxbzls=cancel_match.group(3),
                    xkkz_id=cancel_match.group(4),
                    course_name=course_name or cancel_match.group(2),
                    class_name=_extract_html_text(part, "jxbmc") or jxb_id,
                    teacher=_extract_html_text(part, "jsxm"),
                    credit=_extract_input_value(part, "right_jxbxf") or credit,
                )
            )

    return selected


def _get_config_error(config: XkConfig) -> str:
    """Return a human-readable error if the selection config is unusable."""
    if config.is_valid:
        return ""
    if config.message:
        return config.message
    return "选课配置不完整"


def _classify_select_result(success: bool, msg: str) -> str:
    """Classify a select-course result for retry logic."""
    if success:
        return "success"
    if "已选" in msg or "重复" in msg:
        return "equivalent_success"
    if any(k in msg for k in ["不属于选课阶段", "无操作权限", "禁选"]):
        return "permanent_error"
    return "retryable_error"


def _extract_html_text(html: str, class_name: str) -> str:
    match = re.search(
        rf'class=["\'][^"\']*{re.escape(class_name)}[^"\']*["\'][^>]*>(.*?)</[^>]+>',
        html,
        re.DOTALL,
    )
    if not match:
        return ""
    return html_lib.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()


def _extract_input_value(html: str, name: str) -> str:
    match = re.search(
        rf'<input[^>]*name=["\']{re.escape(name)}["\'][^>]*value=["\']([^"\']*)["\']',
        html,
    )
    return match.group(1) if match else ""


def _extract_hidden(html: str, name: str) -> str:
    """Extract value of a hidden input by ID or name."""
    # Try by id first
    m = re.search(
        rf'id=["\']?{re.escape(name)}["\']?\s+value=["\']([^"\']*)["\']', html
    )
    if not m:
        m = re.search(
            rf'value=["\']([^"\']*?)["\']\s*[^>]*id=["\']?{re.escape(name)}', html
        )
    if not m:
        m = re.search(
            rf'name=["\']?{re.escape(name)}["\']?\s+value=["\']([^"\']*)["\']', html
        )
    return m.group(1) if m else ""
