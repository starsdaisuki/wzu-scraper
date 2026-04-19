"""WZU educational system scraper with session management."""

import json
import re
import time
from pathlib import Path

import httpx

from .crypto import aes_encrypt, generate_aes_key

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
                        c["name"], c["value"],
                        domain=c.get("domain", ""), path=c.get("path", "/"),
                    )
            except (json.JSONDecodeError, KeyError):
                pass

    def login_cas(self, username: str, password: str) -> bool:
        """Login to CAS and follow redirects into the educational system.

        Returns True if login succeeded.
        """
        service_url = f"{JWXT_BASE}/sso/zfiotlogin"
        login_url = f"{CAS_BASE}/login?service={service_url}"

        # Step 1: GET the login page to extract execution token and croypto key
        print("[*] Fetching CAS login page...")
        resp = self._client.get(login_url)
        resp.raise_for_status()
        html = resp.text

        # Check if cookies already got us logged in (CAS auto-redirected)
        if "jwglxt" in str(resp.url):
            print("[+] Already logged in via saved session!")
            self._logged_in = True
            return True

        # Extract execution token (Spring WebFlow)
        exec_match = re.search(r'id="login-page-flowkey"[^>]*>([^<]+)<', html)
        if not exec_match:
            print("[!] Failed to find execution token in login page")
            return False
        execution = exec_match.group(1).strip()

        # Extract the server's croypto key (used to verify we can encrypt)
        croypto_match = re.search(r'id="login-croypto"[^>]*>([^<]+)<', html)
        server_croypto = croypto_match.group(1).strip() if croypto_match else None

        print(f"[*] Got execution token ({len(execution)} chars)")
        print(f"[*] Server croypto: {server_croypto}")

        # Step 2: Generate our AES key and encrypt the password
        aes_key = generate_aes_key()
        import base64
        croypto_b64 = base64.b64encode(aes_key).decode("ascii")
        encrypted_password = aes_encrypt(aes_key, password)

        print(f"[*] Encrypted password, logging in as {username}...")

        # Step 3: POST login
        login_data = {
            "username": username,
            "type": "UsernamePassword",
            "_eventId": "submit",
            "geolocation": "",
            "execution": execution,
            "croypto": croypto_b64,
            "password": encrypted_password,
        }

        # Don't follow redirects for the POST - we need to handle the chain manually
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

        # Check if we ended up at the educational system
        final_url = str(post_resp.url)
        if "jwglxt" in final_url or "index" in final_url:
            print(f"[+] Login successful! Final URL: {final_url}")
            self._logged_in = True
            self._save_cookies()
            return True

        # Check for login failure (still on login page)
        if "/login" in final_url:
            # Try to extract error message
            err_match = re.search(r'class="[^"]*error[^"]*"[^>]*>([^<]+)<', post_resp.text)
            if err_match:
                print(f"[!] Login failed: {err_match.group(1).strip()}")
            else:
                print(f"[!] Login failed, redirected back to: {final_url}")
            return False

        print(f"[*] Ended at: {final_url}")
        # Might still be OK if we got cookies
        self._logged_in = True
        self._save_cookies()
        return True

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

        html = resp.text
        info = {}
        # Extract student name
        name_match = re.search(r'用户名[：:]\s*([^<\s]+)', html)
        if name_match:
            info["name"] = name_match.group(1)

        return info if info else {"raw_length": len(html), "url": str(resp.url)}

    def get_course_schedule(self, school_year: str = "2025-2026", semester: str = "2") -> list[dict]:
        """Fetch course schedule (课程表).

        Args:
            school_year: e.g. "2025-2026"
            semester: "1" for fall, "2" for spring, "3" for summer
        """
        # The 正方 system uses xnm (学年) and xqm (学期) parameters
        # xqm encoding: 3=fall(第1学期), 12=spring(第2学期), 16=summer(第3学期)
        xqm_map = {"1": "3", "2": "12", "3": "16"}
        xnm = school_year.split("-")[0]  # Use the start year

        resp = self._client.post(
            f"{JWXT_BASE}/jwglxt/kbcx/xskbcx_cxXsgrkb.html",
            params={"gnmkdm": "N2151"},
            data={"xnm": xnm, "xqm": xqm_map.get(semester, "12")},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        if resp.status_code != 200:
            print(f"[!] Failed to fetch schedule: {resp.status_code}")
            return []

        try:
            data = resp.json()
        except json.JSONDecodeError:
            print(f"[!] Response is not JSON (might need re-login)")
            return []

        courses = []
        for item in data.get("kbList", []):
            courses.append({
                "name": item.get("kcmc", ""),          # 课程名称
                "teacher": item.get("xm", ""),          # 教师
                "location": item.get("cdmc", ""),       # 教室
                "weekday": item.get("xqjmc", ""),       # 星期几
                "periods": item.get("jcor", ""),        # 第几节
                "weeks": item.get("zcd", ""),           # 周次
                "credit": item.get("xf", ""),           # 学分
            })

        return courses

    def get_grades(self, school_year: str = "2025-2026", semester: str = "2") -> list[dict]:
        """Fetch grades (成绩).

        Args:
            school_year: e.g. "2025-2026"
            semester: "1" for fall, "2" for spring. Use "" for all.
        """
        xqm_map = {"1": "3", "2": "12", "3": "16", "": ""}
        xnm = school_year.split("-")[0] if school_year else ""

        resp = self._client.post(
            f"{JWXT_BASE}/jwglxt/cjcx/cjcx_cxDgXscj.html",
            params={"doType": "query", "gnmkdm": "N305005"},
            data={
                "xnm": xnm,
                "xqm": xqm_map.get(semester, "12"),
                "queryModel.showCount": "100",
                "queryModel.currentPage": "1",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        if resp.status_code != 200:
            print(f"[!] Failed to fetch grades: {resp.status_code}")
            return []

        try:
            data = resp.json()
        except json.JSONDecodeError:
            print(f"[!] Response is not JSON")
            return []

        grades = []
        for item in data.get("items", []):
            grades.append({
                "name": item.get("kcmc", ""),       # 课程名称
                "grade": item.get("cj", ""),         # 成绩
                "gpa_point": item.get("jd", ""),     # 绩点
                "credit": item.get("xf", ""),        # 学分
                "category": item.get("kcxzmc", ""),  # 课程性质
                "type": item.get("kcbj", ""),        # 课程标记
            })

        return grades

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
