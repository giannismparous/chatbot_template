import { useCallback, useEffect, useState } from "react";
import { useAdmin } from "../AdminContext.jsx";
import {
  createDriveSource,
  deleteDriveSource,
  listDriveSources,
  runJobAndWait,
  triggerDriveSync,
} from "../api/adminClient.js";
import {
  formatDriveSyncResult,
  isDriveSyncBusy,
  isRowSyncing,
  runDriveSyncJob,
  syncBusyKey,
  syncPhaseMessage,
} from "../utils/driveSyncUi.js";
import { StatusBadge } from "./StatusBadge.jsx";

const STATUS_LABELS = {
  configured: "Configured",
  synced: "Synced",
  synced_with_warnings: "Synced (warnings)",
  failed_auth: "Failed auth",
  failed_extraction: "Failed extraction",
  disabled: "Disabled",
  stale: "Stale",
};

function formatFailureBreakdown(breakdown) {
  if (!breakdown || !Object.keys(breakdown).length) return null;
  return Object.entries(breakdown)
    .map(([reason, count]) => `${count} ${reason}`)
    .join("; ");
}

export function DriveSourcesPanel({ clientId, onChange }) {
  const { token } = useAdmin();
  const [sources, setSources] = useState([]);
  const [defaults, setDefaults] = useState({});
  const [credentialsConfigured, setCredentialsConfigured] = useState(false);
  const [serviceAccountEmail, setServiceAccountEmail] = useState("");
  const [credentialsError, setCredentialsError] = useState("");
  const [busy, setBusy] = useState("");
  const [syncPhase, setSyncPhase] = useState("");
  const [syncMessage, setSyncMessage] = useState("");
  const [jobInfo, setJobInfo] = useState(null);
  const [lastSyncSummary, setLastSyncSummary] = useState("");
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    folder_id: "",
    title: "",
    enabled: true,
    recursive: true,
    max_files: 200,
  });

  const refresh = useCallback(async () => {
    if (!token || !clientId) return;
    const data = await listDriveSources(token, clientId);
    setSources(data.sources || []);
    setDefaults(data.defaults || {});
    setCredentialsConfigured(!!data.credentials_configured);
    setServiceAccountEmail(data.service_account_email || "");
    setCredentialsError(data.credentials_error || "");
  }, [token, clientId]);

  useEffect(() => {
    refresh().catch((err) => setError(err.message || "Failed to load drive sources."));
  }, [refresh]);

  async function onAdd(e) {
    e.preventDefault();
    if (!form.folder_id.trim()) return;
    setBusy("add");
    setError("");
    try {
      await createDriveSource(token, clientId, {
        folder_id: form.folder_id.trim(),
        title: form.title.trim() || null,
        enabled: form.enabled,
        recursive: form.recursive,
        max_files: Number(form.max_files) || 200,
      });
      setForm({ folder_id: "", title: "", enabled: true, recursive: true, max_files: 200 });
      await refresh();
      await onChange?.();
    } catch (err) {
      setError(err.message || "Failed to add drive source.");
    } finally {
      setBusy("");
    }
  }

  async function onRemove(source) {
    if (!window.confirm(`Remove drive source "${source.id}" and delete cached files?`)) return;
    setBusy(`remove-${source.id}`);
    setError("");
    try {
      await deleteDriveSource(token, clientId, source.id);
      await refresh();
      await onChange?.();
    } catch (err) {
      setError(err.message || "Failed to remove drive source.");
    } finally {
      setBusy("");
    }
  }

  async function onSync(sourceIds = null) {
    const busyKey = syncBusyKey(sourceIds);
    setBusy(busyKey);
    setSyncPhase("starting");
    setSyncMessage(syncPhaseMessage("starting"));
    setJobInfo(null);
    setLastSyncSummary("");
    setError("");
    try {
      const finalJob = await runDriveSyncJob({
        token,
        clientId,
        sourceIds,
        triggerDriveSync,
        runJobAndWait,
        onProgress: (phase, message, job) => {
          setSyncPhase(phase);
          setSyncMessage(message);
          if (job?.job_id) setJobInfo(job);
        },
      });
      setJobInfo(finalJob);
      const summary = formatDriveSyncResult(finalJob);
      if (summary) setLastSyncSummary(summary);
      if (finalJob.status === "failed") {
        setError(finalJob.error || summary || "Drive sync failed.");
      }
      await refresh();
      await onChange?.();
    } catch (err) {
      setSyncPhase("failed");
      setSyncMessage(syncPhaseMessage("failed"));
      setError(err.message || "Drive sync failed.");
    } finally {
      setBusy("");
      setSyncPhase("");
    }
  }

  const syncRunning = isDriveSyncBusy(busy);

  return (
    <div className="admin-section">
      <h4>Drive Sources</h4>
      <p className="admin-hint">
        Sync Google Drive folders into managed drive cache, then run <strong>Ingest → Eval → Deploy</strong>.
        Share each folder with the service account email before syncing.
      </p>
      {!credentialsConfigured ? (
        <div className="admin-warn">
          {credentialsError || "GOOGLE_DRIVE_CREDENTIALS_JSON is not configured on the server."}
        </div>
      ) : serviceAccountEmail ? (
        <div className="admin-note">
          Service account: <code>{serviceAccountEmail}</code>
        </div>
      ) : null}
      {syncRunning ? (
        <div className="admin-note drive-sync-progress">
          <span className="admin-spinner" aria-hidden="true" />
          {syncMessage || "Running…"}
        </div>
      ) : null}
      {jobInfo ? (
        <div className="admin-kv drive-sync-job">
          <div>
            Job: {jobInfo.job_id || "—"} <StatusBadge status={jobInfo.status} />
            {syncPhase ? <span className="admin-muted"> · {syncMessage}</span> : null}
          </div>
        </div>
      ) : null}
      {lastSyncSummary && !syncRunning ? (
        <div className="admin-note drive-sync-summary">{lastSyncSummary}</div>
      ) : null}
      {error ? <div className="admin-error">{error}</div> : null}

      <form className="admin-form-row" onSubmit={onAdd}>
        <input
          placeholder="Drive folder ID"
          value={form.folder_id}
          onChange={(e) => setForm((f) => ({ ...f, folder_id: e.target.value }))}
        />
        <input
          placeholder="Title (optional)"
          value={form.title}
          onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
        />
        <input
          type="number"
          min={1}
          max={500}
          title="Max files"
          value={form.max_files}
          onChange={(e) => setForm((f) => ({ ...f, max_files: e.target.value }))}
        />
        <label className="admin-check">
          <input
            type="checkbox"
            checked={form.recursive}
            onChange={(e) => setForm((f) => ({ ...f, recursive: e.target.checked }))}
          />
          Recursive
        </label>
        <label className="admin-check">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
          />
          Enabled
        </label>
        <button type="submit" className="admin-btn" disabled={!!busy}>
          Add folder
        </button>
      </form>

      <div className="admin-row">
        <button type="button" className="admin-btn secondary" disabled={!!busy} onClick={() => onSync(null)}>
          {busy === "sync-all" ? "Syncing all…" : "Sync all enabled"}
        </button>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>Title / Folder</th>
            <th>Files cap</th>
            <th>Status</th>
            <th>Last synced</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => {
            const rowSyncing = isRowSyncing(s.id, busy);
            return (
              <tr key={s.id} className={rowSyncing ? "drive-row-syncing" : ""}>
                <td>
                  <div>{s.title || s.id}</div>
                  <div className="admin-muted">{s.folder_id}</div>
                  {s.sync_summary ? <div className="admin-note">{s.sync_summary}</div> : null}
                  {formatFailureBreakdown(s.failure_breakdown) ? (
                    <div className="admin-warn">Failures: {formatFailureBreakdown(s.failure_breakdown)}</div>
                  ) : null}
                  {!s.sync_summary && s.admin_message ? <div className="admin-warn">{s.admin_message}</div> : null}
                  {s.last_error && !s.sync_summary ? <div className="admin-warn">{s.last_error}</div> : null}
                </td>
                <td>{s.max_files}</td>
                <td>
                  {rowSyncing ? <span className="admin-spinner" aria-hidden="true" /> : null}
                  <StatusBadge status={s.status} label={STATUS_LABELS[s.status] || s.status} />
                </td>
                <td>{s.last_synced_at || "—"}</td>
                <td className="admin-actions">
                  <button
                    type="button"
                    className="admin-btn secondary"
                    disabled={!!busy || !s.enabled}
                    onClick={() => onSync([s.id])}
                  >
                    {rowSyncing ? "Syncing…" : "Sync"}
                  </button>
                  <button
                    type="button"
                    className="admin-btn danger"
                    disabled={!!busy}
                    onClick={() => onRemove(s)}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!sources.length ? <p className="admin-muted">No Drive folders configured.</p> : null}
      <p className="admin-muted">After sync: Run ingest → eval → deploy.</p>
    </div>
  );
}
