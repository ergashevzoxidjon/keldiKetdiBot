"""
Admin uchun mini web-ilova (Telegram WebApp).

Bu fayl passenger_wsgi.py orqali (Flask/Passenger) ishga tushadi va bot
(main.py) bilan BIR XIL sqlite bazasi (attendance.db) bilan ishlaydi, lekin
ENDI ular IKKITA MUSTAQIL Python jarayoni: bot alohida, cron+nohup orqali
tirik saqlanadigan o'z jarayonida ishlaydi (Passenger'ning uzoq muddatli
background thread'lar uchun mo'ljallanmagani sababli). Shu sabab bu yerdan
foydalanuvchiga xabar yuborish kerak bo'lganda (masalan "Eslatish" tugmasi)
botning asyncio ob'ektiga emas, balki Telegram Bot API'siga TO'G'RIDAN-TO'G'RI
oddiy HTTP so'rov yuboriladi (pastdagi _send_telegram_message).

Xavfsizlik: ba'zi Telegram klientlarida (masalan Desktop) Web App "initData"si
bo'sh kelishi kuzatilgani uchun, asosiy autentifikatsiya sifatida main.py
tomonidan tugma yaratilganda BOT_TOKEN bilan imzolangan `uid` + `sig` so'rov
parametrlaridan foydalanamiz (bu Telegram'ning o'z mexanizmiga bog'liq emas).
Telegram initData (agar mavjud bo'lsa) qo'shimcha tekshiruv sifatida ham
qo'llab-quvvatlanadi.
"""

import calendar as calendar_mod
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import parse_qsl

from flask import Flask, request, jsonify, Response

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import main as bot_main  # noqa: E402

app = Flask(__name__)


# ================= TELEGRAM WEBAPP AUTH =================
def validate_init_data(init_data: str, bot_token: str):
    """Telegram WebApp 'initData'sini tekshiradi. To'g'ri bo'lsa foydalanuvchi
    ma'lumotini (dict) qaytaradi, aks holda None."""
    if not init_data:
        return None
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    user_raw = parsed.get("user")
    if not user_raw:
        return None
    try:
        return json.loads(user_raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _get_init_data() -> str:
    return (
        request.headers.get("X-Telegram-Init-Data")
        or request.args.get("initData")
        or (request.get_json(silent=True) or {}).get("initData")
        or ""
    )


def _get_param(name: str) -> str:
    """Berilgan nomdagi parametrni query string, JSON body yoki header'dan izlaydi."""
    return (
        request.args.get(name)
        or (request.get_json(silent=True) or {}).get(name)
        or request.headers.get(f"X-{name}")
        or ""
    )


def _check_signed_uid() -> int | None:
    """main.py tomonidan tugma yaratilganda qo'shilgan `uid`+`sig` imzosini
    tekshiradi (Telegram initData'ga bog'liq bo'lmagan asosiy usul)."""
    uid_raw = _get_param("uid")
    sig = _get_param("sig")
    if not uid_raw or not sig:
        return None
    try:
        uid = int(uid_raw)
    except ValueError:
        return None
    expected = bot_main._webapp_sig(uid)
    if not hmac.compare_digest(expected, sig):
        return None
    return uid


def _require_admin():
    """Joriy so'rov admin tomonidan yuborilganini tekshiradi.
    Muvaffaqiyatli bo'lsa admin user_id'sini qaytaradi, aks holda None."""
    uid = _check_signed_uid()
    if uid is not None and uid in bot_main.ADMIN_IDS:
        return uid

    # Zaxira yo'l: Telegram initData mavjud va to'g'ri bo'lsa, shuni ham qabul qilamiz.
    init_data = _get_init_data()
    user = validate_init_data(init_data, bot_main.BOT_TOKEN)
    if user and int(user.get("id", 0)) in bot_main.ADMIN_IDS:
        return int(user["id"])

    return None


def _send_telegram_message(chat_id: int, text: str, parse_mode: str | None = "HTML", timeout: float = 10.0) -> bool:
    """Telegram Bot API'siga to'g'ridan-to'g'ri (oddiy, sinxron) HTTP so'rov
    yuborib xabar jo'natadi. Bot alohida jarayonda ishlagani uchun (cron+nohup),
    Web Panel botning asyncio ob'ektiga bog'lanmasdan, aynan shu usul bilan
    xabar yuboradi. Muvaffaqiyatli bo'lsa True, aks holda False qaytaradi -
    hech qachon istisno (exception) tashlamaydi."""
    url = f"https://api.telegram.org/bot{bot_main.BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return bool(body.get("ok"))
    except urllib.error.URLError:
        return False
    except Exception:
        return False


NUDGE_TEXT = "🔔 Ishga kelgan bo'lsangiz, belgilashni unutmang!"


# ================= API =================
@app.get("/webapp/api/status")
def api_status():
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    today_str = bot_main.get_now().strftime("%Y-%m-%d")
    ishda, ketgan, kelmagan = bot_main._get_employee_status_sync(today_str)

    return jsonify({
        "now": bot_main.get_now().strftime("%Y-%m-%d %H:%M"),
        "ishda": [
            {"name": name, "check_in": ci, "lateness": lateness}
            for name, ci, lateness in ishda
        ],
        "ketgan": [
            {"name": name, "check_in": ci, "check_out": co}
            for name, ci, co in ketgan
        ],
        "kelmagan": [
            {"user_id": uid, "name": name} for uid, name in kelmagan
        ],
    })


@app.get("/webapp/api/users")
def api_users():
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    users = bot_main._get_all_users_sync()
    result = []
    for uid, full_name, approved, salary in users:
        if uid in bot_main.ADMIN_IDS:
            continue
        start, end = bot_main._get_user_work_hours_sync(uid)
        result.append({
            "user_id": uid,
            "name": full_name,
            "approved": bool(approved),
            "work_start": start,
            "work_end": end,
            "salary": salary or 0,
        })
    return jsonify({"users": result})


# ================= XODIMNI BOSHQARISH (Admin Panel o'rniga) =================
# Botdagi "⚙️ Admin Panel" tugmasi olib tashlangani sababli, uning barcha
# funksiyalari (xodim qo'shish, ismini/oylik miqdorini o'zgartirish, avans
# berish, o'chirish) endi shu API'lar orqali Web Panel'dan bajariladi.
@app.post("/webapp/api/employee/add")
def api_employee_add():
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(force=True, silent=True) or {}
    try:
        uid = int(body["user_id"])
        name = str(body["name"]).strip()
        if not name:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "invalid_input"}), 400

    bot_main._upsert_user_sync(uid, name)
    return jsonify({"ok": True})


