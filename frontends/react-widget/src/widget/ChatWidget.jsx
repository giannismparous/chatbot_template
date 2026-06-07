import { useEffect, useMemo, useState } from "react";
import {
  CLIENT_ID,
  clearSessionId,
  fetchPublicConfig,
  fetchTheme,
  sendChat,
  themeCssVars,
  themeFeatures,
} from "./api/index.js";
import { MessageBubble } from "./components/MessageBubble.jsx";

const GREETING = "Hello! How can I help you today?";

export function ChatWidget() {
  const [theme, setTheme] = useState(null);
  const [publicConfig, setPublicConfig] = useState(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([{ role: "assistant", content: GREETING }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([fetchTheme(CLIENT_ID), fetchPublicConfig(CLIENT_ID).catch(() => ({}))])
      .then(([themeData, configData]) => {
        setTheme(themeData);
        setPublicConfig(configData);
      })
      .catch(() => setTheme({}));
  }, []);

  const features = useMemo(() => themeFeatures(theme || {}), [theme]);
  const cssVars = useMemo(() => themeCssVars(theme || {}), [theme]);
  const suggested = publicConfig?.suggested_questions || theme?.suggested_questions || [];
  const title = publicConfig?.display_name || theme?.display_name || "Chat Assistant";

  async function onSend(e) {
    e.preventDefault();
    if (!input.trim() || busy) return;
    const question = input.trim();
    setError("");
    setMessages((prev) => [
      ...prev,
      { role: "user", content: question },
      { role: "assistant", content: "", streaming: true, meta: {} },
    ]);
    setInput("");
    setBusy(true);

    try {
      const result = await sendChat({
        clientId: CLIENT_ID,
        message: question,
        streaming: features.streaming_enabled,
        onChunk: (text) => {
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last?.role === "assistant") {
              next[next.length - 1] = {
                ...last,
                content: (last.content || "") + text,
                streaming: true,
                meta: last.meta || {},
              };
            }
            return next;
          });
        },
      });

      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          role: "assistant",
          content: result.answer,
          streaming: false,
          meta: {
            sources: result.sources,
            confidence: result.confidence,
            requires_human: result.requires_human,
            escalation: result.escalation,
          },
        };
        return next;
      });
    } catch (err) {
      setError(err.message || "Unable to reach the assistant. Please try again.");
      setMessages((prev) => {
        const next = [...prev];
        if (next[next.length - 1]?.role === "assistant") next.pop();
        next.push({
          role: "assistant",
          content: "Unable to reach the assistant. Please try again.",
          meta: { confidence: { level: "none", reason: "Request failed." } },
        });
        return next;
      });
    } finally {
      setBusy(false);
    }
  }

  function onNewConversation() {
    clearSessionId(CLIENT_ID);
    setMessages([{ role: "assistant", content: GREETING }]);
    setError("");
  }

  return (
    <div className="chat-shell" style={cssVars}>
      <div className="chat-header">
        <span>{title}</span>
        <button type="button" className="link-btn" onClick={onNewConversation}>
          New chat
        </button>
      </div>
      <div className="chat-body">
        {messages.map((m, idx) => (
          <MessageBubble
            key={idx}
            message={m}
            showConfidence={features.show_confidence}
            showSources={features.citation_rendering}
          />
        ))}
        {error ? <div className="chat-error">{error}</div> : null}
      </div>
      {suggested.length ? (
        <div className="suggested-row">
          {suggested.slice(0, 4).map((q) => (
            <button key={q} type="button" className="suggested-chip" onClick={() => setInput(String(q))}>
              {q}
            </button>
          ))}
        </div>
      ) : null}
      <form className="chat-input-row" onSubmit={onSend}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Type your message..." />
        <button type="submit" disabled={busy}>
          {busy ? "..." : "Send"}
        </button>
      </form>
    </div>
  );
}
