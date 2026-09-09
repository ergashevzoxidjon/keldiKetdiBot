"""Yozilgan tuzatishlarning sof mantig'ini tekshiruvchi skript (haqiqiy botni
ishga tushirmasdan). Har bir bo'lim bitta talabga mos keladi."""
import os
import sys

os.environ.setdefault("DB_PATH", "/tmp/keldiKetdiBot/test_attendance.db")
if os.path.exists("/tmp/keldiKetdiBot/test_attendance.db"):
    os.remove("/tmp/keldiKetdiBot/test_attendance.db")

sys.path.insert(0, "/tmp/keldiKetdiBot")
import main as m  # noqa: E402

failures = []


def check(name, cond):
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        failures.append(name)


# ---------------------------------------------------------------
# 3) Kechikish hisoblash: admin belgilagan vaqtdan kech bo'lsagina musbat
# ---------------------------------------------------------------
check("lateness: aynan vaqtida kelsa 0", m._compute_lateness_minutes("2026-09-09", "10:00:03", "10:00") == 0)
check("lateness: 1 daqiqa oldin kelsa 0", m._compute_lateness_minutes("2026-09-09", "09:59:00", "10:00") == 0)
check("lateness: 15 daqiqa kech kelsa 15", m._compute_lateness_minutes("2026-09-09", "10:15:00", "10:00") == 15)
check("lateness: admin 10:00 belgilasa va xodim 10:00'da kelsa - 1 soat KECH emas",
      m._compute_lateness_minutes("2026-09-09", "10:00:00", "10:00") == 0)

# ---------------------------------------------------------------
# 6) 21:00'dan keyin va yakshanba kunida 2x hisoblash
# ---------------------------------------------------------------
# 2026-09-09 chorshanba (weekday=2), 2026-09-06 yakshanba (weekday=6) ekanini tekshiramiz
import datetime as dt
check("2026-09-06 haqiqatan yakshanba", dt.datetime(2026, 9, 6).weekday() == 6)

# oddiy kun, 18:00-21:00 -> 3 soat, 2x-huquqsiz
p1 = m._compute_paid_hours("2026-09-09", "18:00:00", "21:00:00", 0, False)
check("2x-huquqsiz uchun paid_hours == oddiy soat (3.0)", p1 == 3.0)

# 2x-huquqli, lekin hammasi 21:00'dan OLDIN -> ko'paytirilmaydi
p2 = m._compute_paid_hours("2026-09-09", "09:00:00", "18:00:00", 0, True)
check("2x-huquqli, 21:00'gacha ishlasa oddiy (9.0)", p2 == 9.0)

# 2x-huquqli, 18:00-23:00 -> 18:00-21:00 (3soat x1) + 21:00-23:00 (2soat x2=4) = 7
p3 = m._compute_paid_hours("2026-09-09", "18:00:00", "23:00:00", 0, True)
check("2x-huquqli, 21:00'dan keyingi qism 2x (18:00-23:00 -> 7.0)", p3 == 7.0)

# 2x-huquqli, TO'LIQ 21:00'dan keyin (22:00-23:30 -> 1.5soat x2=3.0)
p4 = m._compute_paid_hours("2026-09-09", "22:00:00", "23:30:00", 0, True)
check("2x-huquqli, to'liq 21:00'dan keyin (22:00-23:30 -> 3.0)", p4 == 3.0)

# Yakshanba kuni (2026-09-06), 2x-huquqli, 09:00-15:00 (6soat) -> hammasi 2x = 12
p5 = m._compute_paid_hours("2026-09-06", "09:00:00", "15:00:00", 0, True)
check("2x-huquqli, yakshanba kuni hammasi 2x (6soat -> 12.0)", p5 == 12.0)

# Yakshanba kuni, 2x-huquqsiz -> oddiy (6.0)
p6 = m._compute_paid_hours("2026-09-06", "09:00:00", "15:00:00", 0, False)
check("2x-huquqsiz, yakshanba kuni ham oddiy hisoblanadi (6.0)", p6 == 6.0)

# Tanaffus hisobga olinishi (18:00-23:00, 60 daqiqa tanaffus 21:00'dan OLDIN) -> 18:00-21:00(3-1=2soat x1)+21:00-23:00(2soat x2=4) = 6
p7 = m._compute_paid_hours("2026-09-09", "18:00:00", "23:00:00", 60, True)
check("tanaffus normal qismdan ayiriladi (18:00-23:00, 60d tanaffus -> 6.0)", p7 == 6.0)

