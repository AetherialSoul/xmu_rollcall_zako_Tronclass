# -*- coding: utf-8 -*-
import argparse
import ast
import json
import time
import traceback
from urllib import parse

import requests
import yaml

from login import LoginError, login
from notify import notify

http_header = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh-Hans;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://jw.xmu.edu.cn/new/index.html",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15"
}

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

parser = argparse.ArgumentParser()
parser.add_argument('--username', metavar='username', help="统一身份认证用户名")
parser.add_argument('--password', metavar='password', help="统一身份认证密码")
parser.add_argument('--interval', metavar='interval', help="查询间隔，单位为分钟")
parser.add_argument('--allow-password-login', action='store_true', help="允许旧版后台密码登录模式（每次运行最多提交一次密码）")
args = parser.parse_args()

try:
    with open("config.yaml", "r", encoding='utf-8') as f:
        conf: dict = yaml.load(f, Loader=yaml.FullLoader)
        username = args.username if args.username else str(conf['info']['username'])
        password = args.password if args.password else str(conf['info']['password'])
        assert username and username != 'None'
        interval = int(args.interval) if args.interval else int(conf['interval'])
        query_terms = conf.get('terms')
        query_courses = conf.get('courses')
        show_score = conf.get('show_score', True)
        score_query = conf.get('score_query', {})
        completion_query = conf.get('completion_query', {})
        query_source = score_query.get('source', 'completion')
        legacy_password_login = conf.get('legacy_password_login', False) or args.allow_password_login
except Exception:
    print("Please fill the parameters in config.yaml or use command line arguments.")
    exit(1)

if not legacy_password_login:
    print("安全保护：app.py 的后台密码登录模式默认禁用。")
    print("请使用 python browser_query.py，在浏览器中登录并复用浏览器会话。")
    print("如果你确实要使用旧模式，请运行 python app.py --allow-password-login；该模式每次运行最多提交一次密码。")
    exit(1)

if not password or password == 'None':
    print("旧版后台密码登录模式需要在 config.yaml 填写 info.password 或传入 --password。")
    exit(1)

try:
    with open("scores.yaml", "r", encoding='utf-8') as f:
        save_scores: dict = yaml.load(f, Loader=yaml.FullLoader)
        if save_scores is None:
            save_scores = {}
except FileNotFoundError:
    save_scores = {}
except Exception:
    print("scores.yaml is not a valid yaml file.")
    exit(1)

session = requests.Session()
session.headers = http_header
loginCount = 0
MAX_LOGIN_ATTEMPTS = 1


class SessionExpiredError(Exception):
    pass


def loginAndGetToken():
    global loginCount
    loginCount += 1
    if loginCount > MAX_LOGIN_ATTEMPTS:
        print("本次运行已尝试登录，停止继续提交密码，避免账号冻结。")
        notify('登录异常提醒', '成绩查询已停止：本次运行已尝试登录，未继续提交密码以避免账号冻结。')
        exit(1)
    session.cookies.clear()
    try:
        login(session, username, password)
    except LoginError as exc:
        print(f"登录失败，已停止继续提交密码：{exc}")
        notify('登录异常提醒', f'成绩查询登录失败，已停止继续提交密码：{exc}')
        exit(1)
    except Exception as exc:
        print(f"登录请求异常，已停止继续提交密码：{exc}")
        notify('登录异常提醒', f'成绩查询登录请求异常，已停止继续提交密码：{exc}')
        exit(1)
    print("login")
    res = session.get("https://jw.xmu.edu.cn/appShow?appId=4768574631264620", allow_redirects=True)
    if 'ids.xmu.edu.cn' in res.url:
        print("登录后仍被重定向到统一认证页，已停止继续提交密码。")
        notify('登录异常提醒', '成绩查询登录后仍被重定向到统一认证页，已停止继续提交密码。')
        exit(1)
    with open('Cookie.txt', 'w') as f:
        f.write(str(session.cookies.get_dict()))


def loadCookies():
    try:
        with open('Cookie.txt', 'r') as f:
            session.cookies.update(ast.literal_eval(f.read()))
    except Exception:
        loginAndGetToken()


def buildCompletionParams():
    pyfadm = completion_query.get('pyfadm')
    if not pyfadm:
        raise ValueError("Please set completion_query.pyfadm in config.yaml")
    return {
        "PCDM": str(completion_query.get('pcdm', '-')),
        "PYFADM": str(pyfadm),
        "PYFAMC": str(completion_query.get('pyfamc', '')),
        "XH": username,
        "YMJS": str(completion_query.get('ymjs', '0')),
        "BYNJDM": str(completion_query.get('bynjdm', '-')),
        "SCLBDM": str(completion_query.get('sclbdm', '04')),
    }


