// K9Chat — MessageList / MessageBubble component
// Renders the chat transcript for the active session and persists messages
// to localStorage (k9chat_msgs_<session_id>). No backend calls here — the
// network requests live in ChatInput; this module only owns rendering +
// local persistence.

const MessageList = (() => {
  const chatHistoryEl = document.getElementById("chat-history");

  function loadMessages(sessionId) {
    return JSON.parse(localStorage.getItem("k9chat_msgs_" + sessionId) || "[]");
  }

  function saveMessages(sessionId, msgs) {
    localStorage.setItem("k9chat_msgs_" + sessionId, JSON.stringify(msgs));
  }

  function formatElapsed(ms) {
    return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }

  function formatTime(ts) {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function scrollToBottom() {
    chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;
  }

  function copyToClipboard(text, btn) {
    navigator.clipboard.writeText(text).then(() => {
      const original = btn.textContent;
      btn.textContent = "✓";
      setTimeout(() => { btn.textContent = original; }, 1200);
    }).catch(() => {});
  }

  // MessageBubble — builds one message DOM node (user or assistant)
  function addBubble(role, text, meta = {}) {
    const wrapper = document.createElement("div");
    wrapper.className = `message ${role}`;

    const col = document.createElement("div");
    col.className = "msg-col";

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    col.appendChild(bubble);

    const metaRow = document.createElement("div");
    metaRow.className = "msg-meta";

    const timeSpan = document.createElement("span");
    timeSpan.className = "msg-time";
    if (meta.ts) timeSpan.textContent = formatTime(meta.ts);
    metaRow.appendChild(timeSpan);

    let elapsedSpan = null;
    if (role === "assistant") {
      elapsedSpan = document.createElement("span");
      elapsedSpan.className = "msg-elapsed";
      if (meta.elapsed_ms != null) elapsedSpan.textContent = formatElapsed(meta.elapsed_ms);
      metaRow.appendChild(elapsedSpan);

      const copyBtn = document.createElement("button");
      copyBtn.className = "msg-copy";
      copyBtn.title = "Copy response";
      copyBtn.textContent = "⧉";
      copyBtn.addEventListener("click", () => copyToClipboard(bubble.textContent, copyBtn));
      metaRow.appendChild(copyBtn);

      if (meta.evaluation) {
        const ev = meta.evaluation;
        const gradeEl = document.createElement("span");
        gradeEl.className = `msg-grade grade-${ev.grade.toLowerCase()}`;
        gradeEl.title = `${ev.verdict} · Score: ${ev.score} · ${ev.rationale}`;
        gradeEl.textContent = `${ev.grade} ${ev.score}`;
        metaRow.appendChild(gradeEl);
      }
    }

    col.appendChild(metaRow);
    wrapper.appendChild(col);
    chatHistoryEl.appendChild(wrapper);
    scrollToBottom();

    return { wrapper, bubble, timeSpan, elapsedSpan };
  }

  function addThinkingBubble() {
    const wrapper = document.createElement("div");
    wrapper.className = "message assistant";
    const col = document.createElement("div");
    col.className = "msg-col";
    const bubble = document.createElement("div");
    bubble.className = "bubble thinking";
    bubble.innerHTML = `<span class="dot"></span><span class="dot"></span><span class="dot"></span>`;
    col.appendChild(bubble);
    wrapper.appendChild(col);
    chatHistoryEl.appendChild(wrapper);
    scrollToBottom();
    return wrapper;
  }

  function removeNode(node) {
    if (node && node.parentNode) node.parentNode.removeChild(node);
  }

  function persistMessage(sessionId, role, text, meta = {}) {
    const messages = loadMessages(sessionId);
    const entry = { role, content: text, ts: meta.ts || Date.now() };
    if (meta.elapsed_ms != null) entry.elapsed_ms = meta.elapsed_ms;
    messages.push(entry);
    saveMessages(sessionId, messages);
    return messages;
  }

  function appendMessage(sessionId, role, text, meta = {}) {
    const ts = meta.ts || Date.now();
    addBubble(role, text, { ...meta, ts });
    return persistMessage(sessionId, role, text, { ...meta, ts });
  }

  function renderHistory(sessionId) {
    const messages = loadMessages(sessionId);
    chatHistoryEl.innerHTML = "";
    if (messages.length === 0) {
      addBubble("assistant", "Hello. K9Chat is ready.", {});
      return;
    }
    messages.forEach(m => addBubble(m.role, m.content, m));
  }

  function clear(sessionId) {
    saveMessages(sessionId, []);
    chatHistoryEl.innerHTML = "";
  }

  function addEvalBadge(bubbleRef, evaluation) {
    if (!evaluation || !bubbleRef) return;
    const metaRow = bubbleRef.wrapper.querySelector(".msg-meta");
    if (!metaRow) return;
    if (metaRow.querySelector(".msg-grade")) return; // already added
    const ev = evaluation;
    const gradeEl = document.createElement("span");
    gradeEl.className = `msg-grade grade-${ev.grade.toLowerCase()}`;
    gradeEl.title = `${ev.verdict} · Score: ${ev.score} · ${ev.rationale}`;
    gradeEl.textContent = `${ev.grade} ${ev.score}`;
    metaRow.appendChild(gradeEl);
  }

  return {
    loadMessages,
    saveMessages,
    renderHistory,
    addBubble,
    addThinkingBubble,
    addEvalBadge,
    removeNode,
    appendMessage,
    persistMessage,
    scrollToBottom,
    clear,
  };
})();
