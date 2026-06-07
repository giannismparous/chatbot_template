import { beforeEach, describe, expect, it, vi } from "vitest";

vi.stubGlobal(
  "fetch",
  vi.fn(async () => ({
    ok: true,
    status: 200,
    text: async () => JSON.stringify([]),
  })),
);

const {
  createClient,
  deployIndex,
  listClients,
  probeAdminToken,
  triggerEval,
  triggerIngest,
} = await import("./adminClient.js");

describe("adminClient", () => {
  beforeEach(() => {
    fetch.mockReset();
    fetch.mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify([]),
    });
  });

  it("sends x-admin-token on admin requests", async () => {
    await listClients("admin-secret");
    expect(fetch).toHaveBeenCalledOnce();
    const [, init] = fetch.mock.calls[0];
    expect(init.headers["x-admin-token"]).toBe("admin-secret");
  });

  it("never sends x-client-key", async () => {
    await probeAdminToken("admin-secret");
    const [, init] = fetch.mock.calls[0];
    expect(init.headers).not.toHaveProperty("x-client-key");
    expect(JSON.stringify(init.headers)).not.toContain("x-client-key");
  });

  it("defaults eval llm_mode to live", async () => {
    fetch.mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ job_id: "job-1", status: "pending" }),
    });
    await triggerEval("admin-secret", "default");
    const [url, init] = fetch.mock.calls[0];
    expect(url).toContain("/jobs/eval");
    expect(JSON.parse(init.body).llm_mode).toBe("live");
  });

  it("createClient requests reveal_widget_key", async () => {
    fetch.mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ client_id: "demo", widget_key: "wk_full_key" }),
    });
    const result = await createClient("admin-secret", { client_id: "demo", display_name: "Demo" });
    const [, init] = fetch.mock.calls[0];
    expect(JSON.parse(init.body).reveal_widget_key).toBe(true);
    expect(result.widget_key).toBe("wk_full_key");
  });

  it("ingest uses POST jobs/ingest", async () => {
    fetch.mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ job_id: "ing-1", status: "pending" }),
    });
    await triggerIngest("admin-secret", "default");
    const [url, init] = fetch.mock.calls[0];
    expect(url).toContain("/jobs/ingest");
    expect(init.method).toBe("POST");
  });

  it("deploy uses POST deploy endpoint", async () => {
    fetch.mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ active: "v2" }),
    });
    await deployIndex("admin-secret", "default");
    const [url, init] = fetch.mock.calls[0];
    expect(url).toContain("/deploy");
    expect(init.method).toBe("POST");
  });

  it("surfaces 401 from wrong token", async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: "Unauthorized" }),
    });
    await expect(probeAdminToken("bad-token")).rejects.toMatchObject({
      status: 401,
      message: expect.stringMatching(/admin token/i),
    });
  });

  it("surfaces deploy 409 with reason", async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 409,
      text: async () =>
        JSON.stringify({
          detail: { reason: "eval_version_mismatch", detail: "Re-run eval against pending index." },
        }),
    });
    await expect(deployIndex("admin-secret", "default")).rejects.toMatchObject({
      status: 409,
      reason: "eval_version_mismatch",
      message: "Re-run eval against pending index.",
    });
  });
});
