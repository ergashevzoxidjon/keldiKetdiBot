"""cPanel Cron Jobs: har yakshanba 23:30'da ishga tushirish uchun.
Buyruq: /usr/local/bin/python3 /home/USERNAME/came.mylogo.uz/cron/weekly_backup.py
"""
import os
import sys
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import db  # noqa: E402

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DB_PATH = os.getenv("DB_PATH", "attendance.db")


def esc(v):
    return str(v) if v is not None else ""


def main():
    now_str = db.get_now().strftime("%Y-%m-%d %H:%M")
    db_full_path = os.path.join(os.path.dirname(__file__), "..", DB_PATH)
    for admin_id in ADMIN_IDS:
        try:
            with open(db_full_path, "rb") as f:
                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                    data={"chat_id": admin_id, "caption": f"💾 <b>Haftalik zaxira nusxa (.db):</b> {esc(now_str)}", "parse_mode": "HTML"},
                    files={"document": f},
                    timeout=30,
                )
        except Exception as e:
            print(f"Xatolik ({admin_id}): {e}")


if __name__ == "__main__":
    main()
