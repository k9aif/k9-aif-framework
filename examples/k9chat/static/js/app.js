// K9Chat — app shell: theme toggle, tabs, health check, provider settings,
// and final init wiring between SessionSidebar and MessageList. Loaded
// last so the components above are already defined.

(() => {
  const themeToggle = document.getElementById("theme-toggle");

  function applyTheme(theme) {
    document.body.setAttribute("data-theme", theme);
    themeToggle.textContent = theme === "dark" ? "🌙" : "☀️";
    localStorage.setItem("k9chat_theme", theme);
  }
  applyTheme(localStorage.getItem("k9chat_theme") || "dark");
  themeToggle.addEventListener("click", () => {
    const next = document.body.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
  });

  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("tab-chat").style.display = btn.dataset.tab === "chat" ? "flex" : "none";
      document.getElementById("tab-architecture").style.display = btn.dataset.tab === "architecture" ? "block" : "none";
    });
  });

  // ---------------- Streaming badge ----------------
  function refreshStreamBadge() {
    fetch("/chat/config").then(r => r.json()).then(cfg => {
      const dot = document.getElementById("stream-dot");
      const label = document.getElementById("badge-streaming");
      label.textContent = cfg.stream ? "ON" : "OFF";
      dot.classList.toggle("on", !!cfg.stream);
    }).catch(() => {});
  }
  refreshStreamBadge();

  // ---------------- Evaluation toggle ----------------
  function refreshEvalBadge() {
    fetch("/chat/evaluation").then(r => r.json()).then(cfg => {
      const dot   = document.getElementById("eval-dot");
      const label = document.getElementById("badge-eval");
      const wrap  = document.getElementById("badge-eval-wrap");
      const on    = !!cfg.evaluation_enabled;
      label.textContent = on ? "ON" : "OFF";
      dot.classList.toggle("on", on);
      wrap.classList.toggle("active", on);
    }).catch(() => {});
  }
  refreshEvalBadge();
  document.getElementById("badge-eval-wrap").addEventListener("click", () => {
    fetch("/chat/evaluation/toggle", { method: "POST" })
      .then(() => refreshEvalBadge())
      .catch(() => {});
  });

  // ---------------- Health check ----------------
  const healthBanner = document.getElementById("health-banner");
  function refreshHealth() {
    return fetch("/health").then(r => r.json()).then(status => {
      if (!status.ok) {
        healthBanner.style.display = "block";
        healthBanner.textContent = `⚠ ${status.error}`;
      } else {
        healthBanner.style.display = "none";
      }
      return status;
    }).catch(() => {
      healthBanner.style.display = "block";
      healthBanner.textContent = "⚠ Unable to reach K9Chat backend health check.";
    });
  }
  refreshHealth();

  // ---------------- Provider settings ----------------
  const settingsToggle = document.getElementById("settings-toggle");
  const settingsPanel = document.getElementById("settings-panel");
  const settingsProvider = document.getElementById("settings-provider");
  const settingsBaseUrl = document.getElementById("settings-base-url");
  const settingsApiKey = document.getElementById("settings-api-key");
  const settingsModel = document.getElementById("settings-model");
  const settingsFetchBtn = document.getElementById("settings-fetch-btn");
  const settingsApplyBtn = document.getElementById("settings-apply-btn");
  const settingsStatus = document.getElementById("settings-status");

  settingsToggle.addEventListener("click", () => {
    const isOpen = settingsPanel.style.display !== "none";
    settingsPanel.style.display = isOpen ? "none" : "flex";
  });

  fetch("/chat/runtime").then(r => r.json()).then(rt => {
    settingsProvider.value = rt.provider || "ollama";
    settingsBaseUrl.value = rt.base_url || "";
    settingsModel.innerHTML = `<option value="${rt.model}">${rt.model}</option>`;
  });

  settingsFetchBtn.addEventListener("click", async () => {
    settingsStatus.textContent = "Fetching models...";
    const params = new URLSearchParams({
      provider: settingsProvider.value,
      base_url: settingsBaseUrl.value,
      api_key: settingsApiKey.value,
    });
    try {
      const resp = await fetch(`/chat/models?${params.toString()}`);
      const data = await resp.json();
      if (!resp.ok) {
        settingsStatus.textContent = `⚠ ${data.detail || "Could not list models"}`;
        return;
      }
      settingsModel.innerHTML = "";
      data.models.forEach(name => {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        settingsModel.appendChild(opt);
      });
      settingsStatus.textContent = `Found ${data.models.length} model(s).`;
    } catch (err) {
      settingsStatus.textContent = "⚠ Unable to reach K9Chat backend.";
    }
  });

  settingsApplyBtn.addEventListener("click", async () => {
    const model = settingsModel.value;
    if (!model) {
      settingsStatus.textContent = "⚠ Fetch and pick a model first.";
      return;
    }
    settingsStatus.textContent = "Applying...";
    try {
      const resp = await fetch("/chat/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: settingsProvider.value,
          base_url: settingsBaseUrl.value,
          api_key: settingsApiKey.value,
          model,
        }),
      });
      const status = await resp.json();
      document.getElementById("badge-provider").textContent = status.provider;
      document.getElementById("badge-model").textContent = status.model;
      document.getElementById("badge-host").textContent = status.base_url;
      settingsStatus.textContent = status.ok ? "✓ Applied." : `⚠ Applied, but: ${status.error}`;
      await refreshHealth();
    } catch (err) {
      settingsStatus.textContent = "⚠ Failed to apply settings.";
    }
  });

  // ---------------- Init ----------------
  SessionSidebar.onSwitch = (id) => MessageList.renderHistory(id);
  const activeId = SessionSidebar.ensureActive();
  SessionSidebar.render();
  MessageList.renderHistory(activeId);
})();
