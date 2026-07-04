// K9Chat — ChatInput component
// Owns the textarea + send button, the generating/disabled state, the
// "thinking" placeholder, and the two network paths (/chat, /chat/stream).
// Uses SessionSidebar for the active session id and MessageList for all
// rendering/persistence — this module has no localStorage access of its own.

const ChatInput = (() => {
  const messageInput = document.getElementById("message-input");
  const sendBtn = document.getElementById("send-btn");
  const clearBtn = document.getElementById("clear-btn");

  let streamEnabled = false;
  fetch("/chat/config").then(r => r.json()).then(cfg => { streamEnabled = !!cfg.stream; });

  function setGenerating(isGenerating) {
    messageInput.disabled = isGenerating;
    sendBtn.disabled = isGenerating;
    sendBtn.textContent = isGenerating ? "…" : "➤";
    sendBtn.title = isGenerating ? "Generating…" : "Send";
  }

  async function send() {
    const text = messageInput.value.trim();
    if (!text) return;
    const sessionId = SessionSidebar.activeId;

    MessageList.appendMessage(sessionId, "user", text);
    SessionSidebar.setTitleFromFirstMessage(sessionId, text);
    SessionSidebar.touch(sessionId);
    messageInput.value = "";
    setGenerating(true);

    const thinkingNode = MessageList.addThinkingBubble();

    try {
      if (streamEnabled) {
        await sendStreaming(text, sessionId, thinkingNode);
      } else {
        const response = await fetch("/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, session_id: sessionId }),
        });
        const data = await response.json();
        MessageList.removeNode(thinkingNode);
        MessageList.appendMessage(sessionId, "assistant", data.reply || "", {
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
      body: JSON.stringify({ message: text, session_id: sessionId }),
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

  return { send };
})();
