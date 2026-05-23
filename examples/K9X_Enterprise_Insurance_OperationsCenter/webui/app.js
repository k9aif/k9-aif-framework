// K9-AIF EOC Operations Dashboard — V2
// Agent transparency is the core differentiator: every trace step is clickable,
// revealing the agent YAML, model routing decision, governance gates, and result.

'use strict';

// ─── Application state ────────────────────────────────────────────────────────
const state = {
  scenarios:    [],
  architecture: {},
  config:       {},
  selected:     null,
  isRunning:    false,
  activeTab:    'router',
  liveEvents:   [],
  llmCalls:     [],
  sseSource:    null,
  lastTrace:    [],
  bizMode:      false,
};

// Indexed trace data for drawer lookup: stepNum → step object
const traceData = {};

// ─── Replay state ─────────────────────────────────────────────────────────────
const replay = {
  steps:   [],
  pos:     0,
  playing: false,
  timer:   null,
  speed:   400,
};

// ─── Drawer state ─────────────────────────────────────────────────────────────
let drawerStep      = null;
let drawerActiveTab = 'overview';

// ─── Agent display metadata ───────────────────────────────────────────────────
const AGENT_META = {
  ClaimsTriageAgent:      { icon: '🔍', cls: 'blue'   },
  AdjudicationAgent:      { icon: '⚖️',  cls: 'blue'   },
  DocumentExtractorAgent: { icon: '📄', cls: 'purple' },
  FraudDetectionAgent:    { icon: '🚨', cls: 'orange' },
  GraphSyncAgent:         { icon: '🕸',  cls: 'cyan'   },
  GuardAgent:             { icon: '🛡',  cls: 'yellow' },
  AuditAgent:             { icon: '📝', cls: 'green'  },
  EscalationAgent:        { icon: '🔔', cls: 'red'    },
};

// Maps trace component names → pipeline node element IDs
const COMPONENT_TO_NODE = {
  EOCRouter:       'pnode-EOCRouter',
  EOCOrchestrator: 'pnode-EOCOrchestrator',
  SquadLoader:     'pnode-SquadLoader',
  GuardAgent:      'pnode-guard',
  Guard:           'pnode-guard',
  Pipeline:        'pnode-Pipeline',
  EscalationGate:  'pnode-Pipeline',
  PolicyDecision:  'pnode-Pipeline',
  AuditQuery:      'pnode-Pipeline',
};

// Business vocabulary — shown when BIZ mode is active
const BIZ_VOCAB = {
  'EOCRouter':              'Event Router',
  'EOCOrchestrator':        'Process Manager',
  'SquadLoader':            'Team Assembler',
  'Guard Layer':            'Quality Control',
  'ClaimsTriageAgent':      'Claims Reviewer',
  'AdjudicationAgent':      'Decision Engine',
  'DocumentExtractorAgent': 'Document Processor',
  'FraudDetectionAgent':    'Fraud Investigator',
  'GraphSyncAgent':         'Network Analyzer',
  'GuardAgent':             'Compliance Monitor',
  'AuditAgent':             'Audit Logger',
  'EscalationAgent':        'Escalation Manager',
  'claim_submitted':        'New Claim',
  'document_received':      'Document Filed',
  'fraud_signal_raised':    'Fraud Alert',
  'policy_change_requested':'Policy Request',
  'catastrophe_alert_issued':'Catastrophe Event',
  'customer_interaction_logged':'Customer Contact',
  'audit_query_received':   'Audit Query',
};

// ─── Bootstrap ────────────────────────────────────────────────────────────────
async function init() {
  try {
    const [scenarios, arch, cfg] = await Promise.all([
      apiFetch('/api/eoc/scenarios'),
      apiFetch('/api/eoc/architecture'),
      apiFetch('/api/eoc/config-summary'),
    ]);

    state.scenarios    = scenarios.scenarios || [];
    state.architecture = arch;
    state.config       = cfg;

    renderScenarioList();
    renderIntroBar();
    checkHealth();
    connectSSE();
    renderTab('router');

    if (state.scenarios.length > 0) selectScenario(state.scenarios[0].id);
  } catch (e) {
    console.error('Init failed:', e);
    setHealth('error', 'Backend unreachable');
  }
}

