"""
Web App backend (Flask). Telegram Mini App shu backend bilan gaplashadi.
Xuddi shu attendance.db faylidan foydalanadi (db.py orqali) - bot bilan bir xil ma'lumot.

Ishga tushirish (lokal sinov uchun):
    pip install -r requirements.txt
    python app.py

cPanel'da "Setup Python App" orqali joylashtirilganda, passenger_wsgi.py
shu fayldagi `app` obyektini ishlatadi.
"""
import os
import io
import json
import hmac
import hashlib
import asyncio
import logging
from datetime import datetime
from functools import wraps
from urllib.parse import parse_qsl

from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_file, abort

import db

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("webapp_backend")

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
OFFICE_LAT = float(os.getenv("OFFICE_LAT", "41.3199585"))
OFFICE_LON = float(os.getenv("OFFICE_LON", "69.2661517"))
ALLOWED_RADIUS_METERS = int(os.getenv("ALLOWED_RADIUS_METERS", "100"))
WORK_START_TIME = os.getenv("WORK_START_TIME", "09:00")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
WEBAPP_DEV_MODE = os.getenv("WEBAPP_DEV_MODE", "0") == "1"

if not BOT_TOKEN:
    raise SystemExit("XATOLIK: .env faylida BOT_TOKEN topilmadi.")

db.init_db(ADMIN_IDS)

app = Flask(__name__, static_folder="webapp", static_url_path="")


