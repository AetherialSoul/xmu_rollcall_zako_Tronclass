# -*- coding: utf-8 -*-
import argparse
import json
import os
import sys
import time
import traceback
from urllib import parse

import yaml
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from notify import notify

class TeeWriter:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def setup_runtime_log():
    log_file = open("runtime.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = TeeWriter(sys.__stdout__, log_file)
    sys.stderr = TeeWriter(sys.__stderr__, log_file)
    print("\n" + "=" * 60)
    print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()), "score query started")
    return log_file


def acquire_single_instance_lock():
    lock_path = os.path.abspath("score_query.lock")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        return lock_path
    except FileExistsError:
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                old_pid = f.read().strip()
        except Exception:
            old_pid = "unknown"
        raise RuntimeError(f"成绩查询已在运行或上次异常退出未清理 lock: {lock_path}; pid={old_pid}")


def release_single_instance_lock(lock_path):
    if lock_path:
        try:
            os.remove(lock_path)
        except FileNotFoundError:
            pass


def launch_score_context(browser_type, headless):
    errors = []
    for channel in ("msedge", "chrome", None):
        try:
            label = channel or "playwright chromium"
            print(f"正在启动成绩查询浏览器: {label}", flush=True)
            kwargs = {
                "user_data_dir": "browser_profile",
                "headless": headless,
                "viewport": {"width": 1280, "height": 900},
            }
            if channel:
                kwargs["channel"] = channel
            return browser_type.launch_persistent_context(**kwargs)
        except Exception as exc:
            errors.append(f"{channel or 'playwright chromium'}: {exc}")
            print(f"启动 {channel or 'playwright chromium'} 失败: {exc}", flush=True)
    raise RuntimeError("无法启动成绩查询浏览器:\n" + "\n".join(errors))
JWS_BASE = "https://jw.xmu.edu.cn"
JWS_HOME = f"{JWS_BASE}/new/index.html"
IDS_USERNAME_LOGIN = "https://ids.xmu.edu.cn/authserver/login?type=userNameLogin"
COMPLETION_APP = f"{JWS_BASE}/jwapp/sys/xywcjdMobile/*default/index.do"
STANDARD_SCORE_APP = f"{JWS_BASE}/appShow?appId=4768574631264620"

standard_query_template = {
    "querySetting": [
        {
            "name": "SFYX",
            "caption": "是否有效",
            "linkOpt": "AND",
            "builderList": "cbl_m_List",
            "builder": "m_value_equal",
            "value": "1",
            "value_display": "是"
        },
        {
            "name": "SHOWMAXCJ",
            "caption": "显示最高成绩",
            "linkOpt": "AND",
            "builderList": "cbl_m_List",
            "builder": "m_value_equal",
            "value": "0",
            "value_display": "否"
        },
        {
            "name": "XNXQDM",
            "linkOpt": "AND",
            "builder": "equal",
            "value": ""
        }
    ],
    "*order": "-XNXQDM,-KCH,-KXH"
}


class BrowserLoginRequired(Exception):
    pass


class QueryHttpError(RuntimeError):
    def __init__(self, status, url, current_url, body):
        self.status = status
        self.url = url
        self.current_url = current_url
        self.body = body
        super().__init__(
            f"Query failed with HTTP {status}: {url}; "
            f"page={current_url}; body={body}"
        )


def normalize_optional_list(value, field_name):
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        normalized = []
        for item in value:
            item_text = str(item).strip()
            if item_text:
                normalized.append(item_text)
        return normalized
    raise ValueError(f"{field_name} must be a YAML list or left empty.")


def load_config(args):
    with open("config.yaml", "r", encoding="utf-8") as f:
        conf = yaml.load(f, Loader=yaml.FullLoader) or {}
    info_conf = conf.get("info") or {}
    username = args.username if args.username else str(info_conf.get("username") or "").strip()
    password = str(info_conf.get("password") or "")
    browser_conf = conf.get("browser") or {}
    try:
        interval = int(args.interval) if args.interval else int(conf["interval"])
    except KeyError as exc:
        raise ValueError("Please fill interval in config.yaml or pass --interval.") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError("interval must be a positive integer.") from exc
    if not username or username == "None":
        raise ValueError("Please fill info.username in config.yaml or pass --username.")
    if interval <= 0:
        raise ValueError("interval must be a positive integer.")
    notify_type = str(conf.get("notify") or "").strip().lower()
    if notify_type and notify_type not in ("system", "email", "both", "none", "off", "false"):
        raise ValueError("notify must be system, email, both, or left empty.")
    return {
        "username": username,
        "password": password,
        "browser": browser_conf,
        "interval": interval,
        "query_terms": normalize_optional_list(conf.get("terms"), "terms"),
        "query_courses": normalize_optional_list(conf.get("courses"), "courses"),
        "show_score": conf.get("show_score", True),
        "score_query": conf.get("score_query", {}),
        "completion_query": conf.get("completion_query", {}),
    }


