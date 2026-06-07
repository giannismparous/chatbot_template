import { useCallback, useEffect, useState } from "react";

import { useAdmin } from "../AdminContext.jsx";

import {

  createWebSource,

  deleteWebSource,

  listWebSources,

  triggerCrawl,

  runJobAndWait,

} from "../api/adminClient.js";

import { StatusBadge } from "./StatusBadge.jsx";



const STATUS_LABELS = {

  configured: "Configured",

  fetched: "Fetched",

  failed: "Failed",

  failed_render: "Failed render",

  failed_extraction: "Failed extraction",

  fetched_low_content: "Low content",

  blocked_by_whitelist: "Blocked by whitelist",

  disabled: "Disabled",

  stale: "Stale",

};



const RENDER_MODES = [

  { value: "static", label: "Static (HTTP)" },

  { value: "playwright", label: "Playwright (JS)" },

];



const WAIT_UNTIL_OPTIONS = [

  { value: "networkidle", label: "networkidle" },

  { value: "domcontentloaded", label: "domcontentloaded" },

  { value: "load", label: "load" },

];



export function WebSourcesPanel({ clientId, onChange }) {

  const { token } = useAdmin();

  const [sources, setSources] = useState([]);

  const [defaults, setDefaults] = useState({});

  const [busy, setBusy] = useState("");

  const [error, setError] = useState("");

  const [form, setForm] = useState({

    url: "",

    title: "",

    max_depth: 0,

    max_pages: 1,

    enabled: true,

    render_mode: "static",

    wait_until: "networkidle",

    wait_selector: "",

  });



  const refresh = useCallback(async () => {

    if (!token || !clientId) return;

    const data = await listWebSources(token, clientId);

    setSources(data.sources || []);

    setDefaults(data.defaults || {});

  }, [token, clientId]);



  useEffect(() => {

    refresh().catch((err) => setError(err.message || "Failed to load web sources."));

  }, [refresh]);



  async function onAdd(e) {

    e.preventDefault();

    if (!form.url.trim()) return;

    setBusy("add");

    setError("");

    try {

      const payload = {

        url: form.url.trim(),

        title: form.title.trim() || null,

        enabled: form.enabled,

        max_depth: Number(form.max_depth) || 0,

        max_pages: Number(form.max_pages) || 1,

        render_mode: form.render_mode,

        wait_until: form.wait_until,

      };

      if (form.render_mode === "playwright" && form.wait_selector.trim()) {

        payload.wait_selector = form.wait_selector.trim();

      }

      await createWebSource(token, clientId, payload);

      setForm({

        url: "",

        title: "",

        max_depth: 0,

        max_pages: 1,

        enabled: true,

        render_mode: "static",

        wait_until: "networkidle",

        wait_selector: "",

      });

      await refresh();

      await onChange?.();

    } catch (err) {

      setError(err.message || "Failed to add web source.");

    } finally {

      setBusy("");

    }

  }



  async function onRemove(source) {

    if (!window.confirm(`Remove web source "${source.id}" and delete cached pages?`)) return;

    setBusy(`remove-${source.id}`);

    setError("");

    try {

      await deleteWebSource(token, clientId, source.id);

      await refresh();

      await onChange?.();

    } catch (err) {

      setError(err.message || "Failed to remove web source.");

    } finally {

      setBusy("");

    }

  }



  async function onCrawl(sourceIds = null) {

    setBusy(sourceIds?.length === 1 ? `crawl-${sourceIds[0]}` : "crawl-all");

    setError("");

    try {

      const accepted = await triggerCrawl(token, clientId, sourceIds);

      const finalJob =

        accepted.status === "succeeded" || accepted.status === "failed"

          ? accepted

          : await runJobAndWait(token, clientId, accepted.job_id);

      if (finalJob.status === "failed") {

        setError(finalJob.error || "Crawl failed.");

      }

      await refresh();

      await onChange?.();

    } catch (err) {

      setError(err.message || "Crawl failed.");

    } finally {

      setBusy("");

    }

  }



  const isPlaywright = form.render_mode === "playwright";



  return (

    <div className="admin-section">

      <h4>Web Sources</h4>

      <p className="admin-hint">

        Crawl explicit public URLs into managed web cache, then run <strong>Ingest</strong> to index them.

        Default max depth is {defaults.max_depth ?? 0} (seed page only). Use Playwright for JS-rendered sites.

      </p>

      {error ? <div className="admin-error">{error}</div> : null}



      <form className="admin-form-row" onSubmit={onAdd}>

        <input

          placeholder="https://simasiaai.gr/"

          value={form.url}

          onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}

        />

        <input

          placeholder="Title (optional)"

          value={form.title}

          onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}

        />

        <select

          title="Render mode"

          value={form.render_mode}

          onChange={(e) => setForm((f) => ({ ...f, render_mode: e.target.value }))}

        >

          {RENDER_MODES.map((opt) => (

            <option key={opt.value} value={opt.value}>

              {opt.label}

            </option>

          ))}

        </select>

        {isPlaywright ? (

          <>

            <select

              title="Wait until"

              value={form.wait_until}

              onChange={(e) => setForm((f) => ({ ...f, wait_until: e.target.value }))}

            >

              {WAIT_UNTIL_OPTIONS.map((opt) => (

                <option key={opt.value} value={opt.value}>

                  {opt.label}

                </option>

              ))}

            </select>

            <input

              placeholder="Wait selector (optional)"

              value={form.wait_selector}

              onChange={(e) => setForm((f) => ({ ...f, wait_selector: e.target.value }))}

            />

          </>

        ) : null}

        <input

          type="number"

          min={0}

          max={2}

          title="Max depth"

          value={form.max_depth}

          onChange={(e) => setForm((f) => ({ ...f, max_depth: e.target.value }))}

        />

        <input

          type="number"

          min={1}

          max={50}

          title="Max pages"

          value={form.max_pages}

          onChange={(e) => setForm((f) => ({ ...f, max_pages: e.target.value }))}

        />

        <label className="admin-check">

          <input

            type="checkbox"

            checked={form.enabled}

            onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}

          />

          Enabled

        </label>

        <button type="submit" className="admin-btn" disabled={!!busy}>

          Add source

        </button>

      </form>



      <div className="admin-row">

        <button type="button" className="admin-btn secondary" disabled={!!busy} onClick={() => onCrawl(null)}>

          Crawl all enabled

        </button>

      </div>



      <table className="admin-table">

        <thead>

          <tr>

            <th>Title / URL</th>

            <th>Mode</th>

            <th>Depth</th>

            <th>Pages</th>

            <th>Status</th>

            <th>Last crawled</th>

            <th>Actions</th>

          </tr>

        </thead>

        <tbody>

          {sources.map((s) => (

            <tr key={s.id}>

              <td>

                <div>{s.title || s.id}</div>

                <div className="admin-muted">{s.url}</div>

                {s.admin_message ? <div className="admin-warn">{s.admin_message}</div> : null}

                {s.last_error ? <div className="admin-warn">{s.last_error}</div> : null}

              </td>

              <td>{s.render_mode || "static"}</td>

              <td>{s.max_depth}</td>

              <td>{s.max_pages}</td>

              <td>

                <StatusBadge status={s.status} label={STATUS_LABELS[s.status] || s.status} />

              </td>

              <td>{s.last_crawled_at || "—"}</td>

              <td className="admin-actions">

                <button

                  type="button"

                  className="admin-btn secondary"

                  disabled={!!busy || s.status === "blocked_by_whitelist" || !s.enabled}

                  onClick={() => onCrawl([s.id])}

                >

                  Crawl/Refresh

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

          ))}

        </tbody>

      </table>

      {!sources.length ? <p className="admin-muted">No web sources configured.</p> : null}

    </div>

  );

}

