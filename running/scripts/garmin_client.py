"""Shared Garmin Connect login helper.

Uses cached OAuth tokens in data/.garminconnect/ when available; falls back to
email/password from .env (with MFA prompt). Passing the token dir to login()
makes the library persist fresh tokens there automatically.
"""

import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from garminconnect import Garmin

BASE_DIR = Path(__file__).resolve().parent.parent  # project root
TOKEN_DIR = BASE_DIR / "data" / ".garminconnect"


def get_client() -> Garmin:
    if TOKEN_DIR.exists():
        try:
            client = Garmin()
            client.login(str(TOKEN_DIR))
            return client
        except Exception:
            print("Cached tokens invalid or expired, logging in fresh...")
            # stale tokens would short-circuit the credential login below
            shutil.rmtree(TOKEN_DIR, ignore_errors=True)

    load_dotenv(BASE_DIR / ".env")
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        raise SystemExit(
            "No cached login and no credentials found.\n"
            "Copy .env.example to .env and fill in GARMIN_EMAIL / GARMIN_PASSWORD."
        )

    client = Garmin(
        email=email,
        password=password,
        prompt_mfa=lambda: input("Enter the MFA code Garmin sent you: ").strip(),
    )
    client.login(str(TOKEN_DIR))
    print(f"Login OK, tokens cached in {TOKEN_DIR}")
    return client


if __name__ == "__main__":
    c = get_client()
    print(f"Logged in as: {c.get_full_name()}")
