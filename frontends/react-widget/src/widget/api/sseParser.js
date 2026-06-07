const ALLOWED_EVENTS = new Set(["chunk", "done", "error"]);
const FORBIDDEN_DONE_KEYS = new Set(["trace", "retrieval", "llm", "prompt", "chunks", "block_reason"]);

export function parseSseBlocks(text) {
  const blocks = text.split(/\n\n+/).map((b) => b.trim()).filter(Boolean);
  const events = [];
  for (const block of blocks) {
    let eventName = "message";
    let dataLine = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) eventName = line.slice(6).trim();
      if (line.startsWith("data:")) dataLine += line.slice(5).trim();
    }
    if (!ALLOWED_EVENTS.has(eventName)) continue;
    let data = {};
    if (dataLine) {
      try {
        data = JSON.parse(dataLine);
      } catch {
        continue;
      }
    }
    if (eventName === "done" && !isSafeDonePayload(data)) continue;
    if (eventName === "chunk" && typeof data.text !== "string") continue;
    if (eventName === "error" && typeof data.message !== "string") {
      data = { message: "Please try again in a moment.", code: "unknown" };
    }
    events.push({ event: eventName, data });
  }
  return events;
}

export function isSafeDonePayload(payload) {
  if (!payload || typeof payload !== "object") return false;
  for (const key of Object.keys(payload)) {
    if (FORBIDDEN_DONE_KEYS.has(key)) return false;
  }
  for (const src of payload.sources || []) {
    if (!src || typeof src !== "object") return false;
    if ("score" in src) return false;
  }
  return true;
}

export async function consumeSseStream(response, onEvent) {
  if (!response.body) {
    throw new Error("Streaming body missing.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const events = parseSseBlocks(part);
      for (const evt of events) {
        onEvent(evt);
      }
    }
  }
  if (buffer.trim()) {
    const events = parseSseBlocks(buffer);
    for (const evt of events) {
      onEvent(evt);
    }
  }
}
