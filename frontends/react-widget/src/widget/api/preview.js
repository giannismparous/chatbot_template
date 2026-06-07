import { API_BASE, normalizeApiError, readJsonResponse } from "./client.js";
import { normalizeChatResult } from "../citations.js";

export async function previewChat({ clientId, token, message, indexScope = "active" }) {
  const res = await fetch(`${API_BASE}/v1/admin/clients/${clientId}/preview`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-admin-token": token,
    },
    body: JSON.stringify({
      message,
      index_scope: indexScope,
      stream: false,
      debug: false,
    }),
  });
  const body = await readJsonResponse(res);
  if (!res.ok) throw normalizeApiError(res, body);
  return {
    ...normalizeChatResult(body, { version: "v2" }),
    summary: body.summary || {},
  };
}
