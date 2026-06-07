import { useState } from "react";
import { useAdmin } from "../AdminContext.jsx";
import {
  deployIndex,
  getEvalLatest,
  getIndexStatus,
  getMetrics,
  rollbackIndex,
  runJobAndWait,
  triggerEval,
  triggerIngest,
} from "../api/adminClient.js";
import { AdminApiError } from "../api/errors.js";
import { canDeploy, deployBlockReason } from "../utils/deployEligibility.js";
import { StatusBadge } from "./StatusBadge.jsx";

export function PipelinePanel({ clientId, indexStatus, evalSummary, onRefresh }) {
  const { token } = useAdmin();
  const [busy, setBusy] = useState("");
  const [jobInfo, setJobInfo] = useState(null);
  const [deployError, setDeployError] = useState("");
  const [evalMode, setEvalMode] = useState("live");

  async function runJob(label, startFn) {
    setBusy(label);
    setDeployError("");
    try {
      const accepted = await startFn();
      setJobInfo(accepted);
      const finalJob =
        accepted.status === "succeeded" || accepted.status === "failed"
          ? accepted
          : await runJobAndWait(token, clientId, accepted.job_id);
      setJobInfo(finalJob);
      await onRefresh?.();
      if (finalJob.status === "failed") {
        setDeployError(finalJob.error || "Job failed.");
      }
    } catch (err) {
      setDeployError(err.message || "Job failed.");
    } finally {
      setBusy("");
    }
  }

  async function onDeploy() {
    setBusy("deploy");
    setDeployError("");
    try {
      await deployIndex(token, clientId);
      await onRefresh?.();
    } catch (err) {
      if (err instanceof AdminApiError && err.status === 409) {
        setDeployError(`${err.reason}: ${err.message}`);
      } else {
        setDeployError(err.message || "Deploy failed.");
      }
    } finally {
      setBusy("");
    }
  }

  async function onRollback() {
    if (!window.confirm("Rollback to previous active version?")) return;
    setBusy("rollback");
    setDeployError("");
    try {
      await rollbackIndex(token, clientId);
      await onRefresh?.();
    } catch (err) {
      setDeployError(err.message || "Rollback failed.");
    } finally {
      setBusy("");
    }
  }

  const deployReady = canDeploy(indexStatus, evalSummary);
  const blockReason = deployBlockReason(indexStatus, evalSummary);

  return (
    <div className="admin-section">
      <h4>Index pipeline</h4>
      <div className="admin-kv">
        <div>Active: {indexStatus?.active || "—"}</div>
        <div>Pending: {indexStatus?.pending || "—"}</div>
        <div>Previous: {indexStatus?.previous || "—"}</div>
      </div>
      <div className="admin-row">
        <button type="button" className="admin-btn" disabled={!!busy} onClick={() => runJob("ingest", () => triggerIngest(token, clientId))}>
          Run ingest
        </button>
        <div className="admin-eval-mode">
          <label>
            Eval mode{" "}
            <select value={evalMode} onChange={(e) => setEvalMode(e.target.value)} disabled={!!busy}>
              <option value="live">live (deploy decisions)</option>
              <option value="replay">replay (local UI test only — not for deploy)</option>
            </select>
          </label>
        </div>
        <button
          type="button"
          className="admin-btn"
          disabled={!!busy}
          onClick={() =>
            runJob("eval", () => triggerEval(token, clientId, { suite: "full", llm_mode: evalMode }))
          }
        >
          Run eval
        </button>
        <button type="button" className="admin-btn" disabled={!!busy || !deployReady} onClick={onDeploy}>
          Deploy pending
        </button>
        <button type="button" className="admin-btn secondary" disabled={!!busy || !indexStatus?.previous} onClick={onRollback}>
          Rollback
        </button>
      </div>
      {!deployReady && blockReason ? <p className="admin-note">{blockReason}</p> : null}
      {evalMode === "replay" ? (
        <p className="admin-warn">Replay eval does not represent live answers — do not use for deploy decisions.</p>
      ) : null}
      {deployError ? <div className="admin-error">{deployError}</div> : null}
      {jobInfo ? (
        <div className="admin-kv">
          <div>
            Job: {jobInfo.job_id} <StatusBadge status={jobInfo.status} />
          </div>
          {jobInfo.result ? <pre className="admin-code compact">{JSON.stringify(jobInfo.result, null, 2)}</pre> : null}
        </div>
      ) : null}
    </div>
  );
}

export function EvalSummaryCard({ evalSummary }) {
  if (!evalSummary?.run_id) {
    return (
      <div className="admin-section">
        <h4>Latest eval</h4>
        <p className="admin-muted">No eval report yet.</p>
      </div>
    );
  }
  return (
    <div className="admin-section">
      <h4>Latest eval</h4>
      <div className="admin-kv">
        <div>Run: {evalSummary.run_id}</div>
        <div>
          Status: <StatusBadge status={evalSummary.status} /> deploy_eligible={String(evalSummary.deploy_eligible)}
        </div>
        <div>Version: {evalSummary.evaluated_index_version || "—"}</div>
        <div>At: {evalSummary.evaluated_at || "—"}</div>
      </div>
      {evalSummary.categories ? (
        <pre className="admin-code compact">{JSON.stringify(evalSummary.categories, null, 2)}</pre>
      ) : null}
      {evalSummary.failure_reasons?.length ? (
        <div className="admin-warn">Failures: {evalSummary.failure_reasons.join(", ")}</div>
      ) : null}
      {evalSummary.failed_cases?.length ? (
        <div className="admin-eval-failures">
          <strong>Failed cases</strong>
          <ul>
            {evalSummary.failed_cases.map((item) => (
              <li key={item.id}>
                <code>{item.id}</code> ({item.category}): {item.message}
                {item.failed_assertions?.length ? (
                  <ul>
                    {item.failed_assertions.map((a, idx) => (
                      <li key={`${item.id}-${idx}`}>
                        {a.name}: expected {JSON.stringify(a.expected)}, got {JSON.stringify(a.actual)}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {item.answer_preview ? <div className="admin-muted">{item.answer_preview}</div> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function MetricsCard({ metrics }) {
  if (!metrics) return null;
  return (
    <div className="admin-section">
      <h4>Metrics</h4>
      <div className="admin-kv">
        <div>Total chats: {metrics.total_chats}</div>
        <div>No context: {metrics.no_context}</div>
        <div>Crisis: {metrics.crisis}</div>
        <div>Input blocked: {metrics.input_blocked}</div>
        <div>Avg latency ms: {metrics.avg_latency_ms ?? "—"}</div>
      </div>
      {metrics.confidence_buckets ? (
        <pre className="admin-code compact">{JSON.stringify(metrics.confidence_buckets, null, 2)}</pre>
      ) : null}
    </div>
  );
}
