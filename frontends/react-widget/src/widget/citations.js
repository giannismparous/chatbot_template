const CITATION_MARKER = /\[(\d+)\]/g;

export function isPublicSource(source) {
  if (!source || typeof source !== "object") return false;
  if (source.clickable === false) return false;
  const url = String(source.url || "").trim();
  if (!url) return false;
  const lower = url.toLowerCase();
  if (!lower.startsWith("http://") && !lower.startsWith("https://")) return false;
  if (lower.includes("uploads/") || lower.includes("internal://") || lower.includes("web_cache") || lower.includes("drive.google.com")) {
    return false;
  }
  return true;
}

export function filterPublicSources(sources) {
  if (!Array.isArray(sources)) return [];
  return sources
    .filter(isPublicSource)
    .map((s) => ({
      index: Number(s.index),
      title: String(s.title || "Source"),
      url: String(s.url),
      clickable: s.clickable !== false,
    }));
}

export function mapConfidenceFromV1(score) {
  const value = Number(score);
  if (Number.isNaN(value) || value <= 0) {
    return { level: "none", reason: "No approved knowledge found for this question." };
  }
  if (value >= 0.7) return { level: "high", reason: "Strong document match." };
  if (value >= 0.35) return { level: "medium", reason: "Moderate document match; answer may be incomplete." };
  return { level: "low", reason: "Weak document match; verify with official sources." };
}

export function normalizeChatResult(raw, { version = "v2" } = {}) {
  const sources = filterPublicSources(raw?.sources);
  const confidence =
    raw?.confidence && typeof raw.confidence === "object"
      ? { level: raw.confidence.level || "medium", reason: raw.confidence.reason || "" }
      : version === "v1"
        ? mapConfidenceFromV1(raw?.confidence)
        : { level: "medium", reason: "" };

  return {
    answer: String(raw?.answer || ""),
    sources,
    confidence,
    requires_human: Boolean(raw?.requires_human),
    escalation: raw?.escalation || null,
    session_id: raw?.session_id || null,
    trace_id: raw?.trace_id || null,
  };
}

export function splitCitationSegments(text) {
  const segments = [];
  let lastIndex = 0;
  const input = String(text || "");
  for (const match of input.matchAll(CITATION_MARKER)) {
    const idx = match.index ?? 0;
    if (idx > lastIndex) {
      segments.push({ type: "text", value: input.slice(lastIndex, idx) });
    }
    segments.push({ type: "cite", value: Number(match[1]) });
    lastIndex = idx + match[0].length;
  }
  if (lastIndex < input.length) {
    segments.push({ type: "text", value: input.slice(lastIndex) });
  }
  return segments.length ? segments : [{ type: "text", value: input }];
}
