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

  // Sidebar collapse -- more canvas for the chat/telemetry columns.
  // Persisted like theme so it doesn't reset on reload.
  const appShell = document.querySelector(".app-shell");
  const sidebarCollapseBtn = document.getElementById("sidebar-collapse-btn");
  const sidebarExpandBtn = document.getElementById("sidebar-expand-btn");

  function setSidebarCollapsed(collapsed) {
    appShell.classList.toggle("sidebar-collapsed", collapsed);
    sidebarExpandBtn.style.display = collapsed ? "block" : "none";
    localStorage.setItem("k9chat_sidebar_collapsed", collapsed ? "1" : "0");
  }
  setSidebarCollapsed(localStorage.getItem("k9chat_sidebar_collapsed") === "1");
  sidebarCollapseBtn.addEventListener("click", () => setSidebarCollapsed(true));
  sidebarExpandBtn.addEventListener("click", () => setSidebarCollapsed(false));

  // Projects list -- collapsed by default (not just "last state"), so
  // project names (which can be sensitive -- e.g. an owner's own private
  // project titles) aren't shown on-screen just by opening the app.
  const projectsBlock = document.querySelector(".projects-block");
  const projectsToggleBtn = document.getElementById("projects-toggle-btn");
  const projectList = document.getElementById("project-list");

  function setProjectsExpanded(expanded) {
    projectsBlock.classList.toggle("expanded", expanded);
    projectList.style.display = expanded ? "flex" : "none";
    localStorage.setItem("k9chat_projects_expanded", expanded ? "1" : "0");
  }
  setProjectsExpanded(localStorage.getItem("k9chat_projects_expanded") === "1");
  projectsToggleBtn.addEventListener("click", () => {
    setProjectsExpanded(!projectsBlock.classList.contains("expanded"));
  });

  // Two independent fun dials -- style/register only (see chat_agent.py's
  // UNHINGED_INSTRUCTIONS/PROFANITY_INSTRUCTIONS). Read directly off the
  // slider elements by chat_input.js at send time, same pattern as
  // ProjectPanel.activeProjectId -- no separate state module needed for
  // two persisted numbers.
  const TONE_COLORS = ["#6b7280", "#22c55e", "#eab308", "#f97316", "#ef4444"];

  function wireToneSlider(sliderId, labelId, names, storageKey, defaultLevel = 0) {
    const slider = document.getElementById(sliderId);
    const label = document.getElementById(labelId);

    function apply(level) {
      slider.value = level;
      label.textContent = names[level];
      label.style.color = TONE_COLORS[level];
      localStorage.setItem(storageKey, String(level));
    }
    const stored = localStorage.getItem(storageKey);
    apply(stored !== null ? Number(stored) : defaultLevel);
    slider.addEventListener("input", () => apply(Number(slider.value)));
  }

  // Drives profanity under the hood too, same level, no separate control --
  // chat_input.js's send()/sendStreaming() mirror this slider's value into
  // profanity_level directly rather than reading a second DOM element.
  wireToneSlider(
    "unhinged-slider", "unhinged-label",
    ["Off", "Casual", "Blunt", "Unhinged", "EXTREME"], "k9chat_unhinged",
  );
  // Real prompt instruction (see chat_agent.py's LENGTH_INSTRUCTIONS) --
  // defaults to Normal (1), not the other two dials' Off (0), since
  // "Normal" here means "no injected instruction," not "disabled."
  wireToneSlider(
    "length-slider", "length-label",
    ["Short", "Normal", "Long"], "k9chat_length", 1,
  );

  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("tab-chat").style.display = btn.dataset.tab === "chat" ? "flex" : "none";
      document.getElementById("tab-architecture").style.display = btn.dataset.tab === "architecture" ? "block" : "none";
    });
  });

  // ---------------- Streaming toggle ----------------
  function refreshStreamBadge() {
    fetch("/chat/config").then(r => r.json()).then(cfg => {
      const dot = document.getElementById("stream-dot");
      const label = document.getElementById("badge-streaming");
      const on = !!cfg.stream;
      label.textContent = on ? "ON" : "OFF";
      dot.classList.toggle("on", on);
      ChatInput.setStreamEnabled(on);
    }).catch(() => {});
  }
  refreshStreamBadge();
  document.getElementById("badge-stream-wrap").addEventListener("click", () => {
    fetch("/chat/stream/toggle", { method: "POST" })
      .then(() => refreshStreamBadge())
      .catch(() => {});
  });

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

  // ---------------- Correction auto-learning toggle ----------------
  function refreshLearnBadge() {
    fetch("/chat/learning").then(r => r.json()).then(cfg => {
      const dot   = document.getElementById("learn-dot");
      const label = document.getElementById("badge-learn");
      const wrap  = document.getElementById("badge-learn-wrap");
      const on    = !!cfg.learning_enabled;
      label.textContent = on ? "ON" : "OFF";
      dot.classList.toggle("on", on);
      wrap.classList.toggle("active", on);
    }).catch(() => {});
  }
  refreshLearnBadge();
  document.getElementById("badge-learn-wrap").addEventListener("click", () => {
    fetch("/chat/learning/toggle", { method: "POST" })
      .then(() => refreshLearnBadge())
      .catch(() => {});
  });

  // ---------------- FAQ retrieve-then-rerank shortcut toggle ----------------
  function refreshFaqBadge() {
    fetch("/chat/faq-shortcut").then(r => r.json()).then(cfg => {
      const dot   = document.getElementById("faq-dot");
      const label = document.getElementById("badge-faq");
      const wrap  = document.getElementById("badge-faq-wrap");
      const on    = !!cfg.faq_shortcut_enabled;
      label.textContent = on ? "ON" : "OFF";
      dot.classList.toggle("on", on);
      wrap.classList.toggle("active", on);
    }).catch(() => {});
  }
  refreshFaqBadge();
  document.getElementById("badge-faq-wrap").addEventListener("click", () => {
    fetch("/chat/faq-shortcut/toggle", { method: "POST" })
      .then(() => refreshFaqBadge())
      .catch(() => {});
  });

  // ---------------- Framework Mode toggle ----------------
  // Same backend flag/endpoint as before (internet_search_enabled), shown
  // inverted -- "Framework Mode: ON" means internet search is OFF (scoped
  // to K9-AIF/K9X, zero internet dependency), and "OFF" means general
  // questions + live search are allowed. Ravi's framing: the badge should
  // read as "am I restricted to the framework," not "is search on."
  function refreshInternetBadge() {
    fetch("/chat/internet-search").then(r => r.json()).then(cfg => {
      const dot   = document.getElementById("internet-dot");
      const label = document.getElementById("badge-internet");
      const wrap  = document.getElementById("badge-internet-wrap");
      const frameworkModeOn = !cfg.internet_search_enabled;
      label.textContent = frameworkModeOn ? "ON" : "OFF";
      dot.classList.toggle("on", frameworkModeOn);
      wrap.classList.toggle("active", frameworkModeOn);
      wrap.title = cfg.framework_mode_locked
        ? "Framework Mode is locked for this deployment (K9CHAT_FRAMEWORK_MODE_LOCKED) -- cannot be toggled off"
        : "Click to toggle Framework Mode. ON = scoped to K9-AIF/K9X only, no internet access. OFF = general questions answered via live web search (self-hosted SearxNG)";
      wrap.style.cursor = cfg.framework_mode_locked ? "not-allowed" : "pointer";

      // Read-only mirror of Framework Mode, positioned in row 2 (left of
      // "ollama") rather than a second interactive badge in row 1 --
      // Framework Mode above is the actual control.
      const statusDot = document.getElementById("internet-status-dot");
      const statusLabel = document.getElementById("badge-internet-status");
      if (statusDot && statusLabel) {
        statusLabel.textContent = cfg.internet_search_enabled ? "ON" : "OFF";
        statusDot.classList.toggle("on", cfg.internet_search_enabled);
      }

      // Unhinged/Profanity only work when Framework Mode is OFF -- same
      // rule server-side (chat.py's _clamp_tone_for_framework_mode), this
      // just keeps the slider from misleadingly looking usable when it
      // isn't. Greyed out, not hidden -- still shows the user the dial
      // exists and why it's inert right now.
      const unhingedSlider = document.getElementById("unhinged-slider");
      if (unhingedSlider) {
        unhingedSlider.disabled = frameworkModeOn;
        unhingedSlider.title = frameworkModeOn
          ? "Unavailable while Framework Mode is ON (scoped, professional tone only)"
          : "";
        unhingedSlider.closest(".fun-group")?.classList.toggle("fun-group-disabled", frameworkModeOn);
      }
    }).catch(() => {});
  }
  refreshInternetBadge();
  document.getElementById("badge-internet-wrap").addEventListener("click", () => {
    fetch("/chat/internet-search/toggle", { method: "POST" })
      .then(() => refreshInternetBadge())
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

  // Curated header dropdown (.env-driven, see Architecture tab) -- distinct
  // from the Provider Settings panel's free-form "fetch every model this
  // host has pulled" picker below. setActiveModel() keeps both in sync:
  // if Settings applies a model that isn't in the curated list, it's added
  // as a one-off "(custom)" option rather than silently failing to show.
  const modelPicker = document.getElementById("model-picker");
  let lastGoodModel = modelPicker ? modelPicker.value : null;

  function setActiveModel(model) {
    if (!modelPicker || !model) return;
    let opt = Array.from(modelPicker.options).find(o => o.value === model);
    if (!opt) {
      opt = document.createElement("option");
      opt.value = model;
      opt.textContent = model + " (custom)";
      modelPicker.appendChild(opt);
    }
    modelPicker.value = model;
    lastGoodModel = model;
  }

  if (modelPicker) {
    modelPicker.addEventListener("change", async () => {
      const model = modelPicker.value;
      const provider = document.getElementById("badge-provider").textContent;
      const baseUrl = document.getElementById("badge-host").textContent;
      // The switch now blocks until the model is genuinely loaded (see
      // apply_settings()'s warm-up call) -- for a large model that's real
      // seconds, not instant, so show that plainly rather than leaving
      // the dropdown looking frozen/unresponsive.
      modelPicker.disabled = true;
      const prevTitle = modelPicker.title;
      modelPicker.title = `Loading ${model}...`;
      try {
        const resp = await fetch("/chat/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider, base_url: baseUrl, model }),
        });
        if (resp.status === 429) {
          const err = await resp.json();
          alert(err.detail || "Model was switched too recently — try again shortly.");
          modelPicker.value = lastGoodModel;
          return;
        }
        const status = await resp.json();
        document.getElementById("badge-provider").textContent = status.provider;
        document.getElementById("badge-host").textContent = status.base_url;
        setActiveModel(status.model);
        if (!status.ok) {
          alert(`Switched, but health check failed: ${status.error || "unknown error"}`);
        } else if (status.warmed_up === false) {
          alert(`Model is pulled but the warm-up call failed: ${status.warmup_error || "unknown error"}`);
        }
        await refreshHealth();
      } catch (err) {
        alert("Could not switch model — request failed.");
        modelPicker.value = lastGoodModel;
      } finally {
        modelPicker.disabled = false;
        modelPicker.title = prevTitle;
      }
    });
  }

  fetch("/chat/runtime").then(r => r.json()).then(rt => {
    settingsProvider.value = rt.provider || "ollama";
    settingsBaseUrl.value = rt.base_url || "";
    settingsModel.innerHTML = `<option value="${rt.model}">${rt.model}</option>`;
    setActiveModel(rt.model);
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
      setActiveModel(status.model);
      document.getElementById("badge-host").textContent = status.base_url;
      settingsStatus.textContent = status.ok ? "✓ Applied." : `⚠ Applied, but: ${status.error}`;
      await refreshHealth();
    } catch (err) {
      settingsStatus.textContent = "⚠ Failed to apply settings.";
    }
  });

  // ---------------- Waitlist widget ----------------
  // Polled, not pushed -- only shown once real concurrent load exists
  // (active > 2), so it never nags a single visitor chatting alone.
  const waitlistWidget = document.getElementById("waitlist-widget");

  async function pollQueueStatus() {
    try {
      const resp = await fetch("/chat/queue-status");
      const s = await resp.json();
      if (s.active > 2) {
        const waitingPart = s.waiting > 0 ? ` · ${s.waiting} in queue` : "";
        waitlistWidget.innerHTML =
          `<span class="dot"></span>${s.active} chats running right now${waitingPart}`;
        waitlistWidget.style.display = "flex";
      } else {
        waitlistWidget.style.display = "none";
      }
    } catch (err) {
      waitlistWidget.style.display = "none";
    }
  }
  if (waitlistWidget) {
    pollQueueStatus();
    setInterval(pollQueueStatus, 4000);
  }

  // ---------------- Telemetry panel ----------------
  // Real numbers from gpu_telemetry.py (proxying the actual nvidia-smi
  // server) -- same source queue_control.py's thermal guard checks
  // against, not a separate/decorative readout. 2s poll matches the
  // standalone RTX-5090 dashboard's own cadence.
  const telemetryBody = document.getElementById("telemetry-body");
  const telemetryBanner = document.getElementById("telemetry-throttle-banner");

  function telemetryRow(label, value, pct, level) {
    const cls = level ? ` ${level}` : "";
    const bar = pct != null
      ? `<div class="telemetry-bar-track"><div class="telemetry-bar-fill" style="width:${Math.min(100, Math.max(0, pct))}%"></div></div>`
      : "";
    return `<div class="telemetry-row${cls}"><div class="label">${label}</div><div class="value">${value}</div>${bar}</div>`;
  }

  async function pollTelemetry() {
    if (!telemetryBody) return;
    try {
      const resp = await fetch("/telemetry");
      const d = await resp.json();
      if (d.error || d.temperatureC == null) {
        telemetryBody.innerHTML = '<div class="telemetry-offline">Telemetry server unreachable</div>';
        telemetryBanner.style.display = "none";
        return;
      }

      const limit = d.temp_limit_c ?? 85;
      const temp = d.temperatureC;
      const tempLevel = temp >= limit ? "critical" : temp >= limit - 10 ? "warn" : "";
      const gpuLoadLevel = d.gpuUtilizationPct >= 90 ? "warn" : "";
      const memPct = d.memoryTotalMiB ? (d.memoryUsedMiB / d.memoryTotalMiB) * 100 : null;

      let html = "";
      html += telemetryRow("GPU Load", `${d.gpuUtilizationPct ?? "--"}%`, d.gpuUtilizationPct, gpuLoadLevel);
      html += telemetryRow("GPU Temperature", `${temp}°C`, (temp / limit) * 100, tempLevel);
      html += telemetryRow(
        "GPU Memory",
        `${d.memoryUsedMiB ?? "--"} / ${d.memoryTotalMiB ?? "--"} MiB`,
        memPct,
        memPct != null && memPct >= 90 ? "warn" : "",
      );
      if (d.cpuLoadPct != null) {
        html += telemetryRow("CPU Load", `${d.cpuLoadPct}%`, d.cpuLoadPct, d.cpuLoadPct >= 90 ? "warn" : "");
      }
      if (d.cpuMemory) {
        const cpuMemPct = d.cpuMemory.totalMiB ? (d.cpuMemory.usedMiB / d.cpuMemory.totalMiB) * 100 : null;
        html += telemetryRow(
          "CPU Memory",
          `${d.cpuMemory.usedMiB} / ${d.cpuMemory.totalMiB} MiB`,
          cpuMemPct,
          cpuMemPct != null && cpuMemPct >= 90 ? "warn" : "",
        );
      }
      if (d.cpuTempC != null) {
        html += telemetryRow("CPU Temperature", `${d.cpuTempC}°C`, null, "");
      }

      telemetryBody.innerHTML = html;
      telemetryBanner.style.display = temp >= limit ? "block" : "none";
    } catch (err) {
      telemetryBody.innerHTML = '<div class="telemetry-offline">Telemetry server unreachable</div>';
      telemetryBanner.style.display = "none";
    }
  }
  if (telemetryBody) {
    pollTelemetry();
    setInterval(pollTelemetry, 2000);
  }

  // ---------------- Init ----------------
  SessionSidebar.onSwitch = (id) => MessageList.renderHistory(id);
  const activeId = SessionSidebar.ensureActive();
  SessionSidebar.render();
  MessageList.renderHistory(activeId);
})();
