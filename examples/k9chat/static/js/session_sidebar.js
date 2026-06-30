// K9Chat — SessionSidebar component
// Owns the session list (localStorage: k9chat_sessions) and the active
// session pointer. Depends on MessageList only to read message counts for
// the per-session metadata line; rendering of the transcript itself stays
// in MessageList.

const SessionSidebar = (() => {
  const listEl = document.getElementById("session-list");
  const newChatBtn = document.getElementById("new-chat-btn");

  let activeId = null;
  let onSwitch = null; // set by app.js: function(sessionId)

  function loadSessions() {
    return JSON.parse(localStorage.getItem("k9chat_sessions") || "[]");
  }

  function saveSessions(list) {
    localStorage.setItem("k9chat_sessions", JSON.stringify(list));
  }

  function genId() {
    return "sess-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
  }

  function create() {
    const id = genId();
    const sessions = loadSessions();
    sessions.unshift({ id, title: "New chat", model: null, lastUpdated: Date.now() });
    saveSessions(sessions);
    MessageList.saveMessages(id, []);
    return id;
  }

  function ensureActive() {
    let sessions = loadSessions();
    if (sessions.length === 0) {
      create();
      sessions = loadSessions();
    }
    let id = localStorage.getItem("k9chat_active_session");
    if (!id || !sessions.find(s => s.id === id)) {
      id = sessions[0].id;
    }
    activeId = id;
    localStorage.setItem("k9chat_active_session", id);
    return id;
  }

  function switchTo(id) {
    activeId = id;
    localStorage.setItem("k9chat_active_session", id);
    render();
    if (onSwitch) onSwitch(id);
  }

  function formatRelative(ts) {
    if (!ts) return "—";
    const diffMs = Date.now() - ts;
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  }

  function render() {
    const sessions = loadSessions();
    listEl.innerHTML = "";
    sessions.forEach(s => {
      const messages = MessageList.loadMessages(s.id);

      const item = document.createElement("div");
      item.className = "session-item" + (s.id === activeId ? " active" : "");
      item.addEventListener("click", () => switchTo(s.id));

      const col = document.createElement("div");
      col.className = "session-col";

      const title = document.createElement("div");
      title.className = "session-title";
      title.textContent = s.title;
      col.appendChild(title);

      const meta = document.createElement("div");
      meta.className = "session-meta";
      const modelLabel = s.model || "—";
      const msgWord = messages.length === 1 ? "msg" : "msgs";
      meta.textContent = `${modelLabel} · ${messages.length} ${msgWord} · ${formatRelative(s.lastUpdated)}`;
      col.appendChild(meta);

      const del = document.createElement("button");
      del.className = "session-delete";
      del.textContent = "×";
      del.title = "Delete chat";
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        remove(s.id);
      });

      item.appendChild(col);
      item.appendChild(del);
      listEl.appendChild(item);
    });
  }

  function remove(id) {
    let sessions = loadSessions().filter(s => s.id !== id);
    localStorage.removeItem("k9chat_msgs_" + id);
    fetch(`/chat/session/${id}`, { method: "DELETE" }).catch(() => {});

    if (sessions.length === 0) {
      const newId = create();
      switchTo(newId);
      return;
    }
    saveSessions(sessions);
    if (id === activeId) {
      switchTo(sessions[0].id);
    } else {
      render();
    }
  }

  function touch(id, { model } = {}) {
    const sessions = loadSessions();
    const current = sessions.find(s => s.id === id);
    if (!current) return;
    current.lastUpdated = Date.now();
    if (model) current.model = model;
    saveSessions(sessions);
    render();
  }

  function setTitleFromFirstMessage(id, text) {
    const sessions = loadSessions();
    const current = sessions.find(s => s.id === id);
    if (current && current.title === "New chat") {
      current.title = text.length > 40 ? text.slice(0, 40) + "…" : text;
      saveSessions(sessions);
      render();
    }
  }

  newChatBtn.addEventListener("click", () => {
    const id = create();
    switchTo(id);
  });

  return {
    get activeId() { return activeId; },
    set onSwitch(fn) { onSwitch = fn; },
    ensureActive,
    switchTo,
    render,
    create,
    remove,
    touch,
    setTitleFromFirstMessage,
  };
})();