def queryCompletionScores():
    res = session.get(
        "https://jw.xmu.edu.cn/jwapp/sys/xywcjdMobile/modules/kzkcxq/cxscfakzkc.do",
        params=buildCompletionParams(),
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    if 'ids.xmu.edu.cn' in res.url:
        raise SessionExpiredError("Session expired while querying completion scores")
    if res.status_code != 200:
        raise RuntimeError(f"Completion score query failed with HTTP {res.status_code}")
    rows = json.loads(res.text)['datas']['cxscfakzkc']['rows']
    return [normalizeCompletionScore(row) for row in rows if row.get('CJ') not in (None, '') and row.get('XNXQDM')]


def queryStandardScores():
    terms_res = session.post(
        "https://jw.xmu.edu.cn/jwapp/sys/cjcx/modules/cjcx/cxycjdxnxq.do",
        data={"XH": username}
    )
    if 'ids.xmu.edu.cn' in terms_res.url:
        raise SessionExpiredError("Session expired while querying score terms")
    if terms_res.status_code != 200:
        raise RuntimeError(f"Score terms query failed with HTTP {terms_res.status_code}")
    terms = json.loads(terms_res.text)['datas']['cxycjdxnxq']['rows']
    scores = []
    for term in terms:
        if query_terms and term['XNXQDM_DISPLAY'] not in query_terms and term['XNXQDM'] not in query_terms:
            continue
        standard_query_template['querySetting'][2]['value'] = term['XNXQDM']
        score_res = session.post(
            "https://jw.xmu.edu.cn/jwapp/sys/cjcx/modules/cjcx/xscjcx.do",
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
            data=parse.urlencode(standard_query_template)
        )
        if 'ids.xmu.edu.cn' in score_res.url:
            raise SessionExpiredError("Session expired while querying standard scores")
        if score_res.status_code != 200:
            raise RuntimeError(f"Standard score query failed with HTTP {score_res.status_code}")
        rows = json.loads(score_res.text)['datas']['xscjcx']['rows']
        scores.extend(normalizeStandardScore(row, term) for row in rows if row.get('ZCJ') not in (None, ''))
    return scores


def queryScores():
    if query_source == 'completion':
        return queryCompletionScores()
    if query_source == 'standard':
        return queryStandardScores()
    if query_source == 'auto':
        completion_scores = queryCompletionScores()
        if completion_scores:
            return completion_scores
        return queryStandardScores()
    raise ValueError("score_query.source must be completion, standard, or auto")


def normalizeCompletionScore(score):
    return {
        "course_id": score['KCH'],
        "name": score['KCM'],
        "score": score['CJ'],
        "grade": normalizeGrade(score['CJ']),
        "xf": float(score['XF']),
        "term": score['XNXQDM_DISPLAY'],
        "term_code": score['XNXQDM']
    }


def normalizeStandardScore(score, term):
    return {
        "course_id": score['KCH'],
        "name": score['KCM'],
        "score": score['ZCJ'],
        "grade": normalizeGrade(score.get('XFJD', score['ZCJ'])),
        "xf": float(score['XF']),
        "term": term['XNXQDM_DISPLAY'],
        "term_code": term['XNXQDM']
    }


def scoreMatches(score):
    if query_terms and score['term'] not in query_terms and score['term_code'] not in query_terms:
        return False
    if query_courses and score['name'] not in query_courses and score['course_id'] not in query_courses:
        return False
    return True


def normalizeGrade(value):
    try:
        return float(value)
    except Exception:
        return value


loadCookies()

while True:
    try:
        noti = ""
        try:
            scores = queryScores()
        except SessionExpiredError as exc:
            print(f"{exc}; attempting one fresh login.")
            loginAndGetToken()
            scores = queryScores()
        except Exception:
            traceback.print_exc()
            notify('成绩查询异常', '成绩查询接口返回异常，程序已停止；未继续重新登录以避免账号冻结。')
            exit(1)
        for score in scores:
            if not scoreMatches(score):
                continue
            if score['course_id'] not in save_scores or save_scores[score['course_id']]['score'] != score['score']:
                save_scores[score['course_id']] = {
                    "xf": score['xf'],
                    "score": score['score'],
                    "grade": score['grade'],
                    "name": score['name'],
                    "term": score['term'],
                    "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                }
                if show_score:
                    noti += f"{score['name']}：{score['score']}（学分 {score['xf']} 分，{score['term']}）。\n"
                else:
                    noti += f"{score['name']}\n"
        print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        if noti:
            with open("scores.yaml", "w", encoding='utf-8') as f:
                yaml.dump(save_scores, f, encoding='utf-8', allow_unicode=True)
            noti = "以下课程有新成绩：\n" + noti
            print(noti)
            notify('新成绩', noti)
        else:
            print("没有新成绩")
    except Exception:
        traceback.print_exc()
    time.sleep(interval * 60)
