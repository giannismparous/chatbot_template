import { useState } from "react";
import { useAdmin } from "../AdminContext.jsx";
import { createClient } from "../api/adminClient.js";
import { WidgetKeyRevealModal } from "./WidgetKeyRevealModal.jsx";

export function CreateClientForm({ onCreated }) {
  const { token, setClientId, setRevealedKey } = useAdmin();
  const [clientId, setLocalClientId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [origins, setOrigins] = useState("http://localhost:5173");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pendingKey, setPendingKey] = useState(null);

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await createClient(token, {
        client_id: clientId.trim(),
        display_name: displayName.trim() || clientId.trim(),
        domain_pack: "generic",
        allowed_origins: origins
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        reveal_widget_key: true,
      });
      if (result.widget_key) {
        setRevealedKey(result.client_id, result.widget_key);
        setPendingKey({ clientId: result.client_id, widgetKey: result.widget_key });
      }
      setClientId(result.client_id);
      await onCreated?.();
    } catch (err) {
      setError(err.message || "Create failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form className="admin-form-grid" onSubmit={onSubmit}>
        <input value={clientId} onChange={(e) => setLocalClientId(e.target.value)} placeholder="client_id" required />
        <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="display_name" />
        <input value={origins} onChange={(e) => setOrigins(e.target.value)} placeholder="allowed_origins (comma-separated)" />
        <button type="submit" disabled={busy}>
          Create client
        </button>
      </form>
      {error ? <div className="admin-error">{error}</div> : null}
      {pendingKey ? (
        <WidgetKeyRevealModal
          clientId={pendingKey.clientId}
          widgetKey={pendingKey.widgetKey}
          onDismiss={() => setPendingKey(null)}
        />
      ) : null}
    </>
  );
}
