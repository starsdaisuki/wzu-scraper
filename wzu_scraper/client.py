"""WZU educational system scraper with session management."""

import json
import logging
from pathlib import Path

import httpx

from .auth import build_login_data, extract_login_error, is_jwxt_url, parse_login_page
from .jwxt_api import (
    build_exams_payload,
    build_grades_payload,
    build_schedule_payload,
    parse_exams_json,
    parse_grades_json,
    parse_schedule_json,
    parse_student_info_html,
)
from .xk import (
    SelectedClass,
    TeachingClass,
    XkConfig,
    cancel_course,
    get_selected_classes,
    get_xk_config,
    grab_course,
    query_courses,
    select_course,
)

# CAS login base URL (direct, not through WebVPN - jwxt uses source.wzu.edu.cn)
CAS_BASE = "https://source.wzu.edu.cn"
JWXT_BASE = "https://jwxt.wzu.edu.cn"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

COOKIE_FILE = Path(__file__).parent.parent / ".cookies.json"
logger = logging.getLogger(__name__)


class WZUClient:
    """Client for WZU CAS + educational system (正方教务)."""

    def __init__(self):
        self._client = httpx.Client(
            headers=HEADERS,
            follow_redirects=True,
            timeout=30.0,
            verify=True,
        )
        self._logged_in = False
        self._load_cookies()

    def _save_cookies(self):
        """Persist cookies to disk (with domain info to avoid conflicts)."""
        cookie_list = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self._client.cookies.jar
        ]
        COOKIE_FILE.write_text(json.dumps(cookie_list, ensure_ascii=False, indent=2))

    def _load_cookies(self):
        """Load cookies from disk if available."""
        if COOKIE_FILE.exists():
            try:
                cookie_list = json.loads(COOKIE_FILE.read_text())
                for c in cookie_list:
                    self._client.cookies.set(
                        c["name"],
                        c["value"],
                        domain=c.get("domain", ""),
                        path=c.get("path", "/"),
                    )
            except (json.JSONDecodeError, KeyError):
                pass

    def login_cas(self, username: str, password: str) -> bool:
        """Login to CAS and follow redirects into the educational system.

        Returns True if login succeeded.
        """
        service_url = f"{JWXT_BASE}/sso/zfiotlogin"
        login_url = f"{CAS_BASE}/login?service={service_url}"

        logger.info("Fetching CAS login page")
        resp = self._client.get(login_url)
        resp.raise_for_status()

        if is_jwxt_url(str(resp.url)):
            logger.info("Reused existing CAS session")
            self._logged_in = True
            return True

        login_page = parse_login_page(resp.text)
        if login_page is None:
            logger.warning("Failed to parse execution token from login page")
            return False

        logger.info(
            "Parsed CAS login page fields",
            extra={
                "execution_length": len(login_page.execution),
                "has_server_croypto": bool(login_page.server_croypto),
            },
        )

        login_data = build_login_data(username, password, login_page.execution)
        logger.info("Submitting CAS login request")

        post_resp = self._client.post(
            f"{CAS_BASE}/login",
            data=login_data,
            headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": CAS_BASE,
                "Referer": login_url,
            },
        )

        final_url = str(post_resp.url)
        if is_jwxt_url(final_url):
            logger.info("CAS login succeeded", extra={"final_url": final_url})
            self._logged_in = True
            self._save_cookies()
            return True

        if "/login" in final_url:
            error_message = extract_login_error(post_resp.text)
            if error_message:
                logger.warning("CAS login failed", extra={"error": error_message})
            else:
                logger.warning("CAS login failed", extra={"final_url": final_url})
            return False

        if self.check_session():
            logger.info(
                "CAS login verified via session check", extra={"final_url": final_url}
            )
            self._logged_in = True
            self._save_cookies()
            return True

        logger.warning(
            "CAS login did not yield a valid session",
            extra={"final_url": final_url, "status_code": post_resp.status_code},
        )
        return False

    def check_session(self) -> bool:
        """Check if the current session is still valid."""
        try:
            resp = self._client.get(
                f"{JWXT_BASE}/jwglxt/xtgl/index_cxYhxxIndex.html",
                params={"xt": "jw", "localeKey": "zh_CN", "gnmkdm": "index"},
            )
            # If we get redirected to login, session expired
            if "/login" in str(resp.url):
                return False
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def get_student_info(self) -> dict | None:
        """Fetch current student info from the main page."""
        resp = self._client.get(
            f"{JWXT_BASE}/jwglxt/xtgl/index_cxYhxxIndex.html",
            params={"xt": "jw", "localeKey": "zh_CN", "gnmkdm": "index"},
        )
        if resp.status_code != 200:
            return None

        info = parse_student_info_html(resp.text)
        return info if info else {"raw_length": len(resp.text), "url": str(resp.url)}

    def get_course_schedule(
        self, school_year: str = "2025-2026", semester: str = "2"
    ) -> list[dict]:
        """Fetch course schedule (课程表).

        Args:
            school_year: e.g. "2025-2026"
            semester: "1" for fall, "2" for spring, "3" for summer
        """
        resp = self._client.post(
            f"{JWXT_BASE}/jwglxt/kbcx/xskbcx_cxXsgrkb.html",
            params={"gnmkdm": "N2151"},
            data=build_schedule_payload(school_year, semester),
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        if resp.status_code != 200:
            logger.warning(
                "Failed to fetch schedule", extra={"status_code": resp.status_code}
            )
            return []

        try:
            data = resp.json()
        except json.JSONDecodeError:
            logger.warning("Schedule response was not JSON")
            return []

        return parse_schedule_json(data)

    def get_grades(
        self, school_year: str = "2025-2026", semester: str = "2"
    ) -> list[dict]:
        """Fetch grades (成绩).

        Args:
            school_year: e.g. "2025-2026"
            semester: "1" for fall, "2" for spring. Use "" for all.
        """
        resp = self._client.post(
            f"{JWXT_BASE}/jwglxt/cjcx/cjcx_cxDgXscj.html",
            params={"doType": "query", "gnmkdm": "N305005"},
            data=build_grades_payload(school_year, semester),
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        if resp.status_code != 200:
            logger.warning(
                "Failed to fetch grades", extra={"status_code": resp.status_code}
            )
            return []

        try:
            data = resp.json()
        except json.JSONDecodeError:
            logger.warning("Grades response was not JSON")
            return []

        return parse_grades_json(data)

    def get_exams(
        self, school_year: str = "2025-2026", semester: str = "1"
    ) -> list[dict]:
        """Fetch exam schedule (考试安排).

        Args:
            school_year: e.g. "2025-2026"
            semester: "1" for fall, "2" for spring. Use "" for all.
        """
        resp = self._client.post(
            f"{JWXT_BASE}/jwglxt/kwgl/kscx_cxXsksxxIndex.html",
            params={"doType": "query", "gnmkdm": "N358105"},
            data=build_exams_payload(school_year, semester),
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        if resp.status_code != 200:
            logger.warning(
                "Failed to fetch exams", extra={"status_code": resp.status_code}
            )
            return []

        try:
            data = resp.json()
        except json.JSONDecodeError:
            logger.warning("Exams response was not JSON")
            return []

        return parse_exams_json(data)

    # --- Course Selection (选课) ---

    def get_xk_config(self) -> XkConfig | None:
        """Get current course selection config and status."""
        return get_xk_config(self._client)

    def query_courses(
        self, config: XkConfig, keyword: str = "", page: int = 0
    ) -> list[TeachingClass]:
        """Query available courses/teaching classes."""
        return query_courses(self._client, config, keyword, page)

    def get_selected_courses(self) -> list[SelectedClass]:
        """Fetch selected teaching classes from the right-side panel."""
        return get_selected_classes(self._client)

    def select_course(self, config: XkConfig, tc: TeachingClass) -> tuple[bool, str]:
        """Select a single course. Returns (success, message)."""
        return select_course(self._client, config, tc)

    def cancel_course(
        self, config: XkConfig, tc: TeachingClass | SelectedClass
    ) -> tuple[bool, str]:
        """Cancel a selected course. Returns (success, message)."""
        return cancel_course(self._client, config, tc)

    def grab_course(
        self,
        config: XkConfig,
        tc: TeachingClass,
        max_attempts: int = 50,
        interval: float = 0.3,
        on_attempt: callable = None,
        jitter: float = 0.0,
        start_at: float | None = None,
    ) -> tuple[bool, str, int]:
        """Repeatedly try to select a course (抢课).

        Returns (success, message, attempts_used).
        """
        return grab_course(
            self._client,
            config,
            tc,
            max_attempts,
            interval,
            on_attempt,
            jitter,
            start_at,
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
