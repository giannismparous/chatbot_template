import { describe, expect, it } from "vitest";
import { isSafeDonePayload, parseSseBlocks } from "./sseParser.js";

describe("parseSseBlocks", () => {
  it("parses chunk and done events", () => {
    const text = [
      "event: chunk",
      'data: {"text":"Hello"}',
      "",
      "event: done",
      'data: {"answer":"Hello","sources":[],"confidence":{"level":"high","reason":"ok"}}',
    ].join("\n");

    const events = parseSseBlocks(text);
    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({ event: "chunk", data: { text: "Hello" } });
    expect(events[1].event).toBe("done");
    expect(events[1].data.answer).toBe("Hello");
  });

  it("ignores unknown SSE events", () => {
    const text = [
      "event: trace",
      'data: {"foo":"bar"}',
      "",
      "event: chunk",
      'data: {"text":"x"}',
    ].join("\n");

    expect(parseSseBlocks(text)).toEqual([{ event: "chunk", data: { text: "x" } }]);
  });

  it("drops done payloads with forbidden keys", () => {
    const text = [
      "event: done",
      'data: {"answer":"x","trace":{"secret":true}}',
    ].join("\n");
    expect(parseSseBlocks(text)).toEqual([]);
  });

  it("drops done payloads with source scores", () => {
    const text = [
      "event: done",
      'data: {"answer":"x","sources":[{"index":1,"url":"https://a.com","score":0.9}]}',
    ].join("\n");
    expect(parseSseBlocks(text)).toEqual([]);
  });

  it("normalizes error events with safe message", () => {
    const text = ["event: error", "data: {}"].join("\n");
    const events = parseSseBlocks(text);
    expect(events[0].data.message).toBe("Please try again in a moment.");
  });

  it("ignores chunk events without text", () => {
    const text = ["event: chunk", "data: {}"].join("\n");
    expect(parseSseBlocks(text)).toEqual([]);
  });
});

describe("isSafeDonePayload", () => {
  it("accepts public-safe done payload", () => {
    expect(
      isSafeDonePayload({
        answer: "Hi",
        sources: [{ index: 1, title: "A", url: "https://example.com" }],
      }),
    ).toBe(true);
  });

  it("rejects trace and retrieval fields", () => {
    expect(isSafeDonePayload({ answer: "x", trace: {} })).toBe(false);
    expect(isSafeDonePayload({ answer: "x", retrieval: {} })).toBe(false);
    expect(isSafeDonePayload({ answer: "x", prompt: "secret" })).toBe(false);
  });
});
