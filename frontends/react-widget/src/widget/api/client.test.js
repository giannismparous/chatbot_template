import { describe, expect, it } from "vitest";
import { widgetHeaders } from "./client.js";

describe("widgetHeaders", () => {
  it("never includes x-admin-token", () => {
    const headers = widgetHeaders({ "Content-Type": "application/json" });
    expect(headers).not.toHaveProperty("x-admin-token");
    expect(Object.keys(headers).join(",")).not.toContain("admin");
  });
});
