"""cPanel Cron Jobs: har kuni dush-shan 08:45'da ishga tushirish uchun.
Buyruq (cPanel Cron Jobs'da):
    /usr/local/bin/python3 /home/USERNAME/came.mylogo.uz/cron/daily_reminder.py

DIQQAT - ESKIRGAN (DEPRECATED): main.py ENDI shu eslatmani o'zi ICHKI
scheduler orqali (har bir xodimning SHAXSIY ish boshlash vaqtiga qarab,
15/10/0 daqiqa qolganda) yuboradi va bu YANGI mantiq "ish kunlari
(kalendar)" bo'limida admin belgilagan kunlarni to'liq hisobga oladi.
Agar bu skript ALOHIDA cPanel Cron Job sifatida ham sozlangan bo'lsa,
xodimlarga IKKI MARTA (bir xilda) eslatma boradi, YANA HAM MUHIMI - bu
skript pastda qo'shilgan tekshiruvgacha admin belgilamagan (dam olish)
kunlarida ham xabar yuborar edi, chunki eski db.py "ish kunlari
kalendar"idan umuman xabardor emas edi.

TAVSIYA: cPanel > Cron Jobs bo'limidan shu skriptga ishora qiluvchi
qatorni butunlay o'chirib tashlang - main.py buni allaqachon o'zi
bajaradi. Pastdagi tekshiruv shunchaki xavfsizlik uchun (agar hali
o'chirilmagan bo'lsa, kamida noto'g'ri kunlarda xabar yubormasin deb)
qoldirildi.
"""
import os
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import db  # noqa: E402

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]


def esc(v):
    return str(v) if v is not None else ""


def _is_work_day(cursor, user_id: int, date_str: str) -> bool:
    """main.py._is_work_day bilan BIR XIL qoida. Admin shu oy uchun
    kalendarda hech kun belgilamagan bo'lsa - yakshanbadan boshqa barcha
    kunlar ish kuni. Kamida bitta kun belgilangan bo'lsa - faqat aynan
    o'sha kunlargina ish kuni."""
    month_prefix = date_str[:7]
    cursor.execute(
        "SELECT COUNT(*) FROM work_schedule WHERE user_id = ? AND date LIKE ?",
        (user_id, f"{month_prefix}%")
    )
    has_calendar = cursor.fetchone()[0] > 0
    if has_calendar:
        cursor.execute(
            "SELECT 1 FROM work_schedule WHERE user_id = ? AND date = ?",
            (user_id, date_str)
        )
        return cursor.fetchone() is not None
    weekday = datetime.strptime(date_str, "%Y-%m-%d").weekday()  # Yakshanba=6
    return weekday != 6


def main():
    today_str = db.get_now().strftime("%Y-%m-%d")
    pending = db.get_users_without_checkin_today(today_str)

    with db.get_db() as conn:
        cursor = conn.cursor()
        pending = [
            (user_id, full_name) for user_id, full_name in pending
            if _is_work_day(cursor, user_id, today_str)
        ]

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
