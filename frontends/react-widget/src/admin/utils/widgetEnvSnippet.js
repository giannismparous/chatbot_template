import { ADMIN_API_BASE } from "../api/config.js";

export function buildWidgetEnvSnippet({ clientId, apiBase = ADMIN_API_BASE, widgetKey = null, keyPrefix = null }) {
  const lines = [
    `VITE_CHATBOT_API_BASE=${apiBase}`,
    `VITE_CLIENT_ID=${clientId}`,
  ];

  if (widgetKey) {
    lines.push(`VITE_CLIENT_KEY=${widgetKey}`);
  } else if (keyPrefix) {
    lines.push(`# Full widget key not available — only prefix ${keyPrefix} is stored.`);
    lines.push("# Create a new client or rotate keys if you lost the full key.");
    lines.push("VITE_CLIENT_KEY=wk_REPLACE_ME");
  } else {
    lines.push("VITE_CLIENT_KEY=wk_REPLACE_ME");
  }

  lines.push("VITE_CHAT_API_VERSION=v2");
  lines.push("VITE_CHAT_STREAMING=true");
  lines.push("VITE_SESSION_STORAGE=session");
  return `${lines.join("\n")}\n`;
}
