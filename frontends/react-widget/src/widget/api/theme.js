import { API_BASE, readJsonResponse, widgetHeaders } from "./client.js";

export async function fetchTheme(clientId) {
  const res = await fetch(`${API_BASE}/v1/theme/${clientId}`, {
    headers: widgetHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch theme");
  return readJsonResponse(res);
}

export async function fetchPublicConfig(clientId) {
  const res = await fetch(`${API_BASE}/v1/config/public/${clientId}`, {
    headers: widgetHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch public config");
  return readJsonResponse(res);
}

export function themeFeatures(theme) {
  const features = theme?.features || {};
  return {
    streaming_enabled: features.streaming_enabled !== false,
    citation_rendering: features.citation_rendering !== false,
    show_confidence: features.show_confidence !== false,
  };
}

export function themeCssVars(theme) {
  const colors = theme?.colors || {};
  return {
    "--cb-primary": colors.primary || "#1f4f7a",
    "--cb-secondary": colors.secondary || "#2f6da4",
    "--cb-surface": colors.surface || "#f5f8fc",
    "--cb-text": colors.text_primary || "#1a1a1a",
    "--cb-inverse": colors.text_inverse || "#ffffff",
    "--cb-border": colors.border || "#d9e2ee",
  };
}
