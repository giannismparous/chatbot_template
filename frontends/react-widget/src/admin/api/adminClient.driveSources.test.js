import { describe, expect, it, vi } from "vitest";
import {
  createDriveSource,
  deleteDriveSource,
  listDriveSources,
  triggerDriveSync,
} from "./adminClient.js";

describe("adminClient drive sources", () => {
  it("lists drive sources", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          sources: [{ id: "docs", folder_id: "abc123", status: "configured" }],
          credentials_configured: false,
        }),
    });
    const data = await listDriveSources("token", "default");
    expect(data.sources[0].id).toBe("docs");
  });

  it("creates drive source with folder id", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      text: async () =>
        JSON.stringify({ id: "docs", folder_id: "abc123", status: "configured", enabled: true }),
    });
    const created = await createDriveSource("token", "default", {
      folder_id: "abc123",
      title: "Docs",
    });
    expect(created.folder_id).toBe("abc123");
  });

  it("triggers drive sync job", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      text: async () => JSON.stringify({ job_id: "job_1", job_type: "drive_sync", status: "pending" }),
    });
    const job = await triggerDriveSync("token", "default", ["docs"]);
    expect(job.job_type).toBe("drive_sync");
  });

  it("deletes drive source", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 204, text: async () => "" });
    await deleteDriveSource("token", "default", "docs");
  });
});
