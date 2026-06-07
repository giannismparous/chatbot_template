const PREFIX = "chatbot:session:";

function storageBackend() {
  const mode = (import.meta.env.VITE_SESSION_STORAGE || "session").toLowerCase();
  if (mode === "local") return localStorage;
  return sessionStorage;
}

export function sessionStorageKey(clientId) {
  return `${PREFIX}${clientId}`;
}

export function readSessionId(clientId) {
  try {
    return storageBackend().getItem(sessionStorageKey(clientId)) || null;
  } catch {
    return null;
  }
}

export function writeSessionId(clientId, sessionId) {
  if (!sessionId) return;
  try {
    storageBackend().setItem(sessionStorageKey(clientId), sessionId);
  } catch {
    /* ignore quota errors */
  }
}

export function clearSessionId(clientId) {
  try {
    storageBackend().removeItem(sessionStorageKey(clientId));
  } catch {
    /* ignore */
  }
}

export function listStoredSessionKeys() {
  const backend = storageBackend();
  const keys = [];
  for (let i = 0; i < backend.length; i += 1) {
    const key = backend.key(i);
    if (key && key.startsWith(PREFIX)) keys.push(key);
  }
  return keys;
}
