"""webapp.py'dagi yangi endpoint'larni Flask test client orqali tekshiradi."""
import os
import sys

os.environ.setdefault("DB_PATH", "/tmp/keldiKetdiBot/test_attendance.db")
sys.path.insert(0, "/tmp/keldiKetdiBot")

import webapp  # noqa: E402
import main as bot_main  # noqa: E402

failures = []


def check(name, cond):
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        failures.append(name)


ADMIN_ID = bot_main.ADMIN_IDS[0]
SIG = bot_main._webapp_sig(ADMIN_ID)

client = webapp.app.test_client()


def api_get(path):
    sep = "&" if "?" in path else "?"
    return client.get(f"{path}{sep}uid={ADMIN_ID}&sig={SIG}")


def api_post(path, body):
    sep = "&" if "?" in path else "?"
    return client.post(f"{path}{sep}uid={ADMIN_ID}&sig={SIG}", json=body)


# Test xodim yaratamiz
TEST_UID = 555002
bot_main._upsert_user_sync(TEST_UID, "Web Test Xodim")
bot_main._set_work_time_sync(TEST_UID, "10:00", "18:00")

# 1) /webapp/api/users flags qaytarayaptimi?
r = api_get("/webapp/api/users")
check("GET /users -> 200", r.status_code == 200)
users = r.get_json()["users"]
u = next((x for x in users if x["user_id"] == TEST_UID), None)
check("yangi xodim ro'yxatda bor va flags mavjud",
      u is not None and "auto_checkout_enabled" in u and "overtime_eligible" in u)

# 2) flags saqlash
r = api_post("/webapp/api/employee/flags", {"user_id": TEST_UID, "auto_checkout_enabled": True, "overtime_eligible": True})
check("POST /employee/flags -> 200", r.status_code == 200)
flags = bot_main._get_user_flags_sync(TEST_UID)
check("auto_checkout_enabled saqlandi", flags["auto_checkout_enabled"] is True)
check("overtime_eligible saqlandi", flags["overtime_eligible"] is True)

# 3) o'tgan kun uchun mustaqil checkin/checkout
PAST_DATE = "2026-08-15"
r = api_post("/webapp/api/attendance/checkin", {"user_id": TEST_UID, "check_in": "10:20", "date": PAST_DATE})
check("POST checkin (o'tgan kun) -> 200", r.status_code == 200)

r = api_get(f"/webapp/api/attendance?user_id={TEST_UID}&date={PAST_DATE}")
rec = r.get_json()["record"]
check("checkin saqlandi, checkout hali yo'q", rec["check_in"] == "10:20" and rec["check_out"] == "")
check("kechikish to'g'ri hisoblandi (20 daqiqa)", rec["lateness_minutes"] == 20)

r = api_post("/webapp/api/attendance/checkout", {"user_id": TEST_UID, "check_out": "19:30", "date": PAST_DATE})
check("POST checkout (kelishni qayta kiritmasdan) -> 200", r.status_code == 200)

r = api_get(f"/webapp/api/attendance?user_id={TEST_UID}&date={PAST_DATE}")
rec = r.get_json()["record"]
check("checkout mustaqil saqlandi, checkin o'zgarmadi", rec["check_in"] == "10:20" and rec["check_out"] == "19:30")

# 4) kelish yozuvi yo'q kunga checkout -> 400
EMPTY_DATE = "2026-08-16"
r = api_post("/webapp/api/attendance/checkout", {"user_id": TEST_UID, "check_out": "18:00", "date": EMPTY_DATE})
check("kelish yo'q kunga checkout -> 400 xato", r.status_code == 400 and r.get_json().get("error") == "no_checkin")

print()
if failures:
    print(f"JAMI: {len(failures)} ta test MUVAFFAQIYATSIZ:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("BARCHA WEBAPP TESTLARI MUVAFFAQIYATLI O'TDI ✅")
