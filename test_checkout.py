"""_checkout_sync ichidagi avto-ketish (klemp) mantig'ini get_now()ni
vaqtinchalik almashtirib tekshiradi."""
import os
import sys
from datetime import datetime

os.environ.setdefault("DB_PATH", "/tmp/keldiKetdiBot/test_attendance.db")
sys.path.insert(0, "/tmp/keldiKetdiBot")
import main as m  # noqa: E402

failures = []


def check(name, cond):
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        failures.append(name)


def fake_now(dt_str):
    return lambda: datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=m.TASHKENT_TZ)


UID = 555003
m._upsert_user_sync(UID, "Checkout Test")
m._set_work_time_sync(UID, "09:00", "18:00")
m._set_auto_checkout_sync(UID, True)

DATE = "2026-09-09"

# Checkin ertalab 09:00 da
orig_get_now = m.get_now
m.get_now = fake_now(f"{DATE} 09:00:00")
try:
    aid = m._checkin_sync(UID, DATE, "09:00:00", 0)
    check("check-in yaratildi", aid is not None)

    # Endi xodim ish tugagandan KECH (19:30) "ketdim" bossa
    m.get_now = fake_now(f"{DATE} 19:30:00")
    status, payload = m._checkout_sync(UID, DATE, "19:30:00")
    check("_checkout_sync status ok", status == "ok")
    (net_work_hours, _autoclosed, _added, _u, paid_hours, clamped, effective_time_str) = payload
    check("avto-ketish YOQILGAN bo'lsa, 18:00'dan keyin bossa - KLEMP qilinadi", clamped is True)
    check("ketish vaqti 18:00:00 ga o'rnatildi (haqiqiy 19:30 emas)", effective_time_str == "18:00:00")
    check("ishlangan soat 9.0 (09:00-18:00)", net_work_hours == 9.0)
finally:
    m.get_now = orig_get_now

# Ikkinchi xodim: avto-ketish YOQILMAGAN - kech bossa ham haqiqiy vaqt yozilishi kerak
UID2 = 555004
m._upsert_user_sync(UID2, "Checkout Test 2")
m._set_work_time_sync(UID2, "09:00", "18:00")
# auto_checkout_enabled default False - o'zgartirmaymiz

m.get_now = fake_now(f"{DATE} 09:00:00")
try:
    m._checkin_sync(UID2, DATE, "09:00:00", 0)
    m.get_now = fake_now(f"{DATE} 19:30:00")
    status, payload = m._checkout_sync(UID2, DATE, "19:30:00")
    (net_work_hours2, _a, _b, _u, paid_hours2, clamped2, effective_time_str2) = payload
    check("avto-ketish YOQILMAGAN bo'lsa, haqiqiy (kech) vaqt saqlanadi", clamped2 is False and effective_time_str2 == "19:30:00")
finally:
    m.get_now = orig_get_now

# Uchinchi xodim: ish tugash vaqtigacha bossa (avto-ketish yoqilgan bo'lsa ham) - klemp bo'lmasligi kerak
UID3 = 555005
m._upsert_user_sync(UID3, "Checkout Test 3")
m._set_work_time_sync(UID3, "09:00", "18:00")
m._set_auto_checkout_sync(UID3, True)

m.get_now = fake_now(f"{DATE} 09:00:00")
try:
    m._checkin_sync(UID3, DATE, "09:00:00", 0)
    m.get_now = fake_now(f"{DATE} 17:45:00")
    status, payload = m._checkout_sync(UID3, DATE, "17:45:00")
    (_n, _a, _b, _u, _p, clamped3, effective_time_str3) = payload
    check("18:00'gacha bossa - klemp qilinmaydi, o'z vaqti yoziladi", clamped3 is False and effective_time_str3 == "17:45:00")
finally:
    m.get_now = orig_get_now

print()
if failures:
    print(f"JAMI: {len(failures)} ta test MUVAFFAQIYATSIZ:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("BARCHA CHECKOUT TESTLARI MUVAFFAQIYATLI O'TDI ✅")
