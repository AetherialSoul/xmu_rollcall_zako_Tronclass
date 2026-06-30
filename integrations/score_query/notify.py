import smtplib
from email.mime.text import MIMEText
from email.header import Header
from pathlib import Path

import yaml

CONFIG_PATH = Path("config.yaml")


def load_notify_config():
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            conf = yaml.load(f, Loader=yaml.FullLoader) or {}
    except FileNotFoundError:
        return "", {}
    except Exception as exc:
        print(f"Cannot load notification config from config.yaml: {exc}")
        return "", {}

    return str(conf.get("notify") or "").strip().lower(), conf.get("email") or {}


def report_with_smtp(title, message, smtp_conf):
    try:
        host = smtp_conf["host"]
        port = smtp_conf["port"]
        username = smtp_conf["username"]
        password = smtp_conf["password"]
        receiver = smtp_conf.get("receiver", username)
        use_ssl = smtp_conf.get("use_ssl", False)
        if host is None or port is None or username is None or password is None:
            raise KeyError("SMTP config is incomplete")
        if receiver is None:
            receiver = username

        msg = MIMEText(message, "plain", "utf-8")
        msg['Subject'] = title
        msg['From'] = '%s <%s>' % (Header("成绩提醒", "utf-8").encode(), username)
        msg['To'] = Header(receiver if isinstance(receiver, str) else ",".join(receiver), "utf-8")

        try:
            smtp = smtplib.SMTP_SSL(host, port) if use_ssl else smtplib.SMTP(host, port)
            smtp.login(username, password)
            smtp.sendmail(username, receiver, msg.as_string())
            smtp.quit()
        except smtplib.SMTPException:
            print("Error: 发送邮件失败")
            raise
    except KeyError:
        print("Cannot report with SMTP: email config is incomplete")
        return
    except Exception:
        raise


def report_with_system(title, message):
    try:
        from plyer import notification
    except Exception:
        print("Cannot report with system notification: plyer is not installed")
        return

    notification.notify(
        title=title,
        message=message[:256],
        app_icon=None,
        timeout=10
    )


def is_score_error_title(title):
    return any(keyword in str(title) for keyword in ("异常", "失效", "被拒绝", "失败", "错误"))

def notify(title, message):
    notify_type, smtp_conf = load_notify_config()
    if notify_type in ("", "none", "off", "false"):
        return
    if is_score_error_title(title):
        if notify_type in ("system", "both", "email"):
            report_with_system(title, message)
        print(f"Skip email for score-query error notification: {title}")
        return
    if notify_type in ("email", "both"):
        report_with_smtp(title, message, smtp_conf)
    if notify_type in ("system", "both"):
        report_with_system(title, message)

if __name__ == "__main__":
    notify("嘿嘿嘿", "哇哇哇")
