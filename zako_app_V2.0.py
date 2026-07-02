"""
zako 签到助手 —— CustomTkinter 版
工作流：
 1. 主页选择教学平台 -> 启动浏览器 / CAS 登录
 2. 拿到 cookie + student_id -> 拉取课程列表 -> 跳课程页
 3. 点课程 -> 查最新签到码 -> 跳结果页
 4. 结果页可返回课程页继续查；任何页面右上角日志按钮可展开日志
"""

import asyncio
import atexit
import json
import math
import re
import uuid
import threading
import time
import winsound
import ctypes
import smtplib
import subprocess
import os
import sys
import requests
import webbrowser
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from playwright.async_api import async_playwright
from datetime import datetime, timezone, timedelta
from email.header import Header
from email.mime.text import MIMEText
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib import parse as urlparse

# ── 颜色 / 字体常量 ────────────────────────────────────────
BG        = "#0F0E17"
SURFACE   = "#1A1828"
SURFACE2  = "#221F33"
ACCENT    = "#FF6B9D"
ACCENT_DK = "#CC4477"
TEXT_PRI  = "#FFFFFE"
TEXT_SEC  = "#A7A9BE"
SUCCESS   = "#06D6A0"
WARN      = "#FFD166"
DANGER    = "#EF476F"

BASE_URL = "https://lnt.xmu.edu.cn"
APP_DIR = Path(__file__).resolve().parent
LOGIN_STATE_DIR = APP_DIR / ".zako_browser_profile"
CUSTOM_RADAR_LOCATIONS_FILE = APP_DIR / "custom_radar_locations.json"
ACCOUNT_CONFIG_FILE = APP_DIR / "account.local.json"
INTEGRATIONS_DIR = APP_DIR / "integrations"
SCORE_PROJECT_DIR = INTEGRATIONS_DIR / "score_query"
IQA_PROJECT_DIR = INTEGRATIONS_DIR / "iqa_helper"
COURSE_HELPER_DIR = INTEGRATIONS_DIR / "course_helper"
SCORE_NOTIFY_CONFIG_FILE = SCORE_PROJECT_DIR / "config.yaml"
LEGACY_SCORE_NOTIFY_CONFIG_FILE = Path.home() / "Documents" / "XMUScoreAutoQuery" / "config.yaml"
LNT_REPORTS_DIR = APP_DIR / "lnt_reports"
IDS_USERNAME_LOGIN_URL = "https://ids.xmu.edu.cn/authserver/login?type=userNameLogin"
HEADERS_BASE = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
}
ACTIVE_NUMBER_STATUSES = {"absent"}
FINISHED_NUMBER_STATUSES = {"finished", "closed", "ended", "expired", "on_call_fine", "signed", "submitted", "present"}
SIGNED_ROLLCALL_STATUSES = {"on_call_fine", "signed", "submitted", "present"}


def parse_lnt_timestamp(value):
    if not value:
        return 0
    try:
        raw = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0



def find_nested_value(data, keys, depth=0, max_depth=8):
    if depth > max_depth:
        return None
    if isinstance(keys, str):
        keys = (keys,)
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                return value
        for value in data.values():
            found = find_nested_value(value, keys, depth + 1, max_depth)
            if found not in (None, ""):
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_nested_value(item, keys, depth + 1, max_depth)
            if found not in (None, ""):
                return found
    return None

# ==============================================================================
# 后端逻辑（完美继承原有机制，仅增加 log 参数用于重定向输出到 UI）
# ==============================================================================

