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
    headers: { "Content-Type": "application/json", "X-Telegram-Init-Data": initData, ...(options.headers || {}) },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw { status: res.status, data };
  return data;
}

async function downloadFile(path, filename) {
  const res = await fetch(path, { headers: { "X-Telegram-Init-Data": initData } });
  if (!res.ok) { toast("❌ Yuklab olishda xatolik."); return; }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ---- Tabs ----
document.querySelectorAll(".tab").forEach(tab => {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    ["pending", "users", "report", "broadcast"].forEach(name => {
      document.getElementById(`tab-${name}`).style.display = name === tab.dataset.tab ? "block" : "none";
    });
  };
});

// ---- Modal helper ----
function openModal(html) {
  document.getElementById("modal-content").innerHTML = html;
  document.getElementById("modal-backdrop").classList.add("open");
}
function closeModal() {
  document.getElementById("modal-backdrop").classList.remove("open");
}
document.getElementById("modal-backdrop").onclick = (e) => {
  if (e.target.id === "modal-backdrop") closeModal();
};

// ---- Pending ----
async function loadPending() {
  const list = document.getElementById("pending-list");
  try {
    const users = await api("/api/admin/users");
    const pending = users.filter(u => !u.is_approved);
    if (!pending.length) { list.innerHTML = `<div class="loader">Hozircha yo'q</div>`; return; }
    list.innerHTML = pending.map(u => `
      <div class="pill">
        <div><div class="name">${escapeHtml(u.full_name)}</div><div class="meta">ID: ${u.user_id}</div></div>
        <div style="display:flex;gap:6px">
          <button class="btn" style="width:auto;margin:0;padding:8px 12px" onclick="approveUser(${u.user_id})">✅</button>
          <button class="btn danger" style="width:auto;margin:0;padding:8px 12px" onclick="rejectUser(${u.user_id})">❌</button>
        </div>
      </div>`).join("");
  } catch (err) { list.innerHTML = `<div class="loader">Xatolik yuz berdi</div>`; }
}

async function approveUser(id) {
  await api(`/api/admin/users/${id}/approve`, { method: "POST" });
  toast("✅ Tasdiqlandi");
  loadPending(); loadUsers();
}
async function rejectUser(id) {
  if (!confirm("Rad etilsinmi?")) return;
  await api(`/api/admin/users/${id}/reject`, { method: "POST" });
  toast("Rad etildi");
  loadPending(); loadUsers();
}

// ---- Users ----
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function loadUsers() {
  const list = document.getElementById("users-list");
  try {
    const users = await api("/api/admin/users");
    const approved = users.filter(u => u.is_approved);
    if (!approved.length) { list.innerHTML = `<div class="loader">Hozircha yo'q</div>`; return; }
    list.innerHTML = approved.map(u => `
      <div class="pill" style="cursor:pointer" onclick='openUserModal(${JSON.stringify(u)})'>
        <div><div class="name">${escapeHtml(u.full_name)}</div><div class="meta">${Number(u.monthly_salary).toLocaleString("uz-UZ")} so'm · norma ${u.norm_days} kun</div></div>
        <div class="meta">ID: ${u.user_id}</div>
      </div>`).join("");
  } catch (err) { list.innerHTML = `<div class="loader">Xatolik yuz berdi</div>`; }
}

function openUserModal(u) {
  openModal(`
    <h3 style="margin-top:0">${escapeHtml(u.full_name)} <span style="color:var(--hint);font-size:13px">(ID: ${u.user_id})</span></h3>
    <input id="m-name" value="${escapeHtml(u.full_name)}" placeholder="F.I.Sh">
    <button class="btn secondary" onclick="saveField(${u.user_id}, 'rename', {name: document.getElementById('m-name').value})">✏️ Ismini saqlash</button>

    <input id="m-salary" type="number" value="${u.monthly_salary}" placeholder="Oylik miqdori">
    <button class="btn secondary" onclick="saveField(${u.user_id}, 'salary', {salary: Number(document.getElementById('m-salary').value)})">💰 Oylikni saqlash</button>

    <input id="m-norm" type="number" value="${u.norm_days}" placeholder="Norma kun">
    <button class="btn secondary" onclick="saveField(${u.user_id}, 'norm', {norm_days: Number(document.getElementById('m-norm').value)})">📅 Normani saqlash</button>

    <input id="m-advance" type="number" placeholder="Avans miqdori (so'm)">
    <button class="btn secondary" onclick="saveField(${u.user_id}, 'advance', {amount: Number(document.getElementById('m-advance').value)})">💸 Avans berish</button>

    <button class="btn danger" onclick="deleteUser(${u.user_id})">❌ Xodimni o'chirish</button>
  `);
}

