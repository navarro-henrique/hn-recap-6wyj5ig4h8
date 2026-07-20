"""
One-time interactive Garmin Connect login.

Run this yourself in a terminal (not through Claude) so your password is
typed directly into Garmin's login library and never passes through chat.
Your password is never stored. Only an encrypted session token is saved,
in the local .garmin_tokens folder, so future syncs don't need it again.
"""

import getpass
import os
import sys

from garminconnect import Garmin

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKENSTORE = os.path.join(PROJECT_DIR, ".garmin_tokens")


def main():
    print("=== Garmin Connect one-time login ===")
    print("Your password is hidden as you type and is never saved to disk.")
    print()

    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")

    client = Garmin(
        email,
        password,
        prompt_mfa=lambda: input("Garmin sent you a 2FA code. Enter it here: ").strip(),
    )

    try:
        client.login(TOKENSTORE)
    except Exception as exc:
        print(f"\nLogin failed: {exc}")
        sys.exit(1)

    print()
    print("Login successful.")
    print(f"Session saved to: {TOKENSTORE}")
    print("You will not need to log in again unless Garmin invalidates the session.")


if __name__ == "__main__":
    main()