@app.post("/webapp/api/employee/rename")
def api_employee_rename():
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(force=True, silent=True) or {}
    try:
        uid = int(body["user_id"])
        name = str(body["name"]).strip()
        if not name:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "invalid_input"}), 400

    bot_main._rename_user_sync(uid, name)
    return jsonify({"ok": True})


@app.post("/webapp/api/employee/salary")
def api_employee_salary():
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(force=True, silent=True) or {}
    try:
        uid = int(body["user_id"])
        salary = float(body["salary"])
        if salary < 0:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "invalid_input"}), 400

    bot_main._set_salary_sync(uid, salary)
    return jsonify({"ok": True})


@app.post("/webapp/api/employee/advance")
def api_employee_advance():
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(force=True, silent=True) or {}
    try:
        uid = int(body["user_id"])
        amount = float(body["amount"])
        if amount <= 0:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "invalid_input"}), 400

    today_str = bot_main.get_now().strftime("%Y-%m-%d")
    bot_main._add_advance_sync(uid, amount, today_str)

    _send_telegram_message(
        uid, f"💸 Sizga <b>{amount:,.0f} so'm</b> avans berilgani qayd etildi."
    )

    return jsonify({"ok": True})


@app.post("/webapp/api/employee/delete")
def api_employee_delete():
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(force=True, silent=True) or {}
    try:
        uid = int(body["user_id"])
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "invalid_input"}), 400

    bot_main._delete_user_sync(uid)
    return jsonify({"ok": True})


@app.post("/webapp/api/nudge")
def api_nudge():
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(force=True, silent=True) or {}
    target = body.get("user_id", "all")
    today_str = bot_main.get_now().strftime("%Y-%m-%d")

    if target == "all":
        _, _, kelmagan = bot_main._get_employee_status_sync(today_str)
        sent = 0
        for uid, _name in kelmagan:
            if _send_telegram_message(uid, NUDGE_TEXT):
                sent += 1
        return jsonify({"sent": sent})

    try:
        target_id = int(target)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_input"}), 400

    if _send_telegram_message(target_id, NUDGE_TEXT):
        return jsonify({"sent": 1})
    return jsonify({"error": "xabar yuborilmadi (bot bloklangan yoki vaqtincha ishlamayapti)"}), 400


