import { useCallback, useEffect, useState } from "react";
import { useAdmin } from "../AdminContext.jsx";
import {
  getPipelineStatus,
  listPipelineRuns,
  runPipeline,
} from "../api/adminClient.js";
import { StatusBadge } from "./StatusBadge.jsx";

async function pollPipeline(token, clientId, pipelineId, { pollMs = 2000, timeoutMs = 600000 } = {}) {
  const terminal = new Set(["succeeded", "failed"]);
  const start = Date.now();
  let run = await getPipelineStatus(token, clientId, pipelineId);
  while (!terminal.has(run.status)) {
    if (Date.now() - start > timeoutMs) {
      throw new Error("Pipeline timed out.");
    }
    await new Promise((r) => setTimeout(r, pollMs));
    run = await getPipelineStatus(token, clientId, pipelineId);
  }
  return run;
}

export function PipelineAutomationPanel({ clientId, indexStatus, evalSummary, onRefresh }) {
  const { token } = useAdmin();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [latestRun, setLatestRun] = useState(null);

  const refreshLatest = useCallback(async () => {
    if (!token || !clientId) return;
    const runs = await listPipelineRuns(token, clientId);
    setLatestRun(runs[0] || null);
  }, [token, clientId]);

  useEffect(() => {
    refreshLatest().catch(() => setLatestRun(null));
  }, [refreshLatest]);

  async function startPipeline(payload, label) {
    setBusy(label);
    setError("");
    try {
      const accepted = await runPipeline(token, clientId, { eval_llm_mode: "live", ...payload });
      const finalRun =
        accepted.status === "succeeded" || accepted.status === "failed"
          ? await getPipelineStatus(token, clientId, accepted.pipeline_id)
          : await pollPipeline(token, clientId, accepted.pipeline_id);
      setLatestRun(finalRun);
      await onRefresh?.();
      if (finalRun.status === "failed") {
        setError(finalRun.error || "Pipeline failed.");
      }
    } catch (err) {
      setError(err.message || "Pipeline failed.");
    } finally {
      setBusy("");
    }
  }

  const ingestSummary = latestRun?.ingest_summary || {};
  const evalRun = latestRun?.eval_summary || evalSummary || {};

  return (
    <div className="admin-section">
      <h4>Pipeline automation</h4>
      <p className="admin-muted">
        Run the production pipeline from admin without manual gcloud steps. Deploy runs only when eval passes.
      </p>
      <div className="admin-kv">
        <div>
          Active: {indexStatus?.active || latestRun?.index_manifest?.active || "—"}
        </div>
        <div>Pending: {indexStatus?.pending || latestRun?.index_manifest?.pending || "—"}</div>
        <div>Previous: {indexStatus?.previous || latestRun?.index_manifest?.previous || "—"}</div>
        <div>Sources: {ingestSummary.sources_total ?? "—"}</div>
        <div>Indexed: {ingestSummary.indexed ?? "—"}</div>
        <div>Chunks: {ingestSummary.chunks_total ?? "—"}</div>
      </div>
      <div className="admin-row">
        <button
          type="button"
          className="admin-btn secondary"
          disabled={!!busy}
          onClick={() => startPipeline({ preset: "sync_only" }, "drive-sync")}
        >
          Run Drive Sync
        </button>
        <button
          type="button"
          className="admin-btn secondary"
          disabled={!!busy}
          onClick={() => startPipeline({ steps: ["ingest"] }, "ingest")}
        >
          Run Ingest
        </button>
        <button
          type="button"
          className="admin-btn secondary"
          disabled={!!busy}
          onClick={() => startPipeline({ preset: "ingest_eval" }, "ingest-eval")}
        >
          Run Eval
        </button>
        <button
          type="button"
          className="admin-btn"
          disabled={!!busy}
          onClick={() => startPipeline({ preset: "full_deploy" }, "full-pipeline")}
        >
          Run Full Pipeline
        </button>
      </div>
      {error ? <div className="admin-error">{error}</div> : null}
      {latestRun ? (
        <div className="admin-kv">
          <div>
            Pipeline: {latestRun.pipeline_id} <StatusBadge status={latestRun.status} />
          </div>
          <div>Current step: {latestRun.current_step || "—"}</div>
          <div>
            Eval: {evalRun.status || "—"} deploy_eligible={String(evalRun.deploy_eligible ?? false)}
          </div>
          {latestRun.runtime_refresh_note ? (
            <div className="admin-note">{latestRun.runtime_refresh_note}</div>
          ) : null}
          {latestRun.step_results?.length ? (
            <pre className="admin-code compact">{JSON.stringify(latestRun.step_results, null, 2)}</pre>
          ) : null}
        </div>
      ) : (
        <p className="admin-muted">No pipeline runs yet.</p>
      )}
    </div>
  );
}
