import time
import subprocess
import os
import pyautogui
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from luna_server_secrets import load_secret
from luna_server_secrets import save_secret
save_secret("hanbat_portal", "학번", "비밀번호")

BASE_DIR = Path(__file__).resolve().parent
AUTH_DIR = BASE_DIR / "data" / "auth_states"
AUTH_DIR.mkdir(parents=True, exist_ok=True)

PROFILE_DIR = BASE_DIR / "data" / "profiles"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

LUNA_CHROME_PROFILE = BASE_DIR / "data" / "luna_chrome_profile"
LUNA_CHROME_PROFILE.mkdir(parents=True, exist_ok=True)

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

SITE_CONFIGS = {
    "github": {
        "login_type": "manual_google_bootstrap",
        "login_url": "https://github.com/login",
        "home_url": "https://github.com",
        "success_check_selector": 'summary[aria-label="View profile and more"]',
        "storage_state": str(AUTH_DIR / "github_state.json"),
        "persistent_profile_dir": str(PROFILE_DIR / "github_profile"),
        "browser_channel": "chrome",
    },
    "naver": {
        "login_type": "native",
        "login_url": "https://nid.naver.com/nidlogin.login",
        "home_url": "https://www.naver.com",
        "username_selector": "#id",
        "password_selector": "#pw",
        "submit_selector": "#log\\.login",
        "success_check_selector": ".MyView-module__my_info___GHKqS, .gnb_my_namebox",
        "storage_state": str(AUTH_DIR / "naver_state.json"),
    },
    "hanbat_portal": {
        "login_type": "native",
        "login_url": "https://www.hanbat.ac.kr/kor/login.do",
        "home_url": "https://www.hanbat.ac.kr/kor/",
        "username_selector": "input[type='text']",
        "password_selector": "input[type='password']",
        "submit_selector": "button, input[type='submit']",
        "success_check_selector": "text=로그아웃",
        "storage_state": str(AUTH_DIR / "hanbat_portal_state.json"),
    },
}

def find_chrome_path():
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    return None


def open_luna_chrome(url: str = "https://eclass.hanbat.ac.kr/"):
    chrome = find_chrome_path()
    if not chrome:
        return False, "Chrome 실행 파일을 찾지 못했어."

    subprocess.Popen([
        chrome,
        f"--user-data-dir={str(LUNA_CHROME_PROFILE)}",
        "--profile-directory=Default",
        "--start-maximized",
        url,
    ])

    time.sleep(4)

    try:
        import pyautogui

        pyautogui.hotkey("alt", "tab")
        time.sleep(0.5)

        screen_w, screen_h = pyautogui.size()

        while True:
            print(pyautogui.position())
            time.sleep(1)

        pyautogui.alert("이제 마우스를 움직일게")
        pyautogui.moveTo(x, y, duration=0.6)
        time.sleep(1.0)
        pyautogui.click(x, y)

        return True, "루나 전용 크롬을 열고 통합 로그인 버튼 위치를 눌렀어."

    except Exception as e:
        return True, f"크롬은 열었지만 자동 클릭은 실패했어: {e}"

def wait_for_login_success(page, config, timeout=180000):
    """
    로그인 성공을 더 느슨하게 판정
    1. 성공 selector
    2. 홈 URL로 이동했는지
    둘 중 하나만 되면 성공으로 본다
    """
    success_selector = config.get("success_check_selector")
    home_url = config.get("home_url", "")

    # 1) selector 우선 확인
    if success_selector:
        try:
            page.locator(success_selector).first.wait_for(timeout=5000)
            return True
        except Exception:
            pass

    # 2) URL 변화 확인
    try:
        page.wait_for_url("**", timeout=5000)
        current_url = page.url.lower()
        if home_url and home_url.replace("https://", "").replace("http://", "") in current_url:
            return True
    except Exception:
        pass

    # 3) 조금 더 기다리면서 다시 확인
    end_time = time.time() + (timeout / 1000)
    while time.time() < end_time:
        try:
            if success_selector:
                try:
                    loc = page.locator(success_selector)
                    if loc.count() > 0:
                        return True
                except Exception:
                    pass

            current_url = page.url.lower()
            if home_url and home_url.replace("https://", "").replace("http://", "") in current_url:
                return True

        except Exception:
            pass

        page.wait_for_timeout(1000)

    return False

def login_site(site_key: str, headed: bool = True):
    config = SITE_CONFIGS.get(site_key)
    if not config:
        return False, f"{site_key} 사이트 설정이 없어."

    login_type = config.get("login_type", "native")

    if login_type == "manual_google_bootstrap":
        return bootstrap_manual_login(site_key, headed=headed)

    username, password = load_secret(site_key)
    if not username or not password:
        return False, f"{site_key} 계정 정보가 저장되어 있지 않아."

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed)
            context = browser.new_context()
            page = context.new_page()

            page.goto(config["login_url"], wait_until="domcontentloaded")
            page.locator(config["username_selector"]).fill(username)
            page.locator(config["password_selector"]).fill(password)
            page.locator(config["submit_selector"]).click()

            # 사람 인증/추가 인증 시간 충분히 줌
            success = wait_for_login_success(page, config, timeout=120000)

            if not success:
                browser.close()
                return False, f"{site_key} 로그인 성공 확인을 못 했어."

            # 성공으로 판단되면 상태 저장
            context.storage_state(path=config["storage_state"])
            browser.close()
            return True, f"{site_key} 로그인 성공했고 인증 상태도 저장했어."

    except PlaywrightTimeoutError:
        return False, f"{site_key} 로그인 완료를 3분 안에 확인하지 못했어."
    except Exception as e:
        return False, f"{site_key} 로그인 중 오류가 났어: {e}"


