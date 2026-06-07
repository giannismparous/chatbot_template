import { describe, expect, it } from "vitest";
import {
  filterPublicSources,
  isPublicSource,
  normalizeChatResult,
  splitCitationSegments,
} from "./citations.js";

describe("isPublicSource", () => {
  it("allows https public URLs", () => {
    expect(isPublicSource({ url: "https://example.com/doc", clickable: true })).toBe(true);
  });

  it("blocks uploads, internal, drive, missing, and non-http URLs", () => {
    expect(isPublicSource({ url: "https://x.com/uploads/file.pdf" })).toBe(false);
    expect(isPublicSource({ url: "internal://doc/1" })).toBe(false);
    expect(isPublicSource({ url: "https://drive.google.com/file/d/abc" })).toBe(false);
    expect(isPublicSource({ url: "" })).toBe(false);
    expect(isPublicSource({ url: "ftp://example.com" })).toBe(false);
    expect(isPublicSource({ clickable: false, url: "https://example.com" })).toBe(false);
  });
});

describe("filterPublicSources", () => {
  it("returns only safe public sources", () => {
    const sources = filterPublicSources([
      { index: 1, title: "Good", url: "https://good.com" },
      { index: 2, title: "Upload", url: "https://x.com/uploads/a.pdf" },
      { index: 3, title: "Drive", url: "https://drive.google.com/x" },
    ]);
    expect(sources).toHaveLength(1);
    expect(sources[0].index).toBe(1);
    expect(sources[0]).not.toHaveProperty("score");
  });
});

describe("splitCitationSegments", () => {
  it("splits citation markers", () => {
    expect(splitCitationSegments("See [1] and [2].")).toEqual([
      { type: "text", value: "See " },
      { type: "cite", value: 1 },
      { type: "text", value: " and " },
      { type: "cite", value: 2 },
      { type: "text", value: "." },
    ]);
  });

  it("returns plain text when no markers", () => {
    expect(splitCitationSegments("No citations")).toEqual([{ type: "text", value: "No citations" }]);
  });
});

describe("normalizeChatResult", () => {
  it("filters sources and maps v2 confidence", () => {
    const result = normalizeChatResult(
      {
        answer: "Answer [1]",
        sources: [
          { index: 1, title: "A", url: "https://a.com" },
          { index: 2, title: "B", url: "internal://b" },
        ],
        confidence: { level: "low", reason: "weak" },
        requires_human: true,
        escalation: { message: "Call us" },
        trace: { secret: true },
      },
      { version: "v2" },
    );

    expect(result.sources).toHaveLength(1);
    expect(result.confidence.level).toBe("low");
    expect(result.requires_human).toBe(true);
    expect(result.escalation.message).toBe("Call us");
    expect(result).not.toHaveProperty("trace");
  });

  it("handles crisis/no_context without fake sources", () => {
    const result = normalizeChatResult(
      {
        answer: "I cannot help with that.",
        sources: [],
        confidence: { level: "none", reason: "No approved knowledge found." },
      },
      { version: "v2" },
    );
    expect(result.sources).toEqual([]);
    expect(result.confidence.level).toBe("none");
  });

  it("maps v1 numeric confidence", () => {
    const result = normalizeChatResult({ answer: "x", confidence: 0.8 }, { version: "v1" });
    expect(result.confidence.level).toBe("high");
  });
});
