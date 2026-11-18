// A session started on the upload page lives in sessionStorage; a
// ?session_id=... query param is accepted as a fallback so a dashboard
// URL can be shared/deep-linked directly.
const queryParams = new URLSearchParams(window.location.search);
const querySessionId = queryParams.get("session_id");
if (querySessionId) sessionStorage.setItem("session_id", querySessionId);
const sessionId = sessionStorage.getItem("session_id");

const freqSelect = document.getElementById("freq-select");
const clearBtn = document.getElementById("clear-data-btn");
const aiConsent = document.getElementById("ai-consent");
const aiSuggestBtn = document.getElementById("ai-suggest-btn");
const aiSuggestStatus = document.getElementById("ai-suggest-status");
const evaluationConsent = document.getElementById("evaluation-consent");
const tabButtons = document.querySelectorAll(".tab-btn");
const VALID_TABS = ["spend", "vendors", "pattern", "recommendations"];

let categoryChart, timeseriesChart, dowChart, monthlyChart, creditDebitChart;
let selectedMonth = null; // 'YYYY-MM' or null (= all months)
let selectedWeek = null; // 1-4 or null

if (!sessionId) {
  document.querySelector(".container").innerHTML =
    '<p>No active session found. <a href="/">Go upload a statement</a>.</p>';
} else {
  loadUncategorized();
  loadAnalysis();
}

function activateTab(tabName) {
  const btn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
  if (!btn) return;
  tabButtons.forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
  document.getElementById(`tab-${tabName}`).classList.remove("hidden");
  freqSelect.disabled = tabName !== "spend";
  // Charts drawn while their tab was display:none get a zero-size canvas;
  // resize on reveal so they actually paint.
  [categoryChart, timeseriesChart, dowChart, monthlyChart, creditDebitChart].forEach((c) => c && c.resize());
}

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});
freqSelect.disabled = false; // spend tab is active by default

const initialTab = window.location.hash.replace("#", "");
if (VALID_TABS.includes(initialTab)) activateTab(initialTab);

freqSelect.addEventListener("change", loadAnalysis);

clearBtn.addEventListener("click", async () => {
  if (!confirm("This will permanently delete your uploaded data from the server. Continue?")) return;
  clearBtn.disabled = true;
  try {
    const res = await fetch(`/session/${sessionId}`, { method: "DELETE" });
    if (!res.ok && res.status !== 404) {
      throw new Error(`Server responded with ${res.status}`);
    }
  } catch (err) {
    alert("Couldn't reach the server to clear your data: " + err.message);
    clearBtn.disabled = false;
    return;
  }
  sessionStorage.removeItem("session_id");
  window.location.href = "/";
});

aiConsent.addEventListener("change", () => {
  aiSuggestBtn.disabled = !aiConsent.checked;
  if (!aiConsent.checked) aiSuggestStatus.textContent = "";
});

aiSuggestBtn.addEventListener("click", async () => {
  if (!aiConsent.checked || !sessionId) return;
  aiSuggestBtn.disabled = true;
  aiSuggestStatus.className = "status";
  aiSuggestStatus.textContent = "Requesting suggestions...";
  try {
    const res = await fetch(`/session/${sessionId}/ai-suggestions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ share_redacted_descriptions: true }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "AI suggestions are unavailable.");
    const selects = Array.from(document.querySelectorAll("#uncategorized-list select"));
    let suggested = 0;
    data.suggestions.forEach(({ vendor, category }) => {
      const select = selects.find((item) => item.dataset.vendor === vendor);
      if (!select) return;
      const row = select.parentElement;
      const oldNote = row.querySelector(".suggestion-note");
      if (oldNote) oldNote.remove();
      const note = document.createElement("span");
      note.className = "suggestion-note";
      if (category === "unsure") {
        note.textContent = "AI unsure — choose manually";
      } else if (Array.from(select.options).some((option) => option.value === category)) {
        select.value = category;
        note.textContent = "AI suggestion — review before saving";
        suggested += 1;
      }
      row.appendChild(note);
    });
    aiSuggestStatus.textContent = `${suggested} suggestions filled in. Review them, then click Save. ${data.remaining_count || 0} descriptions were beyond this batch.`;
  } catch (err) {
    aiSuggestStatus.className = "status error";
    aiSuggestStatus.textContent = `${err.message} You can still categorize manually.`;
  } finally {
    aiSuggestBtn.disabled = !aiConsent.checked;
  }
});

async function loadUncategorized() {
  const res = await fetch(`/session/${sessionId}/uncategorized`);
  if (!res.ok) return;
  const data = await res.json();
  const panel = document.getElementById("uncategorized-panel");
  const list = document.getElementById("uncategorized-list");
  if (data.uncategorized_count === 0) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  list.innerHTML = "";
  const categories = data.default_categories;

  data.vendors.forEach((vendor) => {
    const row = document.createElement("div");
    row.className = "vendor-cat-row";
    const label = document.createElement("span");
    label.textContent = vendor;
    const select = document.createElement("select");
    select.dataset.vendor = vendor;
    const noneOpt = document.createElement("option");
    noneOpt.value = "";
    noneOpt.textContent = "Select category...";
    select.appendChild(noneOpt);
    categories.forEach((cat) => {
      const opt = document.createElement("option");
      opt.value = cat;
      opt.textContent = cat;
      select.appendChild(opt);
    });
    row.appendChild(label);
    row.appendChild(select);
    list.appendChild(row);
  });

  const saveBtn = document.createElement("button");
  saveBtn.textContent = "Save";
  saveBtn.style.marginTop = "12px";
  saveBtn.addEventListener("click", async () => {
    const mappings = {};
    list.querySelectorAll("select").forEach((s) => {
      if (s.value) mappings[s.dataset.vendor] = s.value;
    });
    const res = await fetch(`/session/${sessionId}/categorize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mappings, new_categories: [], keep_evaluation_examples: evaluationConsent.checked }),
    });
    if (!res.ok) {
      aiSuggestStatus.className = "status error";
      aiSuggestStatus.textContent = "Could not save categories. Please try again.";
      return;
    }
    aiSuggestStatus.textContent = "";
    loadUncategorized();
    loadAnalysis();
  });
  list.appendChild(saveBtn);
}

