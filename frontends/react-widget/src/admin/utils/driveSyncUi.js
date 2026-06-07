export function isDriveSyncBusy(busy) {
  return busy === "sync-all" || (typeof busy === "string" && busy.startsWith("sync-"));
}

export function syncBusyKey(sourceIds) {
  if (!sourceIds?.length) return "sync-all";
  if (sourceIds.length === 1) return `sync-${sourceIds[0]}`;
  return "sync-all";
}

export function isRowSyncing(sourceId, busy) {
  return busy === "sync-all" || busy === `sync-${sourceId}`;
}

export function syncPhaseMessage(phase) {
  switch (phase) {
    case "starting":
      return "Syncing Drive…";
    case "job_started":
      return "Sync job started";
    case "polling":
      return "Polling job…";
    case "completed":
      return "Sync completed";
    case "failed":
      return "Sync failed";
    default:
      return "Running…";
  }
}

export function formatDriveSyncResult(job) {
  const result = job?.result;
  const sources = Array.isArray(result?.sources) ? result.sources : [];
  if (!sources.length) {
    return job?.status === "failed" ? job?.error || "Drive sync failed." : null;
  }
  const summaries = sources
    .map((row) => row.sync_summary || row.admin_message)
    .filter(Boolean);
  return summaries.length ? summaries.join(" ") : null;
}

export async function runDriveSyncJob({
  token,
  clientId,
  sourceIds,
  triggerDriveSync,
  runJobAndWait,
  onProgress,
}) {
  onProgress?.("starting", syncPhaseMessage("starting"));
  const accepted = await triggerDriveSync(token, clientId, sourceIds);
  onProgress?.("job_started", syncPhaseMessage("job_started"), accepted);

  const terminal = new Set(["succeeded", "failed"]);
  if (terminal.has(accepted.status)) {
    const phase = accepted.status === "failed" ? "failed" : "completed";
    onProgress?.(phase, syncPhaseMessage(phase), accepted);
    return accepted;
  }

  onProgress?.("polling", syncPhaseMessage("polling"), accepted);
  const finalJob = await runJobAndWait(token, clientId, accepted.job_id);
  const phase = finalJob.status === "failed" ? "failed" : "completed";
  onProgress?.(phase, syncPhaseMessage(phase), finalJob);
  return finalJob;
}
