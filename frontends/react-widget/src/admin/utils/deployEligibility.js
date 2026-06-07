export function canDeploy(indexStatus, evalSummary) {
  if (!indexStatus?.pending) return false;
  if (!evalSummary?.deploy_eligible) return false;
  if (evalSummary?.status !== "pass") return false;
  if (evalSummary?.evaluated_index_version !== indexStatus.pending) return false;
  return true;
}

export function deployBlockReason(indexStatus, evalSummary) {
  if (!indexStatus?.pending) return "No pending index — run ingest first.";
  if (!evalSummary?.run_id) return "No eval report — run eval (live mode) first.";
  if (evalSummary.evaluated_index_version !== indexStatus.pending) {
    return "Eval version does not match pending index — re-run eval.";
  }
  if (evalSummary.status !== "pass" || !evalSummary.deploy_eligible) {
    return "Latest eval is not deploy-eligible.";
  }
  return null;
}
