const state = {
  csrf: null,
  validNumbers: [],
  activeCampaignId: null,
  progressTimer: null,
  historyTimer: null,
};

const $ = (selector) => document.querySelector(selector);
const loginView = $("#login-view");
const dashboardView = $("#dashboard-view");

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[char]));
}

function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  $("#toast-region").appendChild(toast);
  window.setTimeout(() => toast.remove(), 4200);
}

async function api(path, options = {}) {
  const config = { credentials: "same-origin", ...options, headers: { ...(options.headers || {}) } };
  if (config.body && typeof config.body !== "string") {
    config.headers["Content-Type"] = "application/json";
    config.body = JSON.stringify(config.body);
  }
  if (["POST", "PUT", "PATCH", "DELETE"].includes(config.method) && state.csrf) {
    config.headers["X-CSRF-Token"] = state.csrf;
  }
  const response = await fetch(path, config);
  let data = {};
  try { data = await response.json(); } catch (_) { data = {}; }
  if (response.status === 401 && path !== "/api/auth/login") {
    showLogin();
    throw new Error("Sessiya bitib. Yenidən daxil olun.");
  }
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : data.detail?.message;
    const error = new Error(detail || "Sorğu icra olunmadı.");
    error.payload = data;
    throw error;
  }
  return data;
}

async function getCsrf() {
  const result = await api("/api/auth/csrf");
  state.csrf = result.csrf_token;
}

function showDashboard() {
  loginView.classList.add("hidden");
  dashboardView.classList.remove("hidden");
  loadDashboard();
}

function showLogin() {
  if (state.progressTimer) window.clearInterval(state.progressTimer);
  state.progressTimer = null;
  dashboardView.classList.add("hidden");
  loginView.classList.remove("hidden");
  $("#password").value = "";
}

function parseError(error) {
  if (error.payload?.detail?.invalid) {
    const invalid = error.payload.detail.invalid;
    return `${error.payload.detail.message} ${invalid.length} səhv nömrə var.`;
  }
  return error.message;
}

async function loadDashboard() {
  try {
    await getCsrf();
    await Promise.all([loadStats(), loadHistory()]);
    const campaigns = await api("/api/campaigns");
    const active = campaigns.find((campaign) => ["running", "paused"].includes(campaign.status));
    if (active) {
      state.activeCampaignId = active.id;
      startProgressPolling();
    }
  } catch (error) {
    showToast(parseError(error), "error");
  }
}

async function loadStats() {
  const stats = await api("/api/dashboard/stats");
  $("#stat-total").textContent = stats.total_numbers.toLocaleString("az-AZ");
  $("#stat-sent").textContent = stats.sent.toLocaleString("az-AZ");
  $("#stat-failed").textContent = stats.failed.toLocaleString("az-AZ");
  $("#stat-pending").textContent = stats.pending.toLocaleString("az-AZ");
}

function statusLabel(status) {
  return { completed: "TAMAMLANDI", running: "GÖNDƏRİLİR", paused: "PAUSE", stopped: "STOP", pending: "GÖZLƏYİR" }[status] || status.toUpperCase();
}

function renderBadge(status) {
  return `<span class="badge badge-${escapeHtml(status)}">${escapeHtml(statusLabel(status))}</span>`;
}

