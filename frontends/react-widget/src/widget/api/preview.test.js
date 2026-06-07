import { beforeEach, describe, expect, it, vi } from "vitest";
import { previewChat } from "./preview.js";

describe("previewChat", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("uses x-admin-token header and not widget key path", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      text: async () =>
        JSON.stringify({
          answer: "preview",
          sources: [],
          confidence: { level: "high", reason: "ok" },
          summary: { chunks: 3 },
        }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await previewChat({
      clientId: "default",
      token: "admin-secret",
      message: "test",
      indexScope: "pending",
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["x-admin-token"]).toBe("admin-secret");
    expect(init.headers["x-client-key"]).toBeUndefined();
    expect(result.answer).toBe("preview");
    expect(result.summary).toEqual({ chunks: 3 });
    expect(result).not.toHaveProperty("trace");

    vi.unstubAllGlobals();
  });
});
