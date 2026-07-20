"""
Emails the latest dashboard.html to the address configured by setup_email.py.

Silently does nothing (exit 0) if setup_email.py hasn't been run yet, so it's
safe to call from the daily sync unconditionally.

Usage:
    venv\\Scripts\\python.exe send_dashboard_email.py
"""

import json
import os
import smtplib
from datetime import date
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_DIR, ".email_config.json")
DASHBOARD_PATH = os.path.join(PROJECT_DIR, "dashboard.html")


def main():
    if not os.path.exists(CONFIG_PATH):
        print("No .email_config.json found — skipping email (run setup_email.py to enable it).")
        return
    if not os.path.exists(DASHBOARD_PATH):
        print("No dashboard.html found — skipping email.")
        return

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    today_str = date.today().isoformat()
    msg = MIMEMultipart()
    msg["Subject"] = f"Garmin recovery & training dashboard — {today_str}"
    msg["From"] = config["sender"]
    msg["To"] = config["recipient"]
    msg.attach(MIMEText(
        "Your Garmin recovery & training dashboard was just updated.\n\n"
        "Open the attached dashboard.html in any browser to view it.\n"
        "This was generated and sent entirely from your own computer.",
        "plain",
    ))

    with open(DASHBOARD_PATH, "rb") as f:
        attachment = MIMEApplication(f.read(), _subtype="html")
    attachment.add_header("Content-Disposition", "attachment", filename=f"garmin-dashboard-{today_str}.html")
    msg.attach(attachment)

    try:
        with smtplib.SMTP(config["smtp_host"], config["smtp_port"], timeout=30) as server:
            server.starttls()
            server.login(config["sender"], config["password"])
            server.send_message(msg)
        print(f"Dashboard emailed to {config['recipient']}")
    except Exception as exc:
        print(f"Warning: could not send dashboard email ({exc})")


if __name__ == "__main__":
    main()
