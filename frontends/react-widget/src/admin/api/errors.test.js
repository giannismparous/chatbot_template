import { describe, expect, it } from "vitest";
import { AdminApiError, adminHeaders, normalizeAdminError } from "./errors.js";

describe("adminHeaders", () => {
  it("includes x-admin-token and merges extras", () => {
    const headers = adminHeaders("secret-token", { "Content-Type": "application/json" });
    expect(headers["x-admin-token"]).toBe("secret-token");
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("never includes x-client-key", () => {
    const headers = adminHeaders("secret-token");
    expect(headers).not.toHaveProperty("x-client-key");
  });
});

describe("normalizeAdminError", () => {
  it("maps 401 to invalid token message", () => {
    const err = normalizeAdminError({ status: 401 }, {});
    expect(err).toBeInstanceOf(AdminApiError);
    expect(err.status).toBe(401);
    expect(err.message).toMatch(/admin token/i);
  });

  it("maps deploy 409 with readable reason", () => {
    const err = normalizeAdminError(
      { status: 409 },
      { detail: { reason: "eval_not_eligible", detail: "Eval did not pass deploy gate." } },
    );
    expect(err.status).toBe(409);
    expect(err.reason).toBe("eval_not_eligible");
    expect(err.message).toBe("Eval did not pass deploy gate.");
  });
});