# ---------------------------------------------------------------
# 5) Ish kuni kalendariga mos xabarnoma / kelmagan belgilash
# ---------------------------------------------------------------
UID = 555001
with m.get_db() as conn:
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO users (user_id, full_name, is_approved, monthly_salary, norm_days) "
        "VALUES (?, 'Test Xodim', 1, 5000000, 26)", (UID,)
    )
    conn.commit()

# Kalendar umuman belgilanmagan -> eski qoida: yakshanbadan tashqari ish kuni
check("kalendar yo'q + dushanba -> ish kuni", m._is_work_day_sync(UID, "2026-09-07"))
check("kalendar yo'q + yakshanba -> DAM OLISH", not m._is_work_day_sync(UID, "2026-09-06"))

# Endi shu oy uchun faqat dushanba/chorshanba/juma belgilaymiz (masalan yarim stavka)
m._set_work_days_sync(UID, "2026-09", [7, 9, 11])  # Dush, Chor, Juma
check("kalendar bor + belgilangan kun (09-07) -> ish kuni", m._is_work_day_sync(UID, "2026-09-07"))
check("kalendar bor + belgilanmagan kun (09-08, seshanba) -> DAM OLISH", not m._is_work_day_sync(UID, "2026-09-08"))
check("kalendar bor + yakshanba ham belgilanmagani uchun DAM OLISH", not m._is_work_day_sync(UID, "2026-09-06"))

# _get_employee_status_sync shu qoidaga rioya qiladimi?
ishda, ketgan, kelmagan = m._get_employee_status_sync("2026-09-08")  # seshanba, ish kuni EMAS
kelmagan_ids = [u for u, _ in kelmagan]
check("ish kuni bo'lmagan kunda xodim 'kelmagan' ro'yxatida YO'Q", UID not in kelmagan_ids)

ishda, ketgan, kelmagan = m._get_employee_status_sync("2026-09-07")  # dushanba, ish kuni
kelmagan_ids = [u for u, _ in kelmagan]
check("ish kuni bo'lgan kunda (kelmagan bo'lsa) xodim 'kelmagan' ro'yxatida BOR", UID in kelmagan_ids)

# reminder targets ham shu qoidaga rioya qiladimi?
targets = m._get_checkin_reminder_targets_sync("2026-09-08", "08:45")
check("ish kuni bo'lmagan kunda checkin-reminder yuborilmaydi",
      all(t[0] != UID for t in targets))

m._set_work_days_sync(UID, "2026-09", [])  # tozalash

# ---------------------------------------------------------------
# 1 & 2) O'tgan kunlar uchun mustaqil kelish/ketish
# ---------------------------------------------------------------
PAST_DATE = "2026-09-01"
ok1 = m._admin_set_checkin_sync(UID, PAST_DATE, "10:05", "10:00")
rec = m._admin_get_attendance_sync(UID, PAST_DATE)
check("o'tgan kun uchun FAQAT kelish saqlandi", ok1 and rec["check_in"] == "10:05" and rec["check_out"] == "")
check("kelish kech bo'lmagani uchun kechikish ~5 daqiqa", rec["lateness_minutes"] == 5)

# Endi keyin, alohida, FAQAT ketishni kiritamiz (kelishni qayta yozmasdan)
ok2 = m._admin_set_checkout_sync(UID, PAST_DATE, "19:00")
rec2 = m._admin_get_attendance_sync(UID, PAST_DATE)
check("mustaqil ravishda FAQAT ketish saqlandi (kelish o'zgarmadi)",
      ok2 and rec2["check_in"] == "10:05" and rec2["check_out"] == "19:00")

# Ketishni kelish yozuvi yo'q kunga kiritishga urinish -> False qaytishi kerak
NO_RECORD_DATE = "2026-09-02"
ok3 = m._admin_set_checkout_sync(UID, NO_RECORD_DATE, "18:00")
check("kelish yozuvi bo'lmagan kunga ketish kiritib bo'lmaydi", ok3 is False)

# ---------------------------------------------------------------
# Umumiy: barcha natijalar
# ---------------------------------------------------------------
print()
if failures:
    print(f"JAMI: {len(failures)} ta test MUVAFFAQIYATSIZ:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("BARCHA TESTLAR MUVAFFAQIYATLI O'TDI ✅")
