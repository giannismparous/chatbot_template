import { describe, expect, it, vi } from "vitest";
import {
  createWebSource,
  deleteWebSource,
  listWebSources,
  triggerCrawl,
} from "./adminClient.js";

describe("adminClient web sources", () => {
  it("lists web sources", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ sources: [{ id: "home", url: "https://simasiaai.gr/", status: "configured" }] }),
    });
    const data = await listWebSources("token", "default");
    expect(data.sources[0].id).toBe("home");
  });

  it("creates web source with render mode", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      text: async () =>
        JSON.stringify({
          id: "home",
          url: "https://simasiaai.gr/",
          status: "configured",
          render_mode: "playwright",
          wait_until: "networkidle",
        }),
    });
    const created = await createWebSource("token", "default", {
      url: "https://simasiaai.gr/",
      render_mode: "playwright",
      wait_until: "networkidle",
      wait_selector: "body",
    });
    expect(created.render_mode).toBe("playwright");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        body: expect.stringContaining('"render_mode":"playwright"'),
      }),
    );
  });

  it("creates and deletes web sources", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 201,
        text: async () => JSON.stringify({ id: "home", url: "https://simasiaai.gr/", status: "configured" }),
      })
      .mockResolvedValueOnce({ ok: true, status: 204, text: async () => "" });
    const created = await createWebSource("token", "default", { url: "https://simasiaai.gr/" });
    expect(created.id).toBe("home");
    await deleteWebSource("token", "default", "home");
  });

  it("triggers crawl job", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      text: async () => JSON.stringify({ job_id: "job_1", job_type: "crawl", status: "pending" }),
    });
    const job = await triggerCrawl("token", "default", ["home"]);
    expect(job.job_type).toBe("crawl");
  });
});
