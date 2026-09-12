const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

const initData = tg?.initData || "";

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 3000);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": initData,
      ...(options.headers || {}),
    },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw { status: res.status, data };
  }
  return data;
}

function getLocation() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("Bu qurilmada joylashuv aniqlanmaydi"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      (err) => reject(err),
      { enableHighAccuracy: true, timeout: 10000 }
    );
  });
}

const ERROR_MESSAGES = {
  out_of_range: (d) => `❌ Ofisgacha masofa: ${d.distance} metr. Ofis hududida bo'lishingiz kerak.`,
  already_checked_in: () => "⚠️ Siz bugun allaqachon kelgansiz!",
  no_checkin: () => "⚠️ Avval ishga kelganingizni belgilang!",
  already_on_break: () => "⚠️ Siz allaqachon tanaffusga chiqqansiz!",
  already_checked_out: () => "⚠️ Siz bugun allaqachon ishdan ketgansiz!",
  not_on_break: () => "⚠️ Siz tanaffusga chiqqaningizni belgilamagansiz!",
  already_returned: () => "⚠️ Siz tanaffusdan qaytganingizni belgilab bo'lgansiz!",
  not_approved: () => "⏳ Arizangiz hali admin tomonidan tasdiqlanmagan.",
  unauthorized: () => "❌ Avtorizatsiya xatosi. Botni Telegram ichida oching.",
};

function describeError(err) {
  const code = err?.data?.error;
  if (code && ERROR_MESSAGES[code]) return ERROR_MESSAGES[code](err.data);
  return "❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.";
}

async function withLocation(action) {
  try {
    toast("📍 Joylashuv aniqlanmoqda...");
    const loc = await getLocation();
    return await action(loc);
  } catch (err) {
    if (err instanceof GeolocationPositionError || err?.code) {
      toast("❌ Joylashuvga ruxsat berilmadi yoki topilmadi.");
    } else {
      toast(describeError(err));
    }
    throw err;
  }
}

function renderActions(today) {
  const area = document.getElementById("action-area");
  area.innerHTML = "";

  const addBtn = (label, cls, onClick) => {
    const b = document.createElement("button");
    b.className = `btn ${cls || ""}`.trim();
    b.textContent = label;
    b.onclick = onClick;
    area.appendChild(b);
    return b;
  };

  if (!today) {
    addBtn("🟢 Ishga keldim", "", () => doCheckin());
    return;
  }
  if (today.check_out_time) {
    const p = document.createElement("div");
    p.className = "card";
    p.style.textAlign = "center";
    p.style.color = "var(--hint)";
    p.textContent = "✅ Bugungi ish kuni yakunlandi.";
    area.appendChild(p);
    return;
  }
  if (today.break_start && !today.break_end) {
    addBtn("🏢 Tanaffusdan qaytdim", "", () => doBreakEnd());
    return;
  }
  addBtn("☕ Tanaffusga chiqdim", "secondary", () => doBreakStart());
  addBtn("🔴 Ishdan ketdim", "danger", () => doCheckout());
}

async function doCheckin() {
  await withLocation(async (loc) => {
    const res = await api("/api/checkin", { method: "POST", body: JSON.stringify(loc) });
    toast(`✅ Ishga kelganingiz belgilandi! ${res.time}`);
    if (res.lateness > 0) {
      const reason = prompt(`Siz ${res.lateness} daqiqa kechikdingiz. Sababini yozing:`);
      if (reason) await api("/api/checkin/reason", { method: "POST", body: JSON.stringify({ attendance_id: res.attendance_id, reason }) });
    }
    await loadMe();
  });
}

async function doCheckout() {
  await withLocation(async (loc) => {
    const res = await api("/api/checkout", { method: "POST", body: JSON.stringify(loc) });
    toast(`🔴 Ishdan ketish belgilandi. ${res.net_work_hours} soat ishladingiz.`);
    await loadMe();
    await loadStats();
  });
}

async function doBreakStart() {
  try {
    const res = await api("/api/break/start", { method: "POST", body: "{}" });
    toast(`☕ Tanaffus boshlandi: ${res.time}`);
    await loadMe();
  } catch (err) { toast(describeError(err)); }
}

async function doBreakEnd() {
  try {
    const res = await api("/api/break/end", { method: "POST", body: "{}" });
    toast(`🏢 Ishga qaytdingiz. Tanaffus: ${res.break_minutes} daqiqa.`);
    await loadMe();
  } catch (err) { toast(describeError(err)); }
}

async function loadMe() {
  try {
    const me = await api("/api/me");
    document.getElementById("greeting").textContent = `Salom, ${me.full_name || "do'stim"}!`;
    document.getElementById("today-date").textContent = new Date().toLocaleDateString("uz-UZ", { day: "numeric", month: "long", year: "numeric" });
    document.getElementById("s-checkin").textContent = me.today?.check_in_time || "—";
    document.getElementById("s-checkout").textContent = me.today?.check_out_time || "—";

    const badge = document.getElementById("s-badge");
    if (!me.today) { badge.textContent = "Kelmadi"; badge.className = "badge red"; }
    else if (me.today.check_out_time) { badge.textContent = "Yakunlandi"; badge.className = "badge green"; }
    else if (me.today.break_start && !me.today.break_end) { badge.textContent = "Tanaffusda"; badge.className = "badge orange"; }
    else { badge.textContent = "Ishda"; badge.className = "badge green"; }

    renderActions(me.today);
  } catch (err) {
    toast(describeError(err));
  }
}

async function loadStats() {
  try {
    const s = await api("/api/me/stats");
    document.getElementById("m-days").textContent = s.days_present;
    document.getElementById("m-hours").textContent = s.total_work_hours;
    document.getElementById("m-late").textContent = s.total_lateness_minutes;
    document.getElementById("m-earned").textContent = Number(s.total_earned).toLocaleString("uz-UZ");

    const sal = await api("/api/me/salary");
    document.getElementById("sal-monthly").textContent = Number(sal.monthly_salary).toLocaleString("uz-UZ") + " so'm";
    document.getElementById("sal-gross").textContent = Number(sal.gross_earned).toLocaleString("uz-UZ") + " so'm";
    document.getElementById("sal-advance").textContent = Number(sal.total_advance).toLocaleString("uz-UZ") + " so'm";
    document.getElementById("sal-net").innerHTML = `<b>${Number(sal.net_payable).toLocaleString("uz-UZ")} so'm</b>`;
  } catch (err) { /* jim tur */ }
}

async function loadCalendar() {
  try {
    const days = await api("/api/me/calendar");
    const now = new Date();
    const year = now.getFullYear(), month = now.getMonth();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const byDate = {};
    days.forEach(d => byDate[d.date] = d);

    const cal = document.getElementById("calendar");
    cal.innerHTML = "";
    for (let d = 1; d <= daysInMonth; d++) {
      const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const cell = document.createElement("div");
      cell.className = "day";
      const rec = byDate[dateStr];
      if (rec) {
        cell.classList.add(rec.lateness > 0 ? "late" : "present");
      }
      cell.textContent = d;
      cal.appendChild(cell);
    }
  } catch (err) { /* jim tur */ }
}

loadMe();
loadStats();
loadCalendar();
