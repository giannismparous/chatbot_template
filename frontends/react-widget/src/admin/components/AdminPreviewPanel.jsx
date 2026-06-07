import { useState } from "react";
import { useAdmin } from "../AdminContext.jsx";
import { previewChat } from "../api/adminClient.js";
import { MessageBubble } from "../../widget/components/MessageBubble.jsx";

export function AdminPreviewPanel({ clientId }) {
  const { token } = useAdmin();
  const [message, setMessage] = useState("");
  const [indexScope, setIndexScope] = useState("active");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onPreview(e) {
    e.preventDefault();
    if (!message.trim()) return;
    setBusy(true);
    setError("");
    try {
      const data = await previewChat(token, clientId, {
        message: message.trim(),
        indexScope,
      });
      setResult(data);
    } catch (err) {
      setResult(null);
      setError(err.message || "Preview failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="admin-section">
      <h4>Preview chatbot</h4>
      <form className="admin-form-grid" onSubmit={onPreview}>
        <select value={indexScope} onChange={(e) => setIndexScope(e.target.value)}>
          <option value="active">index_scope: active</option>
          <option value="pending">index_scope: pending</option>
        </select>
        <textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Preview message..." rows={3} />
        <button type="submit" disabled={busy}>
          Run preview
        </button>
      </form>
      {error ? <div className="admin-error">{error}</div> : null}
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
          <pre className="admin-code compact">{JSON.stringify(result.summary || {}, null, 2)}</pre>
        </div>
      ) : null}
    </div>
  );
}
