import { ADMIN_API_BASE } from "./config.js";
import { adminHeaders, normalizeAdminError, readJsonResponse } from "./errors.js";
import { normalizeChatResult } from "../../widget/citations.js";

function clientsUrl(path = "") {
  return `${ADMIN_API_BASE}/v1/admin/clients${path}`;
}

async function adminFetch(token, path, init = {}) {
  const headers = adminHeaders(token, init.headers || {});
  const res = await fetch(clientsUrl(path), { ...init, headers });
  const body = await readJsonResponse(res);
  if (!res.ok) throw normalizeAdminError(res, body);
  return body;
}

export async function probeAdminToken(token) {
  return adminFetch(token, "");
}

export async function listClients(token) {
  return adminFetch(token, "");
}

export async function getClient(token, clientId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}`);
}

export async function createClient(token, payload) {
  return adminFetch(token, "", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reveal_widget_key: true, ...payload }),
  });
}

export async function listUploads(token, clientId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/uploads`);
}

export async function uploadFile(token, clientId, file) {
  const form = new FormData();
  form.append("file", file, file.name);
  const res = await fetch(clientsUrl(`/${encodeURIComponent(clientId)}/uploads`), {
    method: "POST",
    headers: adminHeaders(token),
    body: form,
  });
  const body = await readJsonResponse(res);
  if (!res.ok) throw normalizeAdminError(res, body);
  return body;
}

export async function deleteUpload(token, clientId, relativePath) {
  const safePath = String(relativePath || "").replace(/^\/+/, "");
  const res = await fetch(
    clientsUrl(`/${encodeURIComponent(clientId)}/uploads/${safePath.split("/").map(encodeURIComponent).join("/")}`),
    { method: "DELETE", headers: adminHeaders(token) },
  );
  if (res.status === 204) return;
  const body = await readJsonResponse(res);
  if (!res.ok) throw normalizeAdminError(res, body);
}

export async function saveUploadCitation(token, clientId, relativePath, payload) {
  const safePath = String(relativePath || "").replace(/^\/+/, "");
  return adminFetch(token, `/${encodeURIComponent(clientId)}/uploads/${safePath.split("/").map(encodeURIComponent).join("/")}/citation`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteUploadCitation(token, clientId, relativePath) {
  const safePath = String(relativePath || "").replace(/^\/+/, "");
  const res = await fetch(
    clientsUrl(`/${encodeURIComponent(clientId)}/uploads/${safePath.split("/").map(encodeURIComponent).join("/")}/citation`),
    { method: "DELETE", headers: adminHeaders(token) },
  );
  if (res.status === 204) return;
  const body = await readJsonResponse(res);
  if (!res.ok) throw normalizeAdminError(res, body);
}

export async function triggerIngest(token, clientId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/jobs/ingest`, { method: "POST" });
}

export async function triggerCrawl(token, clientId, sourceIds = null) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/jobs/crawl`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_ids: sourceIds }),
  });
}

export async function listWebSources(token, clientId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/web-sources`);
}

export async function createWebSource(token, clientId, payload) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/web-sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteWebSource(token, clientId, sourceId) {
  const res = await fetch(
    clientsUrl(`/${encodeURIComponent(clientId)}/web-sources/${encodeURIComponent(sourceId)}`),
    { method: "DELETE", headers: adminHeaders(token) },
  );
  if (res.status === 204) return;
  const body = await readJsonResponse(res);
  if (!res.ok) throw normalizeAdminError(res, body);
}

export async function listDriveSources(token, clientId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/drive-sources`);
}

export async function createDriveSource(token, clientId, payload) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/drive-sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteDriveSource(token, clientId, sourceId) {
  const res = await fetch(
    clientsUrl(`/${encodeURIComponent(clientId)}/drive-sources/${encodeURIComponent(sourceId)}`),
    { method: "DELETE", headers: adminHeaders(token) },
  );
  if (res.status === 204) return;
  const body = await readJsonResponse(res);
  if (!res.ok) throw normalizeAdminError(res, body);
}

export async function triggerDriveSync(token, clientId, sourceIds = null) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/jobs/drive-sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_ids: sourceIds }),
  });
}

export async function triggerEval(token, clientId, { suite = "full", llm_mode = "live" } = {}) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/jobs/eval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ suite, llm_mode }),
  });
}

export async function listJobs(token, clientId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/jobs`);
}

export async function getJob(token, clientId, jobId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/jobs/${encodeURIComponent(jobId)}`);
}

export async function deployIndex(token, clientId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/deploy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
}

export async function rollbackIndex(token, clientId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/rollback`, { method: "POST" });
}

export async function getIndexStatus(token, clientId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/index`);
}

export async function getEvalLatest(token, clientId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/eval/latest`);
}

export async function getMetrics(token, clientId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/metrics`);
}

export async function previewChat(token, clientId, { message, indexScope = "active" }) {
  const res = await fetch(clientsUrl(`/${encodeURIComponent(clientId)}/preview`), {
    method: "POST",
    headers: adminHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify({
      message,
      index_scope: indexScope,
      stream: false,
      debug: false,
    }),
  });
  const body = await readJsonResponse(res);
  if (!res.ok) throw normalizeAdminError(res, body);
  return {
    ...normalizeChatResult(body, { version: "v2" }),
    summary: body.summary || {},
  };
}

export async function runPipeline(token, clientId, payload = {}) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/pipeline/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getPipelineStatus(token, clientId, pipelineId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/pipeline/status/${encodeURIComponent(pipelineId)}`);
}

export async function listPipelineRuns(token, clientId) {
  return adminFetch(token, `/${encodeURIComponent(clientId)}/pipeline/runs`);
}

export async function runJobAndWait(token, clientId, jobId, { pollMs = 1500, timeoutMs = 120000, getJobFn = getJob } = {}) {
  const terminal = new Set(["succeeded", "failed"]);
  const start = Date.now();
  let job = await getJobFn(token, clientId, jobId);
  while (!terminal.has(job.status)) {
    if (Date.now() - start > timeoutMs) {
      throw new Error("Job timed out.");
    }
    await new Promise((r) => setTimeout(r, pollMs));
    job = await getJobFn(token, clientId, jobId);
  }
  return job;
}
