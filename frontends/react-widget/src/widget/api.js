const API_BASE = import.meta.env.VITE_CHATBOT_API_BASE || "http://localhost:8000";

function widgetHeaders(extra = {}) {
  const headers = { ...extra };
  const key = import.meta.env.VITE_CLIENT_KEY || "";
  if (key) headers["x-client-key"] = key;
  return headers;
}

async function adminRequest(path, { method = "GET", data, token = "" } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["x-admin-token"] = token;
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: method === "GET" ? undefined : JSON.stringify({ data }),
  });
  if (!res.ok) throw new Error(`Admin request failed: ${path}`);
  return res.json();
}

export async function fetchAdminConfigs(token = "") {
  const [promptPolicy, themes, clients, driveSources, apiSources] = await Promise.all([
    adminRequest("/v1/admin/prompt-policy", { token }),
    adminRequest("/v1/admin/themes", { token }),
    adminRequest("/v1/admin/clients", { token }),
    adminRequest("/v1/admin/sources/drive", { token }),
    adminRequest("/v1/admin/sources/api", { token }),
  ]);
  return { promptPolicy, themes, clients, driveSources, apiSources };
}

export async function saveAdminConfig(kind, data, token = "") {
  const map = {
    promptPolicy: "/v1/admin/prompt-policy",
    themes: "/v1/admin/themes",
    clients: "/v1/admin/clients",
    driveSources: "/v1/admin/sources/drive",
    apiSources: "/v1/admin/sources/api",
  };
  const path = map[kind];
  if (!path) throw new Error(`Unknown config kind: ${kind}`);
  return adminRequest(path, { method: "PUT", data, token });
}

export async function fetchTheme(clientId = "default") {
  const res = await fetch(`${API_BASE}/v1/theme/${clientId}`, { headers: widgetHeaders() });
  if (!res.ok) throw new Error("Failed to fetch theme");
  return res.json();
}

export async function sendMessage(payload) {
  const { sendChat, CLIENT_ID } = await import("./api/index.js");
  return sendChat({ clientId: payload.clientId || CLIENT_ID, message: payload.message, history: payload.history, mode: payload.mode, top_k: payload.top_k || 5 });
}