// ─── API helpers ──────────────────────────────────────────────────────────────
async function apiFetch(url, opts = {}) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${url}`);
  return r.json();
}

// ─── Health check ─────────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const h = await apiFetch('/health');
    const ok = h.status === 'ok';
    setHealth(ok ? 'ok' : 'warn', ok ? 'System Ready' : h.status);
  } catch {
    setHealth('error', 'Offline');
  }
  setTimeout(checkHealth, 30_000);
}

function setHealth(cls, label) {
  const badge = document.getElementById('health-badge');
  const lbl   = document.getElementById('health-label');
  badge.className = `health-badge ${cls}`;
  lbl.textContent = label;
}

// ─── Mode toggle (ARCH / BIZ) ─────────────────────────────────────────────────
function setMode(mode) {
  state.bizMode = mode === 'biz';
  document.body.classList.toggle('biz-mode', state.bizMode);
  document.getElementById('mode-arch').classList.toggle('active', !state.bizMode);
  document.getElementById('mode-biz').classList.toggle('active',   state.bizMode);
}

function bizLabel(technicalName) {
  return state.bizMode ? (BIZ_VOCAB[technicalName] || technicalName) : technicalName;
}

// ─── Intro bar ────────────────────────────────────────────────────────────────
function renderIntroBar() {
  const c = state.config;
  setText('cfg-backend',    `${c.inference?.backend || '?'} · ${c.inference?.models?.join(', ') || '?'}`);
  setText('cfg-messaging',  `${c.messaging?.backend || '?'} · ${(c.messaging?.brokers||[]).join(', ')}`);
  setText('cfg-governance', c.governance?.enabled ? 'enabled' : 'disabled');
}

// ─── Scenario list ────────────────────────────────────────────────────────────
function renderScenarioList() {
  const el = document.getElementById('scenario-list');
  el.innerHTML = state.scenarios.map(s => `
    <div class="scenario-item" id="sitem-${s.id}" onclick="selectScenario('${s.id}')">
      <div class="scenario-icon">${s.icon}</div>
      <div class="scenario-info">
        <div class="scenario-label">${s.label}</div>
        <div class="scenario-squad">${s.squad}</div>
      </div>
    </div>
  `).join('');
}

// ─── Select scenario ──────────────────────────────────────────────────────────
function selectScenario(id) {
  state.selected = state.scenarios.find(s => s.id === id);
  if (!state.selected) return;

  document.querySelectorAll('.scenario-item').forEach(el => el.classList.remove('active'));
  const navItem = document.getElementById(`sitem-${id}`);
  if (navItem) navItem.classList.add('active');

  setText('exec-title', `${state.selected.icon}  ${state.selected.label}`);
  setText('exec-desc',  state.selected.description);
  renderMetaChips(state.selected);

  document.getElementById('payload-editor').value =
    JSON.stringify(state.selected.sample_payload || {}, null, 2);

  document.getElementById('run-btn').disabled = false;
  renderAgentList(state.selected);
  resetPipeline();
  clearResults();
  hideReplayBar();
}

function renderMetaChips(s) {
  document.getElementById('meta-chips').innerHTML = `
    <div class="meta-chip"><span class="label">squad</span><span class="val">${s.squad}</span></div>
    <div class="meta-chip"><span class="label">topic</span><span class="val">${s.topic}</span></div>
    <div class="meta-chip"><span class="label">agents</span><span class="val">${s.agents.length + s.conditional_agents.length}</span></div>
  `;
}

function renderAgentList(scenario) {
  setText('squad-node-title', scenario.squad.replace('Squad', ''));

  const el = document.getElementById('agent-list');
  const chips = scenario.agents.map(name => {
    const m = AGENT_META[name] || { icon: '🤖', cls: 'blue' };
    return `<div class="agent-chip" id="achip-${name}" data-agent="${name}" onclick="openDrawerByAgent('${name}')">
      <div class="agent-chip-dot"></div>
      <span>${m.icon} ${bizLabel(name).replace('Agent', '')}</span>
    </div>`;
  });
  const optional = scenario.conditional_agents.map(name => {
    const m = AGENT_META[name] || { icon: '🤖', cls: 'blue' };
    return `<div class="agent-chip conditional" id="achip-${name}" data-agent="${name}"
              onclick="openDrawerByAgent('${name}')" title="Conditional — only triggered on escalation">
      <div class="agent-chip-dot"></div>
      <span>${m.icon} ${bizLabel(name).replace('Agent', '')} ?</span>
    </div>`;
  });

  el.innerHTML = [...chips, ...optional].join('');
}

// ─── Payload reset ────────────────────────────────────────────────────────────
function resetPayload() {
  if (!state.selected) return;
  document.getElementById('payload-editor').value =
    JSON.stringify(state.selected.sample_payload || {}, null, 2);
}

// ─── Run scenario ─────────────────────────────────────────────────────────────
async function runScenario() {
  if (!state.selected || state.isRunning) return;

  let payload;
  try {
    payload = JSON.parse(document.getElementById('payload-editor').value);
  } catch {
    alert('Invalid JSON in payload editor.');
    return;
  }

  state.isRunning = true;
  state.lastTrace = [];
  Object.keys(traceData).forEach(k => delete traceData[k]);

  setRunBtn(true);
  clearResults();
  resetPipeline();
  hideReplayBar();

  activateNode('pnode-Event');
  await delay(300);
  doneNode('pnode-Event');

  let data;
  try {
    data = await apiFetch('/api/eoc/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: state.selected.id, payload }),
    });
  } catch (e) {
    appendTrace({ step: 1, component: 'Network', layer: 'error', status: 'error',
                  message: `Request failed: ${e.message}`, final: true });
    state.isRunning = false;
    setRunBtn(false);
    return;
  }

  await animatePipeline(data.trace || []);
  renderResult(data);
  showReplayBar(data.trace || []);

  state.isRunning = false;
  setRunBtn(false);
}

function setRunBtn(running) {
  const btn = document.getElementById('run-btn');
  btn.disabled = running;
  btn.classList.toggle('running', running);
  setText('run-label', running ? 'Running…' : 'RUN SCENARIO');
}

// ─── Pipeline animation ───────────────────────────────────────────────────────
async function animatePipeline(trace) {
  document.getElementById('trace-console').innerHTML = '';
  let stepCount = 0;

  for (const step of trace) {
    const nodeId = resolveNodeId(step.component);
    if (nodeId) activateNode(nodeId);

    await delay(350);

    appendTrace(step);
    stepCount++;
    setText('trace-count', `${stepCount} step${stepCount !== 1 ? 's' : ''}`);

    if (nodeId) {
      if (step.status === 'ok' || step.final)  doneNode(nodeId);
      else if (step.status === 'warn')          warnNode(nodeId);
      else if (step.status === 'error')         errorNode(nodeId);
    }

    const agentEl = document.getElementById(`achip-${step.component}`);
    if (agentEl) {
      agentEl.classList.add(`node-${step.status}`);
      agentEl.classList.remove('conditional');
    }
  }
}

function resolveNodeId(component) {
  if (COMPONENT_TO_NODE[component]) return COMPONENT_TO_NODE[component];
  if (component.includes('Guard')) return 'pnode-guard';
  if (AGENT_META[component] || component.endsWith('Agent')) return 'squad-node';
  return null;
}

// ─── Pipeline node helpers ────────────────────────────────────────────────────
function resetPipeline() {
  document.querySelectorAll('.pnode, .squad-node, .pnode-guard').forEach(n => {
    n.classList.remove('node-active', 'node-done', 'node-warn', 'node-error');
  });
  document.querySelectorAll('.agent-chip').forEach(c => {
    c.classList.remove('node-active', 'node-done', 'node-warn', 'node-error');
    if (c.dataset.agent && state.selected?.conditional_agents?.includes(c.dataset.agent)) {
      c.classList.add('conditional');
    }
  });
}

function activateNode(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('node-done', 'node-warn', 'node-error');
  el.classList.add('node-active');
}

function doneNode(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('node-active', 'node-warn', 'node-error');
  el.classList.add('node-done');
}

function warnNode(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('node-active', 'node-done', 'node-error');
  el.classList.add('node-warn');
}

function errorNode(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('node-active', 'node-done', 'node-warn');
  el.classList.add('node-error');
}

// ─── Trace console ────────────────────────────────────────────────────────────
function appendTrace(step, replayMode = false) {
  const el = document.getElementById('trace-console');
  const empty = el.querySelector('.trace-empty');
  if (empty) empty.remove();

  if (!replayMode) state.lastTrace.push(step);
  traceData[step.step] = step;

  const hasDetail = !!(step.agent_yaml || step.model_routing || step.governance_detail || step.agent_result);
  const icon = step.status === 'ok' ? '✓' : step.status === 'warn' ? '⚠' : step.final ? '◉' : '✗';

  const div = document.createElement('div');
  div.className = `trace-step ${step.status}${step.final ? ' final' : ''}`;
  div.dataset.stepNum = step.step;

  if (hasDetail) {
    div.addEventListener('click', () => openDrawer(step.step));
  }

  div.innerHTML = `
    <div class="trace-num">${step.step}</div>
    <div class="trace-status-icon">${icon}</div>
    <div class="trace-body">
      <div>
        <span class="trace-component">${esc(bizLabel(step.component))}</span>
        <span class="trace-layer">[${esc(step.layer)}]</span>
        ${step.latency_ms ? `<span style="margin-left:6px;font-size:9px;color:var(--text-muted);font-family:var(--font-mono)">${step.latency_ms}ms</span>` : ''}
      </div>
      <div class="trace-msg">${esc(step.message)}</div>
    </div>
    ${hasDetail ? '<div class="trace-expand-icon">›</div>' : ''}
  `;

  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}

function clearResults() {
  document.getElementById('trace-console').innerHTML =
    '<div class="trace-empty">Running…</div>';
  document.getElementById('result-body').innerHTML =
    '<div class="result-empty">Waiting for pipeline…</div>';
  setText('trace-count', '0 steps');
  setText('result-status-badge', '');
}

// ─── Agent detail drawer ──────────────────────────────────────────────────────
function openDrawer(stepNum) {
  const step = traceData[stepNum];
  if (!step) return;
  drawerStep = step;

  // Highlight selected trace step
  document.querySelectorAll('.trace-step').forEach(el => el.classList.remove('selected'));
  const stepEl = document.querySelector(`.trace-step[data-step-num="${stepNum}"]`);
  if (stepEl) stepEl.classList.add('selected');

  // Header
  const m = AGENT_META[step.component] || { icon: '🤖' };
  setText('drawer-icon',     m.icon);
  setText('drawer-title',    step.component);
  const msg = step.message || '';
  setText('drawer-subtitle', msg.length > 90 ? msg.slice(0, 90) + '…' : msg);

  const sb = document.getElementById('drawer-status-badge');
  if (sb) { sb.textContent = step.status; sb.className = `drawer-status ${step.status}`; }

  // Meta row
  setText('dm-layer',      step.layer || '—');
  setText('dm-latency',    step.latency_ms ? `${step.latency_ms}ms` : '—');
  setText('dm-model',      step.model_routing?.model || step.agent_yaml?.model || '—');
  const conf = step.agent_result?.confidence ?? step.model_routing?.confidence;
  setText('dm-confidence', conf !== undefined ? `${(conf * 100).toFixed(0)}%` : '—');

  // Reset to overview tab
  drawerActiveTab = 'overview';
  document.querySelectorAll('.drawer-tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.dtab === 'overview');
  });
  renderDrawerContent('overview', step);

  document.getElementById('agent-drawer').classList.add('open');
  document.getElementById('drawer-overlay').style.display = 'block';
}

function openDrawerByAgent(agentName) {
  const step = [...Object.values(traceData)].reverse().find(s => s.component === agentName);
  if (step) openDrawer(step.step);
}

function closeDrawer() {
  document.getElementById('agent-drawer').classList.remove('open');
  document.getElementById('drawer-overlay').style.display = 'none';
  document.querySelectorAll('.trace-step').forEach(el => el.classList.remove('selected'));
  drawerStep = null;
}

function selectDrawerTab(btn, tab) {
  document.querySelectorAll('.drawer-tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  drawerActiveTab = tab;
  if (drawerStep) renderDrawerContent(tab, drawerStep);
}

function renderDrawerContent(tab, step) {
  const body = document.getElementById('drawer-body');
  switch (tab) {
    case 'overview':   body.innerHTML = renderDrawerOverview(step);   break;
    case 'yaml':       body.innerHTML = renderDrawerYaml(step);       break;
    case 'governance': body.innerHTML = renderDrawerGovernance(step); break;
    case 'result':     body.innerHTML = renderDrawerResult(step);     break;
    default:           body.innerHTML = '<div class="trace-empty">Unknown tab</div>';
  }
}

function renderDrawerOverview(step) {
  const ay = step.agent_yaml || {};
  const mr = step.model_routing || {};
  let html = '';

  if (ay.role) {
    html += section('Role', `<div class="role-text">${esc(ay.role)}</div>`);
  }
  if (ay.goal) {
    html += section('Goal', `<div class="role-text">${esc(ay.goal)}</div>`);
  }

  const cfgRows = [
    kv('component', step.component),
    kv('layer',     step.layer),
    kv('pattern',   ay.pattern || '—'),
    kv('model',     ay.model || mr.model || '—', 'hi'),
    kv('provider',  ay.provider || mr.provider || '—'),
    step.latency_ms ? kv('latency', `${step.latency_ms}ms`) : '',
  ].join('');
  html += section('Configuration', cfgRows);

  if (step.tools?.length) {
    const tags = step.tools.map(t => `<span class="agent-tag">${esc(t)}</span>`).join(' ');
    html += section('Available Tools', tags);
  }

  if (Array.isArray(ay.instructions) && ay.instructions.length) {
    const items = ay.instructions.slice(0, 6)
      .map(i => `<li>${esc(String(i))}</li>`).join('');
    html += section('Instructions', `<ul class="instructions-list">${items}</ul>`);
  }

  if (mr.rationale) {
    html += section('Model Routing Rationale', `<div class="role-text">${esc(mr.rationale)}</div>`);
  }

  return html || '<div class="trace-empty">No overview data for this step</div>';
}

function renderDrawerYaml(step) {
  const ay = step.agent_yaml;
  if (!ay) return '<div class="trace-empty">No agent YAML available for this step</div>';
  return section('Full Agent YAML Config',
    `<pre class="prompt-block">${esc(JSON.stringify(ay, null, 2))}</pre>`);
}

function renderDrawerGovernance(step) {
  const gd = step.governance_detail;
  const mr = step.model_routing;
  const ay = step.agent_yaml;
  let html = '';

  if (gd) {
    const gate = (label, enabled, cls = 'enabled') =>
      `<div class="governance-gate ${enabled ? cls : 'disabled'}">
         <div class="gate-dot"></div>
         <span>${esc(label)}</span>
         <span style="margin-left:auto;font-size:9px">${enabled ? 'ACTIVE' : 'INACTIVE'}</span>
       </div>`;

    let gates = '';
    gates += gate('PII Guard',            gd.pii_guard ?? true);
    gates += gate('Pre-execution Guard',  gd.pre_guard ?? false);
    gates += gate('Post-execution Guard', gd.post_guard ?? false);
    gates += gate('Confidence Threshold', gd.confidence_threshold !== undefined);
    gates += gate('Audit Logging',        gd.audit ?? true);

    let extra = '';
    if (gd.confidence_threshold !== undefined)
      extra += kv('threshold', `${(gd.confidence_threshold * 100).toFixed(0)}%`);
    if (gd.pii_fields?.length)
      extra += kv('pii_fields', gd.pii_fields.join(', '));

    html += section('Governance Gates', gates + extra);
  } else if (ay?.governance) {
    const rows = Object.entries(ay.governance).map(([k, v]) => kv(k, String(v))).join('');
    html += section('Governance Policy (from YAML)', rows);
  }

  if (mr) {
    const rows = [
      kv('model',          mr.model || '—', 'hi'),
      kv('provider',       mr.provider || '—'),
      kv('complexity',     mr.complexity || '—'),
      kv('governance_tag', mr.governance_tag || '—', 'warn'),
      mr.cost_tier ? kv('cost_tier', mr.cost_tier) : '',
    ].join('');
    html += section('Model Routing', rows);
  }

  return html || '<div class="trace-empty">No governance data for this step</div>';
}

function renderDrawerResult(step) {
  const ar = step.agent_result;
  if (!ar) return '<div class="trace-empty">No agent result data available</div>';
  return section('Raw Agent Output',
    `<pre class="result-json-drawer">${esc(JSON.stringify(ar, null, 2))}</pre>`);
}

// Drawer HTML helpers
function section(title, body) {
  return `<div class="drawer-section">
    <div class="drawer-section-title">${esc(title)}</div>
    ${body}
  </div>`;
}

function kv(key, val, valCls = '') {
  return `<div class="drawer-kv">
    <div class="drawer-kv-key">${esc(key)}</div>
    <div class="drawer-kv-val ${valCls}">${esc(String(val ?? '—'))}</div>
  </div>`;
}

// ─── Replay controls ──────────────────────────────────────────────────────────
function showReplayBar(trace) {
  replay.steps   = trace;
  replay.pos     = trace.length;
  replay.playing = false;
  clearTimeout(replay.timer);

  const bar = document.getElementById('replay-bar');
  if (bar) bar.style.display = 'flex';
  updateReplayLabel();
}

function hideReplayBar() {
  const bar = document.getElementById('replay-bar');
  if (bar) bar.style.display = 'none';
}

function updateReplayLabel() {
  const posEl   = document.getElementById('replay-pos');
  const totalEl = document.getElementById('replay-total');
  const playBtn = document.getElementById('replay-play-btn');
  if (posEl)   posEl.textContent   = replay.pos;
  if (totalEl) totalEl.textContent = replay.steps.length;
  if (playBtn) playBtn.textContent = replay.playing ? '⏸' : '▶';
}

function replayPlay() {
  if (replay.playing) {
    replay.playing = false;
    clearTimeout(replay.timer);
    updateReplayLabel();
    return;
  }
  if (replay.pos >= replay.steps.length) replayReset();
  replay.playing = true;
  updateReplayLabel();
  doReplayTick();
}

function doReplayTick() {
  if (!replay.playing) return;
  if (replay.pos >= replay.steps.length) {
    replay.playing = false;
    updateReplayLabel();
    return;
  }
  doReplayStep();
  replay.timer = setTimeout(doReplayTick, replay.speed);
}

function replayStepForward() {
  if (replay.pos < replay.steps.length) doReplayStep();
}

function doReplayStep() {
  if (replay.pos >= replay.steps.length) return;
  const step = replay.steps[replay.pos];
  replay.pos++;

  const nodeId = resolveNodeId(step.component);
  if (nodeId) activateNode(nodeId);
  appendTrace(step, true);

  const cnt = replay.pos;
  setText('trace-count', `${cnt} step${cnt !== 1 ? 's' : ''}`);

  if (nodeId) {
    if (step.status === 'ok' || step.final)  doneNode(nodeId);
    else if (step.status === 'warn')          warnNode(nodeId);
    else if (step.status === 'error')         errorNode(nodeId);
  }
  const agentEl = document.getElementById(`achip-${step.component}`);
  if (agentEl) {
    agentEl.classList.add(`node-${step.status}`);
    agentEl.classList.remove('conditional');
  }
  updateReplayLabel();
}

function replayStop() {
  replay.playing = false;
  clearTimeout(replay.timer);
  replayReset();
}

function replayReset() {
  replay.pos = 0;
  resetPipeline();
  Object.keys(traceData).forEach(k => delete traceData[k]);
  document.getElementById('trace-console').innerHTML =
    '<div class="trace-empty">Press ▶ to replay from step 1…</div>';
  setText('trace-count', '0 steps');
  updateReplayLabel();
}

function replaySetSpeed(v) {
  replay.speed = parseInt(v, 10);
}

// ─── Result panel ─────────────────────────────────────────────────────────────
function deriveOutcomeStatus(r, data) {
  if (r.status === 'timeout')            return { code: 'timeout',    label: 'Pipeline Timeout', cls: 'error'     };
  if (data.error || r.status === 'error') return { code: 'error',    label: 'Error',            cls: 'error'     };
  if (r.status === 'stub')               return { code: 'stub',       label: 'Stub Mode',        cls: 'warn'      };
  if (r.escalation?.ticket_id)           return { code: 'escalated',  label: 'Escalated',        cls: 'escalated' };
  if (r.guard && !r.guard.passed)        return { code: 'blocked',    label: 'Blocked',          cls: 'error'     };
  const conf = r.adjudication?.confidence;
  if (conf !== undefined && conf < 0.6)  return { code: 'low_conf',   label: 'Low Confidence',   cls: 'warn'      };
  if (r.extraction?.validation_status === 'error') return { code: 'partial', label: 'Partial',   cls: 'warn'      };
  return { code: 'completed', label: 'Completed', cls: 'ok' };
}

function renderResult(data) {
  const r = data.result || {};
  const outcome = deriveOutcomeStatus(r, data);

  const badge = document.getElementById('result-status-badge');
  badge.innerHTML = `<span class="result-badge ${outcome.cls}">${outcome.label}</span>`;

  const rows = [];
  const add = (k, v, cls = '') => rows.push(
    `<div class="result-kv">
       <div class="result-key">${esc(k)}</div>
       <div class="result-val ${cls}">${esc(String(v ?? '—'))}</div>
     </div>`
  );

  add('event_type', data.event_type, 'blue');
  add('event_id',   data.event_id);
  add('squad_id',   r.squad_id || data.squad_id || '—');
  add('status',     outcome.label, outcome.cls);

  if (r.adjudication?.decision)    add('decision',   r.adjudication.decision.toUpperCase(), 'ok');
  if (r.adjudication?.confidence)  add('confidence', (r.adjudication.confidence * 100).toFixed(0) + '%');
  if (r.triage?.priority)          add('priority',   r.triage.priority.toUpperCase());
  if (r.fraud_assessment?.risk_score !== undefined)
    add('risk_score', r.fraud_assessment.risk_score.toFixed(2));
  if (r.extraction?.validation_status)
    add('extraction', r.extraction.validation_status);
  if (r.policy_decision)           add('policy_decision', r.policy_decision.toUpperCase());
  if (r.entry_count !== undefined) add('audit_entries', r.entry_count);
  if (r.guard)
    add('guard', r.guard.passed ? 'PASSED ✓' : 'FAILED ✗', r.guard.passed ? 'ok' : 'warn');
  if (r.guard?.pii_detected !== undefined) add('pii_detected', r.guard.pii_detected);
  if (r.escalation?.ticket_id)
    add('escalation_ticket', r.escalation.ticket_id, 'warn');
  if (r.response_plan?.risk_score !== undefined)
    add('cat_risk_score', r.response_plan.risk_score?.toFixed(2));
  add('correlation_id', data.correlation_id);
  if (data.error) add('error', data.error, 'error');

  const body = document.getElementById('result-body');
  body.innerHTML = rows.join('') + `
    <button class="result-json-toggle" onclick="toggleJson(this)">{ } View full JSON</button>
    <pre class="result-json-block" id="result-json">${esc(JSON.stringify(data.result, null, 2))}</pre>
  `;
}

function toggleJson(btn) {
  const block = document.getElementById('result-json');
  block.classList.toggle('visible');
  btn.textContent = block.classList.contains('visible') ? '{ } Hide JSON' : '{ } View full JSON';
}

// ─── Architecture tabs ────────────────────────────────────────────────────────
function selectTab(btn, tab) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  state.activeTab = tab;
  renderTab(tab);
}

function renderTab(tab) {
  const el = document.getElementById('tab-content');
  const a  = state.architecture;

  switch (tab) {
    case 'router':     el.innerHTML = renderRouterTab(a); break;
    case 'squads':     el.innerHTML = renderSquadsTab(a); break;
    case 'agents':     el.innerHTML = renderAgentsTab(a); break;
    case 'governance': el.innerHTML = renderGovernanceTab(a); break;
    case 'models':     el.innerHTML = renderModelsTab(a); break;
    case 'graph':      renderGraphTab(); break;
    case 'config':     el.innerHTML = renderConfigTab(); break;
    case 'livefeed':   el.innerHTML = renderLiveFeed(); break;
    case 'llmcalls':   el.innerHTML = renderLlmCallsTab(); break;
    case 'hitl':       renderHitlTab(); break;
    case 'demo':       el.innerHTML = renderDemoTab(); break;
    default:           el.innerHTML = '<div class="trace-empty">Unknown tab</div>';
  }
}

function renderRouterTab(a) {
  if (!a.router) return '<div class="trace-empty">Loading…</div>';
  const rows = Object.entries(a.router.routing_table || {}).map(([evt, topic]) =>
    `<tr><td>${esc(evt)}</td><td>${esc(topic)}</td></tr>`
  ).join('');
  return `
    <div style="display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap">
      <div style="flex:0 0 300px">
        <div class="arch-card">
          <div class="arch-card-header">
            <div class="arch-card-icon">⇄</div>
            <div class="arch-card-name">${esc(a.router.class || 'EOCRouter')}</div>
          </div>
          <div class="arch-card-body">
            <div class="arch-row"><div class="arch-row-key">pattern</div><div class="arch-row-val hi">deterministic</div></div>
            <div class="arch-row"><div class="arch-row-key">routes</div><div class="arch-row-val">${Object.keys(a.router.routing_table||{}).length} event types</div></div>
            <div class="arch-row mt-4" style="display:block"><div style="color:var(--text-muted);font-size:11px;line-height:1.5">${esc(a.router.description||'')}</div></div>
          </div>
        </div>
      </div>
      <div style="flex:1;min-width:280px">
        <div style="font-size:10px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:var(--text-muted);margin-bottom:8px">Routing Table</div>
        <div class="arch-card"><div class="arch-card-body" style="padding:0">
          <table class="route-table">
            <thead><tr><th>event_type</th><th>kafka topic</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div></div>
      </div>
    </div>`;
}

function renderSquadsTab(a) {
  if (!a.squads) return '<div class="trace-empty">Loading…</div>';
  const cards = a.squads.map(sq => {
    const agentTags = (sq.agents||[]).map(n => `<span class="agent-tag">${esc(n)}</span>`).join('');
    const condTags  = (sq.conditional_agents||[]).map(n => `<span class="agent-tag conditional">${esc(n)} ?</span>`).join('');
    return `
      <div class="arch-card">
        <div class="arch-card-header">
          <div class="arch-card-icon">📦</div>
          <div class="arch-card-name">${esc(sq.id)}</div>
          <div class="arch-card-tag tool">${esc(sq.event_type||'')}</div>
        </div>
        <div class="arch-card-body">
          <div class="arch-row"><div class="arch-row-key">orchestrator</div><div class="arch-row-val hi">${esc(sq.orchestrator||'')}</div></div>
          <div class="arch-row mt-4"><div class="arch-row-key">agents</div></div>
          <div class="agent-tags" style="margin-top:4px">${agentTags}${condTags}</div>
          <div class="arch-row mt-4" style="display:block"><div style="color:var(--text-muted);font-size:10.5px;line-height:1.4;margin-top:6px">${esc(sq.description||'')}</div></div>
        </div>
      </div>`;
  }).join('');
  return `<div class="arch-grid">${cards}</div>`;
}

function renderAgentsTab(a) {
  if (!a.agents) return '<div class="trace-empty">Loading…</div>';
  const cards = a.agents.map(ag => {
    const m   = AGENT_META[ag.class] || { icon: '🤖' };
    const gov = ag.governance || {};
    const govStr = [gov.pre && 'pre-guard', gov.post && 'post-guard'].filter(Boolean).join(' + ') || 'none';
    return `
      <div class="arch-card">
        <div class="arch-card-header">
          <div class="arch-card-icon">${m.icon}</div>
          <div class="arch-card-name">${esc(ag.class)}</div>
          <div class="arch-card-tag ${esc(ag.pattern||'')}">${esc(ag.pattern||'')}</div>
        </div>
        <div class="arch-card-body">
          <div class="arch-row"><div class="arch-row-key">model</div><div class="arch-row-val hi">${esc(ag.model||'?')}</div></div>
          <div class="arch-row"><div class="arch-row-key">governance</div><div class="arch-row-val">${esc(govStr)}</div></div>
          ${ag.note ? `<div class="arch-row mt-4" style="display:block"><div style="color:var(--text-muted);font-size:10px;line-height:1.4">${esc(ag.note)}</div></div>` : ''}
        </div>
      </div>`;
  }).join('');
  return `<div class="arch-grid">${cards}</div>`;
}

function renderGovernanceTab(a) {
  if (!a.governance) return '<div class="trace-empty">Loading…</div>';
  const cards = Object.entries(a.governance).map(([name, pol]) => `
    <div class="policy-card">
      <div class="policy-enabled">ENABLED</div>
      <div class="policy-card-name">${esc(name)}</div>
      <div class="policy-card-desc">${esc(pol.description || '')}</div>
      ${pol.threshold !== undefined ? `<div style="margin-top:6px;font-size:11px;font-family:var(--font-mono);color:var(--cyan)">threshold: ${pol.threshold}</div>` : ''}
      ${pol.model ? `<div style="margin-top:4px;font-size:11px;font-family:var(--font-mono);color:var(--yellow)">model: ${pol.model}</div>` : ''}
    </div>`).join('');
  return `<div class="policy-grid">${cards}</div>`;
}

function renderModelsTab(a) {
  if (!a.model_routing) return '<div class="trace-empty">Loading…</div>';
  const cards = Object.entries(a.model_routing).map(([name, m]) => {
    const caps = (m.capabilities || []).map(c => `<span class="agent-tag">${esc(c)}</span>`).join('');
    return `
      <div class="arch-card">
        <div class="arch-card-header">
          <div class="arch-card-icon">🧠</div>
          <div class="arch-card-name">${esc(name)}</div>
          <div class="arch-card-tag reasoning">${esc(m.provider||'ollama')}</div>
        </div>
        <div class="arch-card-body">
          <div class="arch-row"><div class="arch-row-key">model_id</div><div class="arch-row-val hi">${esc(m.model||'?')}</div></div>
          <div class="arch-row mt-4"><div class="arch-row-key">capabilities</div></div>
          <div class="agent-tags" style="margin-top:4px">${caps}</div>
        </div>
      </div>`;
  }).join('');
  return `<div class="arch-grid">${cards}</div>`;
}

function renderConfigTab() {
  const c = state.config;
  if (!c || !Object.keys(c).length) return '<div class="trace-empty">Loading…</div>';
  return `<pre class="config-block">${esc(JSON.stringify(c, null, 2))}</pre>`;
}

// ─── Runtime Graph (Cytoscape.js) — three views ───────────────────────────────
let graphView = 'architecture';

// Node style palettes per view
const GRAPH_STYLES = {
  architecture: {
    router:          { bg: 'rgba(69,137,255,0.2)',   border: '#4589ff', shape: 'diamond' },
    orchestrator:    { bg: 'rgba(165,110,255,0.2)',  border: '#a56eff', shape: 'rectangle' },
    agent:           { bg: 'rgba(51,177,255,0.15)',  border: '#33b1ff', shape: 'ellipse' },
    governanceagent: { bg: 'rgba(241,194,27,0.15)',  border: '#f1c21b', shape: 'ellipse' },
    governance:      { bg: 'rgba(241,194,27,0.15)',  border: '#f1c21b', shape: 'ellipse' },
    audit:           { bg: 'rgba(66,190,101,0.15)',  border: '#42be65', shape: 'ellipse' },
    squad:           { bg: 'rgba(0,180,216,0.12)',   border: '#00b4d8', shape: 'rectangle' },
    conditional:     { bg: 'rgba(255,131,43,0.12)',  border: '#ff832b', shape: 'ellipse' },
    input:           { bg: 'rgba(69,137,255,0.08)',  border: '#3b5fc0', shape: 'ellipse' },
    output:          { bg: 'rgba(36,161,72,0.12)',   border: '#24a148', shape: 'ellipse' },
  },
  entities: {
    claimant: { bg: 'rgba(51,177,255,0.2)',   border: '#33b1ff', shape: 'ellipse' },
    claim:    { bg: 'rgba(69,137,255,0.2)',   border: '#4589ff', shape: 'rectangle' },
    policy:   { bg: 'rgba(165,110,255,0.2)',  border: '#a56eff', shape: 'diamond' },
    document: { bg: 'rgba(66,190,101,0.15)',  border: '#42be65', shape: 'triangle' },
    alert:    { bg: 'rgba(218,30,40,0.2)',    border: '#da1e28', shape: 'star' },
  },
  fraud_network: {
    claimant: { bg: 'rgba(51,177,255,0.2)',   border: '#33b1ff', shape: 'ellipse' },
    claim:    { bg: 'rgba(69,137,255,0.2)',   border: '#4589ff', shape: 'rectangle' },
    policy:   { bg: 'rgba(165,110,255,0.2)',  border: '#a56eff', shape: 'diamond' },
  },
};

const GRAPH_LEGENDS = {
  architecture: [
    { color: '#4589ff', bg: 'rgba(69,137,255,0.2)',   label: 'Router' },
    { color: '#a56eff', bg: 'rgba(165,110,255,0.2)',  label: 'Orchestrator' },
    { color: '#33b1ff', bg: 'rgba(51,177,255,0.15)',  label: 'Agent' },
    { color: '#f1c21b', bg: 'rgba(241,194,27,0.15)',  label: 'Governance' },
    { color: '#42be65', bg: 'rgba(66,190,101,0.15)',  label: 'Audit' },
  ],
  entities: [
    { color: '#33b1ff', bg: 'rgba(51,177,255,0.2)',   label: 'Claimant' },
    { color: '#4589ff', bg: 'rgba(69,137,255,0.2)',   label: 'Claim' },
    { color: '#a56eff', bg: 'rgba(165,110,255,0.2)',  label: 'Policy' },
    { color: '#42be65', bg: 'rgba(66,190,101,0.15)',  label: 'Document' },
    { color: '#da1e28', bg: 'rgba(218,30,40,0.2)',    label: 'Alert' },
  ],
  fraud_network: [
    { color: '#33b1ff', bg: 'rgba(51,177,255,0.2)',   label: 'Claimant' },
    { color: '#4589ff', bg: 'rgba(69,137,255,0.2)',   label: 'Claim' },
    { color: '#a56eff', bg: 'rgba(165,110,255,0.2)',  label: 'Policy' },
    { color: '#da1e28', bg: 'rgba(218,30,40,0.2)',    label: 'High-risk Policy (⚠ multi-claim)' },
  ],
};

async function renderGraphTab() {
  const el = document.getElementById('tab-content');
  el.innerHTML = `
    <div class="graph-toolbar">
      <div class="graph-view-btns">
        <button class="gview-btn ${graphView==='architecture'?'active':''}"
                onclick="setGraphView('architecture',this)">🏗 Architecture</button>
        <button class="gview-btn ${graphView==='entities'?'active':''}"
                onclick="setGraphView('entities',this)">🕸 Claimant Network</button>
        <button class="gview-btn ${graphView==='fraud_network'?'active':''}"
                onclick="setGraphView('fraud_network',this)">🚨 Fraud Network</button>
      </div>
      <span class="graph-source-badge" id="graph-source-badge"></span>
    </div>
    <div id="graph-container" style="height:430px"></div>
    <div class="graph-legend" id="graph-legend"></div>`;

  await loadGraphView(graphView);
}

async function setGraphView(view, btn) {
  graphView = view;
  document.querySelectorAll('.gview-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  await loadGraphView(view);
}

async function loadGraphView(view) {
  const container = document.getElementById('graph-container');
  if (!container) return;

  if (typeof cytoscape === 'undefined') {
    container.innerHTML =
      '<div class="trace-empty" style="padding:20px">Cytoscape.js not loaded (CDN unreachable).</div>';
    return;
  }

  container.innerHTML =
    '<div class="trace-empty" style="padding:20px;text-align:center">Loading graph from Neo4j…</div>';

  const url = `/api/eoc/graph?view=${view}`;
  let data;
  try {
    data = await apiFetch(url);
  } catch (e) {
    container.innerHTML =
      `<div class="trace-empty" style="padding:20px">Graph error: ${esc(e.message)}</div>`;
    return;
  }

  // Source badge
  const badge = document.getElementById('graph-source-badge');
  if (badge) {
    badge.textContent = data.source === 'neo4j' ? '● Neo4j' : data.source === 'static' ? '○ static' : '✗ error';
    badge.style.color = data.source === 'neo4j' ? 'var(--green-lt)' : 'var(--text-muted)';
  }

  if (data.empty || !data.nodes?.length) {
    const hint = view === 'architecture'
      ? 'Run the seed: <code>deploy/build-run.sh seed-neo4j</code>'
      : 'Run a few scenarios first — GraphSyncAgent will write entity nodes to Neo4j.';
    container.innerHTML =
      `<div class="trace-empty" style="padding:24px;line-height:1.8">
         No ${view.replace('_',' ')} data in Neo4j yet.<br>
         <span style="font-size:11px;color:var(--text-muted)">${hint}</span>
       </div>`;
    return;
  }

  renderCytoscape(container, data, view);
  renderGraphLegend(view);
}

function renderCytoscape(container, data, view) {
  container.innerHTML = '';
  const palette = GRAPH_STYLES[view] || GRAPH_STYLES.architecture;

  const cy = cytoscape({
    container,
    elements: [
      ...data.nodes.map(n => ({ data: { ...n } })),
      ...data.edges.map(e => ({ data: { ...e } })),
    ],
    style: [
      {
        selector: 'node',
        style: {
          'label':            'data(label)',
          'color':            '#e8f0fe',
          'font-size':        10,
          'font-family':      'IBM Plex Mono, monospace',
          'text-valign':      'bottom',
          'text-halign':      'center',
          'text-margin-y':    8,
          'text-wrap':        'wrap',
          'text-max-width':   90,
          'width':            52,
          'height':           52,
          'background-color': '#1d2f56',
          'border-color':     '#3b5fc0',
          'border-width':     2,
        }
      },
      // Type-specific styles from palette
      ...Object.entries(palette).map(([type, s]) => ({
        selector: `node[type="${type}"]`,
        style: {
          'background-color': s.bg,
          'border-color':     s.border,
          'shape':            s.shape || 'ellipse',
        }
      })),
      // Fraud network: high-risk policy gets red border
      {
        selector: 'node[risk="high"]',
        style: {
          'border-color': '#da1e28',
          'border-width':  3,
          'background-color': 'rgba(218,30,40,0.18)',
        }
      },
      {
        selector: 'edge',
        style: {
          'width':               1.5,
          'line-color':          '#2d4070',
          'target-arrow-color':  '#4589ff',
          'target-arrow-shape':  'triangle',
          'curve-style':         'bezier',
          'label':               'data(label)',
          'font-size':           8,
          'color':               '#3b5fc0',
          'font-family':         'IBM Plex Mono, monospace',
          'text-rotation':       'autorotate',
          'opacity':             0.85,
        }
      },
      {
        selector: 'node:selected',
        style: { 'border-width': 3, 'border-color': '#ffffff', 'z-index': 10 }
      },
    ],
    layout: view === 'architecture'
      ? { name: 'breadthfirst', directed: true, padding: 40, spacingFactor: 1.6, avoidOverlap: true }
      : { name: 'cose', padding: 50, nodeRepulsion: 8000, idealEdgeLength: 120,
          edgeElasticity: 100, gravity: 0.4, animate: true, animationDuration: 500,
          fit: true, randomize: false },
    userZoomingEnabled: true,
    userPanningEnabled: true,
  });

  cy.on('tap', 'node', (evt) => {
    cy.animate({ zoom: Math.min(cy.zoom() * 1.6, 3), center: { eles: evt.target } }, { duration: 280 });
  });
  cy.on('tap', (evt) => {
    if (evt.target === cy) cy.fit(undefined, 36);
  });
}

function renderGraphLegend(view) {
  const el = document.getElementById('graph-legend');
  if (!el) return;
  const items = GRAPH_LEGENDS[view] || [];
  el.innerHTML = items.map(item =>
    `<div class="legend-item">
       <div class="legend-dot" style="border-color:${item.color};background:${item.bg}"></div>
       ${esc(item.label)}
     </div>`
  ).join('');
}

// ─── LLM Calls — live table ────────────────────────────────────────────────────
function renderLlmCallsTab() {
  const calls = state.llmCalls;

  const TASK_COL = {
    fraud: 'var(--red,#e06c75)', adjudication: 'var(--magenta,#c678dd)',
    guardrails: 'var(--yellow)', extraction: 'var(--blue,#61afef)',
    audit_report: 'var(--green-lt)', general: 'var(--cyan)',
    customer_intent: 'var(--cyan)', summarization: 'var(--cyan)',
  };
  const MODEL_COL = {
    reasoning: 'var(--magenta,#c678dd)', guardian: 'var(--yellow)',
    extraction: 'var(--blue,#61afef)', general: 'var(--cyan)',
  };

  const latColour = ms => ms > 5000 ? 'var(--red,#e06c75)' : ms > 2000 ? 'var(--yellow)' : 'var(--green-lt)';

  const header = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
      <div>
        <span style="font-size:13px;font-weight:600;color:var(--text-primary)">Live LLM Calls</span>
        <span style="margin-left:10px;font-size:11px;color:var(--text-muted)">real-time — updates as scenarios run</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <span style="width:8px;height:8px;border-radius:50%;background:var(--cyan);display:inline-block;${calls.length ? 'animation:pulse 1.4s ease-in-out infinite' : 'opacity:.3'}"></span>
        <span style="font-family:var(--font-mono);font-size:11px;color:var(--cyan)">${calls.length} call${calls.length !== 1 ? 's' : ''}</span>
        ${calls.length ? `<button onclick="state.llmCalls=[];renderTab('llmcalls')" style="font-size:10px;color:var(--text-muted);background:none;border:1px solid var(--border);border-radius:2px;padding:2px 7px;cursor:pointer">Clear</button>` : ''}
      </div>
    </div>`;

  if (!calls.length) {
    return header + `<div class="trace-empty" style="margin-top:32px">No LLM calls yet — run a scenario to see live inference activity here.</div>`;
  }

  const TH = (label, align='left', extra='') =>
    `<th style="text-align:${align};padding:6px 10px 8px ${align==='right'?'4':'0'}px;color:var(--text-muted);font-weight:600;font-size:10px;letter-spacing:.06em;text-transform:uppercase;${extra}">${label}</th>`;

  const rows = [...calls].reverse().slice(0, 60).map((c, i) => {
    const taskCol  = TASK_COL[c.task_type]  || 'var(--text-secondary)';
    const modelKey = (c.model || '').split(':')[0].replace(/[0-9.-]/g,'').trim().toLowerCase();
    const modelCol = MODEL_COL[modelKey] || 'var(--text-secondary)';
    const lat = c.latency_ms;
    const latStr  = lat ? `${lat.toLocaleString()} ms` : '—';
    const latCol  = lat ? latColour(lat) : 'var(--text-muted)';
    const tokIn   = c.tokens_in  != null ? c.tokens_in  : '—';
    const tokOut  = c.tokens_out != null ? c.tokens_out : '—';
    const ts = new Date(c._ts || Date.now()).toISOString().slice(11, 23);
    return `<tr style="border-bottom:1px solid var(--border);${i===0?'background:var(--bg-hover)':''}">
      <td style="padding:7px 10px 7px 0;font-family:var(--font-mono);font-size:10px;color:var(--text-muted)">${ts}</td>
      <td style="padding:7px 10px 7px 0;font-size:11px;color:var(--cyan)">${esc(c.agent)}</td>
      <td style="padding:7px 10px 7px 0;font-family:var(--font-mono);font-size:10px;color:${taskCol}">${esc(c.task_type)}</td>
      <td style="padding:7px 10px 7px 0;font-family:var(--font-mono);font-size:10px;color:${modelCol}">${esc(c.model)}</td>
      <td style="padding:7px 4px 7px 0;font-family:var(--font-mono);font-size:11px;color:${latCol};text-align:right">${latStr}</td>
      <td style="padding:7px 4px 7px 0;font-family:var(--font-mono);font-size:10px;color:var(--text-muted);text-align:right">${tokIn}</td>
      <td style="padding:7px 0 7px 0;font-family:var(--font-mono);font-size:10px;color:var(--text-muted);text-align:right">${tokOut}</td>
    </tr>`;
  }).join('');

  return header + `
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead><tr style="border-bottom:1px solid var(--border)">
        ${TH('Time')} ${TH('Agent')} ${TH('Task')} ${TH('Model')} ${TH('Latency','right')} ${TH('Tok In','right')} ${TH('Tok Out','right')}
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ─── HITL Queue tab ────────────────────────────────────────────────────────────
let hitlOperatorId = 'OPS-001';

async function renderHitlTab() {
  const el = document.getElementById('tab-content');
  el.innerHTML = `<div class="trace-empty">Loading HITL queue…</div>`;

  let data;
  try {
    data = await apiFetch('/escalation/queue');
  } catch (e) {
    el.innerHTML = `<div class="trace-empty">Could not load queue: ${esc(e.message)}</div>`;
    return;
  }

  const tickets = data.tickets || [];

  // Update tab badge
  const badge = document.getElementById('hitl-count');
  if (badge) {
    badge.textContent = tickets.length ? `(${tickets.length})` : '';
    badge.style.color = tickets.length ? 'var(--orange)' : '';
  }

  const PRIORITY_COLOR = { critical: 'var(--red,#e06c75)', high: 'var(--orange)', normal: 'var(--cyan)', low: 'var(--text-muted)' };

  const operatorBar = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;padding:10px 14px;background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius)">
      <span style="font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);white-space:nowrap">Operator ID</span>
      <input id="hitl-operator-id" value="${esc(hitlOperatorId)}"
        oninput="hitlOperatorId=this.value"
        style="font-family:var(--font-mono);font-size:12px;background:var(--bg-base);border:1px solid var(--border);border-radius:3px;color:var(--cyan);padding:4px 8px;width:160px;outline:none"
        placeholder="OPS-001" />
      <span style="font-size:11px;color:var(--text-muted)">Applied to all resolution actions below</span>
      <button onclick="renderHitlTab()" style="margin-left:auto;font-size:11px;padding:4px 12px;background:var(--bg-elevated);border:1px solid var(--border);border-radius:3px;color:var(--text-secondary);cursor:pointer">↻ Refresh</button>
    </div>`;

  if (!tickets.length) {
    el.innerHTML = operatorBar + `
      <div style="text-align:center;padding:40px 20px;color:var(--text-muted);font-size:13px">
        <div style="font-size:32px;margin-bottom:12px">✓</div>
        No open escalation tickets — queue is clear.
      </div>`;
    return;
  }

  const cards = tickets.map(t => {
    const ctx = (() => { try { return typeof t.context_payload === 'string' ? JSON.parse(t.context_payload) : (t.context_payload || {}); } catch { return {}; } })();
    const priority = (t.priority || 'normal').toLowerCase();
    const pColor = PRIORITY_COLOR[priority] || 'var(--text-muted)';
    const ticketId = t.ticket_id || t.correlation_id || '—';
    const reason = t.reason || t.escalation_reason || '—';
    const claimId = ctx.claim_id || t.event_id || '—';
    const amount = ctx.amount_claimed != null ? `$${Number(ctx.amount_claimed).toLocaleString()}` : '—';
    const confidence = ctx.confidence != null ? `${(ctx.confidence * 100).toFixed(0)}%` : '—';
    const claimType = ctx.claim_type || ctx.event_type || '—';
    const safeId = ticketId.replace(/[^a-zA-Z0-9_-]/g, '_');

    return `
      <div id="card-${safeId}" style="background:var(--bg-card);border:1px solid var(--border);border-left:4px solid ${pColor};border-radius:var(--radius);margin-bottom:12px;overflow:hidden">

        <!-- Card header -->
        <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:var(--bg-elevated);border-bottom:1px solid var(--border)">
          <span style="font-size:10px;font-weight:700;font-family:var(--font-mono);color:${pColor};text-transform:uppercase;padding:1px 6px;border:1px solid ${pColor};border-radius:2px">${esc(priority)}</span>
          <span style="font-size:12px;font-weight:600;font-family:var(--font-mono);color:var(--text-primary)">${esc(ticketId)}</span>
          <span style="font-size:10px;color:var(--text-muted);font-family:var(--font-mono);margin-left:auto">${esc(t.event_type || t.squad_id || '')}</span>
        </div>

        <!-- Key facts -->
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:0;padding:10px 14px 6px">
          ${[
            ['Claim ID',    claimId],
            ['Amount',      amount],
            ['Claim Type',  claimType],
            ['Confidence',  confidence],
          ].map(([k,v]) => `
            <div style="padding:3px 8px 3px 0">
              <div style="font-size:9px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--text-muted)">${esc(k)}</div>
              <div style="font-size:12px;font-family:var(--font-mono);color:var(--text-primary)">${esc(String(v))}</div>
            </div>`
          ).join('')}
        </div>

        <!-- Reason -->
        <div style="padding:4px 14px 10px">
          <div style="font-size:9px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--text-muted);margin-bottom:3px">Escalation Reason</div>
          <div style="font-size:11px;color:var(--text-secondary);font-family:var(--font-mono);line-height:1.5">${esc(reason)}</div>
        </div>

        <!-- Rationale (if any) -->
        ${t.agent_rationale ? `
        <div style="padding:0 14px 10px">
          <div style="font-size:9px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--text-muted);margin-bottom:3px">Agent Rationale</div>
          <div style="font-size:11px;color:var(--text-secondary);line-height:1.5;font-style:italic">${esc(t.agent_rationale)}</div>
        </div>` : ''}

        <!-- Notes input + action buttons -->
        <div style="padding:8px 14px 12px;border-top:1px solid var(--border-subtle);display:flex;flex-direction:column;gap:8px">
          <textarea id="notes-${safeId}" placeholder="Resolution notes (optional)…"
            style="font-family:var(--font-mono);font-size:11px;background:var(--bg-base);border:1px solid var(--border);border-radius:3px;color:var(--text-secondary);padding:6px 8px;width:100%;height:48px;resize:none;outline:none"></textarea>
          <div style="display:flex;gap:8px">
            <button onclick="hitlResolve('${esc(ticketId)}','${safeId}','approve')"
              style="flex:1;padding:6px 0;font-size:12px;font-weight:600;background:rgba(36,161,72,0.15);border:1px solid var(--green);border-radius:var(--radius);color:var(--green-lt);cursor:pointer;transition:all 150ms">
              ✓ Approve
            </button>
            <button onclick="hitlResolve('${esc(ticketId)}','${safeId}','deny')"
              style="flex:1;padding:6px 0;font-size:12px;font-weight:600;background:rgba(218,30,40,0.12);border:1px solid var(--red);border-radius:var(--radius);color:var(--red);cursor:pointer;transition:all 150ms">
              ✕ Deny
            </button>
            <button onclick="hitlResolve('${esc(ticketId)}','${safeId}','defer')"
              style="flex:1;padding:6px 0;font-size:12px;font-weight:600;background:rgba(241,194,27,0.10);border:1px solid var(--yellow);border-radius:var(--radius);color:var(--yellow);cursor:pointer;transition:all 150ms">
              ⏸ Defer
            </button>
          </div>
        </div>
      </div>`;
  }).join('');

  el.innerHTML = operatorBar + cards;
}