def load_saved_scores():
    try:
        with open("scores.yaml", "r", encoding="utf-8") as f:
            scores = yaml.load(f, Loader=yaml.FullLoader)
            return scores or {}
    except FileNotFoundError:
        return {}
    except Exception:
        raise ValueError("scores.yaml is not a valid yaml file.")


def save_scores(scores):
    with open("scores.yaml", "w", encoding="utf-8") as f:
        yaml.dump(scores, f, encoding="utf-8", allow_unicode=True)


def is_login_page(page):
    return "ids.xmu.edu.cn" in page.url or "authserver/login" in page.url


def build_completion_page_url(config):
    params = build_completion_params(config)
    display_params = {
        "PCDM": params["PCDM"],
        "PYFADM": params["PYFADM"],
        "PYFAMC": params["PYFAMC"],
        "XH": params["XH"],
        "YMJS": params["YMJS"],
    }
    return f"{COMPLETION_APP}#/pyfaxq?{parse.urlencode(display_params)}"


def get_start_url(config):
    browser_conf = config["browser"]
    if browser_conf.get("start_url"):
        return str(browser_conf["start_url"])

    source = config["score_query"].get("source", "completion")
    if source in ("completion", "auto"):
        return build_completion_page_url(config)
    if source == "standard":
        return STANDARD_SCORE_APP
    return JWS_HOME


def get_username_login_url(config):
    return f"{IDS_USERNAME_LOGIN}&service={parse.quote(get_start_url(config), safe='')}"


def auto_login_once(page, config):
    if not config["browser"].get("auto_login_once", False):
        return False
    if not config["password"]:
        print("已开启自动登录一次，但 config.yaml 中未填写密码，改为等待手动登录。")
        return False

    username_input = page.locator("input[name='username'], input#username, input[type='text']").first
    password_input = page.locator("input[type='password'], input[name='password'], input#password").first
    try:
        username_input.wait_for(state="visible", timeout=10000)
        password_input.wait_for(state="visible", timeout=10000)
        username_input.fill(config["username"])
        password_input.fill(config["password"])
        username_input.dispatch_event("input")
        username_input.dispatch_event("change")
        password_input.dispatch_event("input")
        password_input.dispatch_event("change")
        print("已在浏览器中自动提交一次登录；如果失败，将不再重试。")

        clicked = False
        submit_selectors = [
            "#login_submit",
            "input#login_submit",
            "button#login_submit",
            "a#login_submit",
            "button[type='submit']",
            "input[type='submit']",
            ".login-btn",
            ".btn-login",
            "button:has-text('登录')",
            "button:has-text('登 录')",
            "a:has-text('登录')",
            "a:has-text('登 录')",
        ]
        for selector in submit_selectors:
            candidate = page.locator(selector).first
            try:
                if candidate.is_visible(timeout=1000):
                    candidate.click(timeout=5000)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            password_input.press("Enter")

        try:
            page.wait_for_url(lambda url: "ids.xmu.edu.cn" not in str(url), timeout=30000)
        except PlaywrightTimeoutError:
            pass
        return True
    except Exception as exc:
        print(f"自动登录一次未完成，改为等待手动登录：{exc}")
        return False