async function saveField(id, field, body) {
  try {
    await api(`/api/admin/users/${id}/${field}`, { method: "POST", body: JSON.stringify(body) });
    toast("✅ Saqlandi");
    closeModal();
    loadUsers();
  } catch (err) { toast("❌ Xatolik: noto'g'ri qiymat"); }
}

async function deleteUser(id) {
  if (!confirm("Butunlay o'chirilsinmi? Bu amalni qaytarib bo'lmaydi.")) return;
  await api(`/api/admin/users/${id}`, { method: "DELETE" });
  toast("O'chirildi");
  closeModal();
  loadUsers();
}

document.getElementById("add-user-btn").onclick = () => {
  openModal(`
    <h3 style="margin-top:0">Yangi xodim qo'shish</h3>
    <input id="new-id" type="number" placeholder="Telegram User ID">
    <input id="new-name" placeholder="F.I.Sh">
    <button class="btn" onclick="addUser()">✅ Qo'shish</button>
  `);
};

async function addUser() {
  const user_id = document.getElementById("new-id").value;
  const name = document.getElementById("new-name").value;
  if (!user_id || !name) { toast("Barcha maydonlarni to'ldiring"); return; }
  try {
    await api("/api/admin/users", { method: "POST", body: JSON.stringify({ user_id: Number(user_id), name }) });
    toast("✅ Qo'shildi");
    closeModal();
    loadUsers();
  } catch (err) { toast("❌ Xatolik"); }
}

// ---- Reports ----
document.getElementById("daily-date").valueAsDate = new Date();
document.getElementById("daily-load-btn").onclick = async () => {
  const date = document.getElementById("daily-date").value;
  const res = await api(`/api/admin/report/daily?date=${date}`);
  const rows = res.present.map(p => `
    <tr><td>${escapeHtml(p.full_name)}</td><td>${p.check_in || "-"}</td><td>${p.check_out || "-"}</td>
    <td>${p.lateness}</td><td>${p.work_hours ?? 0}</td></tr>`).join("");
  const absentRows = res.absent.map(n => `<tr><td>${escapeHtml(n)}</td><td colspan="4" style="color:var(--red)">KELMADI</td></tr>`).join("");
  document.getElementById("daily-result").innerHTML = `
    <table><thead><tr><th>Ism</th><th>Kelgan</th><th>Ketgan</th><th>Kechikish</th><th>Soat</th></tr></thead>
    <tbody>${rows}${absentRows}</tbody></table>`;
};
document.getElementById("daily-xlsx-btn").onclick = () => {
  const date = document.getElementById("daily-date").value;
  downloadFile(`/api/admin/report/daily.xlsx?date=${date}`, `Kunlik_Hisobot_${date}.xlsx`);
};

document.getElementById("monthly-date").value = new Date().toISOString().slice(0, 7);
document.getElementById("monthly-load-btn").onclick = async () => {
  const month = document.getElementById("monthly-date").value;
  const res = await api(`/api/admin/report/monthly?month=${month}`);
  const rows = res.rows.map(r => `
    <tr><td>${escapeHtml(r.full_name)}</td><td>${Number(r.monthly_salary).toLocaleString("uz-UZ")}</td>
    <td>${r.work_hours}</td><td>${Number(r.earned).toLocaleString("uz-UZ")}</td>
    <td>${Number(r.advance).toLocaleString("uz-UZ")}</td><td>${Number(r.net_salary).toLocaleString("uz-UZ")}</td></tr>`).join("");
  document.getElementById("monthly-result").innerHTML = `
    <table><thead><tr><th>Ism</th><th>Oylik</th><th>Soat</th><th>Hisoblangan</th><th>Avans</th><th>Sof</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
};
document.getElementById("monthly-xlsx-btn").onclick = () => {
  const month = document.getElementById("monthly-date").value;
  downloadFile(`/api/admin/report/monthly.xlsx?month=${month}`, `Oylik_Hisobot_${month}.xlsx`);
};

// ---- Broadcast ----
document.getElementById("broadcast-send-btn").onclick = async () => {
  const text = document.getElementById("broadcast-text").value.trim();
  if (!text) { toast("Matn kiriting"); return; }
  if (!confirm("Barcha tasdiqlangan xodimlarga yuborilsinmi?")) return;
  try {
    const res = await api("/api/admin/broadcast", { method: "POST", body: JSON.stringify({ text }) });
    toast(`✅ ${res.success} taga yuborildi${res.failed ? `, ${res.failed} ta muvaffaqiyatsiz` : ""}`);
    document.getElementById("broadcast-text").value = "";
  } catch (err) { toast("❌ Xatolik"); }
};

loadPending();
loadUsers();