async function hitlResolve(ticketId, safeId, resolution) {
  const notesEl = document.getElementById(`notes-${safeId}`);
  const notes = notesEl ? notesEl.value.trim() : '';
  const opId = (document.getElementById('hitl-operator-id') || {}).value || hitlOperatorId || 'OPS-001';

  const card = document.getElementById(`card-${safeId}`);
  if (card) card.style.opacity = '0.5';

  try {
    await apiFetch(`/escalation/${encodeURIComponent(ticketId)}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ operator_id: opId, resolution, resolution_notes: notes }),
    });
    if (card) {
      card.style.opacity = '1';
      card.style.borderLeftColor = resolution === 'approve' ? 'var(--green)' : resolution === 'deny' ? 'var(--red)' : 'var(--yellow)';
      card.innerHTML = `
        <div style="padding:16px 14px;text-align:center;font-family:var(--font-mono);color:var(--text-secondary)">
          <span style="font-size:18px">${resolution === 'approve' ? '✓' : resolution === 'deny' ? '✕' : '⏸'}</span>
          <div style="margin-top:6px;font-size:12px">
            Ticket <strong style="color:var(--text-primary)">${esc(ticketId)}</strong>
            resolved as <strong style="color:${resolution==='approve'?'var(--green-lt)':resolution==='deny'?'var(--red)':'var(--yellow)'}">${esc(resolution.toUpperCase())}</strong>
            by ${esc(opId)}
          </div>
        </div>`;
    }
    // Update badge count
    const badge = document.getElementById('hitl-count');
    if (badge) {
      const n = parseInt(badge.textContent.replace(/\D/g,'')) - 1;
      badge.textContent = n > 0 ? `(${n})` : '';
      badge.style.color = n > 0 ? 'var(--orange)' : '';
    }
  } catch (e) {
    if (card) card.style.opacity = '1';
    alert(`Resolution failed: ${e.message}`);
  }
}

// ─── How to Demo tab ───────────────────────────────────────────────────────────
function renderDemoTab() {
  const card = (icon, title, body) => `
    <div class="arch-card" style="margin-bottom:16px">
      <div class="arch-card-header">
        <div class="arch-card-icon">${icon}</div>
        <div class="arch-card-name">${title}</div>
      </div>
      <div class="arch-card-body">${body}</div>
    </div>`;

  const kv = (k, v, color='') => `
    <div class="arch-row">
      <div class="arch-row-key">${k}</div>
      <div class="arch-row-val ${color}">${v}</div>
    </div>`;

  const tip = (label, text, color='var(--cyan)') => `
    <div style="display:flex;gap:10px;align-items:flex-start;margin:6px 0;padding:8px 10px;background:var(--bg-hover);border-radius:4px;border-left:3px solid ${color}">
      <span style="font-size:11px;font-weight:700;color:${color};white-space:nowrap;min-width:90px">${label}</span>
      <span style="font-size:12px;color:var(--text-secondary);line-height:1.5">${text}</span>
    </div>`;

  const code = s => `<code style="font-family:var(--font-mono);font-size:11px;background:var(--bg-hover);padding:1px 5px;border-radius:3px;color:var(--cyan)">${esc(s)}</code>`;

  const scenarios = [
    {
      icon: '📋', id: 'claim_submitted', label: 'Claim Submitted',
      desc: 'The core claims pipeline: triage → adjudication → guard → audit → (optional) escalation.',
      fields: [
        ['amount_claimed', 'Try $5,000 (normal), $50,000 (high), $150,000 (critical). Amounts ≥ $100,000 force critical priority.'],
        ['is_repeat_claimant', 'Set to true — not yet wired to escalation, but run it twice with the same claim_id to trigger resubmission detection.'],
        ['notes', 'Add text like "My SSN is 123-45-6789" to test the PII guard. The guard will catch it and block downstream.'],
        ['claim_type', 'Try "unknown" to fail the coverage match and lower adjudication confidence below 0.75, triggering escalation.'],
      ],
      escalates: 'adjudication.confidence < 0.75  OR  adjudication.decision = escalate  OR  guard.passed = false  OR  resubmission detected',
    },
    {
      icon: '📄', id: 'document_received', label: 'Document Received',
      desc: 'OCR extraction → PII guard → Neo4j graph sync → audit.',
      fields: [
        ['raw_text', 'This is the full document text. Paste any text here — the Guard scans it for SSN (###-##-####), credit cards (16 digits), email, phone.'],
        ['raw_text (PII test)', 'Add "My SSN is 890-99-9999" anywhere in raw_text — Guard should now catch it and set pii_detected: true, passed: false.'],
        ['filename', 'Cosmetic only — used for logging and DB record. Try different extensions.'],
      ],
      escalates: 'No EscalationAgent in this flow. Guard failure is recorded in audit only.',
    },
    {
      icon: '🚨', id: 'fraud_signal_raised', label: 'Fraud Signal Raised',
      desc: 'Fraud detection → guard → audit → escalation (if risk_score ≥ 0.8).',
      fields: [
        ['severity', 'Use "high" or "critical" — the LLM uses this to score risk. "low" typically stays below 0.8 threshold.'],
        ['amount_claimed', 'Large amounts (> $100k) combined with high severity usually produce risk_score ≥ 0.8, triggering escalation.'],
        ['description', 'Mention "third claim", "duplicate invoice", "same vendor" — fraud keywords the LLM weights heavily.'],
      ],
      escalates: 'fraud_assessment.risk_score ≥ 0.8  OR  guard.passed = false',
    },
    {
      icon: '📝', id: 'policy_change_requested', label: 'Policy Change Requested',
      desc: 'Guard pre-screens the request, audit records outcome. Minimal pipeline — good for testing the guard alone.',
      fields: [
        ['change_description', 'Add PII here (SSN, email) to test the Guard in isolation without the full claims pipeline.'],
        ['notes', 'Any free text is scanned. Try "Contact claimant at user@example.com" to trigger EMAIL PII detection.'],
      ],
      escalates: 'No EscalationAgent. Only the guard gate applies here.',
    },
    {
      icon: '⚠️', id: 'catastrophe_alert_issued', label: 'Catastrophe Alert Issued',
      desc: 'Mass-loss exposure assessment via FraudDetectionAgent acting as a risk scorer, then audit.',
      fields: [
        ['estimated_exposure', 'Dollar value of total exposure. Try $500M, $2B, $10B — influences LLM risk assessment.'],
        ['severity', '"critical" will prompt the LLM for the most aggressive risk response.'],
        ['affected_regions', 'List of US states or regions. More regions = higher exposure signals.'],
      ],
      escalates: 'No EscalationAgent in this flow.',
    },
    {
      icon: '💬', id: 'customer_interaction_logged', label: 'Customer Interaction',
      desc: 'Intent detection via ClaimsTriageAgent → guard → audit → escalation (if confidence < 0.75).',
      fields: [
        ['customer_message', 'The free-text message from the customer. Vague messages lower confidence and can trigger escalation.'],
        ['customer_message (PII)', 'Include "call me at 555-867-5309" or an email to test phone/email PII detection.'],
        ['interaction_type', 'Try "complaint", "claim_status", "coverage_question" — signals the intent classification.'],
      ],
      escalates: 'intent.confidence < 0.75  OR  guard.passed = false',
    },
    {
      icon: '🔍', id: 'audit_query_received', label: 'Audit Query',
      desc: 'Query the immutable audit trail. No LLM involved.',
      fields: [
        ['limit', 'Number of records to return (default 10). Try higher values after running multiple scenarios.'],
        ['correlation_id', 'Copy a correlation_id from a previous run result to retrieve just that run\'s audit trail.'],
      ],
      escalates: 'No escalation — read-only compliance query.',
    },
  ];

  const scenarioCards = scenarios.map(s => {
    const fieldRows = s.fields.map(([f, desc]) =>
      `<div style="margin:5px 0 5px 0">
        <div style="font-size:10px;font-weight:700;color:var(--yellow);font-family:var(--font-mono);margin-bottom:2px">${esc(f)}</div>
        <div style="font-size:12px;color:var(--text-secondary);line-height:1.5;padding-left:4px">${esc(desc)}</div>
      </div>`
    ).join('<div style="height:1px;background:var(--border);margin:6px 0"></div>');

    return `
      <div class="arch-card" style="margin-bottom:14px">
        <div class="arch-card-header" style="cursor:pointer" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">
          <div class="arch-card-icon">${s.icon}</div>
          <div style="flex:1">
            <div class="arch-card-name">${esc(s.label)}</div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">${esc(s.id)}</div>
          </div>
          <div style="font-size:10px;color:var(--text-muted);font-family:var(--font-mono)">click to expand ▼</div>
        </div>
        <div class="arch-card-body" style="display:none">
          <div style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;line-height:1.6">${esc(s.desc)}</div>
          <div style="font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);margin-bottom:8px">Fields to experiment with</div>
          ${fieldRows}
          <div style="margin-top:12px;padding:7px 10px;background:var(--bg-hover);border-radius:4px;border-left:3px solid var(--green-lt)">
            <span style="font-size:10px;font-weight:700;color:var(--green-lt)">ESCALATES WHEN  </span>
            <span style="font-size:11px;color:var(--text-secondary);font-family:var(--font-mono)">${esc(s.escalates)}</span>
          </div>
        </div>
      </div>`;
  }).join('');

  const quickRef = `
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px">
      ${[
        ['Force escalation', 'Set amount_claimed to 0 and claim_type to "unknown" — completeness × coverage = 0.0 confidence, always escalates', 'var(--red,#e06c75)'],
        ['Trigger PII guard', 'Add "SSN: 123-45-6789" in any notes/raw_text/description field — regex catches it before LLM sees it', 'var(--yellow)'],
        ['Resubmission test', 'Run Claim Submitted twice with the same claim_id — 2nd run sets is_resubmission=true and forces critical priority + escalation', 'var(--magenta,#c678dd)'],
        ['High-risk fraud', 'Fraud scenario: set severity=critical, amount=200000, description mentioning "duplicate invoice" — risk_score ≥ 0.8', 'var(--red,#e06c75)'],
        ['Low confidence path', 'Set claim_type="unknown" in claim_submitted — coverage_match=false, confidence drops to 0.5, adjudication likely escalates', 'var(--cyan)'],
        ['Happy path', 'claim_submitted with amount 10000–50000, valid claim_type, no PII in notes — typically approve with confidence ≥ 0.75', 'var(--green-lt)'],
      ].map(([title, desc, color]) => `
        <div style="padding:10px;background:var(--bg-hover);border-radius:4px;border-left:3px solid ${color}">
          <div style="font-size:11px;font-weight:700;color:${color};margin-bottom:4px">${esc(title)}</div>
          <div style="font-size:11px;color:var(--text-secondary);line-height:1.5">${esc(desc)}</div>
        </div>`
      ).join('')}
    </div>`;

  return `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:flex-start">

      <!-- LEFT: overview + quick ref -->
      <div>
        ${card('✦', 'How This Demo Works',
          `<div style="font-size:12px;color:var(--text-secondary);line-height:1.7">
            <p style="margin:0 0 10px">Select a scenario in the left panel. The payload editor pre-loads a working example JSON. Edit the JSON freely and click <strong style="color:var(--cyan)">RUN SCENARIO</strong> to push it through the full K9-AIF pipeline.</p>
            <p style="margin:0 0 10px">Every run goes through: <strong style="color:var(--text-primary)">Router → Orchestrator → SquadLoader → Squad → Agents → GuardAgent → AuditAgent → (EscalationAgent)</strong>. The Runtime Trace panel on the right shows each step with real outputs.</p>
            <p style="margin:0">Click any step in the Runtime Trace to open the Agent Detail drawer — it shows the YAML config, model routing decision, governance checks, and the actual agent output for that step.</p>
          </div>`
        )}
        ${card('🔑', 'Key JSON Fields Across All Scenarios',
          [
            kv('event_type', 'Set automatically — matches the scenario you selected', 'cyan'),
            kv('correlation_id', 'Auto-generated UUID. You can supply your own to trace across runs', ''),
            kv('event_id', 'Auto-generated per run. Used to link audit trail entries', ''),
            kv('claim_id', 'Stable across runs. Same ID on 2nd run = resubmission detected', 'yellow'),
            kv('claimant_id', 'Links claims, documents, and fraud signals to one claimant in Neo4j', ''),
            kv('policy_id', 'Must exist (or will be stub-created). Links claim to coverage', ''),
          ].join('')
        )}
        ${card('⚡', 'Quick-Reference: Interesting Scenarios to Try', quickRef)}
      </div>

      <!-- RIGHT: per-scenario breakdown -->
      <div>
        <div style="font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--text-muted);margin-bottom:12px">Scenarios — click to expand</div>
        ${scenarioCards}
      </div>

    </div>`;
}

// ─── Live feed V2 ──────────────────────────────────────────────────────────────
function renderLiveFeed() {
  const TOPIC_CLS = {
    'claim_submitted':              'claims',
    'document_received':            'documents',
    'fraud_signal_raised':          'fraud',
    'policy_change_requested':      'policy',
    'catastrophe_alert_issued':     'catastrophe',
    'customer_interaction_logged':  'customer',
    'audit_query_received':         'audit',
    'scenario_run':                 'scenario',
  };

  if (state.liveEvents.length === 0) {
    return '<div class="trace-empty">No events yet — run a scenario to see live activity.</div>';
  }

  // Counter badges
  const counts = {};
  state.liveEvents.forEach(e => {
    const t = e.event_type || e.type || 'unknown';
    counts[t] = (counts[t] || 0) + 1;
  });

  const counterHtml = Object.entries(counts).map(([topic, cnt]) => {
    const cls = TOPIC_CLS[topic] || '';
    return `<div class="topic-counter">
      <span class="live-topic ${cls}" style="font-size:9px">${esc(topic.replace(/_/g, ' '))}</span>
      <span class="tc-count">${cnt}</span>
    </div>`;
  }).join('');

  const rows = [...state.liveEvents].reverse().slice(0, 60).map(e => {
    const topic    = e.event_type || e.type || 'unknown';
    const topicCls = TOPIC_CLS[topic] || '';
    const stCls    = (e.status === 'completed' || e.status === 'ok') ? 'ok' : 'error';
    return `<div class="live-event-row">
      <div class="live-ts">${esc(new Date(e._ts || Date.now()).toISOString().slice(11, 23))}</div>
      <div class="live-topic ${topicCls}">${esc(topic.replace(/_/g, ' '))}</div>
      <div class="live-status ${stCls}">${esc(e.status || '—')}</div>
      <div class="live-msg">${esc(e.event_id || e.correlation_id || '—')}</div>
    </div>`;
  }).join('');

  return `
    <div class="topic-counters">${counterHtml}</div>
    <div class="live-feed-v2">
      <div class="live-feed-header"><span>TIME</span><span>EVENT TYPE</span><span>STATUS</span><span>ID</span></div>
      ${rows}
    </div>`;
}

// ─── SSE live feed ────────────────────────────────────────────────────────────
function connectSSE() {
  if (state.sseSource) state.sseSource.close();
  const es = new EventSource('/events/stream');
  es.onmessage = (e) => {
    try {
      const evt = JSON.parse(e.data);
      evt._ts = Date.now();
      state.liveEvents.push(evt);
      if (state.liveEvents.length > 200) state.liveEvents.shift();
      setText('live-count', `(${state.liveEvents.length})`);
      if (state.activeTab === 'livefeed') renderTab('livefeed');

      if (evt.type === 'EscalationRaised') {
        state.hitlCount = (state.hitlCount || 0) + 1;
        const b = document.getElementById('hitl-count');
        if (b) { b.textContent = `(${state.hitlCount})`; b.style.color = 'var(--orange)'; }
        if (state.activeTab === 'hitl') renderHitlTab();
      }
      if (evt.type === 'EscalationResolved') {
        state.hitlCount = Math.max(0, (state.hitlCount || 1) - 1);
        const b = document.getElementById('hitl-count');
        if (b) { b.textContent = state.hitlCount ? `(${state.hitlCount})` : ''; b.style.color = state.hitlCount ? 'var(--orange)' : ''; }
      }
      if (evt.type === 'LLMCall') {
        state.llmCalls.push(evt);
        if (state.llmCalls.length > 100) state.llmCalls.shift();
        const dot = document.getElementById('llm-call-dot');
        if (dot) {
          dot.classList.add('active');
          clearTimeout(dot._t);
          dot._t = setTimeout(() => dot.classList.remove('active'), 800);
        }
      }
    } catch {}
  };
  es.onerror = () => {};
  state.sseSource = es;
}

// ─── DOM utilities ────────────────────────────────────────────────────────────
function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function delay(ms) {
  return new Promise(r => setTimeout(r, ms));
}

// ─── Entry point ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
