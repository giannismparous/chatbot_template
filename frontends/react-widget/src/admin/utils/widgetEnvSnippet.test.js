import { describe, expect, it } from "vitest";
import { buildWidgetEnvSnippet } from "./widgetEnvSnippet.js";

describe("buildWidgetEnvSnippet", () => {
  it("includes full widget key when still in memory", () => {
    const snippet = buildWidgetEnvSnippet({
      clientId: "demo",
      widgetKey: "wk_full_secret_key",
      apiBase: "http://127.0.0.1:8000",
    });
    expect(snippet).toContain("VITE_CLIENT_KEY=wk_full_secret_key");
    expect(snippet).toContain("VITE_CLIENT_ID=demo");
  });

  it("shows prefix guidance when full key is unavailable", () => {
    const snippet = buildWidgetEnvSnippet({
      clientId: "demo",
      keyPrefix: "wk_OuAL",
    });
    expect(snippet).toContain("prefix wk_OuAL");
    expect(snippet).toContain("VITE_CLIENT_KEY=wk_REPLACE_ME");
    expect(snippet).not.toContain("wk_full");
  });
});