def load_account_config(log=print):
    if not ACCOUNT_CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(ACCOUNT_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log(f"⚠️ 统一账号配置读取失败: {exc}")
        return None
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    if not username or not password:
        log("⚠️ account.local.json 缺少 username/password，跳过账号同步。")
        return None
    return username, password


def yaml_quote(value):
    return json.dumps(str(value), ensure_ascii=False)


def yaml_format_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return ("%.6f" % value).rstrip("0").rstrip(".")
    return yaml_quote(value)


def parse_yaml_scalar(value, default=""):
    raw = str(value).strip()
    if not raw:
        return default
    if raw[0] in ('"', "'"):
        quote = raw[0]
        escaped = False
        for idx in range(1, len(raw)):
            char = raw[idx]
            if quote == '"' and char == "\\" and not escaped:
                escaped = True
                continue
            if char == quote and not escaped:
                token = raw[:idx + 1]
                if quote == '"':
                    try:
                        return json.loads(token)
                    except Exception:
                        return token[1:-1]
                return token[1:-1].replace("''", "'")
            escaped = False
    raw = raw.split("#", 1)[0].strip()
    if not raw:
        return default
    lowered = raw.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("null", "none", "~"):
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw

def as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    lowered = str(value).strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off", "none", ""):
        return False
    return default


def settings_int(value, default, min_value=None, max_value=None, label="数值"):
    try:
        result = int(str(value).strip())
    except Exception:
        result = int(default)
    if min_value is not None:
        result = max(result, min_value)
    if max_value is not None:
        result = min(result, max_value)
    return result


def settings_float(value, default, min_value=None, max_value=None, label="数值"):
    try:
        result = float(str(value).strip())
    except Exception:
        result = float(default)
    if min_value is not None:
        result = max(result, min_value)
    if max_value is not None:
        result = min(result, max_value)
    return result


def normalize_login_method(value):
    value = str(value or "browser").strip().lower()
    return value if value in ("browser", "account") else "browser"


def load_account_data(log=print):
    if not ACCOUNT_CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(ACCOUNT_CONFIG_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        log(f"⚠️ 统一账号配置读取失败: {exc}")
        return {}


def get_login_method():
    data = load_account_data(lambda _msg: None)
    if data.get("login_method") in ("browser", "account"):
        return normalize_login_method(data.get("login_method"))
    if str(data.get("username") or "").strip() and str(data.get("password") or ""):
        return "account"
    return "browser"


def _line_ending(text):
    return "\r\n" if "\r\n" in text else "\n"


def _split_line_newline(line):
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    return line, ""


def _replace_yaml_line_value(line, key, value):
    body, newline = _split_line_newline(line)
    pattern = rf"^(\s*{re.escape(key)}\s*:\s*)(.*?)(\s+#.*)?$"
    match = re.match(pattern, body)
    if not match:
        return line
    comment = match.group(3) or ""
    return f"{match.group(1)}{yaml_format_scalar(value)}{comment}{newline}"


def yaml_get_root_scalar(text, key, default=""):
    pattern = rf"^{re.escape(key)}\s*:"
    for raw_line in text.splitlines():
        if re.match(pattern, raw_line):
            return parse_yaml_scalar(raw_line.split(":", 1)[1], default)
    return default


def yaml_get_section_scalar(text, section, key, default=""):
    in_section = False
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 0:
            if re.match(rf"^{re.escape(section)}\s*:\s*(?:#.*)?$", raw_line):
                in_section = True
                continue
            if in_section:
                return default
        elif in_section and re.match(rf"^\s+{re.escape(key)}\s*:", raw_line):
            return parse_yaml_scalar(raw_line.split(":", 1)[1], default)
    return default


def replace_yaml_scalar(text, key, value):
    return set_yaml_root_scalar(text, key, value)


def set_yaml_root_scalar(text, key, value):
    lines = text.splitlines(True)
    for idx, line in enumerate(lines):
        body, _newline = _split_line_newline(line)
        if re.match(rf"^{re.escape(key)}\s*:", body):
            lines[idx] = _replace_yaml_line_value(line, key, value)
            return "".join(lines)
    eol = _line_ending(text)
    prefix = "" if not text or text.endswith(("\n", "\r\n")) else eol
    return text + prefix + f"{key}: {yaml_format_scalar(value)}{eol}"


def set_yaml_section_scalar(text, section, key, value):
    lines = text.splitlines(True)
    section_idx = None
    insert_idx = len(lines)
    for idx, line in enumerate(lines):
        body, _newline = _split_line_newline(line)
        if section_idx is None:
            if re.match(rf"^{re.escape(section)}\s*:\s*(?:#.*)?$", body):
                section_idx = idx
                insert_idx = idx + 1
            continue
        if body.strip() and not body.startswith((" ", "\t")):
            insert_idx = idx
            break
        if re.match(rf"^\s+{re.escape(key)}\s*:", body):
            lines[idx] = _replace_yaml_line_value(line, key, value)
            return "".join(lines)
        insert_idx = idx + 1

    eol = _line_ending(text)
    if section_idx is None:
        prefix = "" if not text or text.endswith(("\n", "\r\n")) else eol
        return text + prefix + f"{section}:{eol}  {key}: {yaml_format_scalar(value)}{eol}"
    lines.insert(insert_idx, f"  {key}: {yaml_format_scalar(value)}{eol}")
    return "".join(lines)


def ensure_score_config(log=print):
    config_path = SCORE_PROJECT_DIR / "config.yaml"
    if config_path.exists():
        return config_path
    example = SCORE_PROJECT_DIR / "config.yaml.example"
    if example.exists():
        config_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        return config_path
    log("⚠️ 成绩查询缺少 config.yaml 和 config.yaml.example，无法保存配置。")
    return None


def ensure_course_config(log=print):
    config_dir = COURSE_HELPER_DIR / "config"
    config_path = config_dir / "user.yaml"
    if config_path.exists():
        return config_path
    example = config_dir / "user.example.yaml"
    if example.exists():
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        return config_path
    log("⚠️ 选课缺少 config/user.yaml 和 config/user.example.yaml，无法保存配置。")
    return None


def get_score_notify_config_file():
    return SCORE_NOTIFY_CONFIG_FILE if SCORE_NOTIFY_CONFIG_FILE.exists() else LEGACY_SCORE_NOTIFY_CONFIG_FILE


def load_settings_values(log=print):
    account_data = load_account_data(log)
    score_path = SCORE_PROJECT_DIR / "config.yaml"
    score_text = score_path.read_text(encoding="utf-8") if score_path.exists() else ""
    course_path = COURSE_HELPER_DIR / "config" / "user.yaml"
    course_text = course_path.read_text(encoding="utf-8") if course_path.exists() else ""
    return {
        "username": str(account_data.get("username") or ""),
        "password": str(account_data.get("password") or ""),
        "login_method": get_login_method(),
        "default_radar_location": str(account_data.get("default_radar_location") or ""),
        "score_auto_login_once": as_bool(yaml_get_section_scalar(score_text, "browser", "auto_login_once", True), True),
        "score_interval": settings_int(yaml_get_root_scalar(score_text, "interval", 10), 10, 1),
        "score_notify": str(yaml_get_root_scalar(score_text, "notify", "none") or "none").strip().lower(),
        "score_show_score": as_bool(yaml_get_root_scalar(score_text, "show_score", True), True),
        "score_source": str(yaml_get_section_scalar(score_text, "score_query", "source", "standard") or "standard").strip().lower(),
        "score_start_url": str(yaml_get_section_scalar(score_text, "browser", "start_url", "") or ""),
        "completion_pyfadm": str(yaml_get_section_scalar(score_text, "completion_query", "pyfadm", "") or ""),
        "completion_pyfamc": str(yaml_get_section_scalar(score_text, "completion_query", "pyfamc", "") or ""),
        "completion_pcdm": str(yaml_get_section_scalar(score_text, "completion_query", "pcdm", "-") or "-"),
        "completion_ymjs": str(yaml_get_section_scalar(score_text, "completion_query", "ymjs", "0") or "0"),
        "completion_bynjdm": str(yaml_get_section_scalar(score_text, "completion_query", "bynjdm", "-") or "-"),
        "completion_sclbdm": str(yaml_get_section_scalar(score_text, "completion_query", "sclbdm", "04") or "04"),
        "course_campus": str(yaml_get_root_scalar(course_text, "campus", "6") or "6"),
        "course_auto_add_enable": as_bool(yaml_get_root_scalar(course_text, "auto_add_enable", False), False),
        "course_check_interval": settings_int(yaml_get_root_scalar(course_text, "check_interval", 15), 15, 5),
        "course_fast_check_interval": settings_int(yaml_get_root_scalar(course_text, "fast_check_interval", 5), 5, 5),
        "course_fast_monitor_seconds": settings_int(yaml_get_root_scalar(course_text, "fast_monitor_seconds", 120), 120, 0),
        "course_add_retry_count": settings_int(yaml_get_root_scalar(course_text, "add_retry_count", 5), 5, 0),
        "course_add_retry_interval": settings_float(yaml_get_root_scalar(course_text, "add_retry_interval", 1.0), 1.0, 0),
        "course_interval_jitter": settings_float(yaml_get_root_scalar(course_text, "interval_jitter", 0.10), 0.10, 0, 0.3),
        "captcha_type": str(yaml_get_section_scalar(course_text, "captcha", "type", "manual") or "manual").strip().lower(),
        "captcha_base_url": str(yaml_get_section_scalar(course_text, "captcha", "base_url", "") or ""),
        "captcha_api_key": str(yaml_get_section_scalar(course_text, "captcha", "api_key", "") or ""),
        "captcha_model": str(yaml_get_section_scalar(course_text, "captcha", "model", "") or ""),
    }


def save_settings_values(values, log=print):
    username = str(values.get("username") or "").strip()
    password = str(values.get("password") or "")
    login_method = normalize_login_method(values.get("login_method"))

    account_data = load_account_data(log)
    account_data.update({
        "username": username,
        "password": password,
        "login_method": login_method,
        "default_radar_location": str(values.get("default_radar_location") or ""),
    })
    ACCOUNT_CONFIG_FILE.write_text(
        json.dumps(account_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    score_path = ensure_score_config(log)
    if score_path:
        text = score_path.read_text(encoding="utf-8")
        text = set_yaml_section_scalar(text, "info", "username", username)
        text = set_yaml_section_scalar(text, "info", "password", password)
        text = set_yaml_section_scalar(text, "browser", "auto_login_once", bool(values.get("score_auto_login_once")))
        text = set_yaml_root_scalar(text, "interval", settings_int(values.get("score_interval"), 10, 1))
        text = set_yaml_root_scalar(text, "notify", str(values.get("score_notify") or "none"))
        text = set_yaml_root_scalar(text, "show_score", bool(values.get("score_show_score")))
        text = set_yaml_section_scalar(text, "score_query", "source", str(values.get("score_source") or "standard"))
        text = set_yaml_section_scalar(text, "browser", "start_url", str(values.get("score_start_url") or ""))
        text = set_yaml_section_scalar(text, "completion_query", "pyfadm", str(values.get("completion_pyfadm") or ""))
        text = set_yaml_section_scalar(text, "completion_query", "pyfamc", str(values.get("completion_pyfamc") or ""))
        text = set_yaml_section_scalar(text, "completion_query", "pcdm", str(values.get("completion_pcdm") or "-"))
        text = set_yaml_section_scalar(text, "completion_query", "ymjs", str(values.get("completion_ymjs") or "0"))
        text = set_yaml_section_scalar(text, "completion_query", "bynjdm", str(values.get("completion_bynjdm") or "-"))
        text = set_yaml_section_scalar(text, "completion_query", "sclbdm", str(values.get("completion_sclbdm") or "04"))
        score_path.write_text(text, encoding="utf-8")

    course_path = ensure_course_config(log)
    if course_path:
        text = course_path.read_text(encoding="utf-8")
        text = set_yaml_root_scalar(text, "username", username)
        text = set_yaml_root_scalar(text, "password", password)
        text = set_yaml_root_scalar(text, "campus", str(values.get("course_campus") or "6"))
        text = set_yaml_root_scalar(text, "auto_add_enable", bool(values.get("course_auto_add_enable")))
        text = set_yaml_root_scalar(text, "check_interval", settings_int(values.get("course_check_interval"), 15, 5))
        text = set_yaml_root_scalar(text, "fast_check_interval", settings_int(values.get("course_fast_check_interval"), 5, 5))
        text = set_yaml_root_scalar(text, "fast_monitor_seconds", settings_int(values.get("course_fast_monitor_seconds"), 120, 0))
        text = set_yaml_root_scalar(text, "add_retry_count", settings_int(values.get("course_add_retry_count"), 5, 0))
        text = set_yaml_root_scalar(text, "add_retry_interval", settings_float(values.get("course_add_retry_interval"), 1.0, 0))
        text = set_yaml_root_scalar(text, "interval_jitter", settings_float(values.get("course_interval_jitter"), 0.10, 0, 0.3))
        text = set_yaml_section_scalar(text, "captcha", "type", str(values.get("captcha_type") or "manual"))
        text = set_yaml_section_scalar(text, "captcha", "base_url", str(values.get("captcha_base_url") or ""))
        text = set_yaml_section_scalar(text, "captcha", "api_key", str(values.get("captcha_api_key") or ""))
        text = set_yaml_section_scalar(text, "captcha", "model", str(values.get("captcha_model") or ""))
        course_path.write_text(text, encoding="utf-8")


def extract_completion_query_from_url(url):
    raw = str(url or "").strip()
    if not raw:
        return {}
    parsed = urlparse.urlparse(raw)
    query_text = parsed.query or ""
    if "#" in raw:
        fragment = raw.split("#", 1)[1]
        if "?" in fragment:
            query_text = fragment.split("?", 1)[1]
        elif "&" in fragment or "=" in fragment:
            query_text = fragment
    query = urlparse.parse_qs(query_text, keep_blank_values=True)
    mapping = {
        "PYFADM": "completion_pyfadm",
        "PYFAMC": "completion_pyfamc",
        "PCDM": "completion_pcdm",
        "YMJS": "completion_ymjs",
        "BYNJDM": "completion_bynjdm",
        "SCLBDM": "completion_sclbdm",
    }
    result = {}
    for source_key, target_key in mapping.items():
        value = query.get(source_key, [None])[0]
        if value not in (None, ""):
            result[target_key] = value
    return result


def sync_score_account_config(log=print):
    account = load_account_config(log)
    if not account:
        return False
    username, password = account
    config_path = ensure_score_config(log)
    if not config_path:
        return False
    text = config_path.read_text(encoding="utf-8")
    text = set_yaml_section_scalar(text, "info", "username", username)
    text = set_yaml_section_scalar(text, "info", "password", password)
    config_path.write_text(text, encoding="utf-8")
    return True


def sync_course_account_config(log=print):
    account = load_account_config(log)
    if not account:
        return False
    username, password = account
    config_path = ensure_course_config(log)
    if not config_path:
        return False
    text = config_path.read_text(encoding="utf-8")
    text = set_yaml_root_scalar(text, "username", username)
    text = set_yaml_root_scalar(text, "password", password)
    config_path.write_text(text, encoding="utf-8")
    return True


def build_ids_username_login_url(current_url, fallback_service=BASE_URL):
    service = fallback_service
    try:
        query = urlparse.parse_qs(urlparse.urlparse(str(current_url)).query)
        service = query.get("service", [fallback_service])[0] or fallback_service
    except Exception:
        pass
    return f"{IDS_USERNAME_LOGIN_URL}&service={urlparse.quote(service, safe='')}"


async def auto_login_cas_page(page, log=print):
    account = load_account_config(log)
    if not account:
        log("⚠️ 未配置统一账号密码，等待手动登录。")
        return False
    username, password = account
    log("🔐 检测到统一认证登录页，正在尝试账号密码自动登录。")
    username_input = page.locator("input[name='username'], input#username, input[type='text']").first
    password_input = page.locator("input[type='password'], input[name='password'], input#password").first
    try:
        await username_input.wait_for(state="visible", timeout=10000)
        await password_input.wait_for(state="visible", timeout=10000)
        await username_input.fill(username)
        await password_input.fill(password)
        await username_input.dispatch_event("input")
        await username_input.dispatch_event("change")
        await password_input.dispatch_event("input")
        await password_input.dispatch_event("change")
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
            candidate = page.locator(selector).first
            try:
                if await candidate.count() and await candidate.is_visible(timeout=1000):
                    await candidate.click()
                    break
            except Exception:
                continue
        else:
            await password_input.press("Enter")
        return True
    except Exception as exc:
        log(f"⚠️ 自动登录填表失败，改为等待手动登录: {exc}")
        return False

def get_current_semester_info(cookie, log=print):
    headers = {**HEADERS_BASE, "cookie": cookie}
    try:
        resp = requests.get(
            f"{BASE_URL}/api/current-semester-info", headers=headers, timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            return str(data["semester"]["id"]), str(data["academic_year"]["id"])
    except Exception:
        pass
    log("⚠️ 动态获取学期失败，使用内置默认值...")
    return "29", "12"


async def login_and_get_cookie(log=print, login_method=None):
    log("❤ 正在打开浏览器喵 ❤，连接厦大CAS畅课登录系统喵❤")
    async with async_playwright() as p:
        context = None
        page = None
        LOGIN_STATE_DIR.mkdir(exist_ok=True)
        log(f"🔐 登录状态会保存在：{LOGIN_STATE_DIR}")
        
        # 🌟 核心升级：本地浏览器自动轮询策略
        # 按照 Edge -> Chrome 的顺序尝试本地浏览器
        local_channels = ["msedge", "chrome"]
        
        for channel in local_channels:
            try:
                log(f"🔄 正在尝试唤醒本地 [{channel}] 浏览器喵...")
                context = await p.chromium.launch_persistent_context(
                    str(LOGIN_STATE_DIR),
                    headless=False,
                    channel=channel,
                )
                log(f"✅ 成功连接到本地 [{channel}] 喵！")
                break  # 一旦成功启动，立刻跳出循环！
            except Exception as e:
                log(f"⚠️ [{channel}] 启动失败喵，准备尝试下一个...")
        
        # 终极兜底方案：如果用户电脑连 Edge 和 Chrome 都没有
        if context is None:
            log("🔄 没找到合适的本地浏览器，尝试启用 Playwright 备用内核喵...")
            try:
                context = await p.chromium.launch_persistent_context(
                    str(LOGIN_STATE_DIR),
                    headless=False,
                )
            except Exception as e:
                log("❌ 彻底失败了呜呜呜... 找不到任何可用浏览器。")
                return None, None # 直接终结流程
        
        page = context.pages[0] if context.pages else await context.new_page()
        student_id = None

        def handle_request(request):
            nonlocal student_id
            if student_id is None:
                m = re.search(r"/student/(\d+)/rollcalls", request.url)
                if m:
                    student_id = int(m.group(1))
                    log(f"✅ 找到主人真实学生ID了喵❤：{student_id}")

        page.on("request", handle_request)
        await page.goto(BASE_URL)

        if "ids.xmu.edu.cn" in page.url:
            login_method = normalize_login_method(login_method or get_login_method())
            if login_method == "account":
                await page.goto(build_ids_username_login_url(page.url, BASE_URL), wait_until="domcontentloaded")
                await auto_login_cas_page(page, log)
                log("👉 已尝试账号密码自动登录；如未自动跳转，请在浏览器中手动完成统一认证。")
            else:
                log("👉 请在浏览器中输入账号密码登录，登录成功后脚本才自动继续喵~❤")
            await page.wait_for_function(
                "() => !window.location.href.includes('ids.xmu.edu.cn')",
                timeout=120000,
            )
            log("✅ 登录成功喵❤！等待页面跳转喵❤！")

        try:
            await page.wait_for_url(
                "**/lnt.xmu.edu.cn/**", timeout=15000, wait_until="commit"
            )
            log("⚡ 票据交接完成！不等主页加载，直接开始截胡喵！")
            await asyncio.sleep(1)
        except Exception:
            log("⚠️ zako网络稍慢喵，跳过等待直接进入提取流程喵...")

        if student_id is None:
            log("🚀 喵要空降连招❤：后台拉取课程并强制跳转...")
            try:
                cookies_tmp = await context.cookies()
                cookie_str_tmp = "; ".join(
                    f"{c['name']}={c['value']}"
                    for c in cookies_tmp
                    if "xmu.edu.cn" in c.get("domain", "")
                )
                s_id, y_id = get_current_semester_info(cookie_str_tmp, log)
                payload_tmp = {
                    "conditions": {
                        "semester_id": [s_id],
                        "academic_year_id": [y_id],
                        "keyword": "",
                        "classify_type": "recently_started",
                        "display_studio_list": False,
                    },
                    "fields": "id,name",
                    "page": 1,
                    "page_size": 1,
                    "showScorePassedStatus": False,
                }
                resp_tmp  = await context.request.post(
                    f"{BASE_URL}/api/my-courses", data=payload_tmp
                )
                data_tmp  = await resp_tmp.json()
                courses_tmp = data_tmp.get("courses", data_tmp.get("data", []))
                if courses_tmp:
                    first_id = courses_tmp[0]["id"]
                    log(f"👉 后台秒定课程ID {first_id}喵，正在控制浏览器直接跳走喵！")
                    await page.goto(f"{BASE_URL}/course/{first_id}/rollcall")
                    for _ in range(15):
                        if student_id is not None:
                            break
                        await asyncio.sleep(1)
            except Exception as e:
                log(f"⚠️ 跳转触发失败，原因：{e}")

        cookies = await context.cookies()
        lnt_cookies = [c for c in cookies if "lnt.xmu.edu.cn" in c.get("domain", "")]
        cookie_str  = "; ".join(f"{c['name']}={c['value']}" for c in lnt_cookies)
        await context.close()

        if not student_id:
            log("❌ 经过所有手段均未能获取学生ID。呜喵")
        return cookie_str, student_id


def get_courses(cookie, s_id, y_id, log=print):
    log("❤ 正在获取课程列表喵~❤...")
    headers = {
        **HEADERS_BASE,
        "cookie": cookie,
        "content-type": "application/json",
        "referer": "https://lnt.xmu.edu.cn/user/index",
    }
    payload = {
        "conditions": {
            "semester_id": [s_id],
            "academic_year_id": [y_id],
            "keyword": "",
            "classify_type": "recently_started",
            "display_studio_list": False,
        },
        "fields": "id,name,display_name",
        "page": 1,
        "page_size": 30,
        "showScorePassedStatus": False,
    }
    resp = requests.post(f"{BASE_URL}/api/my-courses", headers=headers, json=payload, timeout=15)
    try:
        data = resp.json()
    except Exception:
        log(f"⚠️ 返回数据解析失败: {resp.text}")
        return []

    if isinstance(data, list):
        courses = data
    elif "courses" in data:
        courses = data["courses"]
    elif "data" in data:
        courses = data["data"]
    else:
        log("⚠️ 无法解析课程列表喵呜~")
        return []

    seen, unique = set(), []
    for c in courses:
        cid = c.get("id")
        if cid not in seen:
            seen.add(cid)
            unique.append(c)
    return unique


def get_latest_rollcall_id(course_id, cookie, student_id):
    headers = {**HEADERS_BASE, "cookie": cookie}
    url  = (
        f"{BASE_URL}/api/course/{course_id}"
        f"/student/{student_id}/rollcalls?page=1&page_size=99"
    )
    resp = requests.get(url, headers=headers, timeout=12)
    data = resp.json()

    if isinstance(data, list):
        rollcalls = data
    elif isinstance(data, dict) and "rollcalls" in data:
        rollcalls = data["rollcalls"]
    elif isinstance(data, dict) and "data" in data:
        rollcalls = data["data"]
    else:
        rollcalls = []

    if not rollcalls:
        return None, None
    latest = max(
        rollcalls,
        key=lambda item: parse_lnt_timestamp(
            item.get("rollcall_time") or item.get("created_at") or item.get("start_time") or item.get("updated_at")
        ),
    )
    return (
        latest.get("id") or latest.get("rollcall_id"),
        latest.get("rollcall_time") or latest.get("created_at") or latest.get("start_time"),
    )


def get_number_code(rollcall_id, cookie):
    headers = {**HEADERS_BASE, "cookie": cookie}
    url  = f"{BASE_URL}/api/rollcall/{rollcall_id}/student_rollcalls"
    resp = requests.get(url, headers=headers, timeout=12)
    data = resp.json()
    status = str(find_nested_value(data, ("status", "rollcall_status")) or "").lower()
    code = find_nested_value(data, ("number_code", "numberCode"))
    end_time = find_nested_value(data, ("end_time", "endTime", "ended_at", "end_at"))
    return code, status, end_time


def is_number_rollcall_active(status):
    return str(status or "").lower() in ACTIVE_NUMBER_STATUSES


def is_number_rollcall_finished(status):
    return str(status or "").lower() in FINISHED_NUMBER_STATUSES


def normalize_rollcall_event(rollcall):
    if not isinstance(rollcall, dict):
        return None
    rollcall_id = rollcall.get("rollcall_id") or rollcall.get("id")
    if not rollcall_id:
        return None
    course_id = rollcall.get("course_id") or rollcall.get("courseId") or "-"
    status = str(rollcall.get("status") or "").lower()
    rollcall_status = str(rollcall.get("rollcall_status") or "").lower()
    return {
        "raw": rollcall,
        "rollcall_id": rollcall_id,
        "course_id": course_id,
        "course_name": rollcall.get("course_title") or rollcall.get("course_name") or str(course_id),
        "is_number": bool(rollcall.get("is_number")),
        "is_radar": bool(rollcall.get("is_radar")),
        "is_expired": bool(rollcall.get("is_expired")),
        "status": status,
        "rollcall_status": rollcall_status,
        "time": rollcall.get("created_at") or rollcall.get("rollcall_time") or rollcall.get("start_time") or "待签到",
    }


def is_active_number_event(event):
    if not event or not event.get("is_number") or event.get("is_radar"):
        return False
    if event.get("is_expired"):
        return False
    status = str(event.get("status") or "").lower()
    rollcall_status = str(event.get("rollcall_status") or "").lower()
    if status in SIGNED_ROLLCALL_STATUSES or rollcall_status in FINISHED_NUMBER_STATUSES:
        return False
    return is_number_rollcall_active(status)


def is_active_radar_event(event):
    if not event or not event.get("is_radar"):
        return False
    if event.get("is_expired"):
        return False
    status = str(event.get("status") or "").lower()
    return status == "absent"


def get_active_rollcall_events(cookie, log=print):
    return [
        event for event in (normalize_rollcall_event(item) for item in get_radar_rollcalls(cookie, log))
        if event and (is_active_number_event(event) or is_active_radar_event(event))
    ]


def get_radar_rollcalls(cookie, log=print):
    data = lnt_get_json(cookie, "/api/radar/rollcalls?api_version=1.1.0", log)
    return _extract_lnt_list(data, "rollcalls")
def _parse_notify_scalar(value):
    value = str(value).strip()
    if not value:
        return None
    if value[0] in ('"', "'") and value[-1:] == value[0]:
        value = value[1:-1]
    else:
        value = value.split("#", 1)[0].strip()
    lowered = value.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("", "null", "none", "~"):
        return None
    try:
        return int(value)
    except ValueError:
        return value


def load_score_notify_config(log=print):
    """Read the score-query notification config without requiring PyYAML."""
    config_file = get_score_notify_config_file()
    if not config_file.exists():
        return "", {}
    try:
        import yaml
        with config_file.open("r", encoding="utf-8") as f:
            conf = yaml.load(f, Loader=yaml.FullLoader) or {}
        return str(conf.get("notify") or "").strip().lower(), conf.get("email") or {}
    except FileNotFoundError:
        return "", {}
    except ModuleNotFoundError:
        pass
    except Exception as exc:
        log(f"[monitor] cannot load score notification config: {exc}")
        return "", {}

    notify_type = ""
    email_conf = {}
    in_email = False
    try:
        for raw_line in config_file.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            line = raw_line.strip()
            if indent == 0:
                in_email = False
                if line.startswith("notify:"):
                    notify_type = str(_parse_notify_scalar(line.split(":", 1)[1]) or "").strip().lower()
                elif line.startswith("email:"):
                    in_email = True
            elif in_email and ":" in line:
                key, value = line.split(":", 1)
                email_conf[key.strip()] = _parse_notify_scalar(value)
    except Exception as exc:
        log(f"[monitor] cannot parse score notification config: {exc}")
        return "", {}

    return notify_type, email_conf

def report_rollcall_with_smtp(title, message, smtp_conf):
    host = smtp_conf.get("host")
    port = smtp_conf.get("port")
    username = smtp_conf.get("username")
    password = smtp_conf.get("password")
    receiver = smtp_conf.get("receiver") or username
    use_ssl = bool(smtp_conf.get("use_ssl", False))
    if not host or not port or not username or not password or not receiver:
        raise ValueError("SMTP notification config is incomplete")

    recipients = receiver if isinstance(receiver, list) else [receiver]
    msg = MIMEText(message, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = "%s <%s>" % (Header("签到提醒", "utf-8").encode(), username)
    msg["To"] = Header(",".join(str(r) for r in recipients), "utf-8")

    smtp = smtplib.SMTP_SSL(host, int(port), timeout=15) if use_ssl else smtplib.SMTP(host, int(port), timeout=15)
    try:
        smtp.login(username, password)
        smtp.sendmail(username, recipients, msg.as_string())
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


def report_rollcall_with_system_notification(title, message, log=print):
    try:
        from plyer import notification
    except Exception:
        log("[monitor] plyer is not installed; skipped score-style system notification")
        return
    notification.notify(title=title, message=message[:256], app_icon=None, timeout=10)


def notify_with_score_config(title, message, log=print):
    notify_type, smtp_conf = load_score_notify_config(log)
    if notify_type in ("", "none", "off", "false"):
        return
    if notify_type in ("email", "both"):
        report_rollcall_with_smtp(title, message, smtp_conf)
        log("[monitor] score-style email notification sent")
    if notify_type in ("system", "both"):
        report_rollcall_with_system_notification(title, message, log)

# ── 雷达签到：常用教学楼预设位置 ──────────────────────────────

# ── 学习通/畅课课程工具：考试、课堂互动、试题与答案查询 ───────────────
class LntHtmlTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("p", "div", "section", "article", "tr", "ul", "ol"):
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "img":
            src = attrs.get("src") or attrs.get("data-src") or ""
            if src:
                self.parts.append(f"[图片: {src}]")
        elif tag == "span" and "__blank__" in attrs.get("class", ""):
            self.parts.append("____")

    def handle_data(self, data):
        if data:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in ("p", "div", "section", "article", "tr", "li"):
            self.parts.append("\n")


def lnt_html_to_text(value):
    if value is None:
        return ""
    raw = str(value)
    if "<" not in raw and "&" not in raw:
        return raw.strip()
    parser = LntHtmlTextParser()
    try:
        parser.feed(raw)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        text = raw
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


SUBJECT_TYPE_NAMES = {
    "single_selection": "单选题",
    "multiple_selection": "多选题",
    "true_or_false": "判断题",
    "fill_in_blank": "填空题",
    "short_answer": "简答题",
    "paragraph_desc": "段落说明",
    "analysis": "综合题",
    "media": "听力题",
    "text": "文本",
}


def format_lnt_time(value):
    if value in (None, ""):
        return "未设置"
    if not isinstance(value, str):
        return str(value)
    try:
        raw = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return value


def _lnt_headers(cookie):
    return {
        **HEADERS_BASE,
        "cookie": cookie,
        "referer": f"{BASE_URL}/user/index",
        "x-requested-with": "XMLHttpRequest",
    }


def lnt_get_json(cookie, api_path, log=print):
    url = api_path if str(api_path).startswith("http") else f"{BASE_URL}{api_path}"
    resp = requests.get(url, headers=_lnt_headers(cookie), timeout=15)
    if resp.status_code in (401, 403):
        raise RuntimeError("登录状态可能已过期，请回到主页重新登录后再试。")
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        return resp.json()
    except Exception as exc:
        raise RuntimeError(f"学习通返回内容不是 JSON: {exc}") from exc


def _extract_lnt_list(data, key):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    value = data.get(key)
    if isinstance(value, list):
        return value
    value = data.get("data")
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        nested = value.get(key)
        if isinstance(nested, list):
            return nested
    return []


def get_lnt_exam_list(course_id, cookie, log=print):
    log(f"🧪 正在查询课程 {course_id} 的考试/作业列表...")
    data = lnt_get_json(cookie, f"/api/courses/{course_id}/exams", log)
    return _extract_lnt_list(data, "exams")


def get_lnt_classroom_list(course_id, cookie, log=print):
    log(f"🧩 正在查询课程 {course_id} 的课堂互动列表...")
    data = lnt_get_json(cookie, f"/api/courses/{course_id}/classroom-list", log)
    return _extract_lnt_list(data, "classrooms")


def _subject_type_name(subject):
    raw = str(subject.get("type") or "text")
    return SUBJECT_TYPE_NAMES.get(raw, raw)


def _format_subject(subject, include_answers=False, depth=0):
    indent = "  " * depth
    sort = subject.get("sort")
    number = sort + 1 if isinstance(sort, int) else "?"
    title = f"{indent}{number}. ({_subject_type_name(subject)})"
    point = subject.get("point")
    if point not in (None, ""):
        title += f" [{point} 分]"

    lines = [title]
    description = lnt_html_to_text(subject.get("description"))
    if description:
        lines.append(f"{indent}{description}")

    answer_letters = []
    submitted_letters = []
    options = subject.get("options") or []
    options = sorted(options, key=lambda item: item.get("sort", 0))
    for option in options:
        option_sort = option.get("sort", 0)
        option_chr = chr(ord("A") + int(option_sort) % 26)
        option_text = lnt_html_to_text(option.get("content")) or "(空选项)"
        mark_parts = []
        if include_answers and option.get("is_answer"):
            answer_letters.append(option_chr)
            mark_parts.append("✓")
        if include_answers and option.get("_submitted"):
            submitted_letters.append(option_chr)
            mark_parts.append("你的提交")
        mark = f"  [{' / '.join(mark_parts)}]" if mark_parts else ""
        lines.append(f"{indent}{option_chr}. {option_text}{mark}")

    if include_answers:
        correct_answers = subject.get("correct_answers") or []
        submitted_texts = subject.get("_submitted_answer_texts") or []
        if answer_letters:
            lines.append(f"{indent}正确答案: {''.join(answer_letters)}")
        elif correct_answers:
            correct_answers = sorted(correct_answers, key=lambda item: item.get("sort", 0))
            answer_text = ", ".join(
                lnt_html_to_text(item.get("content")) or str(item.get("content") or "")
                for item in correct_answers
            ).strip(", ")
            lines.append(f"{indent}正确答案: {answer_text or '平台未返回可读答案'}")
        elif subject.get("type") not in ("paragraph_desc", "text"):
            lines.append(f"{indent}正确答案: 平台未返回可解析答案")

        if submitted_letters:
            lines.append(f"{indent}你的提交: {''.join(sorted(set(submitted_letters)))}")
        elif submitted_texts:
            lines.append(f"{indent}你的提交: {', '.join(submitted_texts)}")

        explanation = lnt_html_to_text(subject.get("answer_explanation"))
        wrong_explanation = lnt_html_to_text(subject.get("wrong_explanation"))
        if explanation:
            lines.append(f"{indent}答案解析: {explanation}")
        if wrong_explanation:
            lines.append(f"{indent}错误解析: {wrong_explanation}")

    sub_subjects = subject.get("sub_subjects") or []
    for sub in sorted(sub_subjects, key=lambda item: item.get("sort", 0)):
        lines.append(_format_subject(sub, include_answers=include_answers, depth=depth + 1))

    return "\n".join(line for line in lines if line is not None)

def format_lnt_subjects(subjects, include_answers=False):
    if not subjects:
        return "平台没有返回题目内容。"
    rendered = []
    for subject in sorted(subjects, key=lambda item: item.get("sort", 0)):
        rendered.append(_format_subject(subject, include_answers=include_answers))
    return "\n\n".join(rendered).strip()


def get_lnt_exam_questions(exam_id, cookie, log=print):
    log(f"📄 正在抓取考试/作业 {exam_id} 的试题...")
    data = lnt_get_json(cookie, f"/api/exams/{exam_id}/distribute", log)
    subjects = _extract_lnt_list(data, "subjects")
    return format_lnt_subjects(subjects, include_answers=False)



def _walk_lnt_subjects(subjects):
    for subject in subjects or []:
        yield subject
        yield from _walk_lnt_subjects(subject.get("sub_subjects") or [])


def _extract_submission_subjects(detail):
    if not isinstance(detail, dict):
        return []
    roots = [detail]
    for key in ("data", "submission", "result"):
        value = detail.get(key)
        if isinstance(value, dict):
            roots.append(value)
    for root in roots:
        subject_data = root.get("subjects_data")
        if isinstance(subject_data, dict) and isinstance(subject_data.get("subjects"), list):
            return subject_data["subjects"]
        if isinstance(root.get("subjects"), list):
            return root["subjects"]
    return []


def _extract_correct_answer_entries(detail):
    if not isinstance(detail, dict):
        return []
    roots = [detail]
    for key in ("data", "submission", "result"):
        value = detail.get(key)
        if isinstance(value, dict):
            roots.append(value)
    for root in roots:
        correct_data = root.get("correct_answers_data")
        entries = _extract_lnt_list(correct_data or {}, "correct_answers")
        if entries:
            return entries
    return []


def _merge_correct_answers_into_subjects(subjects, detail):
    entries = _extract_correct_answer_entries(detail)
    by_subject = {}
    for entry in entries:
        subject_id = entry.get("subject_id")
        if subject_id is not None:
            by_subject.setdefault(subject_id, []).append(entry)

    for subject in _walk_lnt_subjects(subjects):
        subject_entries = by_subject.get(subject.get("id"), [])
        if not subject_entries:
            continue

        answer_option_ids = set()
        text_answers = []
        for entry in subject_entries:
            for option_id in entry.get("answer_option_ids") or []:
                answer_option_ids.add(option_id)
            content = entry.get("content")
            if content not in (None, ""):
                text_answers.append({"content": content, "sort": len(text_answers)})

        if answer_option_ids:
            for option in subject.get("options") or []:
                if option.get("id") in answer_option_ids:
                    option["is_answer"] = True
        if text_answers and not subject.get("correct_answers"):
            subject["correct_answers"] = text_answers

    return len(entries)

def _extract_submission_answer_entries(detail):
    if not isinstance(detail, dict):
        return []
    roots = [detail]
    for key in ("data", "submission", "result"):
        value = detail.get(key)
        if isinstance(value, dict):
            roots.append(value)
    for root in roots:
        submission_data = root.get("submission_data")
        entries = _extract_lnt_list(submission_data or {}, "subjects")
        if entries:
            return entries
        for key in ("submitted_answers", "answers", "subject_answers"):
            value = root.get(key)
            if isinstance(value, list):
                return value
    return []


def _merge_submitted_answers_into_subjects(subjects, detail):
    entries = _extract_submission_answer_entries(detail)
    by_subject = {}
    for entry in entries:
        subject_id = entry.get("subject_id") or entry.get("id")
        if subject_id is not None:
            by_subject.setdefault(subject_id, []).append(entry)

    merged = 0
    for subject in _walk_lnt_subjects(subjects):
        subject_entries = by_subject.get(subject.get("id"), [])
        if not subject_entries:
            continue
        option_ids = set()
        text_answers = []
        for entry in subject_entries:
            for key in ("answer_option_ids", "option_ids", "selected_option_ids"):
                for option_id in entry.get(key) or []:
                    option_ids.add(option_id)
            single_option_id = entry.get("answer_option_id") or entry.get("option_id")
            if single_option_id is not None:
                option_ids.add(single_option_id)
            for key in ("answer", "content", "text"):
                content = entry.get(key)
                if content not in (None, ""):
                    text_answers.append(lnt_html_to_text(content) or str(content))

        if option_ids:
            merged += 1
            for option in subject.get("options") or []:
                if option.get("id") in option_ids:
                    option["_submitted"] = True
        if text_answers:
            merged += 1
            subject["_submitted_answer_texts"] = text_answers

    return merged


def save_lnt_json_debug(title, data, log=print):
    LNT_REPORTS_DIR.mkdir(exist_ok=True)
    safe_title = re.sub(r"[^0-9A-Za-z_\-]+", "_", str(title)).strip("_") or "lnt_debug"
    path = LNT_REPORTS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_title}_{uuid.uuid4().hex[:8]}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"✅ 已保存答案接口原始 JSON：{path}")
    return path

def _answer_entry_to_text(entry):
    parts = []
    option_ids = entry.get("answer_option_ids") or entry.get("option_ids") or entry.get("selected_option_ids") or []
    if option_ids:
        parts.append("选项ID: " + ", ".join(str(x) for x in option_ids))
    single_option_id = entry.get("answer_option_id") or entry.get("option_id")
    if single_option_id is not None:
        parts.append(f"选项ID: {single_option_id}")
    for key in ("content", "answer", "text"):
        value = entry.get(key)
        if value not in (None, ""):
            parts.append(lnt_html_to_text(value) or str(value))
    return "；".join(parts) if parts else "无可读内容"


def _format_answer_entries(title, entries):
    if not entries:
        return f"{title}: 无"
    lines = [f"{title}:"]
    for idx, entry in enumerate(entries, 1):
        subject_id = entry.get("subject_id") or entry.get("id") or "-"
        lines.append(f"{idx}. subject_id={subject_id} | {_answer_entry_to_text(entry)}")
    return "\n".join(lines)
def get_lnt_exam_answers(exam_id, cookie, log=print):
    log(f"✅ 正在请求考试/作业 {exam_id} 的答案/解析接口...")
    submissions_data = lnt_get_json(cookie, f"/api/exams/{exam_id}/submissions", log)
    submissions = _extract_lnt_list(submissions_data, "submissions")
    if not submissions:
        raise RuntimeError("未找到提交记录，或平台当前没有向此账号返回可用答案记录。")

    last_detail = None
    last_debug_path = None
    tried_ids = []
    for submission in reversed(submissions):
        submission_id = submission.get("id")
        if not submission_id:
            continue
        tried_ids.append(str(submission_id))
        detail = lnt_get_json(cookie, f"/api/exams/{exam_id}/submissions/{submission_id}", log)
        last_detail = detail
        last_debug_path = save_lnt_json_debug(f"exam_{exam_id}_submission_{submission_id}", detail, log)

        correct_entries = _extract_correct_answer_entries(detail)
        submitted_entries = _extract_submission_answer_entries(detail)
        if correct_entries or submitted_entries:
            note = [
                f"提交ID: {submission_id}",
                f"正确答案条目数: {len(correct_entries)}",
                f"你的提交条目数: {len(submitted_entries)}",
            ]
            if not correct_entries and submitted_entries:
                note.append("当前接口只返回你的提交，没有返回正确答案字段。")
            if last_debug_path:
                note.append(f"原始 JSON 已保存: {last_debug_path}")
            return "\n".join(note) + "\n\n" + _format_answer_entries("正确答案", correct_entries) + "\n\n" + _format_answer_entries("你的提交", submitted_entries)

    if last_detail is not None:
        detail_keys = ", ".join(last_detail.keys()) if isinstance(last_detail, dict) else type(last_detail).__name__
        raise RuntimeError(f"答案接口有返回，但没有答案/提交字段可解析。已尝试提交ID：{', '.join(tried_ids) or '-'}；返回字段：{detail_keys}；原始JSON：{last_debug_path or '-'}")

    raise RuntimeError("提交记录里没有可用 submission_id。")

def get_lnt_classroom_subjects(classroom_id, cookie, log=print):
    log(f"📄 正在抓取课堂互动 {classroom_id} 的题目内容...")
    data = lnt_get_json(cookie, f"/api/classroom/{classroom_id}/subject", log)
    subjects = _extract_lnt_list(data, "subjects")
    return format_lnt_subjects(subjects, include_answers=False)


def save_lnt_html_report(title, body_text, log=print):
    LNT_REPORTS_DIR.mkdir(exist_ok=True)
    file_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.html"
    path = LNT_REPORTS_DIR / file_name
    html = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
<meta charset=\"utf-8\">
<title>{escape(title)}</title>
<style>
body {{ margin: 0; background: #f6f7fb; color: #17141f; font-family: -apple-system, BlinkMacSystemFont, 'Microsoft YaHei', sans-serif; }}
main {{ max-width: 920px; margin: 32px auto; padding: 0 20px 48px; }}
h1 {{ font-size: 24px; margin: 0 0 16px; }}
pre {{ white-space: pre-wrap; word-break: break-word; background: #fff; border: 1px solid #e7e8ef; border-radius: 8px; padding: 20px; line-height: 1.7; font-size: 15px; }}
.meta {{ color: #667085; font-size: 13px; margin-bottom: 16px; }}
</style>
</head>
<body>
<main>
<h1>{escape(title)}</h1>
<div class=\"meta\">生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
<pre>{escape(body_text)}</pre>
</main>
</body>
</html>"""
    path.write_text(html, encoding="utf-8")
    log(f"✅ 已生成 HTML 报告：{path}")
    return path

RADAR_GROUP_ORDER = ["翔安校区", "思明校区", "马来西亚分校", "自定义"]


RADAR_LOCATIONS = {
    # 翔安校区：参考 xmu_assistant_sign_bot 位置库，并保留原项目常用预设。
    "翔安-学武楼": (24.605488, 118.313790),
    "翔安-西部片区2号": (24.604252, 118.299904),
    "翔安-一期田径场": (24.608957, 118.318870),
    "翔安-西部片区4号": (24.605270, 118.300186),
    "翔安-文宣楼": (24.605280, 118.309970),
    "翔安-坤銮楼": (24.605589, 118.312744),
    "翔安-南存钿楼": (24.604958, 118.318860),
    "翔安-佘明培游泳馆": (24.610806, 118.311920),
    "翔安-爱秋体育馆": (24.611519, 118.310510),
    "翔安-一期篮球场": (24.608389, 118.317240),
    "翔安-新工科大楼": (24.614680, 118.310300),
    "翔安-德旺图书馆": (24.605600, 118.311410),
    "翔安-教学楼5号": (24.604890, 118.309050),
    "翔安-二期田径场": (24.609406, 118.302666),
    "翔安-二期篮球场": (24.610474, 118.303000),
    "翔安-西部片区正信楼": (24.603584, 118.300390),
    "翔安-西部片区益海嘉里楼": (24.604538, 118.300995),
    "翔安-西部片区5号": (24.605577, 118.301510),
    "翔安-航院大楼": (24.608620, 118.311130),

    # 思明校区
    "思明-庄汉水楼": (24.437782, 118.096520),
    "思明-南强楼": (24.439000, 118.098000),
    "思明-嘉庚楼群": (24.438500, 118.100000),
    "思明-建南大会堂": (24.440000, 118.097000),
    "思明-法学院": (24.436500, 118.095500),
    "思明-经济学院": (24.437000, 118.093500),
    "思明-管理学院": (24.436000, 118.098500),
    "思明-图书馆": (24.439500, 118.096000),
    "思明-海韵园": (24.430412, 118.113840),
    "思明-集美楼": (24.436747, 118.096320),

    # 马来西亚分校
    "马来西亚-厦门大学马来西亚分校": (1.492700, 103.646600),
}


RADAR_LOCATION_ALIASES = {
    "庄汉水楼": "思明-庄汉水楼",
    "南强楼": "思明-南强楼",
    "嘉庚楼群": "思明-嘉庚楼群",
    "建南大会堂": "思明-建南大会堂",
    "法学院": "思明-法学院",
    "经济学院": "思明-经济学院",
    "管理学院": "思明-管理学院",
    "图书馆": "思明-图书馆",
    "厦门大学马来西亚分校": "马来西亚-厦门大学马来西亚分校",
}


def radar_location_group(name):
    if name.startswith("翔安-"):
        return "翔安校区"
    if name.startswith("思明-"):
        return "思明校区"
    if name.startswith("马来西亚-") or "马来西亚" in name:
        return "马来西亚分校"
    return "自定义"


def grouped_radar_locations(custom_locations):
    grouped = {group: {} for group in RADAR_GROUP_ORDER}
    for name, coords in RADAR_LOCATIONS.items():
        grouped.setdefault(radar_location_group(name), {})[name] = coords
    for name, coords in custom_locations.items():
        grouped.setdefault("自定义", {})[name] = coords
    return {group: items for group, items in grouped.items() if items}


def load_custom_radar_locations(log=print):
    try:
        if not CUSTOM_RADAR_LOCATIONS_FILE.exists():
            return {}
        with CUSTOM_RADAR_LOCATIONS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        locations = {}
        for name, coords in data.items():
            if isinstance(name, str) and isinstance(coords, list) and len(coords) == 2:
                locations[name] = (float(coords[0]), float(coords[1]))
        return locations
    except Exception as e:
        log(f"⚠️ 自定义预设读取失败：{e}")
        return {}


def save_custom_radar_locations(locations, log=print):
    data = {str(name): [float(lat), float(lng)] for name, (lat, lng) in locations.items()}
    try:
        CUSTOM_RADAR_LOCATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with CUSTOM_RADAR_LOCATIONS_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log(f"❌ 自定义预设保存失败：{e}")
        return False


def all_radar_locations(custom_locations):
    return {**RADAR_LOCATIONS, **custom_locations}


def _parse_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        if not match:
            return None
        try:
            return float(match.group(0))
        except ValueError:
            return None


def radar_distance_meters(lat1, lng1, lat2, lng2):
    radius = 6371000.0
    lat1_rad = math.radians(float(lat1))
    lat2_rad = math.radians(float(lat2))
    dlat = math.radians(float(lat2) - float(lat1))
    dlng = math.radians(float(lng2) - float(lng1))
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def format_radar_distance(meters):
    if meters is None:
        return "未知"
    if meters >= 1000:
        return f"{meters / 1000:.2f} km"
    return f"{meters:.0f} m"


def shift_radar_coordinate(latitude, longitude, north_meters=0, east_meters=0):
    radius = 6371000.0
    lat = float(latitude)
    lng = float(longitude)
    next_lat = lat + math.degrees(float(north_meters) / radius)
    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-9:
        next_lng = lng
    else:
        next_lng = lng + math.degrees(float(east_meters) / (radius * cos_lat))
    return next_lat, next_lng


def nearest_radar_locations(latitude, longitude, custom_locations=None, group=None, exclude_name=None, limit=5):
    candidates = []
    for name, (lat, lng) in all_radar_locations(custom_locations or {}).items():
        if exclude_name and name == exclude_name:
            continue
        loc_group = radar_location_group(name)
        if group and loc_group != group:
            continue
        try:
            distance = radar_distance_meters(latitude, longitude, lat, lng)
        except Exception:
            continue
        candidates.append((distance, name, lat, lng, loc_group))
    candidates.sort(key=lambda item: item[0])
    return candidates[:limit]


def _find_first_value(data, keys, depth=0, max_depth=5):
    if depth > max_depth:
        return None
    if isinstance(data, dict):
        for key in keys:
            if key in data:
                return data.get(key)
        for value in data.values():
            found = _find_first_value(value, keys, depth + 1, max_depth)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_first_value(item, keys, depth + 1, max_depth)
            if found is not None:
                return found
    return None


def parse_radar_failure_detail(resp):
    try:
        data = resp.json()
    except Exception:
        text = (resp.text or "").strip()
        return {
            "status": resp.status_code,
            "message": text[:200] if text else "平台未返回可解析内容",
            "distance": None,
            "raw": {},
        }

    message = None
    if isinstance(data, dict):
        for key in ("message", "msg", "error", "error_message"):
            if data.get(key):
                message = str(data.get(key))
                break
        distance = _parse_float(_find_first_value(data, ("distance", "distance_m", "meter", "meters")))
    else:
        message = str(data)[:200]
        distance = None

    return {
        "status": resp.status_code,
        "message": message or "平台未返回错误说明",
        "distance": distance,
        "raw": data if isinstance(data, dict) else {"data": data},
    }


def format_radar_failure_detail(detail):
    parts = [f"HTTP {detail.get('status')}"]
    if detail.get("message"):
        parts.append(str(detail.get("message")))
    distance = detail.get("distance")
    if distance is not None:
        parts.append(f"平台判定当前坐标距签到点约 {format_radar_distance(distance)}")
    return "；".join(parts)


def build_radar_location_advice(latitude, longitude, custom_locations=None, location_name=None, server_distance=None):
    lines = []
    if server_distance is not None:
        if server_distance >= 1000:
            lines.append("距离偏大，优先检查校区或楼宇预设是否选错。")
        elif server_distance >= 120:
            lines.append("可能是楼宇附近坐标偏移，可改选同校区相邻预设。")
        else:
            lines.append("距离已经较近，可优先校正到当前教室所在楼宇入口附近。")

    group = None
    if location_name:
        group = radar_location_group(location_name)
        if group != "自定义":
            lines.append(f"当前预设：{location_name}（{group}）")
        else:
            group = None
            lines.append(f"当前预设：{location_name}")

    candidates = nearest_radar_locations(
        latitude,
        longitude,
        custom_locations or {},
        group=group,
        exclude_name=location_name,
        limit=5,
    )
    if not candidates and group:
        candidates = nearest_radar_locations(
            latitude,
            longitude,
            custom_locations or {},
            exclude_name=location_name,
            limit=5,
        )

    if candidates:
        label = "同校区附近预设" if group else "附近预设"
        items = [f"{name}({format_radar_distance(distance)})" for distance, name, _lat, _lng, _group in candidates]
        lines.append(f"{label}：" + "；".join(items))

    return "\n".join(lines)


def find_number_code(data, depth=0, max_depth=10):
    if depth > max_depth:
        return None
    if isinstance(data, dict):
        number_code = data.get("number_code")
        if number_code is not None:
            return str(number_code)
        for value in data.values():
            nested = find_number_code(value, depth + 1, max_depth)
            if nested:
                return nested
    elif isinstance(data, list):
        for item in data:
            nested = find_number_code(item, depth + 1, max_depth)
            if nested:
                return nested
    return None


def send_number_rollcall(rollcall_id, cookie, number_code=None, log=print):
    """提交数字签到。调用方必须已经获得用户确认。"""
    headers = {
        **HEADERS_BASE,
        "content-type": "application/json",
        "cookie": cookie,
    }
    if not number_code:
        try:
            resp = requests.get(
                f"{BASE_URL}/api/rollcall/{rollcall_id}/student_rollcalls",
                headers=headers,
                timeout=10,
            )
            if resp.status_code != 200:
                msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                log(f"❌ 获取数字签到码失败：{msg}")
                return False, msg
            number_code = find_number_code(resp.json())
        except Exception as exc:
            log(f"❌ 获取数字签到码异常：{exc}")
            return False, str(exc)
    if not number_code:
        msg = "未找到 number_code"
        log(f"❌ 数字签到失败：{msg}")
        return False, msg

    payload = {"deviceId": str(uuid.uuid4()), "numberCode": str(number_code)}
    try:
        resp = requests.put(
            f"{BASE_URL}/api/rollcall/{rollcall_id}/answer_number_rollcall",
            json=payload,
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            log(f"✅ 数字签到已提交，签到码：{number_code}")
            return True, None
        msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
        log(f"❌ 数字签到提交失败：{msg}")
        return False, msg
    except Exception as exc:
        log(f"❌ 数字签到请求异常：{exc}")
        return False, str(exc)


def get_default_radar_location(custom_locations=None):
    data = load_account_data(lambda _msg: None)
    name = str(data.get("default_radar_location") or "").strip()
    if not name:
        return None
    locations = all_radar_locations(custom_locations or load_custom_radar_locations(lambda _msg: None))
    coords = locations.get(name)
    if not coords:
        return None
    return name, coords[0], coords[1]

def parse_radar_failure(resp):
    return format_radar_failure_detail(parse_radar_failure_detail(resp))





def _latlon_to_xy(lat, lon, lat0, lon0):
    R = 6371000
    x = math.radians(lon - lon0) * R * math.cos(math.radians(lat0))
    y = math.radians(lat - lat0) * R
    return x, y


def _xy_to_latlon(x, y, lat0, lon0):
    R = 6371000
    lat = lat0 + math.degrees(y / R)
    lon = lon0 + math.degrees(x / (R * math.cos(math.radians(lat0))))
    return lat, lon


def _circle_intersections(x1, y1, d1, x2, y2, d2):
    D = math.hypot(x2 - x1, y2 - y1)
    if D > d1 + d2 or D < abs(d1 - d2):
        return None
    a = (d1**2 - d2**2 + D**2) / (2 * D)
    h = math.sqrt(d1**2 - a**2)
    xm = x1 + a * (x2 - x1) / D
    ym = y1 + a * (y2 - y1) / D
    rx = -(y2 - y1) * (h / D)
    ry = (x2 - x1) * (h / D)
    return (xm + rx, ym + ry), (xm - rx, ym - ry)


def _trilaterate(lat1, lon1, lat2, lon2, d1, d2):
    lat0 = (lat1 + lat2) / 2
    lon0 = (lon1 + lon2) / 2
    x1, y1 = _latlon_to_xy(lat1, lon1, lat0, lon0)
    x2, y2 = _latlon_to_xy(lat2, lon2, lat0, lon0)
    sols = _circle_intersections(x1, y1, d1, x2, y2, d2)
    if sols is None:
        return None
    return _xy_to_latlon(sols[0][0], sols[0][1], lat0, lon0), _xy_to_latlon(sols[1][0], sols[1][1], lat0, lon0)


def send_radar_rollcall(rollcall_id, cookie, latitude, longitude, log=print, location_name=None, custom_locations=None):
    """向畅课平台发送雷达（GPS）签到请求。调用方必须已经获得用户确认。

    支持自动坐标修正：如果首次提交距离过远，会使用两个探测点
    进行三边测量（trilateration）推算签到点的精确位置后重试。
    """
    url = f"{BASE_URL}/api/rollcall/{rollcall_id}/answer?api_version=1.76"
    headers = {
        "user-agent": (
            "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/141.0.0.0 Mobile Safari/537.36 Edg/141.0.0.0"
        ),
        "content-type": "application/json",
        "cookie": cookie,
    }

    def _build_payload(lat, lng):
        return {
            "accuracy": 35,
            "altitude": 0,
            "altitudeAccuracy": None,
            "deviceId": str(uuid.uuid1()),
            "heading": None,
            "latitude": lat,
            "longitude": lng,
            "speed": None,
        }

    def _do_submit(lat, lng):
        return requests.put(url, json=_build_payload(lat, lng), headers=headers, timeout=10)

    try:
        resp = _do_submit(latitude, longitude)
        if resp.status_code == 200:
            log(f"✅ 雷达签到成功喵❤！位置 ({latitude}, {longitude})")
            return True, None

        detail = parse_radar_failure_detail(resp)
        d1 = detail.get("distance")
        if d1 is not None and d1 > 0:
            PROBE_LAT_1, PROBE_LON_1 = 24.3, 118.0
            PROBE_LAT_2, PROBE_LON_2 = 24.6, 118.2

            resp1 = _do_submit(PROBE_LAT_1, PROBE_LON_1)
            data1 = resp1.json() if resp1.status_code != 200 else {}
            if resp1.status_code == 200:
                return True, None
            dist1 = _parse_float(data1.get("distance")) if isinstance(data1, dict) else None

            resp2 = _do_submit(PROBE_LAT_2, PROBE_LON_2)
            data2 = resp2.json() if resp2.status_code != 200 else {}
            if resp2.status_code == 200:
                return True, None
            dist2 = _parse_float(data2.get("distance")) if isinstance(data2, dict) else None

            if dist1 is not None and dist2 is not None and dist1 > 0 and dist2 > 0:
                sols = _trilaterate(PROBE_LAT_1, PROBE_LON_1, PROBE_LAT_2, PROBE_LON_2, dist1, dist2)
                if sols:
                    for sol_lat, sol_lon in sols:
                        sol_resp = _do_submit(sol_lat, sol_lon)
                        if sol_resp.status_code == 200:
                            return True, None

        msg = format_radar_failure_detail(detail)
        advice = build_radar_location_advice(
            latitude,
            longitude,
            custom_locations or {},
            location_name=location_name,
            server_distance=d1,
        )
        if advice:
            msg = f"{msg}\n{advice}"
        log(f"❌ 雷达签到失败：{msg}")
        return False, msg
    except Exception as e:
        log(f"❌ 雷达签到请求异常：{e}")
        return False, str(e)


# ==============================================================================
# 工具：在后台线程里跑 asyncio 事件循环
# ==============================================================================

def run_async(coro, callback):
    """在独立线程里运行 async 协程，完成后把结果用 callback 送回主线程。"""
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(coro)
            callback(result, None)
        except Exception as e:
            callback(None, e)
        finally:
            loop.close()
    threading.Thread(target=_run, daemon=True).start()


def run_sync_in_thread(fn, callback, *args, **kwargs):
    """在独立线程里运行普通同步函数，完成后 callback 送回结果。"""
    def _run():
        try:
            result = fn(*args, **kwargs)
            callback(result, None)
        except Exception as e:
            callback(None, e)
    threading.Thread(target=_run, daemon=True).start()


# ==============================================================================
# UI 辅助组件
# ==============================================================================

def make_label(parent, text, size=13, color=TEXT_PRI, bold=False, anchor="w", wraplength=0):
    weight = "bold" if bold else "normal"
    return ctk.CTkLabel(
        parent, text=text, font=("Microsoft YaHei", size, weight),
        text_color=color, anchor=anchor, wraplength=wraplength
    )


def make_button(parent, text, command, fg=ACCENT, hover=ACCENT_DK, width=200, height=40, size=13):
    return ctk.CTkButton(
        parent, text=text, command=command,
        fg_color=fg, hover_color=hover, text_color=BG,
        font=("Microsoft YaHei", size, "bold"),
        width=width, height=height, corner_radius=12,
    )


def separator(parent):
    return ctk.CTkFrame(parent, height=1, fg_color=SURFACE2)


# ==============================================================================
# 主应用
# ==============================================================================

class ZakoApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # ── 窗口基础设置 ─────────────────────────────
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.title("Zako 签到助手 ❤")
        self.geometry("680x700")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── 共享状态 ─────────────────────────────────
        self._cookie     = None
        self._student_id = None
        self._courses    = []
        self._busy       = False        # 防止重复点击
        self._monitor_thread = None
        self._monitor_stop = threading.Event()
        self._monitor_seen = set()
        self._monitor_interval = 30
        self._monitor_status_label = None
        self._score_process = None
        self._auto_mode = False
        atexit.register(self._cleanup_child_processes)

        # ── 日志缓冲 ─────────────────────────────────
        self._log_lines  = []

        # ── 根布局：顶栏 + 内容区 ─────────────────────
        self._build_topbar()
        self._content = ctk.CTkFrame(self, fg_color=BG)
        self._content.pack(fill="both", expand=True, padx=0, pady=0)

        # ── 日志抽屉（隐藏态，覆盖在内容区上方）────────
        self._log_drawer_visible = False
        self._build_log_drawer()

        # ── 初始页面 ──────────────────────────────────
        self._custom_radar_locations = load_custom_radar_locations(self._log)
        self._show_home()

    # ─────────────────────────────────────────────────────
    # 顶栏
    # ─────────────────────────────────────────────────────
    def _build_topbar(self):
        bar = ctk.CTkFrame(self, fg_color=SURFACE, height=48, corner_radius=0)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        make_label(bar, "❤ zako", size=15, color=ACCENT, bold=True).pack(
            side="left", padx=16
        )
        ctk.CTkButton(
            bar, text="📋 日志", width=72, height=30,
            fg_color=SURFACE2, hover_color="#2E2C3F", text_color=TEXT_SEC,
            font=("Microsoft YaHei", 12), corner_radius=8,
            command=self._toggle_log_drawer,
        ).pack(side="right", padx=12, pady=9)

    # ─────────────────────────────────────────────────────
    # 日志抽屉
    # ─────────────────────────────────────────────────────
    def _build_log_drawer(self):
        self._drawer = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        # 不 pack，靠 place 覆盖
        self._log_text = ctk.CTkTextbox(
            self._drawer,
            fg_color="#0A0912", text_color=TEXT_SEC,
            font=("Courier New", 11),
            wrap="word", state="disabled",
            corner_radius=8,
        )
        self._log_text.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        ctk.CTkButton(
            self._drawer, text="✕ 关闭日志", width=120, height=28,
            fg_color=SURFACE2, hover_color=ACCENT_DK, text_color=TEXT_SEC,
            font=("Microsoft YaHei", 12), corner_radius=8,
            command=self._toggle_log_drawer,
        ).pack(pady=(0, 8))

    def _toggle_log_drawer(self):
        if self._log_drawer_visible:
            self._drawer.place_forget()
            self._log_drawer_visible = False
        else:
            self._drawer.place(relx=0, rely=0.08, relwidth=1, relheight=0.92)
            self._log_drawer_visible = True

    def _log(self, msg: str):
        """线程安全的日志写入（可从任意线程调用）。"""
        self._log_lines.append(msg)
        print(msg)
        self.after(0, self._flush_log, msg)

    def _flush_log(self, msg: str):
        self._log_text.configure(state="normal")
        self._log_text.insert("end", msg + "\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _terminate_process_tree(self, proc, name="子进程"):
        if not proc or proc.poll() is not None:
            return
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=8,
            )
            self._log(f"✅ 已关闭{name}。")
        except Exception as exc:
            self._log(f"⚠️ 关闭{name}失败，尝试普通终止: {exc}")
            try:
                proc.terminate()
            except Exception:
                pass

    def _cleanup_child_processes(self):
        self._monitor_stop.set()
        self._terminate_process_tree(self._score_process, "成绩查询")
        self._score_process = None

    def _on_close(self):
        self._cleanup_child_processes()
        self.destroy()

    # ─────────────────────────────────────────────────────
    # 内容区切换（清空再重建）
    # ─────────────────────────────────────────────────────
    def _clear_content(self):
        for w in self._content.winfo_children():
            w.destroy()

    # =======================================================
    # 第 1 页：主页  ——  猫爪按钮
    # =======================================================
    def _show_home(self):
        self._clear_content()
        f = self._content

        ctk.CTkFrame(f, fg_color=BG, height=56).pack()

        make_label(f, "XMU 学习工具", size=26, bold=True, anchor="center").pack()
        make_label(f, "选择要启动的功能", size=13, color=TEXT_SEC, anchor="center").pack(pady=(4, 0))

        ctk.CTkFrame(f, fg_color=BG, height=34).pack()

        button_box = ctk.CTkFrame(f, fg_color=BG)
        button_box.pack(pady=(0, 12))

        make_button(
            button_box,
            "成绩查询",
            self._start_score_query,
            fg=SURFACE2,
            hover=ACCENT_DK,
            width=220,
            height=46,
            size=15,
        ).pack(pady=7)

        make_button(
            button_box,
            "教学平台",
            self._open_teaching_platform,
            fg=ACCENT,
            hover=ACCENT_DK,
            width=220,
            height=46,
            size=15,
        ).pack(pady=7)

        make_button(
            button_box,
            "自动评教",
            self._start_iqa_helper,
            fg=SURFACE2,
            hover=ACCENT_DK,
            width=220,
            height=46,
            size=15,
        ).pack(pady=7)

        make_button(
            button_box,
            "选课",
            self._start_course_helper,
            fg=SURFACE2,
            hover=ACCENT_DK,
            width=220,
            height=46,
            size=15,
        ).pack(pady=7)

        make_button(
            button_box,
            "设置",
            self._show_settings,
            fg=WARN,
            hover="#E6B84E",
            width=220,
            height=42,
            size=14,
        ).pack(pady=7)
        ctk.CTkFrame(f, fg_color=BG, height=10).pack()

        self._home_status = make_label(
            f, "运行 setup.bat 初始化；自动评教/选课用 setup_optional_integrations.bat 安装。",
            size=12, color=TEXT_SEC, anchor="center"
        )
        self._home_status.pack()

        ctk.CTkFrame(f, fg_color=BG, height=20).pack()

        make_label(
            f, "厦大 CAS 本机工具",
            size=11, color=TEXT_SEC, anchor="center"
        ).pack(side="bottom", pady=16)
    def _show_settings(self):
        self._clear_content()
        settings = load_settings_values(self._log)
        f = self._content

        header = ctk.CTkFrame(f, fg_color=BG)
        header.pack(fill="x", padx=20, pady=(16, 10))
        ctk.CTkButton(
            header, text="← 返回主页", width=88, height=28,
            fg_color=SURFACE2, hover_color=SURFACE, text_color=TEXT_SEC,
            font=("Microsoft YaHei", 12), corner_radius=8,
            command=self._show_home,
        ).pack(anchor="w", pady=(0, 10))
        make_label(header, "设置", size=24, bold=True).pack(anchor="w")
        make_label(
            header, "调整统一账号、登录、成绩查询、选课和验证码参数。",
            size=12, color=TEXT_SEC
        ).pack(anchor="w", pady=(2, 0))

        login_options = {"复用浏览器会话": "browser", "账号密码自动登录": "account"}
        score_source_options = {"标准成绩接口": "standard", "培养方案完成度": "completion", "自动优先完成度": "auto"}
        notify_options = {"系统通知": "system", "邮件通知": "email", "系统+邮件": "both", "关闭通知": "none"}
        captcha_options = {"LLM 自动识别": "llm", "手动输入": "manual"}
        radar_location_options = {"不设置默认位置": ""}
        radar_location_options.update({name: name for name in all_radar_locations(self._custom_radar_locations)})

        def label_for(mapping, value):
            for label, raw in mapping.items():
                if raw == value:
                    return label
            return next(iter(mapping.keys()))

        vars_map = {
            "username": tk.StringVar(value=settings["username"]),
            "password": tk.StringVar(value=settings["password"]),
            "login_method": tk.StringVar(value=label_for(login_options, settings["login_method"])),
            "default_radar_location": tk.StringVar(value=label_for(radar_location_options, settings["default_radar_location"])),
            "score_auto_login_once": tk.BooleanVar(value=settings["score_auto_login_once"]),
            "score_interval": tk.StringVar(value=str(settings["score_interval"])),
            "score_notify": tk.StringVar(value=label_for(notify_options, settings["score_notify"])),
            "score_show_score": tk.BooleanVar(value=settings["score_show_score"]),
            "score_source": tk.StringVar(value=label_for(score_source_options, settings["score_source"])),
            "score_start_url": tk.StringVar(value=settings["score_start_url"]),
            "completion_pyfadm": tk.StringVar(value=settings["completion_pyfadm"]),
            "completion_pyfamc": tk.StringVar(value=settings["completion_pyfamc"]),
            "completion_pcdm": tk.StringVar(value=settings["completion_pcdm"]),
            "completion_ymjs": tk.StringVar(value=settings["completion_ymjs"]),
            "completion_bynjdm": tk.StringVar(value=settings["completion_bynjdm"]),
            "completion_sclbdm": tk.StringVar(value=settings["completion_sclbdm"]),
            "course_campus": tk.StringVar(value=settings["course_campus"]),
            "course_auto_add_enable": tk.BooleanVar(value=settings["course_auto_add_enable"]),
            "course_check_interval": tk.StringVar(value=str(settings["course_check_interval"])),
            "course_fast_check_interval": tk.StringVar(value=str(settings["course_fast_check_interval"])),
            "course_fast_monitor_seconds": tk.StringVar(value=str(settings["course_fast_monitor_seconds"])),
            "course_add_retry_count": tk.StringVar(value=str(settings["course_add_retry_count"])),
            "course_add_retry_interval": tk.StringVar(value=str(settings["course_add_retry_interval"])),
            "course_interval_jitter": tk.StringVar(value=str(settings["course_interval_jitter"])),
            "captcha_type": tk.StringVar(value=label_for(captcha_options, settings["captcha_type"])),
            "captcha_base_url": tk.StringVar(value=settings["captcha_base_url"]),
            "captcha_api_key": tk.StringVar(value=settings["captcha_api_key"]),
            "captcha_model": tk.StringVar(value=settings["captcha_model"]),
        }

        scroll = ctk.CTkScrollableFrame(f, fg_color=BG, corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        def section(title):
            box = ctk.CTkFrame(scroll, fg_color=SURFACE, corner_radius=12)
            box.pack(fill="x", pady=(0, 12))
            make_label(box, title, size=15, bold=True).pack(anchor="w", padx=16, pady=(14, 10))
            return box

        def row(parent, title):
            line = ctk.CTkFrame(parent, fg_color="transparent")
            line.pack(fill="x", padx=16, pady=(0, 10))
            make_label(line, title, size=12, color=TEXT_SEC).pack(side="left", padx=(0, 12))
            return line

        def entry(parent, title, var, width=300, show=None):
            line = row(parent, title)
            kwargs = {
                "textvariable": var,
                "width": width,
                "height": 32,
                "fg_color": "#0A0912",
                "border_color": SURFACE2,
                "text_color": TEXT_PRI,
                "font": ("Microsoft YaHei", 12),
            }
            if show:
                kwargs["show"] = show
            ctk.CTkEntry(line, **kwargs).pack(side="right")

        def option(parent, title, var, labels, width=230):
            line = row(parent, title)
            ctk.CTkOptionMenu(
                line, variable=var, values=list(labels), width=width, height=32,
                fg_color=SURFACE2, button_color=SURFACE2, button_hover_color=ACCENT_DK,
                dropdown_fg_color=SURFACE, dropdown_hover_color=SURFACE2,
                text_color=TEXT_PRI, font=("Microsoft YaHei", 12),
            ).pack(side="right")

        account_box = section("统一账号与登录")
        entry(account_box, "统一认证账号", vars_map["username"])
        entry(account_box, "统一认证密码", vars_map["password"], show="*")
        option(account_box, "教学平台登录方式", vars_map["login_method"], login_options)
        option(account_box, "默认雷达签到位置", vars_map["default_radar_location"], radar_location_options)

        score_box = section("成绩查询")
        option(score_box, "查分方式", vars_map["score_source"], score_source_options)
        entry(score_box, "查询间隔（分钟）", vars_map["score_interval"], width=160)
        option(score_box, "通知方式", vars_map["score_notify"], notify_options)
        entry(score_box, "教务起始页面 URL", vars_map["score_start_url"])
        make_label(
            score_box,
            "留空时按查分方式自动打开；学业完成进度模式可粘贴培养方案详情页完整 URL。",
            size=11, color=TEXT_SEC, wraplength=560,
        ).pack(anchor="w", padx=16, pady=(0, 8))
        entry(score_box, "PYFADM 培养方案代码", vars_map["completion_pyfadm"])
        entry(score_box, "PYFAMC 培养方案名称", vars_map["completion_pyfamc"])
        compact = ctk.CTkFrame(score_box, fg_color="transparent")
        compact.pack(fill="x", padx=16, pady=(0, 10))
        for idx, (label, key) in enumerate((
            ("PCDM", "completion_pcdm"),
            ("YMJS", "completion_ymjs"),
            ("BYNJDM", "completion_bynjdm"),
            ("SCLBDM", "completion_sclbdm"),
        )):
            compact.grid_columnconfigure(idx, weight=1)
            cell = ctk.CTkFrame(compact, fg_color="transparent")
            cell.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 6, 0))
            make_label(cell, label, size=11, color=TEXT_SEC).pack(anchor="w")
            ctk.CTkEntry(
                cell, textvariable=vars_map[key], height=32,
                fg_color="#0A0912", border_color=SURFACE2, text_color=TEXT_PRI,
                font=("Microsoft YaHei", 12),
            ).pack(fill="x", pady=(2, 0))
        ctk.CTkCheckBox(
            score_box, text="启动成绩查询时尝试账号密码自动登录", variable=vars_map["score_auto_login_once"],
            fg_color=ACCENT, hover_color=ACCENT_DK, text_color=TEXT_SEC,
            font=("Microsoft YaHei", 12), corner_radius=6,
        ).pack(anchor="w", padx=16, pady=(0, 10))
        ctk.CTkCheckBox(
            score_box, text="成绩通知中显示具体分数", variable=vars_map["score_show_score"],
            fg_color=ACCENT, hover_color=ACCENT_DK, text_color=TEXT_SEC,
            font=("Microsoft YaHei", 12), corner_radius=6,
        ).pack(anchor="w", padx=16, pady=(0, 14))

        course_box = section("选课")
        entry(course_box, "校区代码", vars_map["course_campus"], width=160)
        entry(course_box, "常规监听间隔（秒）", vars_map["course_check_interval"], width=160)
        entry(course_box, "快速监听间隔（秒）", vars_map["course_fast_check_interval"], width=160)
        entry(course_box, "快速监听时长（秒）", vars_map["course_fast_monitor_seconds"], width=160)
        entry(course_box, "补选重试次数", vars_map["course_add_retry_count"], width=160)
        entry(course_box, "补选重试间隔（秒）", vars_map["course_add_retry_interval"], width=160)
        entry(course_box, "间隔随机抖动（0-0.3）", vars_map["course_interval_jitter"], width=160)
        ctk.CTkCheckBox(
            course_box, text="发现余量后自动提交选课", variable=vars_map["course_auto_add_enable"],
            fg_color=ACCENT, hover_color=ACCENT_DK, text_color=TEXT_SEC,
            font=("Microsoft YaHei", 12), corner_radius=6,
        ).pack(anchor="w", padx=16, pady=(0, 14))

        captcha_box = section("选课验证码")
        option(captcha_box, "识别方式", vars_map["captcha_type"], captcha_options)
        entry(captcha_box, "LLM 接口地址", vars_map["captcha_base_url"])
        entry(captcha_box, "LLM 模型", vars_map["captcha_model"], width=220)
        entry(captcha_box, "LLM API Key", vars_map["captcha_api_key"], show="*")

        footer = ctk.CTkFrame(f, fg_color=BG)
        footer.pack(fill="x", padx=20, pady=(0, 16))
        self._settings_status = make_label(footer, "", size=12, color=TEXT_SEC)
        self._settings_status.pack(side="left")
        make_button(
            footer, "保存设置",
            command=lambda: self._save_settings_from_vars(
                vars_map, login_options, score_source_options, notify_options, captcha_options, radar_location_options
            ),
            fg=SUCCESS, hover="#04B888", width=130, height=36, size=12,
        ).pack(side="right")

    def _save_settings_from_vars(self, vars_map, login_options, score_source_options, notify_options, captcha_options, radar_location_options):
        def read_int(key, label, min_value=0, max_value=None):
            raw = vars_map[key].get().strip()
            if raw == "":
                raise ValueError(f"{label} 不能为空")
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(f"{label} 必须是整数") from exc
            if value < min_value:
                raise ValueError(f"{label} 不能小于 {min_value}")
            if max_value is not None and value > max_value:
                raise ValueError(f"{label} 不能大于 {max_value}")
            return value

        def read_float(key, label, min_value=0, max_value=None):
            raw = vars_map[key].get().strip()
            if raw == "":
                raise ValueError(f"{label} 不能为空")
            try:
                value = float(raw)
            except ValueError as exc:
                raise ValueError(f"{label} 必须是数字") from exc
            if value < min_value:
                raise ValueError(f"{label} 不能小于 {min_value}")
            if max_value is not None and value > max_value:
                raise ValueError(f"{label} 不能大于 {max_value}")
            return value

        try:
            score_start_url = vars_map["score_start_url"].get().strip()
            completion_from_url = extract_completion_query_from_url(score_start_url)

            def completion_value(key, default=""):
                raw = vars_map[key].get().strip()
                from_url = completion_from_url.get(key)
                if from_url and (not raw or raw == default):
                    return from_url
                return raw or default

            values = {
                "username": vars_map["username"].get().strip(),
                "password": vars_map["password"].get(),
                "login_method": login_options[vars_map["login_method"].get()],
                "default_radar_location": radar_location_options[vars_map["default_radar_location"].get()],
                "score_source": score_source_options[vars_map["score_source"].get()],
                "score_interval": read_int("score_interval", "成绩查询间隔", 1),
                "score_notify": notify_options[vars_map["score_notify"].get()],
                "score_auto_login_once": bool(vars_map["score_auto_login_once"].get()),
                "score_show_score": bool(vars_map["score_show_score"].get()),
                "score_start_url": vars_map["score_start_url"].get().strip(),
                "completion_pyfadm": completion_value("completion_pyfadm"),
                "completion_pyfamc": completion_value("completion_pyfamc"),
                "completion_pcdm": completion_value("completion_pcdm", "-"),
                "completion_ymjs": completion_value("completion_ymjs", "0"),
                "completion_bynjdm": completion_value("completion_bynjdm", "-"),
                "completion_sclbdm": completion_value("completion_sclbdm", "04"),
                "course_campus": vars_map["course_campus"].get().strip() or "6",
                "course_auto_add_enable": bool(vars_map["course_auto_add_enable"].get()),
                "course_check_interval": read_int("course_check_interval", "常规监听间隔", 5),
                "course_fast_check_interval": read_int("course_fast_check_interval", "快速监听间隔", 5),
                "course_fast_monitor_seconds": read_int("course_fast_monitor_seconds", "快速监听时长", 0),
                "course_add_retry_count": read_int("course_add_retry_count", "补选重试次数", 0),
                "course_add_retry_interval": read_float("course_add_retry_interval", "补选重试间隔", 0),
                "course_interval_jitter": read_float("course_interval_jitter", "间隔随机抖动", 0, 0.3),
                "captcha_type": captcha_options[vars_map["captcha_type"].get()],
                "captcha_base_url": vars_map["captcha_base_url"].get().strip(),
                "captcha_api_key": vars_map["captcha_api_key"].get().strip(),
                "captcha_model": vars_map["captcha_model"].get().strip(),
            }
            save_settings_values(values, self._log)
            self._settings_status.configure(text="设置已保存，重新启动相关工具后生效。", text_color=SUCCESS)
            self._log("✅ 设置已保存。")
        except Exception as exc:
            self._settings_status.configure(text=f"保存失败：{exc}", text_color=DANGER)
            self._log(f"❌ 设置保存失败: {exc}")
    def _start_score_query(self):
        """Launch the score query project in its own command window."""
        try:
            if not SCORE_PROJECT_DIR.exists():
                self._log(f"❌ 成绩查询项目不存在: {SCORE_PROJECT_DIR}")
                return
            sync_score_account_config(self._log)
            venv_python = SCORE_PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
            python_exe = venv_python if venv_python.exists() else Path(sys.executable)
            script = SCORE_PROJECT_DIR / "browser_query.py"
            if not python_exe.exists() or not script.exists():
                self._log("❌ 成绩查询启动失败：缺少 Python 或 browser_query.py")
                return
            if self._score_process and self._score_process.poll() is None:
                if hasattr(self, "_home_status"):
                    self._set_home_status("成绩查询已在运行。", WARN)
                self._log("ℹ️ 成绩查询已在运行，关闭主界面时会一起退出。")
                return
            self._score_process = subprocess.Popen(
                [str(python_exe), "-u", str(script)],
                cwd=str(SCORE_PROJECT_DIR),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            if hasattr(self, "_home_status"):
                self._set_home_status("已打开成绩查询窗口。", SUCCESS)
            self._log("📊 已打开成绩查询窗口；首次使用请在弹出的教务窗口完成 CAS 登录。")
            self._log("ℹ️ 成绩查询使用教务系统登录态，和学习通同属 CAS，但会单独保存浏览器会话。")
        except Exception as exc:
            self._log(f"❌ 成绩查询启动失败: {exc}")
    def _show_optional_integration_missing(self, feature, expected_path):
        setup_script = APP_DIR / "setup_optional_integrations.bat"
        self._log(f"❌ {feature}可选集成尚未安装：找不到 {expected_path}")
        self._log(f"ℹ️ 请先在项目根目录运行 {setup_script.name}，它会把对应上游项目下载到 integrations/。")
        if hasattr(self, "_home_status"):
            self._set_home_status(f"{feature}未安装，请运行 {setup_script.name}", WARN)
        try:
            message = (
                f"{feature}还没有安装到本机。\n\n"
                f"请在项目根目录运行：\n{setup_script.name}\n\n"
                f"安装后再回到这里点击按钮。\n\n"
                f"期望路径：\n{expected_path}"
            )
            messagebox.showinfo("可选功能未安装", message, parent=self)
        except Exception:
            pass

    def _start_iqa_helper(self):
        """Launch the automatic course evaluation helper."""
        try:
            script = IQA_PROJECT_DIR / "start.bat"
            if not script.exists():
                self._show_optional_integration_missing("自动评教", script)
                return
            env = os.environ.copy()
            env["XMU_CAS_PROFILE_DIR"] = str(LOGIN_STATE_DIR)
            account = load_account_config(self._log)
            if account:
                env["XMU_USERNAME"] = account[0]
                env["XMU_PASSWORD"] = account[1]
            subprocess.Popen(
                ["cmd", "/k", str(script)],
                cwd=str(IQA_PROJECT_DIR),
                env=env,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            if hasattr(self, "_home_status"):
                self._set_home_status("已打开自动评教窗口。", SUCCESS)
            self._log("📝 已打开自动评教窗口。")
        except Exception as exc:
            self._log(f"❌ 自动评教启动失败: {exc}")

    def _start_course_helper(self):
        """Launch the course selection helper."""
        try:
            script = COURSE_HELPER_DIR / "client.py"
            config = COURSE_HELPER_DIR / "config" / "user.yaml"
            example = COURSE_HELPER_DIR / "config" / "user.example.yaml"
            if not script.exists():
                self._show_optional_integration_missing("选课助手", script)
                return
            sync_course_account_config(self._log)
            if not config.exists() and example.exists():
                cmd_line = r'copy "config\user.example.yaml" "config\user.yaml" >nul && echo Created config\user.yaml. Fill it, save it, then run again. && notepad "config\user.yaml"'
                subprocess.Popen(
                    ["cmd", "/k", cmd_line],
                    cwd=str(COURSE_HELPER_DIR),
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                subprocess.Popen(
                    [sys.executable, str(script)],
                    cwd=str(COURSE_HELPER_DIR),
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            if hasattr(self, "_home_status"):
                self._set_home_status("已打开选课窗口。", SUCCESS)
            self._log("📚 已打开选课窗口。")
        except Exception as exc:
            self._log(f"❌ 选课启动失败: {exc}")
    def _set_home_status(self, msg, color=TEXT_SEC):
        self.after(0, lambda: self._home_status.configure(text=msg, text_color=color))

    def _open_teaching_platform(self):
        """Open teaching-platform tools, reusing the in-memory session when possible."""
        if self._busy:
            return
        if self._cookie and self._student_id and self._courses:
            self._log("✅ 已复用当前教学平台登录状态，直接返回课程页。")
            self._show_courses()
            return
        self._start_login()
    # ── 第1步：启动登录流程 ──────────────────────────────
    def _start_login(self):
        self._busy = True
        self._set_home_status("正在启动浏览器，请稍候喵~❤")

        def on_done(result, err):
            if err or result is None:
                self._log(f"❌ 登录异常: {err}")
                self._busy = False
                self._set_home_status("❌ 出错了，再试一次喵~", DANGER)
                return

            cookie, student_id = result
            if not cookie or not student_id:
                self._log("❌ 未能获取凭证或学生ID")
                self._busy = False
                self._set_home_status("❌ 未能获取凭证，再试一次喵~", DANGER)
                return

            self._cookie     = cookie
            self._student_id = student_id
            self._set_home_status("✅ 凭证就绪！正在拉取课程喵~", SUCCESS)
            self._log("✅ 凭证获取成功，开始拉取课程列表...")

            # 第2步：拉取学期信息 + 课程列表（同步，放子线程）
            def fetch_courses():
                s_id, y_id = get_current_semester_info(cookie, self._log)
                return get_courses(cookie, s_id, y_id, self._log)

            def on_courses(courses, err2):
                self._busy = False
                if err2 or not courses:
                    self._log(f"❌ 课程拉取失败: {err2}")
                    self._set_home_status("❌ 课程列表拉取失败喵哦~", DANGER)
                    return
                self._courses = courses
                self._monitor_seen.clear()
                self.after(0, self._show_courses)   # 切换到课程页（主线程）

            run_sync_in_thread(fetch_courses, on_courses)

        run_async(login_and_get_cookie(log=self._log, login_method=get_login_method()), on_done)

    def _set_monitor_status(self, text, color=TEXT_SEC):
        if self._monitor_status_label is None:
            return
        self.after(0, lambda: self._monitor_status_label.configure(text=text, text_color=color))

    def _notify_rollcall(self, course_name, code, status_time, kind="数字签到"):
        title = "XMU 签到提醒"
        message = f"{course_name}\n类型: {kind}\n信息: {code or 'N/A'}\n时间: {status_time or '-'}"
        self._log(f"[monitor] active rollcall: {course_name} | type={kind} | code={code or 'N/A'} | time={status_time or '-'}")

        def _show_native_alert():
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass
            try:
                ctypes.windll.user32.MessageBoxW(0, message, title, 0x40 | 0x1000)
            except Exception:
                pass

        def _show_score_style_alert():
            try:
                notify_with_score_config(title, message, self._log)
            except Exception as exc:
                self._log(f"[monitor] score-style notification failed: {exc}")

        threading.Thread(target=_show_native_alert, daemon=True).start()
        threading.Thread(target=_show_score_style_alert, daemon=True).start()

    def _confirm_rollcall_submit(self, event):
        kind = event.get("kind")
        course_name = event.get("course_name") or "未知课程"
        rollcall_id = event.get("rollcall_id")
        if not rollcall_id:
            return
        if kind == "number":
            number_code = event.get("number_code") or ""
            ok = messagebox.askyesno(
                "确认数字签到",
                f"检测到数字签到：\n\n课程：{course_name}\n签到码：{number_code or '将自动获取'}\n时间：{event.get('time') or '-'}\n\n是否现在提交？",
                parent=self,
            )
            if ok:
                self._submit_number_rollcall(course_name, rollcall_id, number_code)
            return

        if kind == "radar":
            default_loc = get_default_radar_location(self._custom_radar_locations)
            if default_loc:
                loc_name, lat, lng = default_loc
                ok = messagebox.askyesno(
                    "确认雷达签到",
                    f"检测到雷达签到：\n\n课程：{course_name}\n默认位置：{loc_name}\n坐标：{lat}, {lng}\n\n是否用该位置提交？",
                    parent=self,
                )
                if ok:
                    self._submit_radar_rollcall(course_name, rollcall_id, lat, lng, loc_name)
            else:
                ok = messagebox.askyesno(
                    "需要设置雷达位置",
                    f"检测到雷达签到：\n\n课程：{course_name}\n\n当前没有默认雷达位置。是否打开雷达签到页面手动选择？",
                    parent=self,
                )
                if ok:
                    self._show_radar_page(str(rollcall_id), event.get("course_id") or "-", course_name)

    def _submit_number_rollcall(self, course_name, rollcall_id, number_code=None):
        self._set_monitor_status(f"正在提交数字签到：{course_name}", WARN)

        def _run():
            return send_number_rollcall(rollcall_id, self._cookie, number_code, self._log)

        def _done(result, err):
            if err:
                self._log(f"❌ 数字签到提交异常: {err}")
                self._set_monitor_status("数字签到提交异常", DANGER)
                return
            ok, reason = result
            if ok:
                self._set_monitor_status(f"数字签到已提交：{course_name}", SUCCESS)
                messagebox.showinfo("数字签到", f"{course_name}\n提交成功。", parent=self)
            else:
                self._set_monitor_status(f"数字签到失败：{reason}", DANGER)
                messagebox.showerror("数字签到失败", f"{course_name}\n{reason}", parent=self)

        run_sync_in_thread(_run, _done)

    def _submit_radar_rollcall(self, course_name, rollcall_id, latitude, longitude, location_name=None):
        self._set_monitor_status(f"正在提交雷达签到：{course_name}", WARN)

        def _run():
            return send_radar_rollcall(rollcall_id, self._cookie, latitude, longitude, self._log, location_name, self._custom_radar_locations)

        def _done(result, err):
            if err:
                self._log(f"❌ 雷达签到提交异常: {err}")
                self._set_monitor_status("雷达签到提交异常", DANGER)
                return
            ok, reason = result
            if ok:
                self._set_monitor_status(f"雷达签到已提交：{course_name}", SUCCESS)
                messagebox.showinfo("雷达签到", f"{course_name}\n提交成功。", parent=self)
            else:
                self._set_monitor_status(f"雷达签到失败：{reason}", DANGER)
                messagebox.showerror("雷达签到失败", f"{course_name}\n{reason}", parent=self)

        run_sync_in_thread(_run, _done)

    def _auto_submit_number_rollcall(self, course_name, rollcall_id, number_code=None):
        self._set_monitor_status(f"自动提交数字签到：{course_name}", WARN)

        def _run():
            return send_number_rollcall(rollcall_id, self._cookie, number_code, self._log)

        def _done(result, err):
            if err:
                self._log(f"❌ 自动数字签到异常: {err}")
                self._set_monitor_status("自动数字签到异常", DANGER)
                return
            ok, reason = result
            if ok:
                self._set_monitor_status(f"自动数字签到已提交：{course_name}", SUCCESS)
                self._log(f"✅ 自动数字签到成功：{course_name}")
            else:
                self._set_monitor_status(f"自动数字签到失败：{reason}", DANGER)
                self._log(f"❌ 自动数字签到失败：{course_name} - {reason}")

        run_sync_in_thread(_run, _done)

    def _auto_submit_radar_rollcall(self, course_name, rollcall_id):
        default_loc = get_default_radar_location(self._custom_radar_locations)
        if default_loc:
            loc_name, lat, lng = default_loc
            self._set_monitor_status(f"自动提交雷达签到：{course_name}", WARN)

            def _run():
                return send_radar_rollcall(rollcall_id, self._cookie, lat, lng, self._log, loc_name, self._custom_radar_locations)

            def _done(result, err):
                if err:
                    self._log(f"❌ 自动雷达签到异常: {err}")
                    self._set_monitor_status("自动雷达签到异常", DANGER)
                    return
                ok, reason = result
                if ok:
                    self._set_monitor_status(f"自动雷达签到已提交：{course_name}", SUCCESS)
                    self._log(f"✅ 自动雷达签到成功：{course_name}")
                else:
                    self._set_monitor_status(f"自动雷达签到失败：{reason}", DANGER)
                    self._log(f"❌ 自动雷达签到失败：{course_name} - {reason}")

            run_sync_in_thread(_run, _done)
        else:
            self._log(f"⚠️ 未设置默认雷达位置，跳过自动雷达签到：{course_name}")

    def _prompt_rollcall_confirmation(self, event):
        self.after(0, lambda: self._confirm_rollcall_submit(event))
    def _start_rollcall_monitor(self):
        if not self._cookie or not self._student_id or not self._courses:
            self._log("[monitor] cannot start: missing login state or courses")
            self._set_monitor_status("请先进入教学平台完成登录", DANGER)
            return
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._set_monitor_status("签到监听已在运行", SUCCESS)
            return

        self._monitor_stop.clear()
        mode_label = "自动提交" if self._auto_mode else "手动确认"
        self._set_monitor_status(f"签到监听运行中（{mode_label}），每 30 秒检查一次", SUCCESS)
        self._log(f"[monitor] started: {mode_label} mode")

        def _loop():
            while not self._monitor_stop.is_set():
                number_count = 0
                radar_count = 0
                try:
                    try:
                        events = get_active_rollcall_events(self._cookie, self._log)
                    except Exception as exc:
                        self._log(f"[monitor] active rollcall check failed: {exc}")
                        events = []

                    for event in events:
                        if self._monitor_stop.is_set():
                            break
                        kind = "radar" if event.get("is_radar") else "number"
                        course_id = event.get("course_id") or "-"
                        course_name = event.get("course_name") or str(course_id)
                        rollcall_id = event.get("rollcall_id")
                        key = f"{kind}:{course_id}:{rollcall_id}"
                        if kind == "radar":
                            radar_count += 1
                        else:
                            number_count += 1

                        if key in self._monitor_seen:
                            continue

                        if kind == "number":
                            try:
                                number_code, status, _ = get_number_code(rollcall_id, self._cookie)
                            except Exception as exc:
                                self._log(f"[monitor] {course_name} number code fetch failed: {exc}")
                                continue
                            if not number_code:
                                self._log(f"[monitor] 跳过疑似数字签到：{course_name} 没有返回 number_code。")
                                continue
                            if status and not is_number_rollcall_active(status):
                                self._log(f"[monitor] 跳过数字签到：{course_name} 当前状态为 {status}。")
                                continue

                            self._monitor_seen.add(key)
                            self._notify_rollcall(course_name, number_code, event.get("time"), "数字签到")
                            if self._auto_mode:
                                self._auto_submit_number_rollcall(course_name, rollcall_id, number_code)
                            else:
                                self._prompt_rollcall_confirmation({
                                    "kind": "number",
                                    "course_id": course_id,
                                    "course_name": course_name,
                                    "rollcall_id": rollcall_id,
                                    "number_code": number_code,
                                    "time": event.get("time"),
                                })
                        else:
                            self._monitor_seen.add(key)
                            self._notify_rollcall(
                                course_name,
                                f"雷达点名 ID {rollcall_id}",
                                event.get("time") or "待签到",
                                "雷达签到",
                            )
                            if self._auto_mode:
                                self._auto_submit_radar_rollcall(course_name, rollcall_id)
                            else:
                                self._prompt_rollcall_confirmation({
                                    "kind": "radar",
                                    "course_id": course_id,
                                    "course_name": course_name,
                                    "rollcall_id": rollcall_id,
                                    "time": event.get("time") or "待签到",
                                })
                        self._monitor_stop.wait(0.2)

                    if not self._monitor_stop.is_set():
                        stamp = datetime.now().strftime("%H:%M:%S")
                        mode_tag = "自动" if self._auto_mode else "待确认"
                        self._set_monitor_status(
                            f"签到监听中 [{mode_tag}] | 数字: {number_count} | 雷达: {radar_count} | {stamp}", SUCCESS
                        )
                except Exception as exc:
                    self._log(f"[monitor] loop error: {exc}")
                    self._set_monitor_status(f"签到监听异常: {exc}", DANGER)
                self._monitor_stop.wait(self._monitor_interval)

            self._set_monitor_status("签到监听已停止", TEXT_SEC)
            self._log("[monitor] stopped")
        self._monitor_thread = threading.Thread(target=_loop, daemon=True)
        self._monitor_thread.start()
    def _stop_rollcall_monitor(self):
        self._monitor_stop.set()
        self._set_monitor_status("正在停止签到监听...", WARN)

    # =======================================================
    # 第 2 页：课程列表
    # =======================================================
    def _show_courses(self):
        self._clear_content()
        f = self._content

        # 标题区
        hdr = ctk.CTkFrame(f, fg_color=BG)
        hdr.pack(fill="x", padx=20, pady=(16, 8))

        # ↓↓↓ 绝对原位插入：仅在此处新增一个返回按钮，其他排版代码1个字都不变 ↓↓↓
        back_btn = ctk.CTkButton(
            hdr, text="← 返回主页", width=80, height=28,
            fg_color=SURFACE2, hover_color=SURFACE, text_color=TEXT_SEC,
            font=("Microsoft YaHei", 12), corner_radius=8,
            command=self._show_home,
        )
        back_btn.pack(anchor="w", pady=(0, 10))
        ctk.CTkButton(
            hdr, text="学习通工具", width=108, height=28,
            fg_color=ACCENT, hover_color=ACCENT_DK, text_color=BG,
            font=("Microsoft YaHei", 12, "bold"), corner_radius=8,
            command=self._show_lnt_tools,
        ).pack(anchor="w", pady=(0, 10))
        # ↑↑↑ 插入结束 ↑↑↑

        make_label(hdr, "选择课程", size=24, bold=True).pack(anchor="w")
        make_label(
            hdr, f"共 {len(self._courses)} 门课，点击查看最新签到码",
            size=12, color=TEXT_SEC
        ).pack(anchor="w", pady=(2, 0))


        monitor_box = ctk.CTkFrame(hdr, fg_color=SURFACE, corner_radius=10)
        monitor_box.pack(fill="x", pady=(10, 0))

        def _toggle_auto_mode():
            self._auto_mode = not self._auto_mode
            new_text = "🔁 自动签到" if self._auto_mode else "📋 手动签到"
            auto_btn.configure(text=new_text)
            auto_btn.configure(fg_color=ACCENT if self._auto_mode else SURFACE2)
            status_text = f"切换到{'自动' if self._auto_mode else '手动'}模式，运行中的监听将立即生效"
            if self._monitor_status_label:
                self._monitor_status_label.configure(text=status_text)
            self._log(f"[monitor] {'自动' if self._auto_mode else '手动'}签到模式")

        auto_btn = ctk.CTkButton(
            monitor_box, text="📋 手动签到", width=108, height=30,
            fg_color=SURFACE2, hover_color=ACCENT_DK, text_color=TEXT_PRI,
            font=("Microsoft YaHei", 12), corner_radius=8,
            command=_toggle_auto_mode,
        )
        auto_btn.pack(side="left", padx=(10, 4), pady=8)

        ctk.CTkButton(
            monitor_box, text="▶ 开始", width=72, height=30,
            fg_color=SUCCESS, hover_color="#04B888", text_color=BG,
            font=("Microsoft YaHei", 12, "bold"), corner_radius=8,
            command=self._start_rollcall_monitor,
        ).pack(side="left", padx=4, pady=8)
        ctk.CTkButton(
            monitor_box, text="■ 停止", width=72, height=30,
            fg_color=SURFACE2, hover_color=ACCENT_DK, text_color=TEXT_SEC,
            font=("Microsoft YaHei", 12), corner_radius=8,
            command=self._stop_rollcall_monitor,
        ).pack(side="left", padx=4, pady=8)
        self._monitor_status_label = ctk.CTkLabel(
            monitor_box,
            text="签到监听未启动。点击「手动签到」切换为自动签到模式。",
            font=("Microsoft YaHei", 11), text_color=TEXT_SEC, anchor="w"
        )
        self._monitor_status_label.pack(side="left", fill="x", expand=True, padx=10)

        separator(f).pack(fill="x", padx=20, pady=4)

        # 可滚动课程列表
        scroll = ctk.CTkScrollableFrame(f, fg_color=BG, scrollbar_button_color=SURFACE2)
        scroll.pack(fill="both", expand=True, padx=12, pady=4)

        for course in self._courses:
            self._make_course_row(scroll, course)

    def _make_course_row(self, parent, course):
        name = course.get("display_name") or course.get("name") or "未知课程"
        cid  = course.get("id")

        row = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=12)
        row.pack(fill="x", pady=5, padx=4)

        icon = ctk.CTkLabel(
            row, text="📚", font=("Segoe UI Emoji", 22),
            width=44, height=44, fg_color=SURFACE2, corner_radius=10
        )
        icon.pack(side="left", padx=(10, 8), pady=10)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, pady=10)
        name_label = ctk.CTkLabel(
            info, text=name,
            font=("Microsoft YaHei", 13, "bold"),
            text_color=TEXT_PRI, anchor="w"
        )
        name_label.pack(anchor="w")
        id_label = ctk.CTkLabel(
            info, text=f"ID: {cid}",
            font=("Courier New", 11),
            text_color=TEXT_SEC, anchor="w"
        )
        id_label.pack(anchor="w")

        arrow = ctk.CTkLabel(row, text="›", font=("Arial", 22), text_color=TEXT_SEC)
        arrow.pack(side="right", padx=12)

        # 点击整行进入结果页
        def on_click(e, _cid=cid, _name=name):
            if getattr(self, "_course_click_pending", False):
                return
            self._course_click_pending = True
            self.after(700, lambda: setattr(self, "_course_click_pending", False))
            self._show_code(_cid, _name)

        def on_enter(e):
            row.configure(fg_color=SURFACE2)
        def on_leave(e):
            row.configure(fg_color=SURFACE)

        for w in (row, icon, info, name_label, id_label, arrow):
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>",    on_enter)
            w.bind("<Leave>",    on_leave)

    # =======================================================
    # 学习通工具：考试/作业与课堂互动查询
    # =======================================================
    def _make_lnt_header(self, parent, title, back_command, subtitle=None):
        hdr = ctk.CTkFrame(parent, fg_color=BG)
        hdr.pack(fill="x", padx=12, pady=(14, 4))
        ctk.CTkButton(
            hdr, text="← 返回", width=72, height=32,
            fg_color=SURFACE2, hover_color=SURFACE, text_color=TEXT_SEC,
            font=("Microsoft YaHei", 12), corner_radius=8,
            command=back_command,
        ).pack(side="left")
        title_box = ctk.CTkFrame(hdr, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True, padx=10)
        make_label(title_box, title, size=15, bold=True, wraplength=500).pack(anchor="w")
        if subtitle:
            make_label(title_box, subtitle, size=11, color=TEXT_SEC, wraplength=500).pack(anchor="w", pady=(2, 0))
        separator(parent).pack(fill="x", padx=20, pady=6)

    def _show_lnt_tools(self):
        self._clear_content()
        f = self._content
        self._make_lnt_header(
            f,
            "学习通工具",
            self._show_courses,
            "选择课程后查看考试/作业、课堂互动、试题与答案/解析。",
        )

        scroll = ctk.CTkScrollableFrame(f, fg_color=BG, scrollbar_button_color=SURFACE2)
        scroll.pack(fill="both", expand=True, padx=12, pady=4)
        for course in self._courses:
            self._make_lnt_course_row(scroll, course)

    def _make_lnt_course_row(self, parent, course):
        name = course.get("display_name") or course.get("name") or "未知课程"
        cid = course.get("id")
        row = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=12)
        row.pack(fill="x", pady=5, padx=4)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=14, pady=12)
        make_label(info, name, size=13, bold=True, wraplength=330).pack(anchor="w")
        make_label(info, f"课程 ID: {cid}", size=11, color=TEXT_SEC).pack(anchor="w", pady=(2, 0))

        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.pack(side="right", padx=10, pady=10)
        ctk.CTkButton(
            btns, text="考试/作业", width=88, height=30,
            fg_color=ACCENT, hover_color=ACCENT_DK, text_color=BG,
            font=("Microsoft YaHei", 12, "bold"), corner_radius=8,
            command=lambda: self._show_lnt_exams(cid, name),
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btns, text="课堂互动", width=88, height=30,
            fg_color=SUCCESS, hover_color="#04B888", text_color=BG,
            font=("Microsoft YaHei", 12, "bold"), corner_radius=8,
            command=lambda: self._show_lnt_classrooms(cid, name),
        ).pack(side="left", padx=4)

    def _show_lnt_loading(self, title, back_command, text="正在查询..."):
        self._clear_content()
        f = self._content
        self._make_lnt_header(f, title, back_command)
        card = ctk.CTkFrame(f, fg_color=SURFACE, corner_radius=18)
        card.pack(fill="both", expand=True, padx=28, pady=28)
        ctk.CTkLabel(card, text="🔎", font=("Segoe UI Emoji", 46)).pack(pady=(100, 8))
        make_label(card, text, size=14, color=TEXT_SEC, anchor="center").pack()
        bar = ctk.CTkProgressBar(card, width=220, mode="indeterminate", progress_color=ACCENT, fg_color=SURFACE2)
        bar.pack(pady=18)
        bar.start()

    def _show_lnt_error(self, title, err, back_command):
        self._clear_content()
        f = self._content
        self._make_lnt_header(f, title, back_command)
        card = ctk.CTkFrame(f, fg_color=SURFACE, corner_radius=18)
        card.pack(fill="both", expand=True, padx=28, pady=28)
        ctk.CTkLabel(card, text="⚠️", font=("Segoe UI Emoji", 48)).pack(pady=(80, 8))
        make_label(card, "查询失败", size=20, bold=True, color=DANGER, anchor="center").pack(pady=(4, 8))
        make_label(card, str(err), size=13, color=TEXT_SEC, anchor="center", wraplength=520).pack(padx=24)

    def _show_lnt_exams(self, course_id, course_name):
        self._show_lnt_loading(f"{course_name} | 考试/作业", self._show_lnt_tools, "正在查询考试/作业列表...")

        def fetch():
            return get_lnt_exam_list(course_id, self._cookie, self._log)

        def done(result, err):
            if err:
                self._log(f"❌ 考试/作业列表查询失败: {err}")
                self.after(0, lambda: self._show_lnt_error("考试/作业", err, self._show_lnt_tools))
                return
            self._log(f"✅ {course_name} 获取到 {len(result)} 个考试/作业")
            self.after(0, lambda: self._render_lnt_exam_list(course_id, course_name, result))

        run_sync_in_thread(fetch, done)

    def _render_lnt_exam_list(self, course_id, course_name, exams):
        self._clear_content()
        f = self._content
        self._make_lnt_header(f, f"{course_name} | 考试/作业", self._show_lnt_tools)

        if not exams:
            make_label(f, "这门课没有返回考试/作业记录。", size=14, color=TEXT_SEC, anchor="center").pack(expand=True)
            return

        scroll = ctk.CTkScrollableFrame(f, fg_color=BG, scrollbar_button_color=SURFACE2)
        scroll.pack(fill="both", expand=True, padx=12, pady=4)
        for exam in exams:
            exam_id = exam.get("id")
            title = exam.get("title") or "未命名考试/作业"
            row = ctk.CTkFrame(scroll, fg_color=SURFACE, corner_radius=12)
            row.pack(fill="x", pady=5, padx=4)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=14, pady=10)
            make_label(info, title, size=13, bold=True, wraplength=360).pack(anchor="w")
            meta = (
                f"ID: {exam_id} | 开始: {format_lnt_time(exam.get('start_time'))} | "
                f"结束: {format_lnt_time(exam.get('end_time'))} | "
                f"{'已开始' if exam.get('is_started') else '未开始'}"
            )
            make_label(info, meta, size=10, color=TEXT_SEC, wraplength=390).pack(anchor="w", pady=(3, 0))

            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.pack(side="right", padx=10, pady=10)
            ctk.CTkButton(
                btns, text="试题", width=72, height=30,
                fg_color=ACCENT, hover_color=ACCENT_DK, text_color=BG,
                font=("Microsoft YaHei", 12, "bold"), corner_radius=8,
                command=lambda e=exam: self._show_lnt_exam_questions(course_id, course_name, e),
            ).pack(pady=(0, 6))
            ctk.CTkButton(
                btns, text="答案/解析", width=72, height=30,
                fg_color=SUCCESS, hover_color="#04B888", text_color=BG,
                font=("Microsoft YaHei", 12, "bold"), corner_radius=8,
                command=lambda e=exam: self._show_lnt_exam_answers(course_id, course_name, e),
            ).pack()

    def _show_lnt_exam_questions(self, course_id, course_name, exam):
        title = exam.get("title") or f"考试 {exam.get('id')}"
        exam_id = exam.get("id")
        back = lambda: self._show_lnt_exams(course_id, course_name)
        self._show_lnt_loading(f"{title} | 试题", back, "正在抓取试题内容...")

        def fetch():
            return get_lnt_exam_questions(exam_id, self._cookie, self._log)

        def done(result, err):
            if err:
                self._log(f"❌ 试题抓取失败: {err}")
                self.after(0, lambda: self._show_lnt_error("试题抓取", err, back))
                return
            self.after(0, lambda: self._show_lnt_text_result(f"{title} | 试题", result, back))

        run_sync_in_thread(fetch, done)

    def _show_lnt_exam_answers(self, course_id, course_name, exam):
        title = exam.get("title") or f"考试 {exam.get('id')}"
        exam_id = exam.get("id")
        back = lambda: self._show_lnt_exams(course_id, course_name)
        self._show_lnt_loading(f"{title} | 答案/解析", back, "正在请求答案/解析接口...")

        def fetch():
            return get_lnt_exam_answers(exam_id, self._cookie, self._log)

        def done(result, err):
            if err:
                self._log(f"❌ 答案/解析查询失败: {err}")
                self.after(0, lambda: self._show_lnt_error("答案/解析", err, back))
                return
            self.after(0, lambda: self._show_lnt_text_result(f"{title} | 答案/解析", result, back))

        run_sync_in_thread(fetch, done)

    def _show_lnt_classrooms(self, course_id, course_name):
        self._show_lnt_loading(f"{course_name} | 课堂互动", self._show_lnt_tools, "正在查询课堂互动列表...")

        def fetch():
            return get_lnt_classroom_list(course_id, self._cookie, self._log)

        def done(result, err):
            if err:
                self._log(f"❌ 课堂互动列表查询失败: {err}")
                self.after(0, lambda: self._show_lnt_error("课堂互动", err, self._show_lnt_tools))
                return
            self._log(f"✅ {course_name} 获取到 {len(result)} 个课堂互动")
            self.after(0, lambda: self._render_lnt_classroom_list(course_id, course_name, result))

        run_sync_in_thread(fetch, done)

    def _render_lnt_classroom_list(self, course_id, course_name, classrooms):
        self._clear_content()
        f = self._content
        self._make_lnt_header(f, f"{course_name} | 课堂互动", self._show_lnt_tools)

        if not classrooms:
            make_label(f, "这门课没有返回课堂互动记录。", size=14, color=TEXT_SEC, anchor="center").pack(expand=True)
            return

        scroll = ctk.CTkScrollableFrame(f, fg_color=BG, scrollbar_button_color=SURFACE2)
        scroll.pack(fill="both", expand=True, padx=12, pady=4)
        for item in classrooms:
            classroom_id = item.get("id")
            title = item.get("title") or "未命名课堂互动"
            row = ctk.CTkFrame(scroll, fg_color=SURFACE, corner_radius=12)
            row.pack(fill="x", pady=5, padx=4)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=14, pady=10)
            make_label(info, title, size=13, bold=True, wraplength=380).pack(anchor="w")
            meta = (
                f"ID: {classroom_id} | 开始: {format_lnt_time(item.get('start_at'))} | "
                f"结束: {format_lnt_time(item.get('finish_at'))} | 状态: {item.get('status') or '-'}"
            )
            make_label(info, meta, size=10, color=TEXT_SEC, wraplength=410).pack(anchor="w", pady=(3, 0))
            ctk.CTkButton(
                row, text="互动题目", width=86, height=32,
                fg_color=ACCENT, hover_color=ACCENT_DK, text_color=BG,
                font=("Microsoft YaHei", 12, "bold"), corner_radius=8,
                command=lambda c=item: self._show_lnt_classroom_subjects(course_id, course_name, c),
            ).pack(side="right", padx=12, pady=12)

    def _show_lnt_classroom_subjects(self, course_id, course_name, classroom):
        title = classroom.get("title") or f"课堂互动 {classroom.get('id')}"
        classroom_id = classroom.get("id")
        back = lambda: self._show_lnt_classrooms(course_id, course_name)
        self._show_lnt_loading(f"{title} | 互动题目", back, "正在抓取互动题目内容...")

        def fetch():
            return get_lnt_classroom_subjects(classroom_id, self._cookie, self._log)

        def done(result, err):
            if err:
                self._log(f"❌ 互动题目抓取失败: {err}")
                self.after(0, lambda: self._show_lnt_error("互动题目", err, back))
                return
            self.after(0, lambda: self._show_lnt_text_result(f"{title} | 互动题目", result, back))

        run_sync_in_thread(fetch, done)

    def _show_lnt_text_result(self, title, body_text, back_command):
        self._clear_content()
        f = self._content
        self._make_lnt_header(f, title, back_command)

        actions = ctk.CTkFrame(f, fg_color=BG)
        actions.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkButton(
            actions, text="打开 HTML 报告", width=132, height=32,
            fg_color=SUCCESS, hover_color="#04B888", text_color=BG,
            font=("Microsoft YaHei", 12, "bold"), corner_radius=8,
            command=lambda: self._open_lnt_report(title, body_text),
        ).pack(side="left")

        box = ctk.CTkTextbox(
            f, fg_color=SURFACE, text_color=TEXT_PRI,
            font=("Microsoft YaHei", 12), wrap="word", corner_radius=12,
        )
        box.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        box.insert("1.0", body_text or "没有可显示内容。")
        box.configure(state="disabled")

    def _open_lnt_report(self, title, body_text):
        try:
            path = save_lnt_html_report(title, body_text, self._log)
            webbrowser.open(path.as_uri())
        except Exception as exc:
            self._log(f"❌ 打开 HTML 报告失败: {exc}")

    # =======================================================
    # 第 3 页：签到码结果
    # =======================================================
    def _show_code(self, course_id, course_name):
        self._current_code_request = uuid.uuid4().hex
        request_id = self._current_code_request
        self._clear_content()
        f = self._content

        # 顶部：返回按钮 + 课程名
        hdr = ctk.CTkFrame(f, fg_color=BG)
        hdr.pack(fill="x", padx=12, pady=(14, 4))

        back_btn = ctk.CTkButton(
            hdr, text="← 返回", width=72, height=32,
            fg_color=SURFACE2, hover_color=SURFACE, text_color=TEXT_SEC,
            font=("Microsoft YaHei", 12), corner_radius=8,
            command=self._show_courses,
        )
        back_btn.pack(side="left")

        make_label(
            hdr, text=course_name, size=14, bold=True,
            color=TEXT_PRI, anchor="w", wraplength=330
        ).pack(side="left", padx=10)

        separator(f).pack(fill="x", padx=20, pady=6)

        # 结果卡片容器（先放 loading）
        self._code_card_frame = ctk.CTkFrame(f, fg_color=BG)
        self._code_card_frame.pack(fill="both", expand=True, padx=20, pady=10)

        self._show_loading_card()

        # 后台拉取签到码
        def fetch():
            r_id, r_time = get_latest_rollcall_id(
                course_id, self._cookie, self._student_id
            )
            if not r_id:
                return None
            number_code, status, _ = get_number_code(r_id, self._cookie)
            try:
                dt = datetime.fromisoformat(r_time.replace("Z", "+00:00"))
                time_str = dt.astimezone(timezone(timedelta(hours=8))).strftime(
                    "%Y-%m-%d %H:%M"
                )
            except Exception:
                time_str = str(r_time)
            return {"code": number_code, "status": status, "time": time_str, "rid": r_id}

        def on_result(result, err):
            if request_id != getattr(self, "_current_code_request", None):
                return
            if err:
                self._log(f"❌ 查询出错: {err}")
                self.after(0, self._show_result_card, None, course_id, course_name)
                return
            self._log(
                f"✅ {course_name} | {result['time'] if result else '-'} "
                f"| 签到码: {result['code'] if result else '无'}"
            )
            self.after(0, self._show_result_card, result, course_id, course_name)

        run_sync_in_thread(fetch, on_result)

    def _show_loading_card(self):
        for w in self._code_card_frame.winfo_children():
            w.destroy()
        card = ctk.CTkFrame(self._code_card_frame, fg_color=SURFACE, corner_radius=20)
        card.pack(fill="both", expand=True)
        ctk.CTkLabel(
            card, text="🔍", font=("Segoe UI Emoji", 48)
        ).place(relx=0.5, rely=0.4, anchor="center")
        ctk.CTkLabel(
            card, text="正在查询签到码喵~",
            font=("Microsoft YaHei", 14), text_color=TEXT_SEC
        ).place(relx=0.5, rely=0.56, anchor="center")
        ctk.CTkProgressBar(
            card, width=200, mode="indeterminate",
            progress_color=ACCENT, fg_color=SURFACE2
        ).place(relx=0.5, rely=0.68, anchor="center")
        # 启动动画
        for w in card.winfo_children():
            if isinstance(w, ctk.CTkProgressBar):
                w.start()

    def _show_result_card(self, result, course_id, course_name):
        for w in self._code_card_frame.winfo_children():
            w.destroy()

        card = ctk.CTkFrame(self._code_card_frame, fg_color=SURFACE, corner_radius=20)
        card.pack(fill="both", expand=True)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")

        rollcall_id = result["rid"] if result else None

        if result is None:
            ctk.CTkLabel(inner, text="😿", font=("Segoe UI Emoji", 52)).pack()
            make_label(inner, "暂无签到记录", size=18, bold=True, anchor="center").pack(pady=(8,2))
            make_label(inner, "这门课还没有签到喵~", size=13, color=TEXT_SEC, anchor="center").pack()

        elif result["code"]:
            status_map = {
                "active": ("✅ 进行中", SUCCESS),
                "in_progress": ("✅ 进行中", SUCCESS),
                "on_call": ("✅ 进行中", SUCCESS),
                "ongoing": ("✅ 进行中", SUCCESS),
                "finished": ("🔒 已结束", TEXT_SEC),
                "closed": ("🔒 已结束", TEXT_SEC),
                "ended": ("🔒 已结束", TEXT_SEC),
                "expired": ("🔒 已结束", TEXT_SEC),
            }
            status_txt, status_clr = status_map.get(result["status"], (result["status"], TEXT_SEC))

            ctk.CTkLabel(inner, text="🐾", font=("Segoe UI Emoji", 46)).pack()
            make_label(inner, "签到码", size=13, color=TEXT_SEC, anchor="center").pack(pady=(4,0))

            code_entry = ctk.CTkEntry(
                inner, width=240, height=80,
                font=("Arial Black", 48),
                text_color=ACCENT, fg_color="transparent",
                border_width=0, justify="center",
            )
            code_entry.insert(0, str(result["code"]))
            code_entry.configure(state="readonly")
            code_entry.pack(pady=4)

            status_frame = ctk.CTkFrame(inner, fg_color=SURFACE2, corner_radius=20)
            status_frame.pack(pady=4)
            ctk.CTkLabel(
                status_frame, text=status_txt,
                font=("Microsoft YaHei", 12, "bold"),
                text_color=status_clr
            ).pack(padx=16, pady=5)

            make_label(
                inner, f"签到时间：{result['time']}",
                size=12, color=TEXT_SEC, anchor="center"
            ).pack(pady=(6, 0))

        else:
            ctk.CTkLabel(inner, text="📍", font=("Segoe UI Emoji", 52)).pack()
            make_label(inner, "无数字签到码", size=18, bold=True, anchor="center").pack(pady=(8,2))
            make_label(
                inner, "可能是 GPS / 扫码等其他签到方式喵~",
                size=12, color=TEXT_SEC, anchor="center"
            ).pack()
            make_label(
                inner, f"签到时间：{result['time']}",
                size=12, color=TEXT_SEC, anchor="center"
            ).pack(pady=(6, 0))

        # ── 按钮区 ──
        btn_frame = ctk.CTkFrame(self._code_card_frame, fg_color=BG)
        btn_frame.pack(fill="x", pady=(10, 2))

        make_button(
            btn_frame, "🔄 再查一次",
            command=lambda: self._show_code(course_id, course_name),
            width=180, height=38
        ).pack(side="left", padx=(20, 6))

        if rollcall_id:
            make_button(
                btn_frame, "雷达签到",
                command=lambda: self._show_radar_page(rollcall_id, course_id, course_name),
                fg=SUCCESS, hover="#04B888",
                width=120, height=38
            ).pack(side="right", padx=6)
            if result and result.get("code") and is_number_rollcall_active(result.get("status")):
                make_button(
                    btn_frame, "数字签到",
                    command=lambda: self._submit_number_rollcall(course_name, rollcall_id, result.get("code")),
                    fg=SUCCESS, hover="#04B888",
                    width=120, height=38
                ).pack(side="right", padx=6)
    # =======================================================
    # 雷达签到页面
    # =======================================================
    def _show_radar_page(self, rollcall_id, course_id, course_name):
        self._clear_content()
        f = self._content

        # 顶部
        hdr = ctk.CTkFrame(f, fg_color=BG)
        hdr.pack(fill="x", padx=12, pady=(14, 4))

        ctk.CTkButton(
            hdr, text="← 返回", width=72, height=32,
            fg_color=SURFACE2, hover_color=SURFACE, text_color=TEXT_SEC,
            font=("Microsoft YaHei", 12), corner_radius=8,
            command=lambda: self._show_code(course_id, course_name),
        ).pack(side="left")

        make_label(hdr, text="📍 雷达签到", size=15, bold=True).pack(side="left", padx=10)

        separator(f).pack(fill="x", padx=20, pady=6)

        rollcall_ch = str(rollcall_id)

        # 卡片容器
        card_frame = ctk.CTkFrame(f, fg_color=BG)
        card_frame.pack(fill="both", expand=True, padx=16, pady=6)

        # ── 左侧: 预设位置列表 ──
        left = ctk.CTkFrame(card_frame, fg_color=SURFACE, corner_radius=14)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6), pady=4)

        make_label(left, "👇 预设位置", size=15, bold=True, anchor="center").pack(pady=(14, 6))

        self._radar_selected_loc = ctk.StringVar(value="")
        preset_scroll = ctk.CTkScrollableFrame(
            left, fg_color="transparent", scrollbar_button_color=SURFACE2,
        )
        preset_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        # ── 右侧: 自定义坐标 + 签到按钮 ──
        right = ctk.CTkFrame(card_frame, fg_color=SURFACE, corner_radius=14)
        right.pack(side="right", fill="both", expand=True, padx=(6, 0), pady=4)

        make_label(right, "⚙️ 自定义位置", size=15, bold=True, anchor="center").pack(pady=(14, 8))

        make_label(right, "纬度 (Latitude)", size=12, color=TEXT_SEC, anchor="w").pack(fill="x", padx=18)
        lat_entry = ctk.CTkEntry(
            right, placeholder_text="例: 24.4378",
            font=("Courier New", 13), height=36,
            fg_color=SURFACE2, text_color=TEXT_PRI,
        )
        lat_entry.pack(fill="x", padx=18, pady=(2, 8))

        make_label(right, "经度 (Longitude)", size=12, color=TEXT_SEC, anchor="w").pack(fill="x", padx=18)
        lng_entry = ctk.CTkEntry(
            right, placeholder_text="例: 118.0965",
            font=("Courier New", 13), height=36,
            fg_color=SURFACE2, text_color=TEXT_PRI,
        )
        lng_entry.pack(fill="x", padx=18, pady=(2, 8))

        make_label(right, "预设名称", size=12, color=TEXT_SEC, anchor="w").pack(fill="x", padx=18)
        preset_name_entry = ctk.CTkEntry(
            right, placeholder_text="例: 我的教学楼",
            font=("Microsoft YaHei", 13), height=36,
            fg_color=SURFACE2, text_color=TEXT_PRI,
        )
        preset_name_entry.pack(fill="x", padx=18, pady=(2, 8))

        adjust_box = ctk.CTkFrame(right, fg_color=SURFACE2, corner_radius=10)
        adjust_box.pack(fill="x", padx=18, pady=(0, 8))
        make_label(adjust_box, "现场微调", size=12, color=TEXT_SEC, anchor="w").pack(fill="x", padx=10, pady=(8, 2))

        adjust_top = ctk.CTkFrame(adjust_box, fg_color="transparent")
        adjust_top.pack(fill="x", padx=10, pady=(0, 6))
        make_label(adjust_top, "步长(米)", size=11, color=TEXT_SEC).pack(side="left")
        adjust_step_entry = ctk.CTkEntry(
            adjust_top,
            width=72,
            height=28,
            font=("Courier New", 12),
            fg_color=SURFACE,
            text_color=TEXT_PRI,
        )
        adjust_step_entry.insert(0, "10")
        adjust_step_entry.pack(side="left", padx=(8, 0))

        def _shift_current_coordinate(north_meters=0, east_meters=0):
            try:
                lat_v = float(lat_entry.get())
                lng_v = float(lng_entry.get())
                step = float(adjust_step_entry.get() or "10")
            except ValueError:
                self._log("❌ 微调前请输入有效的坐标和步长")
                return
            next_lat, next_lng = shift_radar_coordinate(
                lat_v,
                lng_v,
                north_meters=north_meters * step,
                east_meters=east_meters * step,
            )
            lat_entry.delete(0, "end")
            lat_entry.insert(0, f"{next_lat:.7f}")
            lng_entry.delete(0, "end")
            lng_entry.insert(0, f"{next_lng:.7f}")
            self._log(f"📍 已微调坐标：{next_lat:.7f}, {next_lng:.7f}")

        adjust_grid = ctk.CTkFrame(adjust_box, fg_color="transparent")
        adjust_grid.pack(padx=10, pady=(0, 10))
        ctk.CTkButton(
            adjust_grid, text="北", width=52, height=28,
            fg_color=SURFACE, hover_color=ACCENT_DK, text_color=TEXT_PRI,
            font=("Microsoft YaHei", 11), corner_radius=8,
            command=lambda: _shift_current_coordinate(north_meters=1),
        ).grid(row=0, column=1, padx=3, pady=3)
        ctk.CTkButton(
            adjust_grid, text="西", width=52, height=28,
            fg_color=SURFACE, hover_color=ACCENT_DK, text_color=TEXT_PRI,
            font=("Microsoft YaHei", 11), corner_radius=8,
            command=lambda: _shift_current_coordinate(east_meters=-1),
        ).grid(row=1, column=0, padx=3, pady=3)
        ctk.CTkButton(
            adjust_grid, text="东", width=52, height=28,
            fg_color=SURFACE, hover_color=ACCENT_DK, text_color=TEXT_PRI,
            font=("Microsoft YaHei", 11), corner_radius=8,
            command=lambda: _shift_current_coordinate(east_meters=1),
        ).grid(row=1, column=2, padx=3, pady=3)
        ctk.CTkButton(
            adjust_grid, text="南", width=52, height=28,
            fg_color=SURFACE, hover_color=ACCENT_DK, text_color=TEXT_PRI,
            font=("Microsoft YaHei", 11), corner_radius=8,
            command=lambda: _shift_current_coordinate(north_meters=-1),
        ).grid(row=2, column=1, padx=3, pady=3)

        def _fill_location_entries(lat, lng):
            lat_entry.delete(0, "end")
            lat_entry.insert(0, str(lat))
            lng_entry.delete(0, "end")
            lng_entry.insert(0, str(lng))

        def _render_location_rows():
            for child in preset_scroll.winfo_children():
                child.destroy()

            for group_name, locations in grouped_radar_locations(self._custom_radar_locations).items():
                make_label(
                    preset_scroll, group_name,
                    size=12, color=ACCENT, bold=True, anchor="w"
                ).pack(fill="x", padx=6, pady=(8, 3))

                for loc_name, (lat, lng) in locations.items():
                    row = ctk.CTkFrame(preset_scroll, fg_color=SURFACE2, corner_radius=10)
                    row.pack(fill="x", padx=2, pady=3)

                    ctk.CTkRadioButton(
                        row, text=loc_name,
                        variable=self._radar_selected_loc, value=loc_name,
                        font=("Microsoft YaHei", 12),
                        fg_color=ACCENT, hover_color=ACCENT_DK,
                        text_color=TEXT_PRI,
                    ).pack(side="left", padx=(8, 4), pady=8)

                    if loc_name in self._custom_radar_locations:
                        ctk.CTkButton(
                            row, text="删", width=28, height=24,
                            fg_color=DANGER, hover_color=ACCENT_DK, text_color=TEXT_PRI,
                            font=("Microsoft YaHei", 11), corner_radius=8,
                            command=lambda name=loc_name: _delete_custom_preset(name),
                        ).pack(side="right", padx=(4, 8))

                    ctk.CTkLabel(
                        row, text=f"{lat:.5f}, {lng:.5f}",
                        font=("Courier New", 9), text_color=TEXT_SEC,
                    ).pack(side="right", padx=4)

        def _save_custom_preset():
            name = preset_name_entry.get().strip()
            if not name:
                self._log("❌ 请输入自定义预设名称喵！")
                return
            if name in RADAR_LOCATIONS:
                self._log("❌ 不能覆盖内置预设，请换一个名称喵！")
                return
            try:
                lat_v = float(lat_entry.get())
                lng_v = float(lng_entry.get())
            except ValueError:
                self._log("❌ 保存预设前请输入有效的经纬度数字喵！")
                return

            next_locations = {**self._custom_radar_locations, name: (lat_v, lng_v)}
            if not save_custom_radar_locations(next_locations, self._log):
                return
            self._custom_radar_locations = next_locations
            _render_location_rows()
            self._radar_selected_loc.set(name)
            self._log(f"✅ 已保存自定义雷达预设：{name} ({lat_v}, {lng_v}) -> {CUSTOM_RADAR_LOCATIONS_FILE}")

        def _delete_custom_preset(name):
            if name not in self._custom_radar_locations:
                self._log("❌ 只能删除自定义预设喵！")
                return
            next_locations = dict(self._custom_radar_locations)
            del next_locations[name]
            if not save_custom_radar_locations(next_locations, self._log):
                return
            self._custom_radar_locations = next_locations
            if self._radar_selected_loc.get() == name:
                self._radar_selected_loc.set("")
            _render_location_rows()
            self._log(f"✅ 已删除自定义雷达预设：{name}")

        preset_btn_row = ctk.CTkFrame(right, fg_color="transparent")
        preset_btn_row.pack(fill="x", padx=18, pady=(0, 8))
        ctk.CTkButton(
            preset_btn_row, text="💾 保存为预设", command=_save_custom_preset,
            fg_color=ACCENT, hover_color=ACCENT_DK, text_color=BG,
            font=("Microsoft YaHei", 12, "bold"), height=34, corner_radius=10,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(
            preset_btn_row, text="删除选中", command=lambda: _delete_custom_preset(self._radar_selected_loc.get()),
            fg_color=SURFACE2, hover_color=DANGER, text_color=TEXT_SEC,
            font=("Microsoft YaHei", 12), height=34, corner_radius=10,
        ).pack(side="right", fill="x", expand=True, padx=(4, 0))

        # 选择预设时自动填入自定义框
        def _on_preset_change(*_):
            loc = self._radar_selected_loc.get()
            locations = all_radar_locations(self._custom_radar_locations)
            if loc and loc in locations:
                plat, plng = locations[loc]
                _fill_location_entries(plat, plng)
                preset_name_entry.delete(0, "end")
                if loc in self._custom_radar_locations:
                    preset_name_entry.insert(0, loc)

        self._radar_selected_loc.trace_add("write", _on_preset_change)
        _render_location_rows()

        def _do_radar_sign():
            try:
                lat_v = float(lat_entry.get())
                lng_v = float(lng_entry.get())
            except ValueError:
                self._log("❌ 请输入有效的经纬度数字喵！")
                return

            selected_loc = self._radar_selected_loc.get().strip() or None
            locations = all_radar_locations(self._custom_radar_locations)
            if selected_loc not in locations:
                selected_loc = None
            self._log(f"📍 正在发送雷达签到 ({lat_v}, {lng_v}) ...")

            def _run():
                return send_radar_rollcall(
                    rollcall_ch,
                    self._cookie,
                    lat_v,
                    lng_v,
                    self._log,
                    selected_loc,
                    self._custom_radar_locations,
                )

            def _on_done(result, err):
                if err:
                    reason = str(err)
                    self.after(0, lambda: self._show_radar_result(False, course_id, course_name, rollcall_ch, reason))
                    return
                ok, reason = result
                if ok:
                    self.after(0, lambda: self._show_radar_result(True, course_id, course_name, rollcall_ch))
                else:
                    self.after(0, lambda: self._show_radar_result(False, course_id, course_name, rollcall_ch, reason))

            run_sync_in_thread(_run, _on_done)

        make_button(
            right, "🚀 发送雷达签到",
            command=_do_radar_sign,
            fg=SUCCESS, hover="#04B888",
            width=240, height=44, size=14
        ).pack(pady=(6, 4))

        ctk.CTkLabel(
            right,
            text="选中预设会自动填入坐标\n可输入名称并保存为自定义预设",
            font=("Microsoft YaHei", 11),
            text_color=TEXT_SEC, wraplength=250, justify="center",
        ).pack(pady=(4, 10))

    def _show_radar_result(self, success, course_id, course_name, rollcall_id=None, reason=None):
        self._clear_content()
        f = self._content

        card = ctk.CTkFrame(f, fg_color=SURFACE, corner_radius=20, width=440, height=350)
        card.pack(expand=True, pady=80)
        card.pack_propagate(False)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.place(relx=0.5, rely=0.45, anchor="center")

        if success:
            ctk.CTkLabel(inner, text="🎉", font=("Segoe UI Emoji", 60)).pack()
            make_label(inner, "雷达签到成功喵❤！", size=22, bold=True, color=SUCCESS, anchor="center").pack(pady=(10, 4))
            make_label(inner, "畅课平台已收到你的GPS位置", size=13, color=TEXT_SEC, anchor="center").pack()
        else:
            ctk.CTkLabel(inner, text="!", font=("Microsoft YaHei", 52, "bold"), text_color=DANGER).pack()
            make_label(inner, "雷达签到失败", size=22, bold=True, color=DANGER, anchor="center").pack(pady=(10, 4))
            reason_text = reason or "请查看日志了解详细原因"
            make_label(inner, reason_text, size=12, color=TEXT_SEC, anchor="center", wraplength=360).pack(pady=(0, 4))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.place(relx=0.5, rely=0.88, anchor="center")

        if rollcall_id:
            back_text = "返回雷达签到"
            back_command = lambda: self._show_radar_page(rollcall_id, course_id, course_name)
        else:
            back_text = "返回签到码"
            back_command = lambda: self._show_code(course_id, course_name)

        make_button(
            btn_row, back_text,
            command=back_command,
            width=160, height=36, size=12
        ).pack(side="left", padx=8)

        make_button(
            btn_row, "🏠 主页",
            command=self._show_home,
            fg=SURFACE2, hover=ACCENT_DK,
            width=120, height=36, size=12
        ).pack(side="left", padx=8)


# ==============================================================================
# 入口
# ==============================================================================
if __name__ == "__main__":
    app = ZakoApp()
    app.mainloop()
