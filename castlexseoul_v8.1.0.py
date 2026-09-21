# golf_reserver.py  (v7 배포용: v6 + 로그인 검증 + EXE(frozen) 경로/리소스 처리 + 드라이버 안정화)
#
# 필수 설치(개발PC):
#   pip install selenium tkcalendar
# 권장(로고 안정/리사이즈):
#   pip install pillow
#
# 같은 폴더(개발 시): castlexseoul_v8.png (선택)
# EXE로 빌드 시: --add-data로 포함 권장
# 자동 생성: user_config.json, screenshots/

import os
import re
import sys
import ctypes
import base64
import json
import time
import queue
import threading
import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from ctypes import wintypes

from tkcalendar import DateEntry

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from urllib.request import Request, urlopen
from email.utils import parsedate_to_datetime

# 로고 안정 로딩(선택)
try:
    from PIL import Image, ImageTk  # type: ignore
    PIL_OK = True
except Exception:
    PIL_OK = False


# -----------------------------
# EXE(frozen) 경로 처리 (b)
# - 설정파일/스크린샷은 "exe가 있는 폴더"에 생성되게 함
# - castlexseoul_v8.png 등 리소스는 PyInstaller 임시폴더(_MEIPASS)도 지원
# -----------------------------
def app_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)  # exe가 있는 폴더
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(rel_path: str) -> str:
    """
    PyInstaller onefile 실행 시 리소스는 sys._MEIPASS에 풀림.
    개발 실행 시에는 스크립트 폴더에 있음.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)  # type: ignore
    return os.path.join(app_base_dir(), rel_path)


BASE_DIR = app_base_dir()
CONFIG_FILE = os.path.join(BASE_DIR, "user_config.json")
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.enc.json")
DEBUG_CAPTURE_ENABLED = False
if DEBUG_CAPTURE_ENABLED:
    SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
else:
    SCREENSHOT_DIR = ""

LOGIN_URL = "https://www.castlexseoul.com/html/member/login.asp"
RESERVE_URL = "https://www.castlexseoul.com/html/reserve/reserve01.asp"
APP_TITLE = "캐슬렉스 서울 예약"
APP_LOGO_PNG = "castlexseoul_v8.png"
APP_ICON_ICO = "castlexseoul_v8.ico"
APP_USER_MODEL_ID = "castlexseoul.castlexseoul_v810"
APP_VERSION = "8.1.5"
EMPTY_TIMES_TIMEOUT_SECONDS = 90.0
EMPTY_TIMES_RETRY_SECONDS = 2.0
TIME_STRATEGIES = {
    "nearest": "최근접 우선",
    "later": "늦은 시간 우선",
    "earlier": "빠른 시간 우선",
    "offset": "최근접에서 N칸 뒤",
}
MAX_SAVED_ACCOUNTS = 20
DPAPI_ENTROPY = b"CastlexSeoul_V8.1.0_Credentials"


# -----------------------------
# 공용 유틸
# -----------------------------
def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob_from_bytes(data: bytes):
    if not data:
        return _DataBlob(0, None), None
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    return blob, buf


def _dpapi_encrypt(plain_text: str) -> str:
    if os.name != "nt":
        raise RuntimeError("DPAPI is available only on Windows.")
    data_blob, data_buf = _blob_from_bytes(plain_text.encode("utf-8"))
    entropy_blob, entropy_buf = _blob_from_bytes(DPAPI_ENTROPY)
    out_blob = _DataBlob()

    try:
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(data_blob),
            "CastlexCredentials",
            ctypes.byref(entropy_blob),
            None,
            None,
            0,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise ctypes.WinError()
        enc_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return base64.b64encode(enc_bytes).decode("ascii")
    finally:
        if out_blob.pbData:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
        _ = data_buf, entropy_buf


def _dpapi_decrypt(cipher_text_b64: str) -> str:
    if os.name != "nt":
        raise RuntimeError("DPAPI is available only on Windows.")
    raw = base64.b64decode(cipher_text_b64.encode("ascii"))
    data_blob, data_buf = _blob_from_bytes(raw)
    entropy_blob, entropy_buf = _blob_from_bytes(DPAPI_ENTROPY)
    out_blob = _DataBlob()
    desc = wintypes.LPWSTR()

    try:
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(data_blob),
            ctypes.byref(desc),
            ctypes.byref(entropy_blob),
            None,
            None,
            0,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise ctypes.WinError()
        dec_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return dec_bytes.decode("utf-8")
    finally:
        if out_blob.pbData:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
        _ = data_buf, entropy_buf


def now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def build_time_options():
    # Preserve the existing endpoints while adding five-minute choices.
    options = []
    for h in range(5, 18):
        for m in range(0, 60, 5):
            if h < 17 or m <= 30:
                options.append(f"{h:02d}:{m:02d}")
    return options


# -----------------------------
# 서버시간(Date 헤더) 기반 대기
# -----------------------------
def get_server_utc_datetime(url: str) -> datetime.datetime:
    req = Request(url, method="HEAD")
    with urlopen(req, timeout=5) as resp:
        date_header = resp.headers.get("Date")
        if not date_header:
            raise RuntimeError("서버 Date 헤더를 읽지 못했습니다.")
        return parsedate_to_datetime(date_header)  # tz-aware (UTC)


def compute_server_offset_seconds(log_func, retries: int = 3) -> float:
    last_err = None
    for i in range(retries):
        try:
            server_dt = get_server_utc_datetime(RESERVE_URL)
            local_utc = datetime.datetime.now(datetime.timezone.utc)
            offset = (server_dt - local_utc).total_seconds()
            log_func(f"서버시간 동기화: offset = {offset:+.3f}s (server_utc - local_utc)")
            return offset
        except Exception as e:
            last_err = e
            log_func(f"서버시간 동기화 재시도 {i+1}/{retries} 실패: {e}")
            time.sleep(0.25)
    raise RuntimeError(f"서버시간 동기화 실패: {last_err}")


def wait_until_server_monday_0900(stop_event: threading.Event, log_func):
    """
    서버 Date 헤더 기반 offset으로 '월요일 09:00' 대기.
    - 한국에서 실행한다는 전제(로컬 타임존 기준 09:00)
    """
    log_func("실예약 모드: 서버시간(Date 헤더) 기준 대기 준비")
    try:
        offset = compute_server_offset_seconds(log_func, retries=3)
    except Exception as e:
        log_func(f"서버시간 동기화 실패 → 로컬시간으로 대기합니다. 이유: {e}")
        offset = None

    log_func("월요일 09:00 대기 시작")
    while not stop_event.is_set():
        if offset is None:
            check = datetime.datetime.now()
        else:
            local_utc = datetime.datetime.now(datetime.timezone.utc)
            server_like_utc = local_utc + datetime.timedelta(seconds=offset)
            check = server_like_utc.astimezone().replace(tzinfo=None)

        # Monday=0
        if check.weekday() == 0 and check.hour == 9 and check.minute == 0:
            log_func("09:00 도달! 예약 진행")
            return True

        time.sleep(0.10)

    return False
    
def wait_until_local_monday_0900(stop_event, log_func):
    log_func("실예약 모드: 로컬시간 기준 월요일 09:00 대기 시작")
    while not stop_event.is_set():
        now = datetime.datetime.now()
        if now.weekday() == 0 and now.hour == 9 and now.minute == 0:
            log_func("09:00 도달! 예약 진행")
            return True
        time.sleep(0.10)
    return False
   

# -----------------------------
# Selenium Bot
# -----------------------------
class CastlexBot:
    def __init__(self, stop_event: threading.Event, log_func):
        self.stop_event = stop_event
        self.log = log_func
        self.driver = None
        self.wait = None

    def _check_stop(self):
        if self.stop_event.is_set():
            raise RuntimeError("사용자가 중단했습니다.")

    def _screenshot(self, prefix="error"):
        if not DEBUG_CAPTURE_ENABLED or not SCREENSHOT_DIR:
            return
        try:
            path = os.path.join(SCREENSHOT_DIR, f"{prefix}_{now_stamp()}.png")
            self.driver.save_screenshot(path)
            self.log(f"스크린샷 저장: {path}")
        except Exception:
            pass

    def start_driver(self):
        """
        배포 안정성을 위해:
        - Selenium Manager(기본)로 먼저 시도 (selenium 4.6+)
        - 실패하면 webdriver-manager 방식으로 폴백
        """
        self.log("Chrome 실행 준비")
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("prefs", {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False
        })

        # 1) Selenium Manager(기본) 시도
        try:
            self.driver = webdriver.Chrome(options=options)
            self.wait = WebDriverWait(self.driver, 15)
            self.log("Chrome 실행 완료 (Selenium Manager)")
            return
        except Exception as e:
            self.log(f"Selenium Manager 실행 실패 → 폴백 시도: {e}")

        # 2) webdriver-manager 폴백 (개발/일부환경)
        try:
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=options
            )
            self.wait = WebDriverWait(self.driver, 15)
            self.log("Chrome 실행 완료 (webdriver-manager 폴백)")
            return
        except Exception as e:
            raise RuntimeError(f"ChromeDriver 실행 실패: {e}")

    def quit_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass

    # ---- 팝업(경고/확인) 처리 ----
    def _drain_one_alert_text(self, timeout=0.4):
        try:
            WebDriverWait(self.driver, timeout).until(EC.alert_is_present())
            alert = self.driver.switch_to.alert
            txt = alert.text
            alert.accept()
            return txt
        except Exception:
            return None

    def _drain_all_dialogs(self, max_loops=6):
        for _ in range(max_loops):
            txt = self._drain_one_alert_text(timeout=0.35)
            if not txt:
                break
            self.log(f"[팝업] {txt}")

    # ---- 로그인 (a: 로그인 검증 추가) ----
    def login(self, user_id: str, user_pw: str):
        self._check_stop()
        self.log("로그인 페이지 이동")
        self.driver.get(LOGIN_URL)

        self.log("아이디/비밀번호 입력")
        self.wait.until(EC.presence_of_element_located((By.ID, "user_id"))).clear()
        self.driver.find_element(By.ID, "user_id").send_keys(user_id)

        self.wait.until(EC.presence_of_element_located((By.ID, "user_pw"))).clear()
        self.driver.find_element(By.ID, "user_pw").send_keys(user_pw)

        self._check_stop()
        self.log("Login_Check() 실행(자바스크립트 로그인)")
        self.driver.execute_script("Login_Check();")

        # 로그인 검증 로직:
        # - 성공 시: LOGOUT 링크 등장 OR 로그인 폼 사라짐 OR 예약페이지로 이동 가능
        self.log("로그인 성공 여부 검증 중...")
        ok = self._wait_login_success(timeout=12)
        if not ok:
            self._screenshot("login_failed")
            raise RuntimeError("로그인 검증 실패: 아이디/비밀번호 또는 사이트 상태를 확인하세요.")
        self.log("로그인 완료(검증 성공)")

    def _wait_login_success(self, timeout=12) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            self._check_stop()
            try:
                # 1) LOGOUT 링크가 있으면 성공
                logout_links = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/html/member/logout.asp']")
                if logout_links:
                    return True

                # 2) 로그인 폼이 없어졌으면 성공(대략)
                login_form = self.driver.find_elements(By.CSS_SELECTOR, "form[name='loginForm'], #login_wrap")
                # login_wrap은 다른 페이지에도 있을 수 있어 100%는 아니지만 참고
                user_id_box = self.driver.find_elements(By.ID, "user_id")
                if (not user_id_box) and (not login_form):
                    return True

                # 3) 혹시 로그인 후 바로 다른 페이지로 리다이렉트 되었는지
                cur = (self.driver.current_url or "").lower()
                if "login.asp" not in cur:
                    # 로그인 페이지에서 벗어났다면 성공 가능성이 큼
                    return True

            except Exception:
                pass

            time.sleep(0.25)

        return False

    def go_reserve_page(self):
        self._check_stop()
        self.log("온라인예약 페이지 이동")
        self.driver.get(RESERVE_URL)
        time.sleep(0.8)
        self._drain_all_dialogs(max_loops=3)

    # ---- 예약 동작 ----
    def select_date_js(self, yyyymmdd: str):
        self._check_stop()
        self.log(f"날짜 선택: {yyyymmdd} (Date_Click)")
        self.driver.execute_script(f"Date_Click('B','{yyyymmdd}');")
        time.sleep(0.55)
        self._drain_all_dialogs(max_loops=3)

    def select_time_js(self, yyyymmdd: str, hhmm: str):
        self._check_stop()
        self.log(f"시간 선택 시도: {hhmm} (Book_Confirm)")
        self.driver.execute_script(f"Book_Confirm('{yyyymmdd}','B','1','OUT','{hhmm}','');")

        # confirm 영역이 뜨는지로 판정(좀 더 안정적으로 대기)
        try:
            WebDriverWait(self.driver, 6).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#confirm, button.btn_reOK"))
            )
            self._drain_all_dialogs(max_loops=3)
            return True
        except Exception:
            self._drain_all_dialogs(max_loops=3)
            return False

    # ---- 7분 단위 시간 리스트 읽기 ----
    def get_available_times_hhmm(self):
        self._check_stop()
        times = []
        anchors = self.driver.find_elements(By.CSS_SELECTOR, "#time a[href*='Book_Confirm']")
        for a in anchors:
            href = a.get_attribute("href") or ""
            found = re.findall(r"\'(\d{4})\'", href)
            for x in found:
                if x.isdigit() and len(x) == 4:
                    times.append(x)

        uniq = sorted(set(times), key=lambda t: int(t))
        self.log(f"가용 시간 {len(uniq)}개 감지")
        if uniq:
            self.log("감지된 전체 시간: " + ", ".join(uniq))
        return uniq

    def wait_for_available_times(self, date):
        available = self.get_available_times_hhmm()
        if available:
            return available

        started = time.monotonic()
        deadline = started + EMPTY_TIMES_TIMEOUT_SECONDS
        self.log(
            f"{date}: 가용 시간 0개 → 지연 오픈 대기 "
            f"(최대 {EMPTY_TIMES_TIMEOUT_SECONDS:.0f}초, 약 {EMPTY_TIMES_RETRY_SECONDS:.0f}초 간격 재조회)"
        )
        while True:
            self._check_stop()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.log(f"{date}: 지연 오픈 대기 종료 → 가용 시간 없음, 다음 순위로")
                return []
            self.stop_event.wait(min(EMPTY_TIMES_RETRY_SECONDS, remaining))
            self._check_stop()
            # Re-select the date to fetch newly opened times from the server.
            self.select_date_js(date)
            available = self.get_available_times_hhmm()
            if available:
                self.log(f"{date}: {time.monotonic() - started:.1f}초 대기 후 가용 시간 감지")
                return available

    def pick_times_by_windows(self, available_hhmm, base_time_hhmm, strategy="nearest", offset=2):
        """
        기준시간 근처부터 확장: ±30 → ±60 → ±120 (분)
        """
        h, m = map(int, base_time_hhmm.split(":"))
        target = h * 60 + m

        def to_min(hhmm):
            return int(hhmm[:2]) * 60 + int(hhmm[2:])

        avail_mins = [(t, to_min(t)) for t in available_hhmm]
        windows = [30, 60, 120]

        ordered = []
        for w in windows:
            cand = []
            for t, mins in avail_mins:
                diff = abs(mins - target)
                if diff <= w:
                    cand.append((diff, t))
            cand.sort(key=lambda x: x[0])
            for _, t in cand:
                if t not in ordered:
                    ordered.append(t)

        if strategy == "nearest" or not ordered:
            return ordered
        if strategy == "later":
            return ([t for t in ordered if to_min(t) >= target]
                    + [t for t in ordered if to_min(t) < target])
        if strategy == "earlier":
            return ([t for t in ordered if to_min(t) <= target]
                    + [t for t in ordered if to_min(t) > target])
        if strategy != "offset":
            raise ValueError("알 수 없는 시간 선택 전략입니다.")
        if not isinstance(offset, int) or not 1 <= offset <= 10:
            raise ValueError("회피 칸 수는 1~10 사이여야 합니다.")
        chronological = sorted(ordered, key=to_min)
        nearest_index = chronological.index(ordered[0])
        # Prefer later slots, then earlier slots, then the nearest and the rest.
        shifts = list(range(offset, 0, -1)) + list(range(-1, -offset - 1, -1)) + [0]
        preferred = [chronological[nearest_index + shift] for shift in shifts
                     if 0 <= nearest_index + shift < len(chronological)]
        return preferred + [t for t in ordered if t not in preferred]

    # ---- 예약하기 클릭 + 판정 ----
    def click_reserve_and_judge(self):
        self._check_stop()
        self.log("예약하기 버튼 클릭")
        btn = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn_reOK")))
        btn.click()

        txt_last = None
        for _ in range(10):
            txt = self._drain_one_alert_text(timeout=0.9)
            if not txt:
                break
            txt_last = txt
            self.log(f"[팝업] {txt}")

        if not txt_last:
            return "NO_ALERT", None

        if ("점검" in txt_last) or ("정비" in txt_last):
            return "MAINTENANCE", txt_last
        if ("이미" in txt_last) or ("불가" in txt_last) or ("다른예약" in txt_last) or ("불가능" in txt_last):
            return "DUPLICATE_OR_FAIL", txt_last
        if ("완료" in txt_last) or ("성공" in txt_last):
            return "SUCCESS_TEXT", txt_last

        return "OTHER_ALERT", txt_last

    # ---- 다건 예약 메인 ----
    def run_priorities_multi(self, mode: str, priorities: list, live_safety_block_submit: bool = False,
                             time_strategy="nearest", time_offset=2):
        success_list = []

        for idx, p in enumerate(priorities, start=1):
            self._check_stop()
            date = p["date"]
            base_time = p["base_time"]

            self.log(f"==== {idx}순위 시작: {date} / 기준 {base_time} ====")

            self.go_reserve_page()
            self.select_date_js(date)

            available = self.wait_for_available_times(date)
            if not available:
                continue

            candidates = self.pick_times_by_windows(available, base_time, time_strategy, time_offset)
            if not candidates:
                self.log("기준시간 주변(±30/60/120)에 후보가 없음 → 다음 순위로")
                continue

            self.log(f"시간 선택 전략: {time_strategy}, 회피 칸 수: {time_offset}")
            self.log("시간 후보(시도순): " + ", ".join(candidates))

            reserved = False

            for candidate_number, hhmm in enumerate(candidates, start=1):
                self._check_stop()
                self.log(f"{date}: 후보 {candidate_number}/{len(candidates)} 시도: {hhmm}")

                ok = self.select_time_js(date, hhmm)
                if not ok:
                    continue

                self.log(f"✅ 시간 선택 성공: {date} {hhmm}")

                # ✅ 테스트 모드 또는 실예약 안전 점검 모드: 클릭하지 않고 다음 순위로 진행
                if mode == "test" or live_safety_block_submit:
                    if mode == "test":
                        msg = "테스트 모드: 예약하기 클릭 전까지 OK → 다음 순위로 이동"
                        tag = "TEST_OK(before click)"
                    else:
                        msg = "실예약 안전 점검: 예약하기 클릭 차단(직전까지 점검) → 다음 순위로 이동"
                        tag = "SAFE_OK(before click)"
                    self.log(msg)
                    success_list.append((date, hhmm, tag))
                    reserved = True

                    # 다음 순위 시작 전에 화면을 초기화(안정성)
                    self.go_reserve_page()
                    break

                # ✅ 실제 예약 모드
                status, txt = self.click_reserve_and_judge()

                if status == "SUCCESS_TEXT":
                    self.log("✅ 예약 성공(팝업 텍스트 기반)")
                    success_list.append((date, hhmm, txt or "SUCCESS"))
                    reserved = True
                    break

                if status == "NO_ALERT":
                    self.log("✅ 예약 성공(추정): 팝업 없음")
                    success_list.append((date, hhmm, "SUCCESS(no alert)"))
                    reserved = True
                    break

                if status == "MAINTENANCE":
                    self.log("⚠️ 점검/정비 팝업 감지 → 전체 중단 권장")
                    return "MAINTENANCE", success_list
                
                # ✅ 성공 팝업 문구는 '성공'으로 처리해야 함
                if txt and ("정상적으로 처리" in txt and "예약" in txt):
                    success_list.append((date, hhmm, "SUCCESS(alert)"))
                    reserved = True
                    self.log(f"✅ 예약 성공(팝업): {date} {hhmm}")
                    break

                self.log(f"❌ 예약 실패/불가로 판단 → 다음 후보로 (msg={txt})")
                self.go_reserve_page()
                self.select_date_js(date)

            if reserved:
                self.log(f"==== {idx}순위 처리 완료 → 다음 순위 진행 ====")
            else:
                self.log(f"==== {idx}순위 실패(근접 후보 소진) → 다음 순위 ====")

        # ✅ 테스트 모드 결과
        if mode == "test":
            if success_list:
                self.log("===== 테스트 모드 결과 =====")
                for d, t, s in success_list:
                    self.log(f"- {d} {t} : {s}")
                return f"TEST_MULTI_OK({len(success_list)})", success_list
            return "TEST_ALL_FAILED", success_list

        if live_safety_block_submit:
            if success_list:
                self.log("===== 실예약 안전 점검 결과(클릭 차단) =====")
                for d, t, s in success_list:
                    self.log(f"- {d} {t} : {s}")
                return f"SAFE_MULTI_OK({len(success_list)})", success_list
            return "SAFE_ALL_FAILED", success_list

        # ✅ 실제 모드 결과
        if success_list:
            self.log("===== 다건 예약 결과 =====")
            for d, t, s in success_list:
                self.log(f"- {d} {t} : {s}")
            return f"REAL_MULTI_SUCCESS({len(success_list)})", success_list

        return "ALL_FAILED", success_list



# -----------------------------
# UI App
# -----------------------------
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1260x720")
        self.root.resizable(False, False)

        self.cfg = load_config()
        self.log_q = queue.Queue()
        self.log_path = None
        self._log_secrets = ()
        try:
            log_dir = os.path.join(BASE_DIR, "logs")
            os.makedirs(log_dir, exist_ok=True)
            self.log_path = os.path.join(log_dir, f"castlex_{now_stamp()}_{os.getpid()}.log")
            with open(self.log_path, "a", encoding="utf-8"):
                pass
            self.log(f"v{APP_VERSION} 로그 파일: {self.log_path}")
        except OSError:
            self.log_path = None
            self.log("로그 파일을 만들 수 없습니다. 화면 로그만 표시합니다.")
        self.stop_event = threading.Event()
        self.saved_accounts = []
        self._cred_error_shown = False

        self.logo_ref = None
        self.window_icon_ref = None

        self._load_credentials()
        self._build_ui()
        self._tick_log()

    
    def _find_resource_candidates(self, filename: str):
        candidates = [resource_path(filename)]
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else app_base_dir()
        candidates.append(os.path.join(exe_dir, filename))
        # Deduplicate while preserving order.
        return [p for i, p in enumerate(candidates) if p and p not in candidates[:i]]

    def _apply_window_icon(self):
        icon_applied = False

        for icon_path in self._find_resource_candidates(APP_ICON_ICO):
            if not os.path.exists(icon_path):
                continue
            try:
                self.root.iconbitmap(icon_path)
                icon_applied = True
                break
            except Exception:
                continue

        for png_path in self._find_resource_candidates(APP_LOGO_PNG):
            if not os.path.exists(png_path):
                continue
            try:
                self.window_icon_ref = tk.PhotoImage(file=png_path)
                self.root.iconphoto(True, self.window_icon_ref)
                icon_applied = True
                break
            except Exception:
                continue

        if not icon_applied:
            self.log(f"아이콘 적용 실패: {APP_ICON_ICO} / {APP_LOGO_PNG} 파일을 찾지 못했습니다.")
    def log(self, msg: str):
        for secret in self._log_secrets:
            if secret:
                msg = msg.replace(secret, "[REDACTED]")
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.log_q.put(f"[{ts}] {msg}")

    def _build_ui(self):
        top = tk.Frame(self.root)
        top.pack(fill="x", padx=10, pady=8)

        # 로고: 개발 시엔 BASE_DIR/castlexseoul_v8.png, exe 시엔 _MEIPASS/castlexseoul_v8.png
        logo_path = resource_path(APP_LOGO_PNG)
        if os.path.exists(logo_path):
            try:
                if PIL_OK:
                    img = Image.open(logo_path)
                    img = img.resize((160, 50))
                    self.logo_ref = ImageTk.PhotoImage(img)
                else:
                    self.logo_ref = tk.PhotoImage(file=logo_path)
                tk.Label(top, image=self.logo_ref).pack(side="left")
            except Exception as e:
                self.log(f"로고 로드 실패: {e} (castlexseoul_v8.png 포맷/경로 확인)")
        else:
            self.log("castlexseoul_v8.png 없음(선택). exe 빌드시 --add-data로 포함 가능")

        tk.Label(top, text=APP_TITLE, font=("맑은고딕", 16, "bold")).pack(side="left", padx=10)

        main = tk.Frame(self.root)
        main.pack(fill="both", expand=True, padx=10, pady=8)

        left = tk.Frame(main)
        left.pack(side="left", fill="y")

        right = tk.Frame(main)
        right.pack(side="right", fill="both", expand=True, padx=(10, 0))

        # 로그인 정보
        login_box = ttk.LabelFrame(left, text="로그인 정보")
        login_box.pack(fill="x", pady=(0, 10))

        ttk.Label(login_box, text="아이디").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        self.id_var = tk.StringVar(value=self.cfg.get("id", ""))
        self.id_entry = ttk.Combobox(login_box, textvariable=self.id_var, width=21)
        self.id_entry.grid(row=0, column=1, padx=6, pady=6, sticky="w")
        self.id_entry.bind("<<ComboboxSelected>>", self._on_id_selected)
        self.id_entry.bind("<FocusOut>", self._on_id_focus_out)
        self.btn_delete_id = ttk.Button(login_box, text="삭제", width=6, command=self._delete_selected_account)
        self.btn_delete_id.grid(row=0, column=2, padx=(0, 6), pady=6, sticky="w")

        ttk.Label(login_box, text="비밀번호").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        self.pw_var = tk.StringVar(value="")
        self.pw_entry = ttk.Entry(login_box, textvariable=self.pw_var, width=24, show="*")
        self.pw_entry.grid(row=1, column=1, padx=6, pady=6)

        self.show_pw = tk.BooleanVar(value=False)
        ttk.Checkbutton(login_box, text="비밀번호 표시", variable=self.show_pw, command=self._toggle_pw)\
            .grid(row=2, column=1, padx=6, pady=(0, 4), sticky="w")

        self.remember_var = tk.BooleanVar(value=self.cfg.get("remember", True))
        ttk.Checkbutton(login_box, text="아이디/비밀번호 기억", variable=self.remember_var)\
            .grid(row=3, column=1, padx=6, pady=(0, 8), sticky="w")
        self._refresh_id_dropdown()
        default_id = self.cfg.get("id", "").strip()
        if default_id:
            self.id_var.set(default_id)
            self._autofill_password_for_id(default_id)
        elif self.saved_accounts and self.remember_var.get():
            first_id = self.saved_accounts[0].get("user_id", "")
            if first_id:
                self.id_var.set(first_id)
                self._autofill_password_for_id(first_id)

        # 실행 모드
        mode_box = ttk.LabelFrame(left, text="실행 모드")
        mode_box.pack(fill="x", pady=(0, 10))

        self.mode_var = tk.StringVar(value=self.cfg.get("mode", "test"))
        ttk.Radiobutton(
            mode_box,
            text="테스트 모드 (예약하기 전에서 멈춤)",
            variable=self.mode_var,
            value="test",
            command=self._on_mode_change
        ).pack(anchor="w", padx=8, pady=4)

        ttk.Radiobutton(
            mode_box,
            text="실제 예약 모드 (월요일 09:00 대기, 서버시간 기준)",
            variable=self.mode_var,
            value="real",
            command=self._on_mode_change
        ).pack(anchor="w", padx=8, pady=4)
      
        # 서버시간 대기 옵션(실제 예약 모드에서만 사용)
        self.wait_server_var = tk.BooleanVar(value=self.cfg.get("wait_server", True))

        self.wait_chk = tk.Checkbutton(
            mode_box,
            text="서버시간 09:00까지 대기 (실제 예약 모드에서만)",
            variable=self.wait_server_var,
            command=self._on_wait_server_change
        )
        self.wait_chk.pack(anchor="w", padx=8, pady=(2, 6))

        self.live_safe_var = tk.BooleanVar(value=self.cfg.get("live_safety_block_submit", True))
        self.live_safe_chk = tk.Checkbutton(
            mode_box,
            text="실예약 안전 점검 (예약 클릭 차단)",
            variable=self.live_safe_var,
            command=self._on_live_safe_change
        )
        self.live_safe_chk.pack(anchor="w", padx=8, pady=(0, 6))

        # 예약 우선순위 1~3
        prio_box = ttk.LabelFrame(left, text="예약 우선순위 (1→2→3 순서, 다건 예약)")
        prio_box.pack(fill="x")

        time_opts = build_time_options()

        self.prio_enabled = []
        self.prio_date = []
        self.prio_time = []

        prio_cfg = self.cfg.get("prio", {})

        for i in range(3):
            rowf = tk.Frame(prio_box)
            rowf.pack(fill="x", padx=8, pady=6)

            en = tk.BooleanVar(value=prio_cfg.get(str(i+1), {}).get("enabled", True))
            self.prio_enabled.append(en)
            ttk.Checkbutton(
                rowf,
                text=f"{i+1}순위 사용",
                variable=en,
                command=lambda idx=i: self._on_prio_enabled_change(idx),
            ).pack(side="left")

            dflt_date = prio_cfg.get(str(i+1), {}).get("date")
            de = DateEntry(rowf, width=10, date_pattern="yyyy-mm-dd", showweeknumbers=False)
            if dflt_date:
                try:
                    date_format = "%Y-%m-%d" if "-" in dflt_date else "%Y%m%d"
                    de.set_date(datetime.datetime.strptime(dflt_date, date_format).date())
                except Exception:
                    pass
            de.pack(side="left", padx=6)
            self.prio_date.append(de)

            dflt_time = prio_cfg.get(str(i+1), {}).get("time", "08:30")
            cb = ttk.Combobox(rowf, values=time_opts, state="readonly", width=7)
            cb.set(dflt_time if dflt_time in time_opts else "")
            cb.pack(side="left", padx=6)
            self.prio_time.append(cb)

            if not en.get():
                self._clear_prio_inputs(i)
            self._apply_prio_enabled_state(i)

        strategy_row = ttk.Frame(left)
        strategy_row.pack(fill="x", pady=(8, 0))
        ttk.Label(strategy_row, text="시간 전략").pack(side="left")
        strategy = self.cfg.get("time_strategy", "nearest")
        self.time_strategy_var = tk.StringVar(value=TIME_STRATEGIES.get(strategy, TIME_STRATEGIES["nearest"]))
        self.strategy_combo = ttk.Combobox(strategy_row, values=list(TIME_STRATEGIES.values()),
                                           textvariable=self.time_strategy_var, state="readonly", width=21)
        self.strategy_combo.pack(side="left", padx=6)
        self.strategy_combo.bind("<<ComboboxSelected>>", self._on_strategy_change)
        offset = self.cfg.get("time_offset", 2)
        if not isinstance(offset, int) or not 1 <= offset <= 10:
            offset = 2
        self.time_offset_var = tk.StringVar(value=str(offset))
        self.offset_spin = ttk.Spinbox(strategy_row, from_=1, to=10, width=3,
                                      textvariable=self.time_offset_var)
        self.offset_spin.pack(side="left")
        ttk.Label(strategy_row, text="칸").pack(side="left", padx=3)
        self._on_strategy_change()

        # 버튼
        btn_row = tk.Frame(left)
        btn_row.pack(fill="x", pady=10)

        self.btn_start = ttk.Button(btn_row, text="예약 시작", command=self.on_start)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_stop = ttk.Button(btn_row, text="중단", command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(left, textvariable=self.status_var, foreground="#1f4e79").pack(anchor="w")

        # 실행 로그
        log_box = ttk.LabelFrame(right, text="실행 로그")
        log_box.pack(fill="both", expand=True)

        self.log_text = tk.Text(log_box, wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_text.configure(state="disabled")

        tip = ttk.Label(
            right,
            text="팁: 테스트 모드/실예약 안전 점검은 예약 클릭을 차단합니다. 실예약은 매우 주의!",
            foreground="#444"
        )
        tip.pack(anchor="w", pady=(6, 0))
        self._on_mode_change()
        footer = tk.Label(
            self.root,
              text=f"Castlex C.C Reservation Tool v{APP_VERSION}\n© 2026. Dev. by Armatech",
              font=("Arial", 10, "italic"),
             fg="gray"
        )
        footer.pack(side="bottom", anchor="w", padx=10, pady=5)

    def _on_strategy_change(self, _event=None):
        self.offset_spin.configure(state="readonly" if self.time_strategy_var.get() == TIME_STRATEGIES["offset"]
                                   else "disabled")

    def _on_mode_change(self):
        # 테스트 모드에서는 실예약 옵션을 비활성화
        if self.mode_var.get() == "test":
            self.wait_server_var.set(False)
            self.live_safe_var.set(True)
            self.wait_chk.configure(state="disabled")
            self.live_safe_chk.configure(state="disabled")
        else:
            self.wait_chk.configure(state="normal")
            self.live_safe_chk.configure(state="normal")
            self._enforce_mode_option_exclusive(prefer="safe")

    def _enforce_mode_option_exclusive(self, prefer: str = "safe"):
        if self.wait_server_var.get() and self.live_safe_var.get():
            if prefer == "wait":
                self.live_safe_var.set(False)
            else:
                self.wait_server_var.set(False)

    def _on_wait_server_change(self):
        if self.mode_var.get() == "test":
            self.wait_server_var.set(False)
            return
        if self.wait_server_var.get():
            self.live_safe_var.set(False)

    def _on_live_safe_change(self):
        if self.mode_var.get() == "test":
            self.live_safe_var.set(True)
            return
        if self.live_safe_var.get():
            self.wait_server_var.set(False)

    def _toggle_pw(self):
        self.pw_entry.configure(show="" if self.show_pw.get() else "*")

    def _get_prio_date_text(self, index: int) -> str:
        return self.prio_date[index].get().strip()

    def _clear_prio_inputs(self, index: int):
        self.prio_date[index].delete(0, "end")
        self.prio_time[index].set("")

    def _apply_prio_enabled_state(self, index: int):
        enabled = bool(self.prio_enabled[index].get())
        state = "readonly" if enabled else "disabled"
        try:
            self.prio_date[index].configure(state=state)
        except Exception:
            pass
        try:
            self.prio_time[index].configure(state=state)
        except Exception:
            pass

    def _on_prio_enabled_change(self, index: int):
        if not self.prio_enabled[index].get():
            self._clear_prio_inputs(index)
        self._apply_prio_enabled_state(index)

    def _show_cred_warn_once(self, msg: str):
        if self._cred_error_shown:
            return
        self._cred_error_shown = True
        try:
            messagebox.showwarning("계정 저장", msg)
        except Exception:
            pass

    def _load_credentials(self):
        self.saved_accounts = []
        if not os.path.exists(CREDENTIALS_FILE):
            return
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)

            loaded = []
            for row in payload.get("accounts", []):
                uid_enc = row.get("user_id_enc", "")
                pw_enc = row.get("password_enc", "")
                if not uid_enc or not pw_enc:
                    continue
                uid = _dpapi_decrypt(uid_enc)
                pw = _dpapi_decrypt(pw_enc)
                if not uid:
                    continue
                loaded.append({
                    "user_id": uid,
                    "password": pw,
                    "updated_at": int(row.get("updated_at", 0)),
                })

            loaded.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
            self.saved_accounts = loaded[:MAX_SAVED_ACCOUNTS]
        except Exception:
            self.saved_accounts = []

    def _persist_credentials(self):
        payload = {"version": 1, "accounts": []}
        for acc in self.saved_accounts[:MAX_SAVED_ACCOUNTS]:
            uid = acc.get("user_id", "").strip()
            pw = acc.get("password", "")
            if not uid or not pw:
                continue
            payload["accounts"].append({
                "user_id_enc": _dpapi_encrypt(uid),
                "password_enc": _dpapi_encrypt(pw),
                "updated_at": int(acc.get("updated_at", int(time.time()))),
            })

        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _refresh_id_dropdown(self):
        ids = [acc["user_id"] for acc in self.saved_accounts if acc.get("user_id")]
        try:
            self.id_entry.configure(values=ids)
            self.btn_delete_id.configure(state="normal" if ids else "disabled")
        except Exception:
            pass

    def _find_saved_account(self, user_id: str):
        uid = (user_id or "").strip()
        if not uid:
            return None
        for acc in self.saved_accounts:
            if acc.get("user_id") == uid:
                return acc
        return None

    def _autofill_password_for_id(self, user_id: str) -> bool:
        acc = self._find_saved_account(user_id)
        if not acc:
            return False
        self.pw_var.set(acc.get("password", ""))
        return True

    def _on_id_selected(self, _evt=None):
        self._autofill_password_for_id(self.id_var.get())

    def _on_id_focus_out(self, _evt=None):
        uid = self.id_var.get().strip()
        if uid and not self.pw_var.get().strip():
            self._autofill_password_for_id(uid)

    def _remember_credentials(self, user_id: str, password: str):
        uid = (user_id or "").strip()
        pw = password or ""
        if not uid or not pw:
            return
        try:
            rest = [acc for acc in self.saved_accounts if acc.get("user_id") != uid]
            rest.insert(0, {"user_id": uid, "password": pw, "updated_at": int(time.time())})
            self.saved_accounts = rest[:MAX_SAVED_ACCOUNTS]
            self._persist_credentials()
            self._refresh_id_dropdown()
        except Exception:
            self._show_cred_warn_once("아이디/비밀번호 암호화 저장에 실패했습니다.")

    def _delete_selected_account(self):
        uid = self.id_var.get().strip()
        if not uid:
            messagebox.showinfo("계정 삭제", "삭제할 아이디를 먼저 선택해 주세요.")
            return
        if not self._find_saved_account(uid):
            messagebox.showinfo("계정 삭제", "저장된 목록에 없는 아이디입니다.")
            return

        ok = messagebox.askyesno("계정 삭제", f"'{uid}' 계정을 저장 목록에서 삭제할까요?")
        if not ok:
            return

        try:
            self.saved_accounts = [acc for acc in self.saved_accounts if acc.get("user_id") != uid]
            self._persist_credentials()
            self._refresh_id_dropdown()

            if self.saved_accounts:
                first_id = self.saved_accounts[0]["user_id"]
                self.id_var.set(first_id)
                self._autofill_password_for_id(first_id)
            else:
                self.id_var.set("")
                self.pw_var.set("")
        except Exception:
            self._show_cred_warn_once("저장 계정 삭제에 실패했습니다.")

    def _tick_log(self):
        lines = []
        try:
            for _ in range(200):
                lines.append(self.log_q.get_nowait())
        except queue.Empty:
            pass
        if lines:
            if self.log_path:
                try:
                    with open(self.log_path, "a", encoding="utf-8") as stream:
                        stream.write("\n".join(lines) + "\n")
                except OSError:
                    self.log_path = None
                    lines.append("로그 파일 저장 실패: 화면 로그만 표시합니다.")
            self.log_text.configure(state="normal")
            self.log_text.insert("end", "\n".join(lines) + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(120, self._tick_log)

    def _set_running(self, running: bool):
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")

    def _save_ui_config(self):
        prio = {}
        for i in range(3):
            enabled = bool(self.prio_enabled[i].get())
            prio[str(i+1)] = {
                "enabled": enabled,
                "date": self.prio_date[i].get().strip() if enabled else "",
                "time": self.prio_time[i].get().strip() if enabled else ""
            }

        data = {
            "id": self.id_var.get().strip(),
            "remember": bool(self.remember_var.get()),
            "mode": self.mode_var.get(),
            "wait_server": bool(self.wait_server_var.get()),
            "live_safety_block_submit": bool(self.live_safe_var.get()),
            "time_strategy": self._selected_time_strategy(),
            "time_offset": int(self.time_offset_var.get()),
            "prio": prio
        }
        save_config(data)

    def _selected_time_strategy(self):
        return next(key for key, label in TIME_STRATEGIES.items() if label == self.time_strategy_var.get())

    def _build_run_config(self):
        user_id = self.id_var.get().strip()
        user_pw = self.pw_var.get()
        if user_id and not user_pw:
            self._autofill_password_for_id(user_id)
            user_pw = self.pw_var.get()

        if not user_id:
            raise ValueError("아이디를 입력하세요.")
        if not user_pw:
            raise ValueError("비밀번호를 입력하세요.")

        priorities = []
        for i in range(3):
            if self.prio_enabled[i].get():
                date_text = self._get_prio_date_text(i)
                t = self.prio_time[i].get().strip()
                if not date_text:
                    raise ValueError(f"{i+1}순위 날짜를 선택하세요.")
                if not t:
                    raise ValueError(f"{i+1}순위 시간을 선택하세요.")
                try:
                    d = datetime.datetime.strptime(date_text, "%Y-%m-%d").strftime("%Y%m%d")
                except ValueError:
                    raise ValueError(f"{i+1}순위 날짜 형식이 올바르지 않습니다.")
                priorities.append({"date": d, "base_time": t})

        if not priorities:
            raise ValueError("최소 1개 이상 우선순위를 '사용'으로 체크하세요.")

        offset = int(self.time_offset_var.get())
        if not 1 <= offset <= 10:
            raise ValueError("회피 칸 수는 1~10 사이여야 합니다.")

        return {
            "id": user_id,
            "pw": user_pw,
            "mode": self.mode_var.get(),
            "wait_server": bool(self.wait_server_var.get()),
            "live_safety_block_submit": bool(self.live_safe_var.get()),
            "time_strategy": self._selected_time_strategy(),
            "time_offset": offset,
            "priorities": priorities
        }

    def on_start(self):
        try:
            cfg = self._build_run_config()
        except Exception as e:
            messagebox.showwarning("입력 오류", str(e))
            return

        if bool(self.remember_var.get()):
            self._remember_credentials(cfg.get("id", ""), cfg.get("pw", ""))
        self._save_ui_config()
        self.stop_event.clear()
        self._set_running(True)
        self.status_var.set("실행 중... (로그 확인)")

        threading.Thread(target=self._worker_main, args=(cfg,), daemon=True).start()

    def on_stop(self):
        self.stop_event.set()
        self.log("중단 요청")
        self.status_var.set("중단 요청됨... 브라우저 종료 중")
        self.btn_stop.configure(state="disabled")

    def _worker_main(self, cfg):
        self._log_secrets = (cfg.get("pw", ""), cfg.get("id", ""))
        bot = CastlexBot(self.stop_event, self.log)
        result = None
        success_list = []

        try:
            self.log("===== 작업 시작 =====")
            bot.start_driver()
            bot.login(cfg["id"], cfg["pw"])
            bot.go_reserve_page()
            self.log(
                f"[DEBUG] cfg.mode={cfg.get('mode')} "
                f"wait_server={cfg.get('wait_server')} "
                f"safe={cfg.get('live_safety_block_submit')}"
            )

           # ✅ 실예약 모드에서만 대기 수행 (테스트 모드에서는 절대 대기 없음)
            if cfg.get("mode") == "real" and cfg.get("wait_server", True):
                use_server = cfg.get("wait_server", True)  # 값이 없으면 기본 True(서버시간)

                if use_server:
                    ok = wait_until_server_monday_0900(self.stop_event, self.log)
                else:
                    ok = wait_until_local_monday_0900(self.stop_event, self.log)

                if not ok:
                    self.log("중단됨(대기 중)")
                    self.status_var.set("중단됨")
                    return

            result, success_list = bot.run_priorities_multi(
                cfg["mode"],
                cfg["priorities"],
                live_safety_block_submit=bool(cfg.get("live_safety_block_submit", False)),
                time_strategy=cfg.get("time_strategy", "nearest"),
                time_offset=cfg.get("time_offset", 2)
            )
            if str(result).startswith("TEST_MULTI_OK"):
                self.status_var.set(f"테스트 완료 {len(success_list)}건(예약 직전까지)")
            elif result == "TEST_ALL_FAILED":
                self.status_var.set("테스트 실패: 모두 진입 실패")
            elif str(result).startswith("SAFE_MULTI_OK"):
                self.status_var.set(f"안전 점검 완료 {len(success_list)}건(실제 클릭 차단)")
            elif result == "SAFE_ALL_FAILED":
                self.status_var.set("안전 점검 실패: 모두 진입 실패")

            if result == "TEST_SUCCESS":
                self.status_var.set("테스트 성공(예약 직전까지)")
            elif str(result).startswith("REAL_MULTI_SUCCESS"):
                self.status_var.set(f"실예약 성공 {len(success_list)}건")
            elif result == "MAINTENANCE":
                self.status_var.set("점검 팝업 감지(중단)")
            elif result == "ALL_FAILED":
                self.status_var.set("실패: 모든 우선순위 실패")
            else:
                self.status_var.set(f"종료: {result}")

            self.log(f"===== 작업 종료: {result} =====")

        except Exception as e:
            if self.stop_event.is_set():
                self.status_var.set("중단됨")
                self.log("사용자 요청으로 작업을 중단했습니다.")
            else:
                self.status_var.set("에러 발생")
                self.log(f"❌ 에러: {e}")
                try:
                    bot._screenshot("exception")
                except Exception:
                    pass
                messagebox.showerror("에러", str(e))

        finally:
            try:
                if self.stop_event.is_set() or self.status_var.get() == "에러 발생":
                    bot.quit_driver()
            except Exception:
                pass
            self._set_running(False)


if __name__ == "__main__":
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass
    root = tk.Tk()
    try:
        style = ttk.Style()
        # Windows에서는 vista / winnative가 체크박스(✓) 표시가 가장 직관적
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "winnative" in style.theme_names():
            style.theme_use("winnative")
        else:
            style.theme_use(style.theme_names()[0])
    except Exception:
        pass
    app = App(root)
    app._apply_window_icon()
    root.mainloop()