@app.post("/webapp/api/schedule")
def api_schedule():
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(force=True, silent=True) or {}
    try:
        uid = int(body["user_id"])
        start = datetime.strptime(body["work_start"], "%H:%M").strftime("%H:%M")
        end = datetime.strptime(body["work_end"], "%H:%M").strftime("%H:%M")
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "invalid_input"}), 400

    bot_main._set_work_time_sync(uid, start, end)
    return jsonify({"ok": True})


@app.get("/webapp/api/workdays")
def api_workdays_get():
    """Berilgan xodim va oy uchun kalendarda belgilangan ish kunlarini qaytaradi.
    Belgilangan kunlar soni o'sha oy uchun ISH NORMASI (norm_days) sifatida
    ishlatiladi (agar hech narsa belgilanmagan bo'lsa - eski norm_days ustuni
    FALLBACK sifatida qo'llaniladi, main.py._norm_days_for_month orqali)."""
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    uid_raw = request.args.get("user_id")
    month = request.args.get("month") or ""
    try:
        uid = int(uid_raw)
        year, mon = (int(x) for x in month.split("-"))
        if not (1 <= mon <= 12):
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        return jsonify({"error": "invalid_input"}), 400

    days_in_month = calendar_mod.monthrange(year, mon)[1]
    marked_dates = bot_main._get_work_days_sync(uid, month)
    marked_days = sorted({int(d.split("-")[2]) for d in marked_dates if d.startswith(month)})

    return jsonify({
        "month": month,
        "days_in_month": days_in_month,
        "marked": marked_days,
        "count": len(marked_days),
    })


@app.post("/webapp/api/workdays/toggle")
def api_workdays_toggle():
    """Bitta kunni belgilaydi/bekor qiladi (tahrirlash uchun - istalgan vaqtda
    qayta bosib o'zgartirish mumkin)."""
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(force=True, silent=True) or {}
    try:
        uid = int(body["user_id"])
        date_str = body["date"]
        datetime.strptime(date_str, "%Y-%m-%d")
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "invalid_input"}), 400

    marked = bot_main._toggle_work_day_sync(uid, date_str)
    return jsonify({"marked": marked})


@app.post("/webapp/api/workdays/set")
def api_workdays_set():
    """Kalendarda mahalliy (frontend'da) belgilangan barcha kunlarni bir yo'la
    saqlaydi (💾 Saqlash tugmasi). Kunlar bosilganda darhol emas, shu
    tugma bosilgandagina serverga yoziladi."""
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(force=True, silent=True) or {}
    try:
        uid = int(body["user_id"])
        month = body["month"]
        datetime.strptime(month + "-01", "%Y-%m-%d")
        days = [int(d) for d in (body.get("days") or [])]
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "invalid_input"}), 400

    bot_main._set_work_days_sync(uid, month, days)
    return jsonify({"ok": True, "count": len(days)})


@app.post("/webapp/api/workdays/clear")
def api_workdays_clear():
    """Shu oy uchun barcha belgilangan kunlarni tozalaydi (qayta boshidan
    belgilash uchun qulay)."""
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(force=True, silent=True) or {}
    try:
        uid = int(body["user_id"])
        month = body["month"]
        datetime.strptime(month + "-01", "%Y-%m-%d")
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "invalid_input"}), 400

    bot_main._set_work_days_sync(uid, month, [])
    return jsonify({"ok": True})


@app.post("/webapp/api/attendance")
def api_attendance():
    user = _require_admin()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(force=True, silent=True) or {}
    try:
        uid = int(body["user_id"])
        check_in = datetime.strptime(body["check_in"], "%H:%M").strftime("%H:%M")
        check_out_raw = body.get("check_out") or None
        check_out = (
            datetime.strptime(check_out_raw, "%H:%M").strftime("%H:%M")
            if check_out_raw else None
        )
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "invalid_input"}), 400

    today_str = bot_main.get_now().strftime("%Y-%m-%d")
    work_start, _ = bot_main._get_user_work_hours_sync(uid)
    bot_main._admin_set_attendance_sync(uid, today_str, check_in, check_out, work_start)

    if check_out:
        notify = (
            f"ℹ️ Admin tomonidan sizning bugungi davomatingiz kiritildi:\n"
            f"Kelgan vaqt: {check_in}\nKetgan vaqt: {check_out}"
        )
    else:
        notify = f"ℹ️ Admin tomonidan siz bugun soat {check_in} da kelgan deb belgilandingiz."
    _send_telegram_message(uid, notify)

    return jsonify({"ok": True})


