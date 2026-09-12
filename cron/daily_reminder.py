"""cPanel Cron Jobs: har kuni dush-shan 08:45'da ishga tushirish uchun.
Buyruq (cPanel Cron Jobs'da):
    /usr/local/bin/python3 /home/USERNAME/came.mylogo.uz/cron/daily_reminder.py
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


def esc(v):
    return str(v) if v is not None else ""


def main():
    today_str = db.get_now().strftime("%Y-%m-%d")
    pending = db.get_users_without_checkin_today(today_str)
    for user_id, full_name in pending:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": user_id,
                    "text": (
                        f"Xayrli kun, <b>{esc(full_name)}</b>! ☀️\n"
                        "Ish vaqti boshlanishiga oz qoldi (09:00).\n"
                        "Ofisga kelgach, <b>🟢 Ishga keldim</b> tugmasini bosishni unutmang!"
                    ),
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
        except Exception as e:
            print(f"Xatolik ({user_id}): {e}")


if __name__ == "__main__":
    main()
