/* K9-AIF RFP Analyzer — Web UI */

let selectedFile = null;

function toggleTheme() {
  const dark = document.body.classList.toggle("dark");
  localStorage.setItem("rfp_theme", dark ? "1" : "0");
  document.getElementById("theme-btn").textContent = dark ? "☀️" : "🌙";
}

(function initTheme() {
  if (localStorage.getItem("rfp_theme") === "1") {
    document.body.classList.add("dark");
    document.getElementById("theme-btn").textContent = "☀️";
  }
})();

function fileSelected(input) {
  if (input.files.length > 0) {
    selectedFile = input.files[0];
    document.getElementById("file-name").textContent = selectedFile.name;
  }
}

function loadSample() {
  selectedFile = null;
  document.getElementById("file-name").textContent = "sample_rfp.md (built-in)";
}

function setStepStatus(step, status) {
  const el = document.getElementById("step-" + step);
  const statusEl = document.getElementById("status-" + step);
  el.className = "step";
  if (status === "running") { el.classList.add("active"); statusEl.textContent = "running..."; }
  else if (status === "done") { el.classList.add("done"); statusEl.textContent = "done"; }
  else if (status === "error") { el.classList.add("error"); statusEl.textContent = "error"; }
  else { statusEl.textContent = "waiting"; }
}

function resetSteps() {
  ["preprocess", "embed", "retrieve", "analyze"].forEach(s => setStepStatus(s, "waiting"));
}

function renderChunks(chunks) {
  const list = document.getElementById("chunk-list");
  const count = document.getElementById("chunk-count");
  count.textContent = chunks.length;
  list.innerHTML = "";
  chunks.forEach((c, i) => {
    const div = document.createElement("div");
    div.className = "chunk-item";
    div.innerHTML = `
      <div class="chunk-section">${esc(c.section || "Section " + i)}</div>
      <div class="chunk-text">${esc(c.text || "")}</div>
      <div class="chunk-meta">#${c.index} · ~${c.token_estimate} tokens</div>
    `;
    list.appendChild(div);
  });
}

function renderOutput(data) {
  const area = document.getElementById("output-area");
  const steps = data.steps || [];
  const analyzeStep = steps.find(s => s.step === "analyze");
  const retrieveStep = steps.find(s => s.step === "retrieve");
  const preprocessStep = steps.find(s => s.step === "preprocess");
  const embedStep = steps.find(s => s.step === "embed");

  let html = `<div class="output-card">`;
  html += `<div class="output-title">RFP Analysis Result</div>`;
  html += `<div class="output-meta">`;
  html += `<span>Query: ${esc(data.query || "")}</span>`;
  if (preprocessStep) html += `<span>Chunks: ${preprocessStep.result.chunk_count}</span>`;
  if (embedStep) html += `<span>Indexed: ${embedStep.result.indexed}</span>`;
  if (retrieveStep) html += `<span>Retrieved: ${retrieveStep.result.count}</span>`;
  if (analyzeStep) html += `<span>Model: ${esc(analyzeStep.result.model_used || "N/A")}</span>`;
  html += `</div>`;

  if (analyzeStep) {
    html += `<div class="output-body">${esc(analyzeStep.result.output || "No output")}</div>`;
  }

  if (retrieveStep && retrieveStep.result.retrieved && retrieveStep.result.retrieved.length > 0) {
    html += `<div class="retrieved-section">`;
    html += `<div class="retrieved-title">Retrieved Chunks (${retrieveStep.result.count})</div>`;
    retrieveStep.result.retrieved.forEach(r => {
      html += `<div class="retrieved-chunk">
        <span class="retrieved-score">score: ${(r.score || 0).toFixed(3)}</span><br>
        ${esc(r.text || "")}
      </div>`;
    });
    html += `</div>`;
  }

  html += `</div>`;
  area.innerHTML = html;
}

async function runPipeline() {
  const query = document.getElementById("query-input").value.trim();
  if (!query) return;

  const btn = document.getElementById("run-btn");
  const runText = document.getElementById("run-text");
  const spinner = document.getElementById("run-spinner");

  btn.disabled = true;
  runText.style.display = "none";
  spinner.style.display = "inline";
  resetSteps();
  document.getElementById("output-area").innerHTML = '<div class="empty-state">Processing...</div>';

  try {
    const formData = new FormData();
    if (selectedFile) formData.append("file", selectedFile);
    formData.append("query", query);

    // Run full pipeline
    setStepStatus("preprocess", "running");

    const resp = await fetch("/api/run", { method: "POST", body: formData });
    const data = await resp.json();

    // Update step statuses
    (data.steps || []).forEach(s => {
      setStepStatus(s.step, "done");
    });

    // Render chunks in left panel
    const preprocessStep = (data.steps || []).find(s => s.step === "preprocess");
    if (preprocessStep && preprocessStep.result.chunks) {
      renderChunks(preprocessStep.result.chunks);
    }

    // Render output
    renderOutput(data);

  } catch (err) {
    document.getElementById("output-area").innerHTML = `<div class="empty-state" style="color:var(--red)">Error: ${esc(err.message)}</div>`;
    ["preprocess", "embed", "retrieve", "analyze"].forEach(s => setStepStatus(s, "error"));
  } finally {
    btn.disabled = false;
    runText.style.display = "inline";
    spinner.style.display = "none";
  }
}

function esc(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}