# ================= HTML SAHIFA =================
@app.get("/webapp/")
@app.get("/webapp")
def webapp_index():
    return Response(ADMIN_PAGE_HTML, mimetype="text/html")


@app.get("/webapp/a/<int:uid>/<sig>")
@app.get("/webapp/a/<int:uid>/<sig>/")
def webapp_index_signed(uid, sig):
    """main.py "Web Panel" tugmasi ochadigan asosiy manzil: uid/sig manzil
    YO'LIDA keladi (so'rov parametri emas), chunki ba'zi Telegram klientlari
    tugma manzilidagi "?..." so'rov qismini olib tashlashi kuzatilgan."""
    return Response(ADMIN_PAGE_HTML, mimetype="text/html")


ADMIN_PAGE_HTML = """<!doctype html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Admin panel</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 12px 14px 32px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--tg-theme-bg-color, #f2f2f7);
    color: var(--tg-theme-text-color, #111);
  }
  h1 { font-size: 18px; margin: 6px 0 14px; }
  .card {
    background: var(--tg-theme-secondary-bg-color, #fff);
    border-radius: 14px; padding: 14px; margin-bottom: 12px;
    box-shadow: 0 1px 2px rgba(0,0,0,.06);
  }
  .card h2 { font-size: 14px; margin: 0 0 8px; opacity: .7; text-transform: uppercase; letter-spacing: .03em;}
  .row { display: flex; justify-content: space-between; align-items: center; padding: 7px 0; border-bottom: 1px solid rgba(0,0,0,.06); gap: 8px; }
  .row:last-child { border-bottom: none; }
  .name { font-weight: 600; font-size: 14px; }
  .meta { font-size: 12px; opacity: .65; }
  .badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 600; white-space: nowrap; }
  .b-green { background: #e3f8ea; color: #1c8a3f; }
  .b-red { background: #fdeaea; color: #c62828; }
  .b-gray { background: #eee; color: #666; }
  button {
    border: none; border-radius: 10px; padding: 8px 12px; font-size: 13px; font-weight: 600;
    background: var(--tg-theme-button-color, #2481cc); color: var(--tg-theme-button-text-color, #fff);
    cursor: pointer;
  }
  button.secondary { background: #eee; color: #333; }
  button:active { opacity: .8; }
  select, input {
    width: 100%; padding: 9px 10px; border-radius: 10px; border: 1px solid #ddd;
    font-size: 14px; margin-bottom: 8px; background: #fff; color: #111;
  }
  .empty { opacity: .55; font-size: 13px; padding: 6px 0; }
  .toast {
    position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%);
    background: #222; color: #fff; padding: 10px 16px; border-radius: 10px;
    font-size: 13px; opacity: 0; transition: opacity .25s; pointer-events: none; max-width: 90%;
    text-align: center;
  }
  .toast.show { opacity: 1; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .locked { text-align: center; padding: 60px 16px; opacity: .6; font-size: 14px; }
  .calnav { display: flex; justify-content: space-between; align-items: center; margin: 4px 0 8px; }
  .calnav button { padding: 5px 14px; }
  .calgrid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 5px; }
  .calcell {
    text-align: center; padding: 9px 0; border-radius: 8px; background: #eee;
    font-size: 13px; cursor: pointer; user-select: none; color: #333;
  }
  .calcell.marked { background: var(--tg-theme-button-color, #2481cc); color: var(--tg-theme-button-text-color, #fff); font-weight: 700; }
  .calcell:active { opacity: .7; }
</style>
</head>
<body>
  <h1 id="title">👥 Xodimlar boshqaruvi</h1>
  <div id="app"></div>
  <div class="toast" id="toast"></div>

<script>
// Telegram obyekti bo'lsa - faqat UI qulayligi uchun (expand va h.k.), ammo
// autentifikatsiya endi bunga bog'liq EMAS (ba'zi Telegram klientlarida
// initData bo'sh kelishi kuzatilgan). Asosiy kirish - main.py tugma
// yaratganda qo'shgan `uid` va `sig` manzil parametrlari orqali.
const tg = window.Telegram ? window.Telegram.WebApp : null;
if (tg) { try { tg.ready(); tg.expand(); } catch (e) {} }

// uid/sig manzil YO'LIDAN o'qiladi (/webapp/a/<uid>/<sig>), chunki ba'zi
// Telegram klientlari tugma manzilidagi "?..." so'rov qismini olib tashlaydi.
// Orqaga moslik uchun so'rov parametrlari ham tekshiriladi.
function extractAuth() {
  const m = window.location.pathname.match(/\/webapp\/a\/(\d+)\/([0-9a-f]+)/);
  if (m) return { uid: m[1], sig: m[2] };
  const qs = new URLSearchParams(window.location.search);
  return { uid: qs.get("uid") || "", sig: qs.get("sig") || "" };
}

const _auth = extractAuth();
const AUTH_UID = _auth.uid;
const AUTH_SIG = _auth.sig;
const hasAuth = !!(AUTH_UID && AUTH_SIG);

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
}

async function api(path, opts) {
  opts = opts || {};
  const sep = path.includes("?") ? "&" : "?";
  const url = path + sep + "uid=" + encodeURIComponent(AUTH_UID) + "&sig=" + encodeURIComponent(AUTH_SIG);
  const headers = Object.assign({"Content-Type": "application/json"}, opts.headers || {});
  const res = await fetch(url, Object.assign({}, opts, {headers}));
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

function el(html) {
  const d = document.createElement("div");
  d.innerHTML = html.trim();
  return d.firstChild;
}

let usersCache = [];

async function loadStatus() {
  const data = await api("/webapp/api/status");
  const app = document.getElementById("app");
  app.innerHTML = "";

  app.appendChild(renderSection("🟢 Ishda", data.ishda.map(u =>
    `<div class="row"><div><div class="name">${escapeHtml(u.name)}</div>
      <div class="meta">${escapeHtml(u.check_in || "").slice(0,5)} dan${u.lateness ? " · ⚠️ " + u.lateness + " daq. kech" : ""}</div></div>
      <span class="badge b-green">ishda</span></div>`
  ).join("") || `<div class="empty">Hozircha yo'q</div>`));

  app.appendChild(renderSection("🔴 Ketgan", data.ketgan.map(u =>
    `<div class="row"><div><div class="name">${escapeHtml(u.name)}</div>
      <div class="meta">${escapeHtml((u.check_in||"").slice(0,5))} – ${escapeHtml((u.check_out||"").slice(0,5))}</div></div>
      <span class="badge b-gray">ketgan</span></div>`
  ).join("") || `<div class="empty">Hozircha yo'q</div>`));

  const kelmaganRows = data.kelmagan.map(u =>
    `<div class="row"><div class="name">${escapeHtml(u.name)}</div>
      <button data-nudge="${u.user_id}" class="secondary">🔔 Eslatish</button></div>`
  ).join("");
  const kelmaganCard = renderSection(
    `⏳ Kelmagan (${data.kelmagan.length})`,
    kelmaganRows || `<div class="empty">Hammasi kelgan ✅</div>`
  );
  if (data.kelmagan.length) {
    const allBtn = el(`<button style="width:100%;margin-top:8px" data-nudge="all">🔔 Hammasiga eslatma yuborish</button>`);
    kelmaganCard.appendChild(allBtn);
  }
  app.appendChild(kelmaganCard);

  app.querySelectorAll("[data-nudge]").forEach(btn => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const r = await api("/webapp/api/nudge", {method: "POST", body: JSON.stringify({user_id: btn.dataset.nudge})});
        toast(r.sent ? `Yuborildi (${r.sent})` : "Yuborilmadi");
      } catch (e) { toast("Xatolik: " + e.message); }
      btn.disabled = false;
    });
  });

  app.appendChild(renderManageCard(data.now));
  app.appendChild(renderAddEmployeeCard());
}

function renderSection(title, innerHtml) {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `<h2>${title}</h2>${innerHtml}`;
  return card;
}

function renderManageCard(nowStr) {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <h2>⚙️ Xodimni boshqarish</h2>
    <select id="userSelect"><option value="">Xodimni tanlang...</option></select>
    <div id="manageBody" style="display:none">
      <div><label class="meta">F.I.Sh</label><input id="empName" placeholder="Ism Familiya"></div>
      <button style="width:100%;margin-bottom:12px" id="saveName">✏️ Ismini saqlash</button>

      <div><label class="meta">Belgilangan oylik (so'm)</label><input id="empSalary" placeholder="5000000" inputmode="numeric"></div>
      <button style="width:100%;margin-bottom:14px" id="saveSalary">💰 Oylikni saqlash</button>

      <div class="grid2">
        <div><label class="meta">Ish boshlash</label><input id="workStart" placeholder="09:00"></div>
        <div><label class="meta">Ish tugash</label><input id="workEnd" placeholder="18:00"></div>
      </div>
      <button style="width:100%;margin-bottom:12px" id="saveSchedule">⏰ Ish vaqtini saqlash</button>

      <div class="grid2">
        <div><label class="meta">Bugun kelgan</label><input id="checkIn" placeholder="08:30"></div>
        <div><label class="meta">Bugun ketgan (ixtiyoriy)</label><input id="checkOut" placeholder="17:30"></div>
      </div>
      <button style="width:100%;margin-bottom:14px" id="saveAttendance">🕐 Davomatni qo'lda kiritish</button>

      <div><label class="meta">Avans miqdori (so'm)</label><input id="advanceAmount" placeholder="500000" inputmode="numeric"></div>
      <button style="width:100%;margin-bottom:14px" id="saveAdvance">💸 Avans berish</button>

      <div style="border-top:1px solid rgba(0,0,0,.08);padding-top:10px">
        <label class="meta">🗓 Ish kunlari (kalendar) — shu oy normasi</label>
        <div class="calnav">
          <button class="secondary" id="calPrev">◀</button>
          <span id="calLabel" style="font-weight:600"></span>
          <button class="secondary" id="calNext">▶</button>
        </div>
        <div class="calgrid" id="calGrid"></div>
        <div class="meta" id="calCount" style="margin:8px 0"></div>
        <button class="secondary" style="width:100%;margin-bottom:8px" id="calClear">🗑 Shu oyni tozalash</button>
        <button style="width:100%" id="calSave">💾 Saqlash</button>
      </div>

      <div style="border-top:1px solid rgba(0,0,0,.08);padding-top:10px;margin-top:12px">
        <button style="width:100%;background:#fdeaea;color:#c62828" id="deleteEmp">❌ Xodimni butunlay o'chirish</button>
      </div>
    </div>
  `;

  const now = nowStr ? new Date(nowStr.replace(" ", "T")) : new Date();
  const calState = {
    userId: null,
    year: now.getFullYear(),
    month: now.getMonth() + 1, // 1-12
    marked: new Set(),   // hozir ekranda belgilangan kunlar (mahalliy, hali saqlanmagan bo'lishi mumkin)
    dirty: false,        // saqlanmagan o'zgarish bormi
  };

  loadUsersInto(card, calState);
  return card;
}

function ymStr(y, m) { return `${y}-${String(m).padStart(2, "0")}`; }

function confirmDiscardIfDirty(calState) {
  if (!calState.dirty) return true;
  return confirm("Kalendarda saqlanmagan o'zgarishlar bor. Ularni tashlab, davom etasizmi?");
}

function renderCalGrid(card, calState, daysInMonth) {
  const grid = card.querySelector("#calGrid");
  const count = card.querySelector("#calCount");
  grid.innerHTML = "";
  for (let d = 1; d <= daysInMonth; d++) {
    const cell = document.createElement("div");
    cell.className = "calcell" + (calState.marked.has(d) ? " marked" : "");
    cell.textContent = d;
    cell.addEventListener("click", () => {
      if (calState.marked.has(d)) calState.marked.delete(d); else calState.marked.add(d);
      cell.classList.toggle("marked", calState.marked.has(d));
      calState.dirty = true;
      count.textContent = `${calState.marked.size} kun belgilangan (saqlanmagan) - 💾 Saqlashni bosing`;
    });
    grid.appendChild(cell);
  }
}

async function loadCalendar(card, calState) {
  if (!calState.userId) return;
  const monthStr = ymStr(calState.year, calState.month);
  const label = card.querySelector("#calLabel");
  const count = card.querySelector("#calCount");
  label.textContent = monthStr;
  card.querySelector("#calGrid").innerHTML = `<div class="empty">Yuklanmoqda...</div>`;

  let data;
  try {
    data = await api(`/webapp/api/workdays?user_id=${calState.userId}&month=${monthStr}`);
  } catch (e) {
    card.querySelector("#calGrid").innerHTML = `<div class="empty">Xatolik: ${escapeHtml(e.message)}</div>`;
    return;
  }

  calState.daysInMonth = data.days_in_month;
  calState.marked = new Set(data.marked);
  calState.dirty = false;
  renderCalGrid(card, calState, data.days_in_month);
  count.textContent = `${data.count} kun belgilangan (shu oy normasi)`;
}

function attachCalendarNav(card, calState) {
  card.querySelector("#calPrev").addEventListener("click", () => {
    if (!confirmDiscardIfDirty(calState)) return;
    calState.month -= 1;
    if (calState.month < 1) { calState.month = 12; calState.year -= 1; }
    loadCalendar(card, calState);
  });
  card.querySelector("#calNext").addEventListener("click", () => {
    if (!confirmDiscardIfDirty(calState)) return;
    calState.month += 1;
    if (calState.month > 12) { calState.month = 1; calState.year += 1; }
    loadCalendar(card, calState);
  });
  card.querySelector("#calClear").addEventListener("click", () => {
    if (!calState.userId) return;
    calState.marked.clear();
    calState.dirty = true;
    renderCalGrid(card, calState, calState.daysInMonth);
    card.querySelector("#calCount").textContent = "0 kun belgilangan (saqlanmagan) - 💾 Saqlashni bosing";
  });
  card.querySelector("#calSave").addEventListener("click", async () => {
    if (!calState.userId) return;
    try {
      const monthStr = ymStr(calState.year, calState.month);
      const r = await api("/webapp/api/workdays/set", {
        method: "POST",
        body: JSON.stringify({
          user_id: calState.userId,
          month: monthStr,
          days: Array.from(calState.marked),
        }),
      });
      calState.dirty = false;
      card.querySelector("#calCount").textContent = `${r.count} kun belgilangan (shu oy normasi)`;
      toast("Kalendar saqlandi ✅");
    } catch (e) { toast("Xatolik: " + e.message); }
  });
}

async function loadUsersInto(card, calState) {
  const data = await api("/webapp/api/users");
  usersCache = data.users;
  const select = card.querySelector("#userSelect");
  usersCache.forEach(u => {
    const opt = document.createElement("option");
    opt.value = u.user_id;
    opt.textContent = u.name + " (" + u.work_start + "-" + u.work_end + ")";
    select.appendChild(opt);
  });

  attachCalendarNav(card, calState);

  const body = card.querySelector("#manageBody");
  select.addEventListener("change", (ev) => {
    if (!confirmDiscardIfDirty(calState)) { select.value = calState.userId || ""; return; }
    const u = usersCache.find(x => String(x.user_id) === select.value);
    if (!u) { body.style.display = "none"; calState.userId = null; return; }
    body.style.display = "block";
    card.querySelector("#empName").value = u.name;
    card.querySelector("#empSalary").value = u.salary || "";
    card.querySelector("#workStart").value = u.work_start;
    card.querySelector("#workEnd").value = u.work_end;
    card.querySelector("#checkIn").value = "";
    card.querySelector("#checkOut").value = "";
    card.querySelector("#advanceAmount").value = "";
    calState.userId = u.user_id;
    loadCalendar(card, calState);
  });

  card.querySelector("#saveName").addEventListener("click", async () => {
    if (!select.value) return;
    const name = card.querySelector("#empName").value.trim();
    if (!name) { toast("Ismni kiriting"); return; }
    try {
      await api("/webapp/api/employee/rename", {method: "POST", body: JSON.stringify({
        user_id: select.value, name,
      })});
      toast("Ism saqlandi ✅");
      const opt = select.querySelector(`option[value="${select.value}"]`);
      if (opt) opt.textContent = name + " (" + card.querySelector("#workStart").value + "-" + card.querySelector("#workEnd").value + ")";
    } catch (e) { toast("Xatolik: " + e.message); }
  });

  card.querySelector("#saveSalary").addEventListener("click", async () => {
    if (!select.value) return;
    const salary = card.querySelector("#empSalary").value.trim();
    if (!salary) { toast("Oylik miqdorini kiriting"); return; }
    try {
      await api("/webapp/api/employee/salary", {method: "POST", body: JSON.stringify({
        user_id: select.value, salary,
      })});
      toast("Oylik saqlandi ✅");
    } catch (e) { toast("Xatolik: " + e.message); }
  });

  card.querySelector("#saveSchedule").addEventListener("click", async () => {
    if (!select.value) return;
    try {
      await api("/webapp/api/schedule", {method: "POST", body: JSON.stringify({
        user_id: select.value,
        work_start: card.querySelector("#workStart").value,
        work_end: card.querySelector("#workEnd").value,
      })});
      toast("Ish vaqti saqlandi ✅");
      loadUsersInto.cacheDirty = true;
    } catch (e) { toast("Xatolik: " + e.message); }
  });

  card.querySelector("#saveAttendance").addEventListener("click", async () => {
    if (!select.value) return;
    const checkIn = card.querySelector("#checkIn").value.trim();
    if (!checkIn) { toast("Kelish vaqtini kiriting"); return; }
    try {
      await api("/webapp/api/attendance", {method: "POST", body: JSON.stringify({
        user_id: select.value,
        check_in: checkIn,
        check_out: card.querySelector("#checkOut").value.trim() || null,
      })});
      toast("Davomat saqlandi ✅");
      loadStatus();
    } catch (e) { toast("Xatolik: " + e.message); }
  });

  card.querySelector("#saveAdvance").addEventListener("click", async () => {
    if (!select.value) return;
    const amount = card.querySelector("#advanceAmount").value.trim();
    if (!amount) { toast("Avans miqdorini kiriting"); return; }
    try {
      await api("/webapp/api/employee/advance", {method: "POST", body: JSON.stringify({
        user_id: select.value, amount,
      })});
      toast("Avans saqlandi ✅");
      card.querySelector("#advanceAmount").value = "";
    } catch (e) { toast("Xatolik: " + e.message); }
  });

  card.querySelector("#deleteEmp").addEventListener("click", async () => {
    if (!select.value) return;
    const opt = select.querySelector(`option[value="${select.value}"]`);
    const label = opt ? opt.textContent : select.value;
    if (!confirm(`${label} butunlay o'chirilsinmi? Bu amalni ortga qaytarib bo'lmaydi - barcha davomat va avans tarixi ham o'chib ketadi!`)) return;
    try {
      await api("/webapp/api/employee/delete", {method: "POST", body: JSON.stringify({
        user_id: select.value,
      })});
      toast("Xodim o'chirildi ✅");
      loadStatus();
    } catch (e) { toast("Xatolik: " + e.message); }
  });
}

function renderAddEmployeeCard() {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <h2>➕ Yangi xodim qo'shish</h2>
    <div><label class="meta">Telegram User ID</label><input id="newEmpId" placeholder="123456789" inputmode="numeric"></div>
    <div><label class="meta">F.I.Sh</label><input id="newEmpName" placeholder="Ism Familiya"></div>
    <button style="width:100%" id="addEmpBtn">➕ Qo'shish</button>
  `;
  card.querySelector("#addEmpBtn").addEventListener("click", async () => {
    const idRaw = card.querySelector("#newEmpId").value.trim();
    const name = card.querySelector("#newEmpName").value.trim();
    if (!idRaw || !name) { toast("ID va Ismni kiriting"); return; }
    try {
      await api("/webapp/api/employee/add", {method: "POST", body: JSON.stringify({
        user_id: idRaw, name,
      })});
      toast("Xodim qo'shildi ✅");
      card.querySelector("#newEmpId").value = "";
      card.querySelector("#newEmpName").value = "";
      loadStatus();
    } catch (e) { toast("Xatolik: " + e.message); }
  });
  return card;
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

if (!hasAuth) {
  document.getElementById("app").innerHTML =
    '<div class="locked">Bu sahifani faqat botdagi "🖥 Web Panel" tugmasi orqali oching.</div>';
} else {
  loadStatus().catch(e => {
    document.getElementById("app").innerHTML =
      `<div class="locked">Kirish rad etildi yoki xatolik: ${escapeHtml(e.message)}</div>`;
  });
}
</script>
</body>
</html>
"""