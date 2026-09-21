// K9Chat — ChatInput component
// Owns the textarea + send button, the generating/disabled state, the
// "thinking" placeholder, and the two network paths (/chat, /chat/stream).
// Uses SessionSidebar for the active session id and MessageList for all
// rendering/persistence — this module has no localStorage access of its own.

const ChatInput = (() => {
  const messageInput = document.getElementById("message-input");
  const sendBtn = document.getElementById("send-btn");
  const clearBtn = document.getElementById("clear-btn");
  const attachBtn = document.getElementById("attach-btn");
  const attachFileInput = document.getElementById("attach-file-input");
  const attachmentChip = document.getElementById("attachment-chip");

  let streamEnabled = false;
  fetch("/chat/config").then(r => r.json()).then(cfg => { streamEnabled = !!cfg.stream; });

  // Single-message file attach -- read client-side, no upload endpoint or
  // persistence needed, since this is scoped to one message rather than
  // a Project's permanent knowledge base. 200KB cap keeps one attached
  // file from blowing out the prompt.
  const MAX_ATTACHMENT_BYTES = 200 * 1024;
  let attachedFile = null; // { name, content }

  function clearAttachment() {
    attachedFile = null;
    attachFileInput.value = "";
    attachmentChip.style.display = "none";
    attachmentChip.innerHTML = "";
  }

  function showAttachmentChip() {
    attachmentChip.innerHTML = "";
    const nameEl = document.createElement("span");
    nameEl.className = "name";
    nameEl.textContent = `📎 ${attachedFile.name}`;
    const removeBtn = document.createElement("button");
    removeBtn.className = "remove";
    removeBtn.textContent = "✕";
    removeBtn.title = "Remove attachment";
    removeBtn.addEventListener("click", clearAttachment);
    attachmentChip.appendChild(nameEl);
    attachmentChip.appendChild(removeBtn);
    attachmentChip.style.display = "flex";
  }

  attachBtn.addEventListener("click", () => attachFileInput.click());

  attachFileInput.addEventListener("change", () => {
    const file = attachFileInput.files[0];
    if (!file) return;
    if (file.size > MAX_ATTACHMENT_BYTES) {
      alert(`"${file.name}" is too large (${Math.round(file.size / 1024)} KB) -- 200 KB max for a single-message attachment.`);
      attachFileInput.value = "";
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      attachedFile = { name: file.name, content: reader.result };
      showAttachmentChip();
    };
    reader.onerror = () => {
      alert(`Could not read "${file.name}".`);
    };
    reader.readAsText(file);
  });

  function setGenerating(isGenerating) {
    messageInput.disabled = isGenerating;
    sendBtn.disabled = isGenerating;
    sendBtn.textContent = isGenerating ? "…" : "➤";
    sendBtn.title = isGenerating ? "Generating…" : "Send";
  }

  async function send() {
    const typed = messageInput.value.trim();
    if (!typed && !attachedFile) return;
    const sessionId = SessionSidebar.activeId;

    // Displayed/persisted bubble stays short (just what was typed, plus a
    // 📎 note) -- the full file content only goes to the backend, same
    // "supplementary, not the main event" principle project/knowledge
    // context already follow server-side.
    const displayText = attachedFile
      ? `${typed}${typed ? "\n\n" : ""}📎 ${attachedFile.name}`
      : typed;
    const sendText = attachedFile
      ? `[Attached file: ${attachedFile.name}]\n\`\`\`\n${attachedFile.content}\n\`\`\`\n\n${typed}`
      : typed;

    MessageList.appendMessage(sessionId, "user", displayText);
    SessionSidebar.setTitleFromFirstMessage(sessionId, displayText);
    SessionSidebar.touch(sessionId);
    messageInput.value = "";
    clearAttachment();
    setGenerating(true);

    const thinkingNode = MessageList.addThinkingBubble();

    try {
      if (streamEnabled) {
        await sendStreaming(sendText, sessionId, thinkingNode);
      } else {
        const response = await fetch("/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: sendText, session_id: sessionId, project_id: ProjectPanel.activeProjectId,
            unhinged_level: Number(document.getElementById("unhinged-slider")?.value || 0),
            profanity_level: Number(document.getElementById("profanity-slider")?.value || 0),
          }),
        });
        const data = await response.json();
        MessageList.removeNode(thinkingNode);
        MessageList.appendMessage(sessionId, "assistant", data.reply || "", {
          elapsed_ms: data.elapsed_ms,
          evaluation: data.evaluation,
        });
        if (data.learned_correction) {
          MessageList.showLearnToast(data.learned_correction.corrected_fact);
        }
        SessionSidebar.touch(sessionId, { model: data.model });
        ArchitectureTrace.record({
          input: text,
          provider: data.provider,
          model: data.model,
          base_url: data.base_url,
          elapsed_ms: data.elapsed_ms,
          mode: "sync",
        });
      }
    } catch (error) {
      MessageList.removeNode(thinkingNode);
      MessageList.appendMessage(sessionId, "assistant", "Error: unable to reach K9Chat backend.");
    } finally {
      setGenerating(false);
    }
  }

  async function sendStreaming(text, sessionId, thinkingNode) {
    const response = await fetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
            message: text, session_id: sessionId, project_id: ProjectPanel.activeProjectId,
            unhinged_level: Number(document.getElementById("unhinged-slider")?.value || 0),
            profanity_level: Number(document.getElementById("profanity-slider")?.value || 0),
          }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let fullText = "";
    let bubbleRef = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n\n");
      buffer = lines.pop(); // keep incomplete trailing chunk

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const data = JSON.parse(line.slice(6));

        if (data.queued) {
          const bubbleEl = thinkingNode.querySelector(".bubble");
          if (bubbleEl) {
            bubbleEl.classList.remove("thinking");
            bubbleEl.textContent = `Waiting for a free slot — ${data.position} ahead of you...`;
          }
        }

        if (data.chunk) {
          if (!bubbleRef) {
            MessageList.removeNode(thinkingNode);
            bubbleRef = MessageList.addBubble("assistant", "", {});
          }
          fullText += data.chunk;
          bubbleRef.bubble.textContent = fullText;
          MessageList.scrollToBottom();
        }

        if (data.done) {
          if (!bubbleRef) {
            MessageList.removeNode(thinkingNode);
            bubbleRef = MessageList.addBubble("assistant", fullText, {});
          }
          if (bubbleRef.elapsedSpan && data.elapsed_ms != null) {
            bubbleRef.elapsedSpan.textContent =
              data.elapsed_ms < 1000 ? `${data.elapsed_ms} ms` : `${(data.elapsed_ms / 1000).toFixed(1)} s`;
          }
          if (data.evaluation) {
            MessageList.addEvalBadge(bubbleRef, data.evaluation);
          }
          if (data.learned_correction) {
            MessageList.showLearnToast(data.learned_correction.corrected_fact);
          }
          MessageList.persistMessage(sessionId, "assistant", fullText, {
            elapsed_ms: data.elapsed_ms,
            evaluation: data.evaluation,
          });
          SessionSidebar.touch(sessionId, { model: data.model });
          ArchitectureTrace.record({
            input: text,
            provider: data.provider,
            model: data.model,
            base_url: data.base_url,
            elapsed_ms: data.elapsed_ms,
            mode: "stream",
          });
          return;
        }
      }
    }
  }

  sendBtn.addEventListener("click", send);

  messageInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  });

  clearBtn.addEventListener("click", function () {
    const sessionId = SessionSidebar.activeId;
    MessageList.clear(sessionId);
    fetch(`/chat/session/${sessionId}`, { method: "DELETE" }).catch(() => {});
    MessageList.renderHistory(sessionId);
    SessionSidebar.render();
  });

  return {
    send,
    setStreamEnabled: (enabled) => { streamEnabled = enabled; },
  };
})();
