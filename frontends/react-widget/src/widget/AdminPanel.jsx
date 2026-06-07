import { useState } from "react";
import { fetchAdminConfigs, saveAdminConfig } from "./api";

const EDITORS = [
  { key: "promptPolicy", label: "Prompt Policy" },
  { key: "themes", label: "Themes" },
  { key: "clients", label: "Clients" },
  { key: "driveSources", label: "Drive Sources" },
  { key: "apiSources", label: "API Sources" },
];

export function AdminPanel() {
  const [token, setToken] = useState("");
  const [active, setActive] = useState("promptPolicy");
  const [configs, setConfigs] = useState({});
  const [editor, setEditor] = useState("{}");
  const [status, setStatus] = useState("Load configs to start.");
  const [busy, setBusy] = useState(false);

  async function onLoad() {
    setBusy(true);
    setStatus("Loading configs...");
    try {
      const data = await fetchAdminConfigs(token);
      setConfigs(data);
      const first = JSON.stringify(data[active] || {}, null, 2);
      setEditor(first);
      setStatus("Configs loaded.");
    } catch (err) {
      setStatus(`Load failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  function onChangeSection(next) {
    setActive(next);
    setEditor(JSON.stringify(configs[next] || {}, null, 2));
  }

  async function onSave() {
    setBusy(true);
    setStatus("Saving...");
    try {
      const parsed = JSON.parse(editor);
      await saveAdminConfig(active, parsed, token);
      setConfigs((prev) => ({ ...prev, [active]: parsed }));
      setStatus("Saved successfully.");
    } catch (err) {
      setStatus(`Save failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="admin-shell">
      <div className="admin-header">
        <h3>Admin Config Editor</h3>
        <div className="admin-token-row">
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="x-admin-token (optional)"
          />
          <button onClick={onLoad} disabled={busy}>
            Load
          </button>
        </div>
      </div>

      <div className="admin-tabs">
        {EDITORS.map((e) => (
          <button key={e.key} className={active === e.key ? "active" : ""} onClick={() => onChangeSection(e.key)}>
            {e.label}
          </button>
        ))}
      </div>

      <textarea value={editor} onChange={(e) => setEditor(e.target.value)} spellCheck={false} />

      <div className="admin-actions">
        <button onClick={onSave} disabled={busy}>
          Save {EDITORS.find((e) => e.key === active)?.label}
        </button>
        <span>{status}</span>
      </div>
    </div>
  );
}
