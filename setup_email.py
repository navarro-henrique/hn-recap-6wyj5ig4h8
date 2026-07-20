"""
One-time interactive setup for daily dashboard emails.

Run this yourself in a terminal (not through Claude), same reasoning as
login.py: your app password is typed directly into this script and never
passes through chat. It's saved locally in .email_config.json so future
syncs can send email without asking again.

Outlook/Hotmail requires an "app password", not your normal login password:
  1. Go to https://account.microsoft.com/security
  2. Turn on two-step verification if it isn't already on
  3. Under "Advanced security options" -> "App passwords", create a new one
  4. Paste that app password here, not your regular Microsoft password

Usage:
    venv\\Scripts\\python.exe setup_email.py
"""

import getpass
import json
import os
import smtplib
from email.mime.text import MIMEText

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_DIR, ".email_config.json")

PROVIDERS = {
    "1": ("Outlook / Hotmail", "smtp-mail.outlook.com", 587),
    "2": ("Gmail", "smtp.gmail.com", 587),
    "3": ("Other", None, 587),
}


def main():
    print("=== Daily dashboard email setup ===")
    print()
    for key, (name, _, _) in PROVIDERS.items():
        print(f"  {key}. {name}")
    choice = input("Pick your email provider [1]: ").strip() or "1"
    name, host, port = PROVIDERS.get(choice, PROVIDERS["1"])
    if host is None:
        host = input("SMTP server host (e.g. smtp.example.com): ").strip()
        port = int(input("SMTP port [587]: ").strip() or "587")

    print()
    sender = input("Sending email address: ").strip()
    password = getpass.getpass("App password (hidden as you type): ")
    recipient = input(f"Send the dashboard to [{sender}]: ").strip() or sender

    print()
    print("Sending a test email to verify these settings...")
    try:
        msg = MIMEText("This is a test message from your garmin-ai daily dashboard setup. If you're reading this, it works.")
        msg["Subject"] = "garmin-ai: email setup successful"
        msg["From"] = sender
        msg["To"] = recipient
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
    except Exception as exc:
        print(f"\nTest email failed: {exc}")
        print("Nothing was saved. Fix the details above and try again.")
        return

    config = {
        "smtp_host": host,
        "smtp_port": port,
        "sender": sender,
        "password": password,
        "recipient": recipient,
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    print()
    print("Test email sent — check your inbox.")
    print(f"Settings saved to {CONFIG_PATH}")
    print("The daily sync will now email you the dashboard automatically.")


if __name__ == "__main__":
    main()