def ensure_logged_in(page, config, login_state):
    start_url = get_start_url(config)
    page.goto(get_username_login_url(config), wait_until="domcontentloaded")
    while is_login_page(page):
        if not login_state["auto_login_used"]:
            login_state["auto_login_used"] = True
            auto_login_once(page, config)
            if not is_login_page(page):
                break
        print("请在打开的浏览器中完成统一身份认证登录。程序不会继续自动提交密码。")
        try:
            page.wait_for_url(lambda url: "ids.xmu.edu.cn" not in str(url), timeout=10 * 60 * 1000)
        except PlaywrightTimeoutError:
            print("等待登录超时，继续等待浏览器登录完成。")
        time.sleep(1)
    page.goto(start_url, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        pass
    if is_login_page(page):
        raise BrowserLoginRequired("Browser is still on the login page.")
    print(f"浏览器已进入教务页面：{page.url}", flush=True)


def force_relogin(page, config, login_state):
    print("接口返回 401/403，清理 XMU 登录状态后重新登录。", flush=True)
    page.context.clear_cookies()
    login_state["auto_login_used"] = False
    ensure_logged_in(page, config, login_state)


def fetch_json(page, url, method="GET", data=None, headers=None):
    result = page.evaluate(
        """async ({ url, method, data, headers }) => {
            const options = {
                method,
                credentials: "include",
                redirect: "follow",
                referrer: window.location.href,
                headers: {
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    ...(headers || {})
                }
            };
            if (data !== null && data !== undefined) {
                options.body = data;
            }
            const response = await fetch(url, options);
            const text = await response.text();
            return {
                currentUrl: window.location.href,
                url: response.url,
                status: response.status,
                text
            };
        }""",
        {"url": url, "method": method, "data": data, "headers": headers or {}}
    )
    if "ids.xmu.edu.cn" in result["url"]:
        raise BrowserLoginRequired("Browser session expired.")
    if result["status"] != 200:
        body = result["text"][:300].replace("\n", " ").replace("\r", " ")
        raise QueryHttpError(result["status"], url, result["currentUrl"], body)
    return json.loads(result["text"])


def build_completion_params(config):
    completion_query = config["completion_query"]
    pyfadm = completion_query.get("pyfadm")
    if not pyfadm:
        raise ValueError("Please set completion_query.pyfadm in config.yaml")
    return {
        "PCDM": str(completion_query.get("pcdm", "-")),
        "PYFADM": str(pyfadm),
        "PYFAMC": str(completion_query.get("pyfamc", "")),
        "XH": config["username"],
        "YMJS": str(completion_query.get("ymjs", "0")),
        "BYNJDM": str(completion_query.get("bynjdm", "-")),
        "SCLBDM": str(completion_query.get("sclbdm", "04")),
    }


def query_completion_scores(page, config):
    url = f"{JWS_BASE}/jwapp/sys/xywcjdMobile/modules/kzkcxq/cxscfakzkc.do"
    params = parse.urlencode(build_completion_params(config))
    data = fetch_json(
        page,
        f"{url}?{params}",
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    rows = data["datas"]["cxscfakzkc"]["rows"]
    return [normalize_completion_score(row) for row in rows if row.get("CJ") not in (None, "") and row.get("XNXQDM")]


def query_standard_scores(page, config):
    terms_data = fetch_json(
        page,
        f"{JWS_BASE}/jwapp/sys/cjcx/modules/cjcx/cxycjdxnxq.do",
        method="POST",
        data=parse.urlencode({"XH": config["username"]}),
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
    )
    terms = terms_data["datas"]["cxycjdxnxq"]["rows"]
    scores = []
    for term in terms:
        query_terms = config["query_terms"]
        if query_terms and term["XNXQDM_DISPLAY"] not in query_terms and term["XNXQDM"] not in query_terms:
            continue
        standard_query_template["querySetting"][2]["value"] = term["XNXQDM"]
        score_data = fetch_json(
            page,
            f"{JWS_BASE}/jwapp/sys/cjcx/modules/cjcx/xscjcx.do",
            method="POST",
            data=parse.urlencode(standard_query_template),
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        )
        rows = score_data["datas"]["xscjcx"]["rows"]
        scores.extend(normalize_standard_score(row, term) for row in rows if row.get("ZCJ") not in (None, ""))
    return scores


def query_scores(page, config):
    source = config["score_query"].get("source", "completion")
    if source == "completion":
        return query_completion_scores(page, config)
    if source == "standard":
        return query_standard_scores(page, config)
    if source == "auto":
        completion_scores = query_completion_scores(page, config)
        if completion_scores:
            return completion_scores
        return query_standard_scores(page, config)
    raise ValueError("score_query.source must be completion, standard, or auto")


def normalize_completion_score(score):
    return {
        "course_id": score["KCH"],
        "name": score["KCM"],
        "score": score["CJ"],
        "grade": normalize_grade(score["CJ"]),
        "xf": float(score["XF"]),
        "term": score["XNXQDM_DISPLAY"],
        "term_code": score["XNXQDM"]
    }


def normalize_standard_score(score, term):
    return {
        "course_id": score["KCH"],
        "name": score["KCM"],
        "score": score["ZCJ"],
        "grade": normalize_grade(score.get("XFJD", score["ZCJ"])),
        "xf": float(score["XF"]),
        "term": term["XNXQDM_DISPLAY"],
        "term_code": term["XNXQDM"]
    }


def normalize_grade(value):
    try:
        return float(value)
    except Exception:
        return value


def score_matches(score, config):
    query_terms = config["query_terms"]
    query_courses = config["query_courses"]
    if query_terms and score["term"] not in query_terms and score["term_code"] not in query_terms:
        return False
    if query_courses and score["name"] not in query_courses and score["course_id"] not in query_courses:
        return False
    return True


def handle_scores(scores, saved_scores, config):
    message = ""
    for score in scores:
        if not score_matches(score, config):
            continue
        if score["course_id"] not in saved_scores or saved_scores[score["course_id"]]["score"] != score["score"]:
            saved_scores[score["course_id"]] = {
                "xf": score["xf"],
                "score": score["score"],
                "grade": score["grade"],
                "name": score["name"],
                "term": score["term"],
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            }
            if config["show_score"]:
                message += f"{score['name']}：{score['score']}（学分 {score['xf']} 分，{score['term']}）。\n"
            else:
                message += f"{score['name']}\n"
    if message:
        save_scores(saved_scores)
        message = "以下课程有新成绩：\n" + message
        print(message)
        notify("新成绩", message)
    else:
        print("没有新成绩")


def run_query_cycle(page, config, saved_scores):
    page.goto(get_start_url(config), wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        pass
    if is_login_page(page):
        raise BrowserLoginRequired("Browser session expired.")
    scores = query_scores(page, config)
    print(f"本次查询返回 {len(scores)} 条已出成绩记录", flush=True)
    handle_scores(scores, saved_scores, config)


def main():
    log_file = setup_runtime_log()
    lock_path = None
    context = None
    try:
        lock_path = acquire_single_instance_lock()
        parser = argparse.ArgumentParser()
        parser.add_argument("--username", metavar="username", help="统一身份认证用户名")
        parser.add_argument("--interval", metavar="interval", help="查询间隔，单位为分钟")
        parser.add_argument("--headless", action="store_true", help="无界面模式，仅适合已保存浏览器登录态后使用")
        args = parser.parse_args()

        config = load_config(args)
        saved_scores = load_saved_scores()
        login_state = {"auto_login_used": False}

        with sync_playwright() as playwright:
            browser_type = playwright.chromium
            context = launch_score_context(browser_type, args.headless)
            page = context.pages[0] if context.pages else context.new_page()
            ensure_logged_in(page, config, login_state)
            while True:
                print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
                try:
                    run_query_cycle(page, config, saved_scores)
                    time.sleep(config["interval"] * 60)
                except BrowserLoginRequired:
                    notify("登录状态失效", "成绩查询浏览器登录状态失效，请在打开的浏览器中重新登录。")
                    ensure_logged_in(page, config, login_state)
                except KeyboardInterrupt:
                    raise
                except QueryHttpError as exc:
                    if exc.status in (401, 403):
                        print("学业完成进度接口返回 401/403，程序正在清理登录状态并重新登录。", flush=True)
                        try:
                            force_relogin(page, config, login_state)
                        except Exception:
                            traceback.print_exc()
                            notify(
                                "成绩查询被拒绝",
                                "学业完成进度接口返回 401/403，且自动重新登录失败，请手动检查浏览器登录状态。"
                            )
                            time.sleep(config["interval"] * 60)
                        else:
                            try:
                                print("重新登录成功，立即补查一次。", flush=True)
                                run_query_cycle(page, config, saved_scores)
                                time.sleep(config["interval"] * 60)
                            except BrowserLoginRequired:
                                notify("登录状态失效", "成绩查询浏览器登录状态失效，请在打开的浏览器中重新登录。")
                                ensure_logged_in(page, config, login_state)
                            except Exception:
                                traceback.print_exc()
                                notify("成绩查询异常", "自动重新登录后立即补查失败；程序继续运行，10 分钟后重试。")
                                time.sleep(config["interval"] * 60)
                    else:
                        traceback.print_exc()
                        notify("成绩查询异常", f"成绩查询接口返回 HTTP {exc.status}；程序继续运行，10 分钟后重试。")
                        time.sleep(config["interval"] * 60)
                except Exception:
                    traceback.print_exc()
                    notify("成绩查询异常", "成绩查询接口返回异常；程序继续运行，10 分钟后重试。")
                    time.sleep(config["interval"] * 60)
    finally:
        if context is not None:
            context.close()
        release_single_instance_lock(lock_path)
        log_file.close()


if __name__ == "__main__":
    main()
