// K9Chat — ArchitectureTrace component
// Builds a per-request execution trace shown in the Architecture tab.
// Purely client-side, reconstructed from data already returned by /chat
// and /chat/stream — no new backend endpoint. Each entry is a flat list
// of {label, detail} steps; future event sources (governance/guard
// checks, RAG retrieval, squad/agent fan-out, token counts,
// validation-loop iterations) can push additional steps without
// changing this shape.

const ArchitectureTrace = (() => {
  const traceEl = document.getElementById("architecture-trace");
  let lastTrace = null;

  function truncate(text, n) {
    if (!text) return "—";
    return text.length > n ? text.slice(0, n) + "…" : text;
  }

  function record({ input, provider, model, base_url, elapsed_ms, mode }) {
    lastTrace = {
      timestamp: Date.now(),
      steps: [
        { label: "User Input", detail: truncate(input, 60) },
        { label: "Presentation Layer", detail: `FastAPI + Jinja2 (${mode === "stream" ? "/chat/stream SSE" : "/chat"})` },
        { label: "Router", detail: "K9ModelRouter (weighted capability scoring)" },
        { label: "Orchestrator", detail: "ChatAgent (single-agent squad)" },
        { label: "LLM Factory", detail: "LLMFactory.get(\"general\")" },
        { label: "Provider Adapter", detail: provider || "—" },
        { label: "Model", detail: `${model || "—"} @ ${base_url || "—"}` },
        { label: "Response", detail: elapsed_ms != null ? `${elapsed_ms} ms` : "—" },
      ],
    };
    render();
  }

  function render() {
    if (!traceEl) return;

    if (!lastTrace) {
      traceEl.innerHTML = `<p class="trace-empty">Send a message to see its live execution trace here.</p>`;
      return;
    }

    traceEl.innerHTML = "";
    const heading = document.createElement("p");
    heading.className = "trace-timestamp";
    heading.textContent = `Last request — ${new Date(lastTrace.timestamp).toLocaleTimeString()}`;
    traceEl.appendChild(heading);

    lastTrace.steps.forEach((step, i) => {
      const row = document.createElement("div");
      row.className = "trace-step";

      const label = document.createElement("div");
      label.className = "trace-label";
      label.textContent = step.label;

      const detail = document.createElement("div");
      detail.className = "trace-detail";
      detail.textContent = step.detail;

      row.appendChild(label);
      row.appendChild(detail);
      traceEl.appendChild(row);

      if (i < lastTrace.steps.length - 1) {
        const arrow = document.createElement("div");
        arrow.className = "trace-arrow";
        arrow.textContent = "↓";
        traceEl.appendChild(arrow);
      }
    });
  }

  render(); // initial empty state

  return { record, render };
})();
