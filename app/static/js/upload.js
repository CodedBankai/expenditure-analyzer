const form = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const fileLabel = document.getElementById("file-label");
const statusEl = document.getElementById("upload-status");
const mappingCard = document.getElementById("mapping-card");
const mappingForms = document.getElementById("mapping-forms");
const submitMappingBtn = document.getElementById("submit-mapping-btn");

let pendingSessionId = null;

fileInput.addEventListener("change", () => {
  const names = Array.from(fileInput.files).map((f) => f.name).join(", ");
  fileLabel.textContent = names || "Choose CSV or Excel file(s)";
});

function setStatus(message, kind) {
  statusEl.textContent = message;
  statusEl.className = "status" + (kind ? " " + kind : "");
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!fileInput.files.length) return;

  const formData = new FormData();
  for (const f of fileInput.files) formData.append("files", f);

  setStatus("Uploading and analyzing...", "");
  try {
    const res = await fetch("/upload", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) {
      setStatus(data.detail || "Upload failed.", "error");
      return;
    }
    if (data.needs_mapping) {
      pendingSessionId = data.session_id;
      renderMappingForms(data.files_needing_mapping);
      mappingCard.classList.remove("hidden");
      setStatus("Column mapping needed — see below.", "");
      return;
    }
    setStatus(
      `Processed ${data.row_count} transactions (${data.cleaning_summary.total_dropped} rows dropped during cleaning).`,
      "success"
    );
    sessionStorage.setItem("session_id", data.session_id);
    setTimeout(() => (window.location.href = "/dashboard"), 800);
  } catch (err) {
    setStatus("Something went wrong: " + err.message, "error");
  }
});

const FIELD_OPTIONS = ["date", "description", "amount", "debit", "credit", "status", "type"];

function renderMappingForms(files) {
  mappingForms.innerHTML = "";
  files.forEach((file) => {
    const block = document.createElement("div");
    block.className = "mapping-block";
    block.dataset.filename = file.filename;

    const title = document.createElement("h3");
    title.textContent = file.filename;
    block.appendChild(title);

    FIELD_OPTIONS.forEach((field) => {
      const label = document.createElement("label");
      label.textContent = field + (field === "date" || field === "description" ? " (required)" : "");
      const select = document.createElement("select");
      select.dataset.field = field;
      const noneOpt = document.createElement("option");
      noneOpt.value = "";
      noneOpt.textContent = "-- none --";
      select.appendChild(noneOpt);
      file.columns.forEach((col) => {
        const opt = document.createElement("option");
        opt.value = col;
        opt.textContent = col;
        select.appendChild(opt);
      });
      label.appendChild(select);
      block.appendChild(label);
    });

    mappingForms.appendChild(block);
  });
}

submitMappingBtn.addEventListener("click", async () => {
  if (!pendingSessionId) return;
  const mappingByFile = {};
  document.querySelectorAll(".mapping-block").forEach((block) => {
    const filename = block.dataset.filename;
    const mapping = {};
    block.querySelectorAll("select").forEach((select) => {
      if (select.value) mapping[select.dataset.field] = select.value;
    });
    mappingByFile[filename] = mapping;
  });

  setStatus("Submitting mapping...", "");
  try {
    const res = await fetch(`/session/${pendingSessionId}/column-mapping`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(mappingByFile),
    });
    const data = await res.json();
    if (!res.ok) {
      setStatus(data.detail || "Mapping failed.", "error");
      return;
    }
    setStatus(`Processed ${data.row_count} transactions.`, "success");
    sessionStorage.setItem("session_id", pendingSessionId);
    setTimeout(() => (window.location.href = "/dashboard"), 800);
  } catch (err) {
    setStatus("Something went wrong: " + err.message, "error");
  }
});
