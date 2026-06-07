import { describe, expect, it } from "vitest";
import { canDeploy, deployBlockReason } from "./deployEligibility.js";

describe("deployEligibility", () => {
  const index = { active: "v1", pending: "v2", previous: "v1" };
  const evalPass = {
    run_id: "run-1",
    status: "pass",
    deploy_eligible: true,
    evaluated_index_version: "v2",
  };

  it("allows deploy when pending eval matches and passes", () => {
    expect(canDeploy(index, evalPass)).toBe(true);
    expect(deployBlockReason(index, evalPass)).toBeNull();
  });

  it("blocks deploy without pending index", () => {
    expect(canDeploy({ active: "v1" }, evalPass)).toBe(false);
    expect(deployBlockReason({ active: "v1" }, evalPass)).toMatch(/pending/i);
  });

  it("blocks deploy when eval version mismatches pending", () => {
    const mismatch = { ...evalPass, evaluated_index_version: "v1" };
    expect(canDeploy(index, mismatch)).toBe(false);
    expect(deployBlockReason(index, mismatch)).toMatch(/version/i);
  });

  it("blocks deploy when eval is not deploy-eligible", () => {
    const fail = { ...evalPass, status: "fail", deploy_eligible: false };
    expect(canDeploy(index, fail)).toBe(false);
    expect(deployBlockReason(index, fail)).toMatch(/deploy-eligible/i);
  });
});
