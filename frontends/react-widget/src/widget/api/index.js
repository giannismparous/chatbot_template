import { CHAT_API_VERSION, CLIENT_ID, STREAMING_ENABLED } from "./client.js";
import { chatV1NonStream, chatV1Stream } from "./chatV1.js";
import { chatV2NonStream, chatV2Stream } from "./chatV2.js";
import { readSessionId, writeSessionId, clearSessionId } from "../session/storage.js";

export { fetchTheme, fetchPublicConfig, themeFeatures, themeCssVars } from "./theme.js";
export { previewChat } from "./preview.js";
export { CLIENT_ID, STREAMING_ENABLED } from "./client.js";
export { clearSessionId } from "../session/storage.js";

export function buildChatPayload({ clientId, message, sessionId, mode, top_k, history }) {
  const payload = {
    client_id: clientId,
    message,
    mode: mode || "hybrid_local",
    top_k: top_k || 6,
  };
  if (sessionId) payload.session_id = sessionId;
  else if (history?.length) payload.history = history;
  return payload;
}

function persistSession(clientId, result) {
  if (result?.session_id) writeSessionId(clientId, result.session_id);
  return result;
}

async function tryV2Stream(payload, onChunk) {
  return chatV2Stream(payload, { onChunk, onDone: () => {}, onError: () => {} });
}

async function tryV1Stream(payload, onChunk) {
  return chatV1Stream(payload, { onChunk, onDone: () => {}, onError: () => {} });
}

export async function sendChat({
  clientId = CLIENT_ID,
  message,
  mode,
  top_k,
  history,
  streaming = STREAMING_ENABLED,
  onChunk,
}) {
  const sessionId = readSessionId(clientId);
  const payload = buildChatPayload({ clientId, message, sessionId, mode, top_k, history });
  const preferV2 = CHAT_API_VERSION !== "v1";
  const errors = [];

  if (preferV2) {
    if (streaming) {
      try {
        return persistSession(clientId, await tryV2Stream(payload, onChunk));
      } catch (err) {
        errors.push(err);
      }
    }
    try {
      return persistSession(clientId, await chatV2NonStream(payload));
    } catch (err) {
      errors.push(err);
    }
  }

  if (streaming) {
    try {
      return persistSession(clientId, await tryV1Stream(payload, onChunk));
    } catch (err) {
      errors.push(err);
    }
  }

  try {
    return persistSession(clientId, await chatV1NonStream(payload));
  } catch (err) {
    errors.push(err);
    throw errors[errors.length - 1] || err;
  }
}