# ================= TELEGRAM WEBAPP AUTH =================
def verify_init_data(init_data: str):
    """Telegram hujjatlariga muvofiq initData imzosini tekshiradi.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    recv_hash = pairs.pop("hash", None)
    if not recv_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, recv_hash):
        return None

    user_json = pairs.get("user")
    if not user_json:
        return None
    return json.loads(user_json)


def auth_required(admin_only=False):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            init_data = request.headers.get("X-Telegram-Init-Data", "")
            user = verify_init_data(init_data)

            if not user and WEBAPP_DEV_MODE:
                # Faqat lokal sinov uchun: ?dev_user_id=123 bilan sinash imkonini beradi.
                dev_id = request.args.get("dev_user_id") or request.headers.get("X-Dev-User-Id")
                if dev_id:
                    user = {"id": int(dev_id), "first_name": "Dev"}

            if not user:
                return jsonify({"error": "unauthorized"}), 401

            user_id = user["id"]
            if admin_only and user_id not in ADMIN_IDS:
                return jsonify({"error": "forbidden"}), 403
            if not admin_only and not db.is_user_approved(user_id, ADMIN_IDS):
                return jsonify({"error": "not_approved"}), 403

            request.tg_user = user
            request.tg_user_id = user_id
            return f(*args, **kwargs)
        return wrapper
    return decorator


def esc(v):
    return str(v) if v is not None else ""


# ================= STATIC PAGES =================
@app.route("/")
def index_page():
    return app.send_static_file("index.html")


@app.route("/admin")
def admin_page():
    return app.send_static_file("admin.html")


# ================= EMPLOYEE API =================
@app.route("/api/me")
@auth_required()
def api_me():
    user_id = request.tg_user_id
    urow = db.get_user(user_id)
    today_str = db.get_now().strftime("%Y-%m-%d")
    today = db.get_today_attendance(user_id, today_str)
    return jsonify({
        "user_id": user_id,
        "full_name": urow[1] if urow else request.tg_user.get("first_name", ""),
        "is_admin": user_id in ADMIN_IDS,
        "today": None if not today else {
            "check_in_time": today[1],
            "check_out_time": today[2],
            "break_start": today[3],
            "break_end": today[4],
            "break_minutes": today[5],
        },
        "office": {"lat": OFFICE_LAT, "lon": OFFICE_LON, "radius": ALLOWED_RADIUS_METERS},
    })


@app.route("/api/checkin", methods=["POST"])
@auth_required()
def api_checkin():
    user_id = request.tg_user_id
    data = request.get_json(force=True, silent=True) or {}
    lat, lon = data.get("lat"), data.get("lon")
    if lat is None or lon is None:
        return jsonify({"error": "location_required"}), 400

    distance = db.calculate_distance(OFFICE_LAT, OFFICE_LON, float(lat), float(lon))
    if distance > ALLOWED_RADIUS_METERS:
        return jsonify({"error": "out_of_range", "distance": int(distance)}), 400

    now = db.get_now()
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    work_start = datetime.strptime(f"{today_str} {WORK_START_TIME}", "%Y-%m-%d %H:%M").replace(tzinfo=db.TASHKENT_TZ)
    lateness = int((now - work_start).total_seconds() / 60) if now > work_start else 0

    attendance_id = db.checkin(user_id, today_str, time_str, lateness)
    if attendance_id is None:
        return jsonify({"error": "already_checked_in"}), 409

    return jsonify({"ok": True, "time": time_str, "lateness": lateness, "attendance_id": attendance_id})


@app.route("/api/checkin/reason", methods=["POST"])
@auth_required()
def api_checkin_reason():
    data = request.get_json(force=True, silent=True) or {}
    attendance_id = data.get("attendance_id")
    reason = (data.get("reason") or "").strip()
    if not attendance_id or not reason:
        return jsonify({"error": "invalid"}), 400
    db.save_lateness_reason(attendance_id, reason)
    return jsonify({"ok": True})


@app.route("/api/checkout", methods=["POST"])
@auth_required()
def api_checkout():
    user_id = request.tg_user_id
    data = request.get_json(force=True, silent=True) or {}
    lat, lon = data.get("lat"), data.get("lon")
    if lat is None or lon is None:
        return jsonify({"error": "location_required"}), 400

    distance = db.calculate_distance(OFFICE_LAT, OFFICE_LON, float(lat), float(lon))
    if distance > ALLOWED_RADIUS_METERS:
        return jsonify({"error": "out_of_range", "distance": int(distance)}), 400

    now = db.get_now()
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    status, payload = db.checkout(user_id, today_str, time_str)

    if status == "no_checkin":
        return jsonify({"error": "no_checkin"}), 409

    net_work_hours, break_autoclosed, added_break_minutes, u_data = payload
    m_salary = u_data[0] if u_data else 0.0
    norm_d = u_data[1] if u_data and u_data[1] > 0 else 26
    hourly_rate = m_salary / (norm_d * 8) if (norm_d * 8) > 0 else 0
    daily_earned = net_work_hours * hourly_rate

    return jsonify({
        "ok": True, "time": time_str, "net_work_hours": net_work_hours,
        "daily_earned": round(daily_earned, 2),
        "break_autoclosed": break_autoclosed, "added_break_minutes": added_break_minutes,
    })


@app.route("/api/break/start", methods=["POST"])
@auth_required()
def api_break_start():
    user_id = request.tg_user_id
    now = db.get_now()
    today_str = now.strftime("%Y-%m-%d")
    now_str = now.strftime("%H:%M:%S")
    status, extra = db.break_start_action(user_id, today_str, now_str)
    if status != "ok":
        return jsonify({"error": status, "extra": extra}), 409
    return jsonify({"ok": True, "time": now_str})


@app.route("/api/break/end", methods=["POST"])
@auth_required()
def api_break_end():
    user_id = request.tg_user_id
    now = db.get_now()
    today_str = now.strftime("%Y-%m-%d")
    now_str = now.strftime("%H:%M:%S")
    status, minutes = db.break_end_action(user_id, today_str, now_str, now)
    if status != "ok":
        return jsonify({"error": status}), 409
    return jsonify({"ok": True, "time": now_str, "break_minutes": minutes})


@app.route("/api/me/stats")
@auth_required()
def api_me_stats():
    user_id = request.tg_user_id
    month_prefix = request.args.get("month") or db.get_now().strftime("%Y-%m")
    row, salary_row = db.get_user_stats(user_id, month_prefix)
    monthly_salary = salary_row[0] if salary_row else 0.0
    norm_days = salary_row[1] if salary_row and salary_row[1] > 0 else 26
    hourly_rate = monthly_salary / (norm_days * 8) if (norm_days * 8) > 0 else 0.0
    total_work_hours = row[2]
    return jsonify({
        "days_present": row[0],
        "total_lateness_minutes": row[1],
        "total_work_hours": round(total_work_hours, 1),
        "total_break_minutes": row[3],
        "monthly_salary": monthly_salary,
        "norm_days": norm_days,
        "hourly_rate": round(hourly_rate, 0),
        "total_earned": round(total_work_hours * hourly_rate, 0),
    })


@app.route("/api/me/salary")
@auth_required()
def api_me_salary():
    user_id = request.tg_user_id
    month_prefix = request.args.get("month") or db.get_now().strftime("%Y-%m")
    result = db.get_salary_details(user_id, month_prefix)
    if not result:
        return jsonify({"error": "not_found"}), 404
    user_info, total_hours, total_advance = result
    full_name, m_salary, norm_days = user_info
    hourly_rate = m_salary / (norm_days * 8) if (norm_days * 8) > 0 else 0.0
    gross_earned = total_hours * hourly_rate
    return jsonify({
        "full_name": full_name, "monthly_salary": m_salary, "norm_days": norm_days,
        "hourly_rate": round(hourly_rate, 0), "total_hours": round(total_hours, 1),
        "gross_earned": round(gross_earned, 0), "total_advance": total_advance,
        "net_payable": round(gross_earned - total_advance, 0),
    })


@app.route("/api/me/calendar")
@auth_required()
def api_me_calendar():
    user_id = request.tg_user_id
    month_prefix = request.args.get("month") or db.get_now().strftime("%Y-%m")
    rows = db.get_month_attendance_days(user_id, month_prefix)
    return jsonify([
        {"date": d, "check_in": ci, "check_out": co, "lateness": lm, "work_hours": wh}
        for d, ci, co, lm, wh in rows
    ])


# ================= ADMIN API =================
@app.route("/api/admin/users")
@auth_required(admin_only=True)
def api_admin_users():
    users = db.get_all_users()
    return jsonify([
        {"user_id": u, "full_name": n, "is_approved": bool(a), "monthly_salary": s, "norm_days": nd}
        for u, n, a, s, nd in users
    ])


@app.route("/api/admin/users", methods=["POST"])
@auth_required(admin_only=True)
def api_admin_add_user():
    data = request.get_json(force=True, silent=True) or {}
    try:
        user_id = int(data.get("user_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_user_id"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name_required"}), 400
    db.upsert_user(user_id, name)
    return jsonify({"ok": True})


@app.route("/api/admin/users/<int:user_id>/approve", methods=["POST"])
@auth_required(admin_only=True)
def api_admin_approve(user_id):
    db.approve_user(user_id)
    _notify(user_id, "🎉 <b>Arizangiz tasdiqlandi!</b> Endi botdan foydalanishingiz mumkin.")
    return jsonify({"ok": True})


@app.route("/api/admin/users/<int:user_id>/reject", methods=["POST"])
@auth_required(admin_only=True)
def api_admin_reject(user_id):
    db.reject_user(user_id)
    _notify(user_id, "❌ Afsuski, arizangiz admin tomonidan rad etildi.")
    return jsonify({"ok": True})


@app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
@auth_required(admin_only=True)
def api_admin_delete(user_id):
    db.delete_user(user_id)
    return jsonify({"ok": True})


@app.route("/api/admin/users/<int:user_id>/rename", methods=["POST"])
@auth_required(admin_only=True)
def api_admin_rename(user_id):
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name_required"}), 400
    db.rename_user(user_id, name)
    return jsonify({"ok": True})


@app.route("/api/admin/users/<int:user_id>/salary", methods=["POST"])
@auth_required(admin_only=True)
def api_admin_salary(user_id):
    data = request.get_json(force=True, silent=True) or {}
    try:
        salary = float(data.get("salary"))
        if salary < 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_salary"}), 400
    db.set_salary(user_id, salary)
    return jsonify({"ok": True})


@app.route("/api/admin/users/<int:user_id>/norm", methods=["POST"])
@auth_required(admin_only=True)
def api_admin_norm(user_id):
    data = request.get_json(force=True, silent=True) or {}
    try:
        norm_days = int(data.get("norm_days"))
        if norm_days <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_norm"}), 400
    db.set_norm_days(user_id, norm_days)
    return jsonify({"ok": True})


@app.route("/api/admin/users/<int:user_id>/advance", methods=["POST"])
@auth_required(admin_only=True)
def api_admin_advance(user_id):
    data = request.get_json(force=True, silent=True) or {}
    try:
        amount = float(data.get("amount"))
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_amount"}), 400
    today_str = db.get_now().strftime("%Y-%m-%d")
    db.add_advance(user_id, amount, today_str)
    return jsonify({"ok": True})


@app.route("/api/admin/report/daily")
@auth_required(admin_only=True)
def api_admin_report_daily():
    date_str = request.args.get("date") or db.get_now().strftime("%Y-%m-%d")
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.full_name, a.check_in_time, a.check_out_time, a.lateness_minutes,
                   a.lateness_reason, a.break_minutes, a.work_hours
            FROM attendance a JOIN users u ON u.user_id = a.user_id
            WHERE a.date = ? ORDER BY u.full_name COLLATE NOCASE
        ''', (date_str,))
        rows = cursor.fetchall()
        cursor.execute('''
            SELECT u.full_name FROM users u
            WHERE u.is_approved = 1 AND u.user_id NOT IN (SELECT user_id FROM attendance WHERE date = ?)
            ORDER BY u.full_name COLLATE NOCASE
        ''', (date_str,))
        absent = [r[0] for r in cursor.fetchall()]
    return jsonify({
        "date": date_str,
        "present": [
            {"full_name": n, "check_in": ci, "check_out": co, "lateness": lm,
             "reason": r, "break_minutes": bm, "work_hours": wh}
            for n, ci, co, lm, r, bm, wh in rows
        ],
        "absent": absent,
    })


@app.route("/api/admin/report/monthly")
@auth_required(admin_only=True)
def api_admin_report_monthly():
    month_prefix = request.args.get("month") or db.get_now().strftime("%Y-%m")
    users = db.get_all_users()
    result = []
    with db.get_db() as conn:
        cursor = conn.cursor()
        for u_id, name, approved, m_salary, norm_d in users:
            if not approved:
                continue
            cursor.execute("SELECT COALESCE(SUM(work_hours), 0.0) FROM attendance WHERE user_id = ? AND date LIKE ?",
                           (u_id, f"{month_prefix}%"))
            w_hours = cursor.fetchone()[0] or 0.0
            cursor.execute("SELECT COALESCE(SUM(amount), 0.0) FROM advances WHERE user_id = ? AND date LIKE ?",
                           (u_id, f"{month_prefix}%"))
            adv_sum = cursor.fetchone()[0] or 0.0
            hourly_rate = m_salary / (norm_d * 8) if norm_d and norm_d > 0 else 0
            earned = w_hours * hourly_rate
            result.append({
                "user_id": u_id, "full_name": name, "monthly_salary": m_salary, "norm_days": norm_d,
                "work_hours": round(w_hours, 1), "earned": round(earned, 2),
                "advance": adv_sum, "net_salary": round(earned - adv_sum, 2),
            })
    return jsonify({"month": month_prefix, "rows": result})


@app.route("/api/admin/report/monthly.xlsx")
@auth_required(admin_only=True)
def api_admin_report_monthly_xlsx():
    month_prefix = request.args.get("month") or db.get_now().strftime("%Y-%m")
    file_path = f"/tmp/Oylik_Hisobot_{month_prefix}.xlsx"
    db.generate_excel_report(month_prefix, file_path)
    return send_file(file_path, as_attachment=True, download_name=f"Oylik_Hisobot_{month_prefix}.xlsx")


@app.route("/api/admin/report/daily.xlsx")
@auth_required(admin_only=True)
def api_admin_report_daily_xlsx():
    date_str = request.args.get("date") or db.get_now().strftime("%Y-%m-%d")
    file_path = f"/tmp/Kunlik_Hisobot_{date_str}.xlsx"
    db.generate_daily_excel_report(date_str, file_path)
    return send_file(file_path, as_attachment=True, download_name=f"Kunlik_Hisobot_{date_str}.xlsx")


@app.route("/api/admin/broadcast", methods=["POST"])
@auth_required(admin_only=True)
def api_admin_broadcast():
    import requests
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text_required"}), 400
    users = db.get_approved_users()
    success, failed = 0, 0
    for user_id, full_name in users:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": user_id, "text": f"📢 <b>E'lon:</b>\n\n{text}", "parse_mode": "HTML"},
                timeout=10,
            )
            if r.ok:
                success += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Broadcast xatosi ({user_id}): {e}")
            failed += 1
    return jsonify({"ok": True, "success": success, "failed": failed})


def _notify(user_id, text):
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": user_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        logger.error(f"Xabar yuborishda xatolik ({user_id}): {e}")


# ================= TELEGRAM WEBHOOK (ixtiyoriy) =================
# Agar hostingda bot 'polling' emas, 'webhook' rejimida ishlashi kerak bo'lsa
# (masalan SSH bo'lmagan cPanel Python App), WEBHOOK_SECRET'ni .env'da belgilang
# va Telegram'ga https://sizning-domen/webhook/<WEBHOOK_SECRET> manzilini bering.
if WEBHOOK_SECRET:
    _webhook_loop = asyncio.new_event_loop()

    @app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
    def telegram_webhook():
        from main import bot, dp  # noqa: bot handlerlari shu yerda ro'yxatdan o'tadi
        from aiogram.types import Update

        update = Update.model_validate(request.get_json(force=True))
        _webhook_loop.run_until_complete(dp.feed_update(bot, update))
        return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=WEBAPP_DEV_MODE)
