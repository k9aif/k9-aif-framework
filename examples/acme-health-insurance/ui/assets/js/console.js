// SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
// K9-AIF™ — Acme Live Console (Event Stream Only)
// Simplified: No Ollama, Kafka, or MCP status indicators.

function el(id) {
  return document.getElementById(id);
}

function logMessage(msg, cls = "log-info") {
  const log = el("consoleLog");
  if (!log) return;
  const p = document.createElement("p");
  p.className = cls;
  p.textContent = msg;
  log.appendChild(p);
  log.scrollTop = log.scrollHeight;
}

// ---------------------------------------------------------------------------
// Initialize Console Panel + WebSocket Stream
// ---------------------------------------------------------------------------
function initConsole() {
  const panel = el("consolePanel");
  const toggle = el("consoleToggle");

  // Toggle open/close for right-side console
  if (toggle && panel) {
    toggle.addEventListener("click", () => {
      panel.classList.toggle("open");
      toggle.innerHTML = panel.classList.contains("open") ? ">" : "<";
    });
  }

  // Initial startup messages
  logMessage("[Console] Initialized — awaiting events...");
  logMessage("[Console] Connecting to backend WebSocket...");

  // -----------------------------------------------------------------------
  // WebSocket Bridge (Backend → Console)
  // -----------------------------------------------------------------------
  const wsUrl = `ws://${window.location.host}/ws/console`;
  logMessage(`[Console] Event stream: ${wsUrl}`);

  try {
    const ws = new WebSocket(wsUrl);

    ws.onopen = () =>
      logMessage("[Console] ✅ Connected to backend WebSocket.", "log-success");

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        // Expected structured events from backend agents
        if (msg.agent && msg.layer && msg.event_type) {
          logMessage(`[${msg.layer}] ${msg.agent} → ${msg.event_type}`, "log-info");
        } else if (msg.message) {
          logMessage(`[Message] ${msg.message}`, "log-info");
        } else {
          logMessage(event.data, "log-info");
        }
      } catch {
        // Fallback for plain-text events
        logMessage(event.data, "log-info");
      }
    };

    ws.onclose = () =>
      logMessage("[Console] ⚠️ WebSocket connection closed.", "log-warning");
    ws.onerror = (err) =>
      logMessage(`[Console] ❌ WebSocket error: ${err.message}`, "log-error");
  } catch (e) {
    logMessage(`[Console] WebSocket initialization failed: ${e.message}`, "log-error");
  }
}

// ---------------------------------------------------------------------------
window.addEventListener("DOMContentLoaded", initConsole);