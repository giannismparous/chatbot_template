import { beforeEach, describe, expect, it, vi } from "vitest";

vi.stubGlobal(
  "fetch",
  vi.fn(async () => ({
    ok: true,
    status: 200,
    text: async () => JSON.stringify({ status: "public_configured", citation_url: "https://example.com/doc" }),
  })),
);

const { saveUploadCitation, deleteUploadCitation } = await import("./adminClient.js");

describe("upload citation admin API", () => {
  beforeEach(() => {
    fetch.mockReset();
  });

  it("saveUploadCitation PUTs safely encoded path", async () => {
    fetch.mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ status: "public_configured" }),
    });
    await saveUploadCitation("admin-secret", "demo", "folder/doc.txt", {
      citation_url: "https://example.com/doc",
      title: "Doc",
      source_visibility: "public",
    });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toContain("/uploads/folder/doc.txt/citation");
    expect(init.method).toBe("PUT");
    expect(init.headers["x-admin-token"]).toBe("admin-secret");
    expect(init.headers).not.toHaveProperty("x-client-key");
  });

  it("deleteUploadCitation DELETEs citation mapping", async () => {
    fetch.mockResolvedValue({ ok: true, status: 204, text: async () => "" });
    await deleteUploadCitation("admin-secret", "demo", "doc.txt");
    const [url, init] = fetch.mock.calls[0];
    expect(url).toContain("/uploads/doc.txt/citation");
    expect(init.method).toBe("DELETE");
  });
});
