"""cPanel Cron Jobs: har oyning 1-kuni 09:00'da ishga tushirish uchun.
Buyruq: /usr/local/bin/python3 /home/USERNAME/came.mylogo.uz/cron/monthly_report.py
"""
import os
import sys
from datetime import timedelta
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
    last_month_date = db.get_now() - timedelta(days=5)
    month_prefix = last_month_date.strftime("%Y-%m")
    month_name = last_month_date.strftime("%B %Y")
    file_path = f"/tmp/Oylik_Hisobot_{month_prefix}.xlsx"
    db.generate_excel_report(month_prefix, file_path)

    for admin_id in ADMIN_IDS:
        try:
            with open(file_path, "rb") as f:
                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                    data={"chat_id": admin_id, "caption": f"📅 <b>{esc(month_name)}</b> oyi uchun avtomatik oylik va avans hisoboti.", "parse_mode": "HTML"},
                    files={"document": f},
                    timeout=30,
                )
        except Exception as e:
            print(f"Xatolik ({admin_id}): {e}")


if __name__ == "__main__":
    main()
