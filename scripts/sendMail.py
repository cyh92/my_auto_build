import os
import json
import ssl
import smtplib
import certifi
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formatdate

def main():
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_TO = os.environ.get("MAIL_TO", "")
    SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.139.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 465))

    TARGET_REPO = os.environ.get("TARGET_REPO", "")
    ADDED = os.environ.get("ADDED", "")
    REMOVED = os.environ.get("REMOVED", "")
    CHANGED = os.environ.get("CHANGED", "")
    NEW_DATA = os.environ.get("NEW_DATA", "{}")

    added = [x for x in ADDED.split() if x]
    removed = [x for x in REMOVED.split() if x]
    changed = [x for x in CHANGED.split() if x]

    try:
        snap = json.loads(NEW_DATA)
    except Exception:
        snap = {}
    branches = snap.get("branches", {})

    if not MAIL_USERNAME or not MAIL_PASSWORD or not MAIL_TO:
        raise SystemExit("参数缺失")

    parts = []
    if added:
        parts.append(f"新增{len(added)}分支")
    if removed:
        parts.append(f"删除{len(removed)}分支")
    if changed:
        parts.append(f"{len(changed)}分支更新")
    subject = f"仓库通知 {TARGET_REPO} {' '.join(parts)}"

    buf = ""
    if added:
        buf += "新增：" + " ".join(added) + "\n"
    if changed:
        buf += "更新：" + " ".join(changed) + "\n"
    if removed:
        buf += "删除：" + " ".join(removed) + "\n"
    buf += f"分支总数:{len(branches)}"

    msg = MIMEText(buf, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = MAIL_USERNAME
    msg["To"] = MAIL_TO
    msg["Date"] = formatdate(localtime=True)

    context = ssl.create_default_context(cafile=certifi.where())
    if SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=30)
    else:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        server.starttls(context=context)
    server.login(MAIL_USERNAME, MAIL_PASSWORD)
    server.sendmail(MAIL_USERNAME, MAIL_TO, msg.as_string())
    server.quit()
    print("✅ 发送成功")

if __name__ == "__main__":
    main()
