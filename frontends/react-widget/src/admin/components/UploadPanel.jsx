import { useEffect, useState } from "react";
import { useAdmin } from "../AdminContext.jsx";
import {
  deleteUpload,
  deleteUploadCitation,
  listUploads,
  saveUploadCitation,
  uploadFile,
} from "../api/adminClient.js";

const ALLOWED_HINT = ".txt, .md, .pdf, .docx";

const STATUS_LABELS = {
  internal_only: "Internal only",
  public_configured: "Public URL configured",
  blocked_by_whitelist: "Blocked by whitelist",
  invalid_url: "Invalid URL",
};

function UploadCitationRow({ file, clientId, token, busy, onRefresh }) {
  const [url, setUrl] = useState(file.citation?.citation_url || "");
  const [title, setTitle] = useState(file.citation?.title || "");
  const [error, setError] = useState("");

  useEffect(() => {
    setUrl(file.citation?.citation_url || "");
    setTitle(file.citation?.title || "");
  }, [file.citation?.citation_url, file.citation?.title]);

  const status = file.citation?.status || "internal_only";

  async function onSave(e) {
    e.preventDefault();
    if (!url.trim()) return;
    setError("");
    try {
      await saveUploadCitation(token, clientId, file.path, {
        citation_url: url.trim(),
        title: title.trim() || null,
        source_visibility: "public",
      });
      await onRefresh?.();
    } catch (err) {
      setError(err.message || "Save failed.");
    }
  }

  async function onClear() {
    if (!file.citation?.citation_url) return;
    setError("");
    try {
      await deleteUploadCitation(token, clientId, file.path);
      setUrl("");
      setTitle("");
      await onRefresh?.();
    } catch (err) {
      setError(err.message || "Clear failed.");
    }
  }

  async function onDeleteFile() {
    if (!window.confirm(`Delete ${file.path}?`)) return;
    setError("");
    try {
      await deleteUpload(token, clientId, file.path);
      await onRefresh?.();
    } catch (err) {
      setError(err.message || "Delete failed.");
    }
  }

  return (
    <li className="admin-upload-row">
      <div className="admin-upload-main">
        <span>{file.path}</span>
        <span className="admin-muted">({file.size_bytes} B)</span>
        <span className={`admin-badge status-${status}`}>{STATUS_LABELS[status] || status}</span>
      </div>
      <form className="admin-upload-citation" onSubmit={onSave}>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="Public citation URL (https://...)"
          disabled={busy}
        />
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title (optional)"
          disabled={busy}
        />
        <button type="submit" className="admin-btn secondary" disabled={busy || !url.trim()}>
          Save URL
        </button>
        <button type="button" className="admin-btn secondary" disabled={busy || !file.citation?.citation_url} onClick={onClear}>
          Clear
        </button>
        <button type="button" className="admin-btn secondary" disabled={busy} onClick={() => onDeleteFile()}>
          Delete file
        </button>
      </form>
      {file.citation?.requires_reingest ? (
        <p className="admin-note">Run ingest again to apply citation URLs to the index.</p>
      ) : null}
      {status === "blocked_by_whitelist" ? (
        <p className="admin-warn">Domain not in source_whitelist.yaml — source stays hidden from widget.</p>
      ) : null}
      {error ? <div className="admin-error">{error}</div> : null}
    </li>
  );
}

export function UploadPanel({ clientId, onChange }) {
  const { token } = useAdmin();
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    if (!clientId || !token) return;
    const data = await listUploads(token, clientId);
    setFiles(data.files || []);
    await onChange?.();
  }

  useEffect(() => {
    if (!token || !clientId) return;
    refresh().catch(() => setFiles([]));
  }, [clientId, token]);

  async function onUpload(e) {
    const picked = e.target.files;
    if (!picked?.length) return;
    setBusy(true);
    setError("");
    try {
      for (const file of picked) {
        if (file.name.includes("\\") || file.name.includes("/")) {
          throw new Error("Filenames must not contain path separators.");
        }
        await uploadFile(token, clientId, file);
      }
      await refresh();
    } catch (err) {
      setError(err.message || "Upload failed.");
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  return (
    <div className="admin-section">
      <h4>Documents</h4>
      <p className="admin-note">
        Allowed: {ALLOWED_HINT}. Paths are relative upload names only. Optional public URLs map citations to whitelisted
        https links.
      </p>
      <input type="file" multiple disabled={busy || !clientId} onChange={onUpload} />
      {error ? <div className="admin-error">{error}</div> : null}
      <ul className="admin-list admin-upload-list">
        {files.map((f) => (
          <UploadCitationRow key={f.path} file={f} clientId={clientId} token={token} busy={busy} onRefresh={refresh} />
        ))}
      </ul>
      {!files.length ? <p className="admin-muted">No uploads yet.</p> : null}
    </div>
  );
}