async function loadHistory() {
  const params = new URLSearchParams();
  const search = $("#history-search").value.trim();
  const status = $("#status-filter").value;
  if (search) params.set("search", search);
  if (status) params.set("status", status);
  const campaigns = await api(`/api/campaigns?${params.toString()}`);
  $("#campaign-count").textContent = `${campaigns.length} kampaniya`;
  const list = $("#history-list");
  if (!campaigns.length) {
    list.innerHTML = `<div class="empty-state"><div class="empty-icon">◫</div><strong>Hələ kampaniya yoxdur</strong><span>Bu filterə uyğun nəticə tapılmadı.</span></div>`;
    return;
  }
  list.innerHTML = campaigns.map((campaign) => {
    const date = new Date(campaign.created_at).toLocaleString("az-AZ", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
    return `<div class="history-row" data-campaign-id="${escapeHtml(campaign.id)}">
      <div class="history-main"><strong>${escapeHtml(campaign.message.slice(0, 52))}${campaign.message.length > 52 ? "…" : ""}</strong><span>${escapeHtml(date)} · ${escapeHtml(campaign.id.slice(0, 8))}</span></div>
      <div class="history-side">${renderBadge(campaign.status)}<span class="history-numbers">${campaign.sent_count} / ${campaign.total_numbers} uğurlu</span></div>
    </div>`;
  }).join("");
  list.querySelectorAll(".history-row").forEach((row) => row.addEventListener("click", () => openDetail(row.dataset.campaignId)));
}

function setValidation(result) {
  state.validNumbers = result.valid;
  const summary = $("#validation-summary");
  summary.classList.remove("hidden");
  summary.innerHTML = `<strong>${result.valid_count} nömrə hazırdır.</strong> ${result.duplicates_removed} duplicate silindi${result.invalid_count ? ` · ${result.invalid_count} səhv format` : ""}`;
  const invalidList = $("#invalid-list");
  if (result.invalid_count) {
    invalidList.classList.remove("hidden");
    invalidList.innerHTML = `<strong>Səhv nömrələr:</strong> ${result.invalid.map((item) => `${escapeHtml(item.value || "(boş)")} — ${escapeHtml(item.reason)}`).join("<br>")}`;
  } else {
    invalidList.classList.add("hidden");
    invalidList.innerHTML = "";
  }
  $("#send-btn").disabled = !state.validNumbers.length || !$("#message-input").value.trim();
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const errorBox = $("#login-error");
  errorBox.textContent = "";
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  try {
    await api("/api/auth/login", {
      method: "POST",
      body: { username: $("#username").value.trim(), password: $("#password").value },
    });
    showDashboard();
  } catch (error) {
    errorBox.textContent = parseError(error);
  } finally {
    button.disabled = false;
  }
});

$("#logout-btn").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
    state.csrf = null;
    showLogin();
    showToast("Sessiyadan təhlükəsiz çıxış edildi.", "success");
  } catch (error) { showToast(parseError(error), "error"); }
});

$("#validate-btn").addEventListener("click", async () => {
  const raw = $("#numbers-input").value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (!raw.length) {
    showToast("Əvvəlcə telefon nömrələrini daxil edin.", "error");
    return;
  }
  const button = $("#validate-btn");
  button.disabled = true;
  try {
    setValidation(await api("/api/contacts/validate", { method: "POST", body: { numbers: raw } }));
    showToast("Nömrələr yoxlanıldı.", "success");
  } catch (error) { showToast(parseError(error), "error"); }
  finally { button.disabled = false; }
});

$("#file-input").addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    // The backend performs the authoritative normalization and validation.
    const values = String(reader.result).split(/\r?\n|,/).map((value) => value.trim().replace(/^"|"$/g, "")).filter(Boolean);
    $("#numbers-input").value = values.join("\n");
    showToast(`${file.name} yükləndi. Nömrələri yoxlayın.`, "success");
  };
  reader.readAsText(file);
  event.target.value = "";
});

$("#message-input").addEventListener("input", (event) => {
  const length = event.target.value.length;
  const counter = $("#char-counter");
  counter.textContent = `${length} / 140`;
  counter.classList.toggle("warn", length >= 125);
  $("#send-btn").disabled = !state.validNumbers.length || !event.target.value.trim();
});

$("#send-btn").addEventListener("click", () => {
  if (!state.validNumbers.length) return showToast("Göndərmədən əvvəl nömrələri yoxlayın.", "error");
  $("#confirm-count").textContent = state.validNumbers.length;
  $("#confirm-message").textContent = $("#message-input").value.trim();
  $("#confirm-modal").classList.remove("hidden");
});

$("#confirm-send-btn").addEventListener("click", async () => {
  const button = $("#confirm-send-btn");
  button.disabled = true;
  try {
    const campaign = await api("/api/campaigns", {
      method: "POST",
      body: { phone_numbers: state.validNumbers, message: $("#message-input").value.trim() },
    });
    await api(`/api/campaigns/${campaign.id}/start`, { method: "POST" });
    state.activeCampaignId = campaign.id;
    $("#confirm-modal").classList.add("hidden");
    $("#send-btn").disabled = true;
    showToast("Kampaniya queue-ya əlavə edildi və başladı.", "success");
    await loadStats();
    await loadHistory();
    startProgressPolling();
  } catch (error) { showToast(parseError(error), "error"); }
  finally { button.disabled = false; }
});

function startProgressPolling() {
  if (state.progressTimer) clearInterval(state.progressTimer);
  $("#active-campaign-card").classList.remove("hidden");
  updateProgress();
  state.progressTimer = setInterval(updateProgress, 1000);
}

