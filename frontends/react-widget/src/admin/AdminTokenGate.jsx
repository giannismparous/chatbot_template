import { useState } from "react";
import { probeAdminToken } from "./api/adminClient.js";
import { AdminApiError } from "./api/errors.js";
import { useAdmin } from "./AdminContext.jsx";

export function AdminTokenGate({ children }) {
  const { token, setToken, disconnect } = useAdmin();
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onConnect(e) {
    e.preventDefault();
    const value = input.trim();
    if (!value) return;
    setBusy(true);
    setError("");
    try {
      await probeAdminToken(value);
      setToken(value);
      setInput("");
    } catch (err) {
      const msg = err instanceof AdminApiError ? err.message : "Connection failed.";
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  if (token) {
    return (
      <div className="admin-app">
        <div className="admin-topbar">
          <span className="admin-connected">Admin connected (token in memory only)</span>
          <button type="button" className="admin-btn secondary" onClick={disconnect}>
            Disconnect
          </button>
        </div>
        {children}
      </div>
    );
  }

  return (
    <div className="admin-gate">
      <h2>Platform Admin</h2>
      <p className="admin-note">
        Enter your local <code>x-admin-token</code>. It is kept in memory only — never stored in browser storage.
      </p>
      <form onSubmit={onConnect}>
        <input
          type="password"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="x-admin-token"
          autoComplete="off"
        />
        <button type="submit" disabled={busy}>
          {busy ? "Connecting..." : "Connect"}
        </button>
      </form>
      {error ? <div className="admin-error">{error}</div> : null}
    </div>
  );
}
