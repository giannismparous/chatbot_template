import { beforeEach, describe, expect, it, vi } from "vitest";

const chatV2NonStream = vi.fn();
const chatV2Stream = vi.fn();
const chatV1NonStream = vi.fn();
const chatV1Stream = vi.fn();
const readSessionId = vi.fn();
const writeSessionId = vi.fn();

vi.mock("./chatV2.js", () => ({
  chatV2NonStream: (...args) => chatV2NonStream(...args),
  chatV2Stream: (...args) => chatV2Stream(...args),
}));

vi.mock("./chatV1.js", () => ({
  chatV1NonStream: (...args) => chatV1NonStream(...args),
  chatV1Stream: (...args) => chatV1Stream(...args),
}));

vi.mock("./client.js", () => ({
  CLIENT_ID: "default",
  STREAMING_ENABLED: true,
  CHAT_API_VERSION: "v2",
}));

vi.mock("../session/storage.js", () => ({
  readSessionId: (...args) => readSessionId(...args),
  writeSessionId: (...args) => writeSessionId(...args),
  clearSessionId: vi.fn(),
}));

const { sendChat, buildChatPayload } = await import("./index.js");

describe("buildChatPayload", () => {
  it("omits history when session_id is present", () => {
    const payload = buildChatPayload({
      clientId: "default",
      message: "hi",
      sessionId: "sess-1",
      history: [{ role: "user", content: "old" }],
    });
    expect(payload.session_id).toBe("sess-1");
    expect(payload.history).toBeUndefined();
  });
});

describe("sendChat fallback chain", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    readSessionId.mockReturnValue(null);
  });

  it("uses v2 non-stream happy path", async () => {
    chatV2NonStream.mockResolvedValue({ answer: "ok", session_id: "s1" });
    const result = await sendChat({ message: "hello", streaming: false });
    expect(chatV2Stream).not.toHaveBeenCalled();
    expect(chatV2NonStream).toHaveBeenCalled();
    expect(result.answer).toBe("ok");
    expect(writeSessionId).toHaveBeenCalledWith("default", "s1");
  });

  it("uses v2 streaming chunk + done handling", async () => {
    chatV2Stream.mockResolvedValue({ answer: "streamed", session_id: "s2" });
    const chunks = [];
    await sendChat({
      message: "hello",
      streaming: true,
      onChunk: (t) => chunks.push(t),
    });
    expect(chatV2Stream).toHaveBeenCalled();
    expect(chatV1NonStream).not.toHaveBeenCalled();
  });

  it("falls back to v2 non-stream when stream fails", async () => {
    chatV2Stream.mockRejectedValue(new Error("stream fail"));
    chatV2NonStream.mockResolvedValue({ answer: "fallback", session_id: "s3" });
    const result = await sendChat({ message: "hello", streaming: true });
    expect(chatV2Stream).toHaveBeenCalled();
    expect(chatV2NonStream).toHaveBeenCalled();
    expect(result.answer).toBe("fallback");
  });

  it("falls back to v1 when v2 fails", async () => {
    chatV2Stream.mockRejectedValue(new Error("stream fail"));
    chatV2NonStream.mockRejectedValue(new Error("v2 fail"));
    chatV1NonStream.mockResolvedValue({ answer: "v1 ok" });
    const result = await sendChat({ message: "hello", streaming: false });
    expect(chatV1NonStream).toHaveBeenCalled();
    expect(result.answer).toBe("v1 ok");
  });

  it("falls back v1 stream after v2 stream and v2 non-stream fail", async () => {
    chatV2Stream.mockRejectedValue(new Error("stream fail"));
    chatV2NonStream.mockRejectedValue(new Error("v2 fail"));
    chatV1Stream.mockResolvedValue({ answer: "v1 stream" });
    const result = await sendChat({ message: "hello", streaming: true });
    expect(chatV1Stream).toHaveBeenCalled();
    expect(result.answer).toBe("v1 stream");
  });
});