async function updateProgress() {
  if (!state.activeCampaignId) return;
  try {
    const progress = await api(`/api/campaigns/${state.activeCampaignId}/progress`);
    $("#active-campaign-card").classList.remove("hidden");
    $("#progress-percent").textContent = `${progress.percentage}%`;
    $("#progress-fill").style.width = `${progress.percentage}%`;
    $("#progress-total").textContent = progress.total;
    $("#progress-done").textContent = progress.sent + progress.failed;
    $("#progress-sent").textContent = progress.sent;
    $("#progress-failed").textContent = progress.failed;
    $("#progress-pending").textContent = progress.pending + progress.sending;
    $("#active-status").outerHTML = `<span id="active-status" class="badge badge-${escapeHtml(progress.status)}">${escapeHtml(statusLabel(progress.status))}</span>`;
    $("#progress-label").textContent = progress.status === "paused" ? "Göndəriş pause edilib" : progress.status === "completed" ? "Göndəriş tamamlandı" : progress.status === "stopped" ? "Göndəriş dayandırıldı" : "SMS göndərilir...";
    $("#pause-btn").textContent = progress.status === "paused" ? "▶ Resume" : "Ⅱ Pause";
    $("#pause-btn").disabled = !["running", "paused"].includes(progress.status);
    $("#stop-btn").disabled = !["running", "paused", "pending"].includes(progress.status);
    if (["completed", "stopped"].includes(progress.status)) {
      clearInterval(state.progressTimer);
      state.progressTimer = null;
      await Promise.all([loadStats(), loadHistory()]);
      if (progress.status === "completed") showToast("Kampaniya tamamlandı.", "success");
    }
  } catch (error) {
    if (!error.message.includes("Sessiya")) showToast(parseError(error), "error");
  }
}

$("#pause-btn").addEventListener("click", async () => {
  const badge = $("#active-status");
  const isPaused = badge && badge.className.includes("paused");
  try {
    await api(`/api/campaigns/${state.activeCampaignId}/${isPaused ? "resume" : "pause"}`, { method: "POST" });
    await updateProgress();
  } catch (error) { showToast(parseError(error), "error"); }
});

$("#stop-btn").addEventListener("click", async () => {
  if (!window.confirm("Bu kampaniyada yeni SMS göndərişini dayandırmaq istəyirsiniz?")) return;
  try {
    await api(`/api/campaigns/${state.activeCampaignId}/stop`, { method: "POST" });
    await updateProgress();
    showToast("Yeni SMS göndərişləri dayandırıldı.", "success");
  } catch (error) { showToast(parseError(error), "error"); }
});

async function openDetail(campaignId) {
  try {
    const campaign = await api(`/api/campaigns/${campaignId}`);
    const date = new Date(campaign.created_at).toLocaleString("az-AZ");
    $("#detail-content").innerHTML = `<div class="detail-title-row"><div><span class="section-kicker">KAMPANİYA DETALI</span><h2>${escapeHtml(campaign.id.slice(0, 13))}…</h2></div>${renderBadge(campaign.status)}</div>
      <div class="detail-meta"><span>${escapeHtml(date)}</span><span>${campaign.total_numbers} nömrə</span><span>${campaign.sent_count} uğurlu · ${campaign.failed_count} uğursuz</span></div>
      <div class="detail-message">${escapeHtml(campaign.message)}</div>
      <table class="result-table"><thead><tr><th>Nömrə</th><th>Status</th><th>Nəticə</th></tr></thead><tbody>${campaign.sms_messages.map((sms) => `<tr><td>${escapeHtml(sms.phone_number)}</td><td>${renderBadge(sms.status)}</td><td>${escapeHtml(sms.error_message || (sms.sent_at ? "Textbelt qəbul edib" : "—"))}</td></tr>`).join("")}</tbody></table>`;
    $("#detail-modal").classList.remove("hidden");
  } catch (error) { showToast(parseError(error), "error"); }
}

document.querySelectorAll("[data-close-modal]").forEach((button) => button.addEventListener("click", () => button.closest(".modal-backdrop").classList.add("hidden")));
document.querySelectorAll(".modal-backdrop").forEach((modal) => modal.addEventListener("click", (event) => { if (event.target === modal) modal.classList.add("hidden"); }));
let searchDebounce;
$("#history-search").addEventListener("input", () => { clearTimeout(searchDebounce); searchDebounce = setTimeout(loadHistory, 280); });
$("#status-filter").addEventListener("change", loadHistory);

(async function init() {
  try {
    await api("/api/auth/session");
    showDashboard();
  } catch (_) {
    showLogin();
  }
})();
