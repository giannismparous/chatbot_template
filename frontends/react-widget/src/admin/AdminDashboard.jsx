import { useCallback, useEffect, useState } from "react";
import { useAdmin } from "./AdminContext.jsx";
import { AdminTokenGate } from "./AdminTokenGate.jsx";
import { listClients } from "./api/adminClient.js";
import { getEvalLatest, getIndexStatus, getMetrics } from "./api/adminClient.js";
import { CreateClientForm } from "./components/CreateClientForm.jsx";
import { UploadPanel } from "./components/UploadPanel.jsx";
import { WebSourcesPanel } from "./components/WebSourcesPanel.jsx";
import { DriveSourcesPanel } from "./components/DriveSourcesPanel.jsx";
import { PipelinePanel, EvalSummaryCard, MetricsCard } from "./components/PipelinePanel.jsx";
import { AdminPreviewPanel } from "./components/AdminPreviewPanel.jsx";
import { WidgetEnvSnippet } from "./components/WidgetEnvSnippet.jsx";

/** Only mounted after AdminTokenGate confirms a valid token. */
function AdminDashboardBody() {
  const { token, clientId, setClientId, revealedKeys } = useAdmin();
  const [clients, setClients] = useState([]);
  const [indexStatus, setIndexStatus] = useState(null);
  const [evalSummary, setEvalSummary] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [error, setError] = useState("");

  const refreshClients = useCallback(async () => {
    if (!token) return;
    const data = await listClients(token);
    setClients(data);
    if (!clientId && data.length) setClientId(data[0].client_id);
  }, [token, clientId, setClientId]);

  const refreshClientState = useCallback(async () => {
    if (!token || !clientId) return;
    const [index, evalLatest, metricsData] = await Promise.all([
      getIndexStatus(token, clientId),
      getEvalLatest(token, clientId).catch(() => ({})),
      getMetrics(token, clientId).catch(() => null),
    ]);
    setIndexStatus(index);
    setEvalSummary(evalLatest);
    setMetrics(metricsData);
  }, [token, clientId]);

  useEffect(() => {
    refreshClients()
      .then(() => setError(""))
      .catch((err) => setError(err.message || "Failed to load clients."));
  }, [refreshClients]);

  useEffect(() => {
    if (!clientId) return;
    refreshClientState()
      .then(() => setError(""))
      .catch((err) => setError(err.message || "Failed to load client state."));
  }, [clientId, refreshClientState]);

  const selected = clients.find((c) => c.client_id === clientId);
  const keyPrefix = selected?.widget_keys?.[0]?.key_prefix;
  const widgetKey = revealedKeys[clientId] || null;

  return (
    <div className="admin-dashboard">
      <h2>Platform Admin Dashboard</h2>
      {error ? <div className="admin-error">{error}</div> : null}

      <div className="admin-section">
        <h4>Clients</h4>
        <div className="admin-row">
          <select value={clientId} onChange={(e) => setClientId(e.target.value)}>
            {clients.map((c) => (
              <option key={c.client_id} value={c.client_id}>
                {c.client_id} — {c.display_name || c.client_id}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="admin-btn secondary"
            onClick={() =>
              refreshClients()
                .then(() => setError(""))
                .catch((err) => setError(err.message))
            }
          >
            Refresh
          </button>
        </div>
        <table className="admin-table">
          <thead>
            <tr>
              <th>client_id</th>
              <th>display_name</th>
              <th>key prefix</th>
              <th>config</th>
            </tr>
          </thead>
          <tbody>
            {clients.map((c) => (
              <tr key={c.client_id}>
                <td>{c.client_id}</td>
                <td>{c.display_name}</td>
                <td>{c.widget_keys?.[0]?.key_prefix || "—"}</td>
                <td>{c.has_config ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <CreateClientForm onCreated={refreshClients} />
      </div>

      {clientId ? (
        <>
          <WidgetEnvSnippet clientId={clientId} widgetKey={widgetKey} keyPrefix={keyPrefix} />
          <UploadPanel clientId={clientId} onChange={refreshClientState} />
          <WebSourcesPanel clientId={clientId} onChange={refreshClientState} />
          <DriveSourcesPanel clientId={clientId} onChange={refreshClientState} />
          <PipelinePanel
            clientId={clientId}
            indexStatus={indexStatus}
            evalSummary={evalSummary}
            onRefresh={refreshClientState}
          />
          <EvalSummaryCard evalSummary={evalSummary} />
          <MetricsCard metrics={metrics} />
          <AdminPreviewPanel clientId={clientId} />
        </>
      ) : null}
    </div>
  );
}

export function AdminDashboard() {
  return (
    <AdminTokenGate>
      <AdminDashboardBody />
    </AdminTokenGate>
  );
}