def bootstrap_manual_login(site_key: str, headed: bool = True):
    config = SITE_CONFIGS.get(site_key)
    if not config:
        return False, f"{site_key} 사이트 설정이 없어."

    if not headed:
        return False, "수동 로그인 저장은 headed=True 상태에서만 가능해."

    profile_dir = config.get("persistent_profile_dir")
    channel = config.get("browser_channel", "chrome")

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
                channel=channel,
                args=[
                    "--disable-blink-features=AutomationControlled"
                ],
            )

            page = context.new_page()

            # 한밭대 LMS는 반드시 메인 → 통합 로그인 순서로 진입
            if site_key == "hanbat_lms":
                page.goto("https://eclass.hanbat.ac.kr/", wait_until="domcontentloaded")
                page.wait_for_timeout(1500)

                # 통합 로그인 버튼/링크를 더 정확하게 클릭
                page.wait_for_timeout(2000)

                clicked = False

                # 1) 버튼 텍스트 클릭 시도
                try:
                    page.get_by_text("통합 로그인").first.click(timeout=5000)
                    clicked = True
                except Exception:
                    pass

                # 2) 실패하면 로그인 링크 직접 찾기
                if not clicked:
                    try:
                        links = page.locator("a").all()
                        for link in links:
                            text = (link.inner_text(timeout=1000) or "").strip()
                            href = link.get_attribute("href")
                            if "통합 로그인" in text or (href and "login" in href.lower()):
                                link.click(timeout=5000)
                                clicked = True
                                break
                    except Exception:
                        pass

                # 3) 그래도 실패하면 오른쪽 로그인 버튼 클릭
                if not clicked:
                    try:
                        page.locator("a[href*='login']").first.click(timeout=5000)
                        clicked = True
                    except Exception:
                        pass

                if not clicked:
                    context.close()
                    return False, "통합 로그인 버튼을 못 찾았어."

                # 여기서 사용자가 직접 로그인할 시간 줌
                end_time = time.time() + 180
                success = False

                while time.time() < end_time:
                    current_url = page.url.lower()

                    try:
                        if page.get_by_text("로그아웃").count() > 0:
                            success = True
                            break
                    except Exception:
                        pass

                    # INVALID_ACCESS면 바로 실패 처리
                    try:
                        if page.get_by_text("invalid_access", exact=False).count() > 0:
                            context.close()
                            return False, "LMS가 비정상 접근으로 막았어. 통합 로그인 버튼 클릭 경로를 다시 확인해야 해."
                    except Exception:
                        pass

                    page.wait_for_timeout(1000)

                if not success:
                    context.close()
                    return False, "hanbat_lms 로그인 성공 확인을 못 했어."

                context.storage_state(path=config["storage_state"])
                context.close()
                return True, "hanbat_lms 로그인 상태를 저장했어. 다음부터는 자동으로 열 수 있어."

            # 다른 사이트 기존 방식
            page.goto(config["login_url"], wait_until="domcontentloaded")

            success = wait_for_login_success(page, config, timeout=180000)

            if not success:
                context.close()
                return False, f"{site_key} 로그인 성공 확인을 못 했어."

            context.storage_state(path=config["storage_state"])
            context.close()

            return True, f"{site_key} 로그인 상태를 저장했어. 다음부터는 자동으로 열 수 있어."

    except PlaywrightTimeoutError:
        return False, f"{site_key} 로그인 완료를 3분 안에 확인하지 못했어."
    except Exception as e:
        return False, f"{site_key} 수동 로그인 상태 저장 중 오류가 났어: {e}"


def open_site_with_saved_login(site_key: str, target_url: str | None = None, headed: bool = True):
    config = SITE_CONFIGS.get(site_key)
    if not config:
        return False, f"{site_key} 사이트 설정이 없어."

    login_type = config.get("login_type", "native")

    try:
        with sync_playwright() as p:
            if login_type == "manual_google_bootstrap":
                profile_dir = config.get("persistent_profile_dir")
                channel = config.get("browser_channel", "chrome")

                context = p.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=False,
                    channel=channel,
                    args=[
                        "--disable-blink-features=AutomationControlled"
                    ]
                )
                page = context.new_page()
                page.goto(target_url or config["home_url"], wait_until="domcontentloaded")
                return True, f"{site_key} 열어뒀어."

            storage_state = config["storage_state"]
            if not Path(storage_state).exists():
                return False, f"{site_key} 저장된 로그인 상태가 없어. 먼저 로그인해야 해."

            browser = p.chromium.launch(headless=not headed)
            context = browser.new_context(storage_state=storage_state)
            page = context.new_page()
            page.goto(target_url or config["home_url"], wait_until="domcontentloaded")
            return True, f"{site_key} 열어뒀어."

    except Exception as e:
        return False, f"{site_key} 열기 실패: {e}"


def click_by_text(site_key: str, text: str, target_url: str | None = None, headed: bool = True):
    config = SITE_CONFIGS.get(site_key)
    if not config:
        return False, f"{site_key} 사이트 설정이 없어."

    storage_state = config["storage_state"]
    if not Path(storage_state).exists():
        return False, f"{site_key} 로그인 상태가 없어. 먼저 로그인해야 해."

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed)
            context = browser.new_context(storage_state=storage_state)
            page = context.new_page()
            page.goto(target_url or config["home_url"], wait_until="domcontentloaded")

            if site_key == "naver" and text == "메일":
                page.get_by_role("tab", name="메일").click(timeout=10000)
            else:
                page.get_by_text(text, exact=False).first.click(timeout=10000)

            if headed:
                page.wait_for_timeout(15000)

            return True, f"'{text}' 클릭했어."
    except Exception as e:
        return False, f"클릭 실패: {e}"