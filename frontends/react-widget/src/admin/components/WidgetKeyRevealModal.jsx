import { useState } from "react";
import { CopyButton } from "./CopyButton.jsx";

export function WidgetKeyRevealModal({ clientId, widgetKey, onDismiss }) {
  const [ack, setAck] = useState(false);
  if (!widgetKey) return null;
  return (
    <div className="admin-modal-backdrop">
      <div className="admin-modal">
        <h3>Widget key — copy now</h3>
        <p>
          Full key for <strong>{clientId}</strong>. This is shown once and cannot be recovered from the API later.
        </p>
        <pre className="admin-code">{widgetKey}</pre>
        <div className="admin-row">
          <CopyButton text={widgetKey} label="Copy key" />
        </div>
        <label className="admin-check">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          I saved the widget key securely
        </label>
        <button type="button" className="admin-btn" disabled={!ack} onClick={onDismiss}>
          Continue
        </button>
      </div>
    </div>
  );
}
