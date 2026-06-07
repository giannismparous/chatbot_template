import { runJobAndWait } from "./adminClient.js";

export async function pollJob(token, clientId, jobId, options = {}) {
  return runJobAndWait(token, clientId, jobId, options);
}

export function isTerminalJobStatus(status) {
  return status === "succeeded" || status === "failed";
}
