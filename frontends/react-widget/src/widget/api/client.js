export const API_BASE = import.meta.env.VITE_CHATBOT_API_BASE || "http://localhost:8000";
export const CLIENT_KEY = import.meta.env.VITE_CLIENT_KEY || "";
export const CLIENT_ID = import.meta.env.VITE_CLIENT_ID || "default";
export const CHAT_API_VERSION = (import.meta.env.VITE_CHAT_API_VERSION || "v2").toLowerCase();
export const STREAMING_ENABLED = import.meta.env.VITE_CHAT_STREAMING !== "false";

export function widgetHeaders(extra = {}) {
  const headers = { ...extra };
  if (CLIENT_KEY) {
    headers["x-client-key"] = CLIENT_KEY;
  }
  return headers;
}

export async function readJsonResponse(res) {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    throw new Error("Invalid JSON response from API.");
  }
}

export function normalizeApiError(res, body) {
  if (res.status === 401 || res.status === 403) {
    return new Error("This chat is not authorized on this site.");
  }
  const detail = body?.detail;
  if (typeof detail === "string") return new Error(detail);
  return new Error(`Request failed (${res.status}).`);
}
