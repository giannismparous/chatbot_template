import { API_BASE, normalizeApiError, readJsonResponse, widgetHeaders } from "./client.js";
import { consumeSseStream } from "./sseParser.js";
import { normalizeChatResult } from "../citations.js";

export async function chatV2NonStream(payload) {
  const res = await fetch(`${API_BASE}/v2/chat/respond`, {
    method: "POST",
    headers: widgetHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ ...payload, stream: false, debug: false }),
  });
  const body = await readJsonResponse(res);
  if (!res.ok) throw normalizeApiError(res, body);
  return normalizeChatResult(body, { version: "v2" });
}

export async function chatV2Stream(payload, { onChunk, onDone, onError }) {
  const res = await fetch(`${API_BASE}/v2/chat/respond`, {
    method: "POST",
    headers: widgetHeaders({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    }),
    body: JSON.stringify({ ...payload, stream: true, debug: false }),
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
  const result = normalizeChatResult(donePayload, { version: "v2" });
  onDone?.(result);
  return result;
}
