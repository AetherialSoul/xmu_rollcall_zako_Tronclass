from pathlib import Path
from urllib import parse
import os

import main as upstream

IDS_USERNAME_LOGIN = "https://ids.xmu.edu.cn/authserver/login?type=userNameLogin"
IQA_CAS_URL = getattr(upstream, "IQA_CAS_URL", "https://iqa.xmu.edu.cn/cas/toUrl")


def get_username_login_url():
    return f"{IDS_USERNAME_LOGIN}&service={parse.quote(IQA_CAS_URL, safe='')}"


def get_account_from_env():
    username = os.environ.get("XMU_USERNAME", "").strip()
    password = os.environ.get("XMU_PASSWORD", "")
    return (username, password) if username and password else None


def get_cas_profile_dir():
    raw = os.environ.get("XMU_CAS_PROFILE_DIR")
    return Path(raw).expanduser() if raw else Path.cwd() / ".iqa_browser_profile"


def launch_context(self):
    self.profile_dir = get_cas_profile_dir()
    self.profile_dir.mkdir(parents=True, exist_ok=True)
    last_error = None
    for channel in ("msedge", "chrome", None):
        try:
            kwargs = {"user_data_dir": str(self.profile_dir), "headless": False}
            if channel:
                kwargs["channel"] = channel
            print(f"Using CAS profile: {self.profile_dir} ({channel or 'playwright chromium'})")
            return self.playwright.chromium.launch_persistent_context(**kwargs)
        except Exception as exc:
            last_error = exc
            print(f"Browser launch failed ({channel or 'playwright chromium'}): {exc}")
    raise last_error


def auto_login_once(self):
    account = get_account_from_env()
    if not account:
        print("XMU_USERNAME/XMU_PASSWORD not provided; waiting for manual login.")
        return
    username, password = account
    try:
        username_input = self.page.locator("input[name='username'], input#username, input[type='text']").first
        password_input = self.page.locator("input[type='password'], input[name='password'], input#password").first
        username_input.wait_for(state="visible", timeout=10000)
        password_input.wait_for(state="visible", timeout=10000)
        username_input.fill(username)
        password_input.fill(password)
        username_input.dispatch_event("input")
        username_input.dispatch_event("change")
        password_input.dispatch_event("input")
        password_input.dispatch_event("change")
        for selector in (
            "#login_submit",
            "input#login_submit",
            "button#login_submit",
            "a#login_submit",
            "input[type='submit']",
            "button[type='submit']",
            ".login-btn",
            ".btn-login",
            "button:has-text('登录')",
            "button:has-text('登 录')",
            "a:has-text('登录')",
            "a:has-text('登 录')",
        ):
            candidate = self.page.locator(selector).first
            try:
                if candidate.count() and candidate.is_visible(timeout=1000):
                    candidate.click()
                    return
            except Exception:
                pass
        password_input.press("Enter")
    except Exception as exc:
        print(f"Auto login failed; waiting for manual login: {exc}")


def login(self):
    self.page.bring_to_front()
    self.page.goto(get_username_login_url(), wait_until="domcontentloaded")
    if "ids.xmu.edu.cn" in self.page.url or "authserver/login" in self.page.url:
        auto_login_once(self)
        print("Finish CAS login in the browser if it does not continue automatically.")
        try:
            self.page.wait_for_url(lambda url: "ids.xmu.edu.cn" not in str(url), timeout=30000)
        except Exception:
            pass
    self.page.goto(IQA_CAS_URL, wait_until="domcontentloaded")
    self.page.wait_for_url("**/xssy/**", timeout=10 * 60 * 1000)
    print("IQA login succeeded")


upstream.IQAHelper._launch_context = launch_context
upstream.IQAHelper.login = login


if __name__ == "__main__":
    with upstream.IQAHelper() as helper:
        helper.run()
