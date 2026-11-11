import os
import json
import ssl
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr, formatdate

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
        raise SystemExit("❌ 邮件参数缺失")

    subject_parts = []
    if added:
        subject_parts.append(f"新增 {len(added)} 个分支")
    if removed:
        subject_parts.append(f"删除 {len(removed)} 个分支")
    if changed:
        subject_parts.append(f"{len(changed)} 个分支代码更新")
    subject = f"仓库变更通知 {TARGET_REPO} " + "，".join(subject_parts)

    def lines(names):
        if not names:
            return "无\n"
        buf = ""
        for b in names:
            sha = branches.get(b, "")
            if sha:
                buf += f"- {b} SHA:{sha[:8]}\n"
            else:
                buf += f"- {b}\n"
        return buf

    text = f"""仓库：{TARGET_REPO}
检测时间：{formatdate(localtime=True)}

新增分支（{len(added)}）
{lines(added)}
代码变更分支（{len(changed)}）
{lines(changed)}
删除分支（{len(removed)}）
{lines(removed)}

当前跟踪分支总数：{len(branches)}
"""

    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr(("通知", MAIL_USERNAME))
    msg["To"] = MAIL_TO
    msg["Date"] = formatdate(localtime=True)

    if SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=30)
    else:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        server.starttls(context=ssl.create_default_context())
    server.login(MAIL_USERNAME, MAIL_PASSWORD)
    # 重点：单个收件人传字符串，不要数组
    server.sendmail(MAIL_USERNAME, MAIL_TO, msg.as_string())
    server.quit()
    print("✅ 邮件发送成功")

if __name__ == "__main__":
    main()