async function loadAnalysis() {
  const freq = freqSelect.value;
  const params = new URLSearchParams({ freq });
  if (selectedMonth) params.set("month", selectedMonth);
  if (selectedWeek) params.set("week", selectedWeek);
  const res = await fetch(`/session/${sessionId}/analysis?${params.toString()}`);
  if (!res.ok) return;
  const data = await res.json();

  document.getElementById("empty-state").classList.toggle("hidden", !data.empty);
  document.getElementById("dashboard-body").classList.toggle("hidden", data.empty);
  if (data.empty) return;

  renderCleaningSummary(data.cleaning_summary);
  renderCategoryChart(data.category_totals);
  renderTimeseriesChart(data.time_series);
  renderVendorLists(data.vendor_totals);
  renderMonthWeekChips(data.available_months);
  renderDowChart(data.day_of_week);
  renderMonthlyChart(data.monthly_totals);
  renderCreditDebit(data.credit_vs_debit);
  renderRecurring(data.recurring);
  renderRecommendations(data.recommendations);
}

function renderCleaningSummary(stats) {
  const el = document.getElementById("cleaning-summary");
  if (!stats) { el.innerHTML = ""; return; }
  el.innerHTML = `<strong>${stats.rows_out}</strong> transactions analyzed — <strong>${stats.total_dropped}</strong> rows removed during cleaning (bad status: ${stats.dropped.bad_status}, null/zero amount: ${stats.dropped.null_or_zero_amount}, unparseable date: ${stats.dropped.unparseable_date}).`;
}

const CHART_COLORS = ["#8ec5e8", "#a8d9b8", "#f0c987", "#e8a3a3", "#c9b3e8", "#8fd0c9", "#e8c3d9", "#b8c98e"];

function renderCategoryChart(totals) {
  const ctx = document.getElementById("category-chart");
  const labels = totals.map((c) => c.category);
  const values = totals.map((c) => c.total);
  if (categoryChart) categoryChart.destroy();
  categoryChart = new Chart(ctx, {
    type: "pie",
    data: { labels, datasets: [{ data: values, backgroundColor: CHART_COLORS }] },
  });
}

function renderTimeseriesChart(series) {
  const ctx = document.getElementById("timeseries-chart");
  const labels = series.map((s) => s.txn_date);
  const values = series.map((s) => s.total);
  if (timeseriesChart) timeseriesChart.destroy();
  timeseriesChart = new Chart(ctx, {
    type: "line",
    data: { labels, datasets: [{ label: "Spend", data: values, borderColor: "#5fa8d8", backgroundColor: "#8ec5e855", tension: 0.2, fill: true }] },
  });
}

function renderVendorLists(vendorTotals) {
  const byAmount = document.getElementById("vendor-by-amount");
  byAmount.innerHTML = "";
  vendorTotals.top_by_amount.forEach((v) => {
    const div = document.createElement("div");
    div.className = "vendor-item";
    div.textContent = `${v.description} — ${v.total.toFixed(2)}`;
    byAmount.appendChild(div);
  });

  const byCount = document.getElementById("vendor-by-count");
  byCount.innerHTML = "";
  vendorTotals.top_by_count.forEach((v) => {
    const div = document.createElement("div");
    div.className = "vendor-item";
    div.textContent = `${v.description} — ${v.transaction_count} txns`;
    byCount.appendChild(div);
  });
}

