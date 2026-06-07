import { API_BASE, normalizeApiError, readJsonResponse, widgetHeaders } from "./client.js";
import { consumeSseStream } from "./sseParser.js";
import { normalizeChatResult } from "../citations.js";

function buildV1Body(payload) {
  const body = {
    client_id: payload.client_id,
    message: payload.message,
    mode: payload.mode,
    top_k: payload.top_k,
    debug: false,
  };
  if (payload.session_id) body.session_id = payload.session_id;
  if (payload.user_id) body.user_id = payload.user_id;
  if (!payload.session_id && payload.history?.length) body.history = payload.history;
  return body;
}

export async function chatV1NonStream(payload) {
  const res = await fetch(`${API_BASE}/v1/chat/respond`, {
    method: "POST",
    headers: widgetHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ ...buildV1Body(payload), stream: false }),
  });
  const body = await readJsonResponse(res);
  if (!res.ok) throw normalizeApiError(res, body);
  return normalizeChatResult(body, { version: "v1" });
}

export async function chatV1Stream(payload, { onChunk, onDone, onError }) {
  const res = await fetch(`${API_BASE}/v1/chat/respond`, {
    method: "POST",
    headers: widgetHeaders({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    }),
    body: JSON.stringify({ ...buildV1Body(payload), stream: true }),
  });
  if (!res.ok) {
    const body = await readJsonResponse(res);
    throw normalizeApiError(res, body);
  }
  let donePayload = null;
  await consumeSseStream(res, ({ event, data }) => {
    if (event === "chunk") onChunk?.(data.text || "");
    if (event === "error") onError?.(data.message || "Stream error.");
    if (event === "done") donePayload = data;
  });
  if (!donePayload) throw new Error("Stream ended without done event.");
  const result = normalizeChatResult(donePayload, { version: "v1" });
  onDone?.(result);
  return result;
}
