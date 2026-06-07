import { useState } from "react";
import { CLIENT_ID, previewChat } from "./api/index.js";
import { MessageBubble } from "./components/MessageBubble.jsx";
import { SourceList } from "./components/SourceList.jsx";
import { ConfidenceBadge } from "./components/ConfidenceBadge.jsx";

export function PreviewPanel() {
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [indexScope, setIndexScope] = useState("active");
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState("Enter admin token and message.");
  const [busy, setBusy] = useState(false);

  async function onPreview(e) {
    e.preventDefault();
    if (!token.trim() || !message.trim()) {
      setStatus("Token and message are required.");
      return;
    }
    setBusy(true);
    setStatus("Running preview...");
    try {
      const data = await previewChat({
        clientId: CLIENT_ID,
        token: token.trim(),
        message: message.trim(),
        indexScope,
      });
      setResult(data);
      setStatus("Preview complete.");
    } catch (err) {
      setResult(null);
      setStatus(err.message || "Preview failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="admin-shell preview-shell">
      <div className="admin-header">
        <h3>Platform Admin Preview</h3>
        <p className="preview-note">Token is kept in memory only — never stored in browser storage.</p>
      </div>
      <form className="preview-form" onSubmit={onPreview}>
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="x-admin-token"
          autoComplete="off"
        />
        <select value={indexScope} onChange={(e) => setIndexScope(e.target.value)}>
          <option value="active">index_scope: active</option>
          <option value="pending">index_scope: pending</option>
        </select>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Preview message..."
          rows={3}
        />
        <button type="submit" disabled={busy}>
          Run preview
        </button>
      </form>
      <div className="preview-status">{status}</div>
      {result ? (
        <div className="preview-result">
          <MessageBubble
            message={{
              role: "assistant",
              content: result.answer,
              meta: {
                sources: result.sources,
                confidence: result.confidence,
                requires_human: result.requires_human,
                escalation: result.escalation,
              },
            }}
          />
          <SourceList sources={result.sources} />
          <ConfidenceBadge confidence={result.confidence} />
          <pre className="preview-summary">{JSON.stringify(result.summary || {}, null, 2)}</pre>
        </div>
      ) : null}
    </div>
  );
}