function renderMonthWeekChips(months) {
  const monthChipsEl = document.getElementById("month-chips");
  const weekChipsEl = document.getElementById("week-chips");

  // Only show month chips when the data spans more than one calendar month.
  if (months.length > 1) {
    monthChipsEl.classList.remove("hidden");
    monthChipsEl.innerHTML = "";
    const allChip = makeChip("All months", selectedMonth === null, () => {
      selectedMonth = null;
      selectedWeek = null;
      loadAnalysis();
    });
    monthChipsEl.appendChild(allChip);
    months.forEach((m) => {
      const chip = makeChip(m.label, selectedMonth === m.key, () => {
        selectedMonth = m.key;
        selectedWeek = null;
        loadAnalysis();
      });
      monthChipsEl.appendChild(chip);
    });
  } else {
    monthChipsEl.classList.add("hidden");
    if (months.length === 1) selectedMonth = months[0].key;
  }

  // Week chips only make sense once a specific month is in view.
  if (selectedMonth) {
    weekChipsEl.classList.remove("hidden");
    weekChipsEl.innerHTML = "";
    const allWeeksChip = makeChip("All weeks", selectedWeek === null, () => {
      selectedWeek = null;
      loadAnalysis();
    });
    weekChipsEl.appendChild(allWeeksChip);
    [1, 2, 3, 4].forEach((w) => {
      const chip = makeChip(`W${w}`, selectedWeek === w, () => {
        selectedWeek = w;
        loadAnalysis();
      });
      weekChipsEl.appendChild(chip);
    });
  } else {
    weekChipsEl.classList.add("hidden");
  }

  const label = document.getElementById("pattern-filter-label");
  const monthLabel = selectedMonth ? (months.find((m) => m.key === selectedMonth)?.label ?? selectedMonth) : "all months";
  const weekLabel = selectedWeek ? `, week ${selectedWeek}` : "";
  label.textContent = `Showing: ${monthLabel}${weekLabel}`;
}

function makeChip(text, active, onClick) {
  const chip = document.createElement("span");
  chip.className = "chip" + (active ? " active" : "");
  chip.textContent = text;
  chip.addEventListener("click", onClick);
  return chip;
}

function renderDowChart(dow) {
  const ctx = document.getElementById("dow-chart");
  const labels = dow.map((d) => d.day_of_week);
  const values = dow.map((d) => d.total);
  if (dowChart) dowChart.destroy();
  dowChart = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ label: "Spend", data: values, backgroundColor: "#a8d9b8" }] },
  });
}

function renderMonthlyChart(monthly) {
  const ctx = document.getElementById("monthly-chart");
  const labels = monthly.map((m) => m.label);
  const values = monthly.map((m) => m.total);
  if (monthlyChart) monthlyChart.destroy();
  monthlyChart = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ label: "Spend", data: values, backgroundColor: "#8ec5e8" }] },
  });
}

function renderCreditDebit(cd) {
  const ctx = document.getElementById("credit-debit-chart");
  if (creditDebitChart) creditDebitChart.destroy();
  creditDebitChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: ["Credit", "Debit"],
      datasets: [{ data: [cd.credit_total, cd.debit_total], backgroundColor: ["#a8d9b8", "#e8a3a3"] }],
    },
    options: { plugins: { legend: { display: false } } },
  });

  const tbody = document.getElementById("credit-debit-table");
  tbody.innerHTML = `
    <tr><td>Credit</td><td>${cd.credit_total.toFixed(2)}</td><td>${cd.credit_count}</td></tr>
    <tr><td>Debit</td><td>${cd.debit_total.toFixed(2)}</td><td>${cd.debit_count}</td></tr>
    <tr><td>Net</td><td>${cd.net.toFixed(2)}</td><td></td></tr>
  `;
}

function renderRecurring(recurring) {
  const el = document.getElementById("recurring-list");
  el.innerHTML = "";
  if (!recurring.length) {
    el.innerHTML = "<p>No recurring charges detected.</p>";
    return;
  }
  recurring.forEach((r) => {
    const div = document.createElement("div");
    div.className = "recur-item";
    const confidence = r.confidence === "high" ? "" : " (possible, low confidence)";
    div.textContent = `${r.vendor}: ~${r.average_amount} every ~${r.avg_interval_days ?? "?"} days, ${r.occurrences} occurrences${confidence}`;
    el.appendChild(div);
  });
}

function renderRecommendations(recs) {
  const el = document.getElementById("recommendations-list");
  el.innerHTML = "";
  if (!recs.length) {
    el.innerHTML = "<p>Nothing stands out right now — looking good.</p>";
    return;
  }
  recs.forEach((r) => {
    const div = document.createElement("div");
    div.className = "rec-item";
    div.textContent = r.message;
    el.appendChild(div);
  });
}
