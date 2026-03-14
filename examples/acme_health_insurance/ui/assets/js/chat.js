// SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
// K9-AIF — Acme WebChat Assistant
// Clean version: plain UI, no emojis, same dynamic features.

function formatChatText(raw) {
  if (!raw) return "";
  let safe = raw.replace(/</g, "&lt;").replace(/>/g, "&gt;");
  safe = safe.replace(/(?:^|\n)(\d+)\.\s(.+)/g, "<li>$1. $2</li>");
  safe = safe.replace(/(?:^|\n)-\s(.+)/g, "<li>• $1</li>");
  if (safe.includes("<li>"))
    safe = "<ul class='list-disc ml-5 space-y-1'>" + safe + "</ul>";
  safe = safe.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  safe = safe.replace(/\n/g, "<br>");
  return safe;
}

function addMessage(text, sender = "user") {
  const chatLog = document.getElementById("chatLog");
  if (!chatLog) return;
  const div = document.createElement("div");
  div.className =
    sender === "user"
      ? "bg-blue-100 text-blue-900 p-2 rounded-lg self-end max-w-[80%]"
      : "bg-gray-100 text-gray-800 p-2 rounded-lg self-start max-w-[80%]";
  div.innerHTML = formatChatText(text);
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

// ---------------------------------------------------------------------------
// Simple loader (text-based, no emojis or animation icons)
// ---------------------------------------------------------------------------
let k9ThinkingEl = null;

function showK9Thinking() {
  const chatLog = document.getElementById("chatLog");
  if (!chatLog || k9ThinkingEl) return;

  k9ThinkingEl = document.createElement("div");
  k9ThinkingEl.className =
    "k9-typing self-start text-blue-700 font-mono text-sm italic";
  k9ThinkingEl.textContent = "K9-AIF Assistant is processing your request...";
  chatLog.appendChild(k9ThinkingEl);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function hideK9Thinking() {
  if (k9ThinkingEl && k9ThinkingEl.parentNode)
    k9ThinkingEl.parentNode.removeChild(k9ThinkingEl);
  k9ThinkingEl = null;
}

// ---------------------------------------------------------------------------
// Message send handler
// ---------------------------------------------------------------------------
async function sendMessage(msgOverride = null) {
  const chatInput = document.getElementById("chatInput");
  const msg = msgOverride || chatInput.value.trim();
  if (!msg) return;

  addMessage(msg, "user");
  chatInput.value = "";

  showK9Thinking();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg }),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);

    const data = await res.json();
    hideK9Thinking();

    // Handle dynamic plan listing
    if (data.reply_type === "plan_list") {
      addMessage(data.message || "Select an ACME Health Plan to view details:", "bot");

      const chatLog = document.getElementById("chatLog");
      const container = document.createElement("div");
      container.className = "flex flex-col space-y-2 mt-2";

      (data.plans || []).forEach((plan) => {
        const btn = document.createElement("button");
        btn.textContent = plan;
        btn.className =
          "bg-blue-700 text-white px-3 py-2 rounded-lg hover:bg-blue-800 text-sm text-left";
        btn.addEventListener("click", () => {
          addMessage(`You selected: ${plan}`, "user");
          sendMessage(`Tell me more about ${plan}`);
        });
        container.appendChild(btn);
      });

      chatLog.appendChild(container);
      chatLog.scrollTop = chatLog.scrollHeight;
      return;
    }

    // Default reply
    addMessage(data.reply || "No response from assistant.", "bot");
  } catch (err) {
    console.error("[Chat] Send failed:", err);
    hideK9Thinking();
    addMessage("Chat connection failed or server not running.", "bot");
  }
}

// ---------------------------------------------------------------------------
// Intent Buttons (plain text, no icons)
// ---------------------------------------------------------------------------
function showIntentOptions() {
  const chatLog = document.getElementById("chatLog");
  if (!chatLog) return;

  chatLog.innerHTML = `
    <div class="flex flex-col space-y-2 mt-2">
      <button class="intent-btn bg-blue-700 text-white px-3 py-2 rounded-lg hover:bg-blue-800" data-intent="health_plans">Health Plans</button>
      <button class="intent-btn bg-blue-700 text-white px-3 py-2 rounded-lg hover:bg-blue-800" data-intent="find_doctor">Find a Doctor</button>
      <button class="intent-btn bg-blue-700 text-white px-3 py-2 rounded-lg hover:bg-blue-800" data-intent="claims_support">Claims Support</button>
      <button class="intent-btn bg-blue-700 text-white px-3 py-2 rounded-lg hover:bg-blue-800" data-intent="talk_agent">Talk to Agent</button>
    </div>
  `;

  document.querySelectorAll(".intent-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const intent = e.target.getAttribute("data-intent");
      addMessage(`You selected: ${btn.textContent}`, "user");
      sendMessage(intent);
    });
  });
}

// ---------------------------------------------------------------------------
// Initialize Chat on Page Load
// ---------------------------------------------------------------------------
window.addEventListener("DOMContentLoaded", () => {
  const toggle = document.getElementById("chatToggle");
  const panel = document.getElementById("chatPanel");
  const sendBtn = document.getElementById("chatSend");
  const input = document.getElementById("chatInput");
  const closeBtn = document.getElementById("chatClose");

  panel.classList.remove("active");

  toggle?.addEventListener("click", () => {
    panel.classList.toggle("active");
    if (panel.classList.contains("active")) showIntentOptions();
  });

  closeBtn?.addEventListener("click", () => {
    panel.classList.remove("active");
  });

  if (sendBtn) sendBtn.addEventListener("click", () => sendMessage());
  if (input)
    input.addEventListener("keypress", (e) => {
      if (e.key === "Enter") sendMessage();
    });

  // Export button
  const exportBtn = document.createElement("button");
  exportBtn.textContent = "Export Chat Log";
  exportBtn.className =
    "bg-blue-700 text-white text-xs px-2 py-1 rounded m-2 hover:bg-blue-800 self-end";
  exportBtn.addEventListener("click", () => {
    const chat = document.getElementById("chatLog")?.innerText || "";
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const blob = new Blob([chat], { type: "text/plain" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `chat_${timestamp}.txt`;
    link.click();
  });
  panel.appendChild(exportBtn);
});