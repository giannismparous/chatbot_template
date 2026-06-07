import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const adminRoot = dirname(fileURLToPath(import.meta.url));

const ADMIN_SOURCE_FILES = [
  "AdminContext.jsx",
  "AdminTokenGate.jsx",
  "AdminDashboard.jsx",
  "api/adminClient.js",
  "api/errors.js",
  "api/pollJob.js",
  "components/CreateClientForm.jsx",
  "components/UploadPanel.jsx",
  "components/PipelinePanel.jsx",
  "components/WidgetEnvSnippet.jsx",
  "components/WidgetKeyRevealModal.jsx",
  "utils/widgetEnvSnippet.js",
];

describe("admin security invariants", () => {
  it("never persists admin token via browser storage APIs", () => {
    for (const file of ADMIN_SOURCE_FILES) {
      const src = readFileSync(join(adminRoot, file), "utf8");
      expect(src, file).not.toMatch(/localStorage|sessionStorage|document\.cookie/);
    }
  });

  it("admin API client does not import widget x-client-key helpers", () => {
    const src = readFileSync(join(adminRoot, "api/adminClient.js"), "utf8");
    expect(src).not.toMatch(/widget\/api\/client/);
    expect(src).not.toMatch(/widgetHeaders/);
    expect(src).not.toMatch(/x-client-key/);
  });
});
