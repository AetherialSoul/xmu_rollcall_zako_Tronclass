# -*- coding: utf-8 -*-
import json
import sys

from bs4 import BeautifulSoup

from utils import encryptAES
from utils import get_wrapped_url


class LoginError(Exception):
    pass


def _extract_login_error(soup):
    selectors = [
        '#msg',
        '#errormsg',
        '.errors',
        '.alert-danger',
        '[id*="error"]',
        '[class*="error"]',
    ]
    for selector in selectors:
        for node in soup.select(selector):
            text = node.get_text(" ", strip=True)
            if text:
                return text

    page_text = soup.get_text(" ", strip=True)
    for marker in ("用户名或密码", "密码错误", "验证码", "账户已锁定", "账号已锁定", "冻结", "认证失败"):
        if marker in page_text:
            return marker
    return None


# Login session by username & password
# cookie login is deprecated because it is likely to be expired in 1-2 days
def login(session, username, password, use_webvpn=False):
    """
    use cookie: just requires "SAAS_U"
    emulate OAuth login:
        POST https://ids.xmu.edu.cn/authserver/login?service=https://xmuxg.xmu.edu.cn/login/cas/xmu
        form data: username, password, lt, dllt, execution, _eventId="submit", rmShown=1
    """

    # workaround for the AES encryption added in 2020/12/27
    # with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "encrypt.js"), "r") as file:
    #     cryptjs = file.read()
    # ctx = execjs.compile(cryptjs)

    try:
        oauth_login_url = get_wrapped_url(
            "https://ids.xmu.edu.cn/authserver/login?type=userNameLogin&service=https://jw.xmu.edu.cn/login?service=https://jw.xmu.edu.cn/new/index.html", use_webvpn)
        resp = session.get(oauth_login_url)
        # print(resp.status_code ,resp.text)

        soup = BeautifulSoup(resp.text, 'html.parser')
        try:
            lt = soup.select('input[name="lt"]')[0]["value"]
        except:
            lt = None
        try:
            dllt = soup.select('input[name="dllt"]')[0]['value']
            execution = soup.select('input[name="execution"]')[0]['value']
            salt = soup.select('input#pwdEncryptSalt')[0]['value']
        except IndexError as exc:
            reason = _extract_login_error(soup) or "Login form not found"
            raise LoginError(reason) from exc

        login_data = {
            "username": username,
            "password": encryptAES(password, salt),
            "lt": lt,
            "dllt": dllt,
            "execution": execution,
            "_eventId": "submit",
            "rmShown": 1
        }
        res = session.post(oauth_login_url, login_data,
                     allow_redirects=True)  # will redirect to https://xmuxg.xmu.edu.cn
        # for rr in res.history:
        #     print(rr.url, rr.headers)
        result_soup = BeautifulSoup(res.text, 'html.parser')
        reason = _extract_login_error(result_soup)
        still_on_login_page = (
            'ids.xmu.edu.cn/authserver/login' in res.url
            or bool(result_soup.select('input[name="execution"]'))
        )
        if reason or still_on_login_page:
            raise LoginError(reason or "Login did not complete; please verify credentials or finish web login manually.")
    except KeyError:
        print(json.dumps({
            "status": "failed",
            "reason": "Login failed (server error)"
        }, indent=4))
        sys.exit(1)
