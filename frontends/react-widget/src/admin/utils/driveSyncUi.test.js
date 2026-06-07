import { describe, expect, it, vi } from "vitest";
import {
  formatDriveSyncResult,
  isDriveSyncBusy,
  isRowSyncing,
  runDriveSyncJob,
  syncBusyKey,
  syncPhaseMessage,
} from "./driveSyncUi.js";

describe("driveSyncUi", () => {
  it("shows loading state keys immediately", () => {
    expect(syncBusyKey(["docs"])).toBe("sync-docs");
    expect(isDriveSyncBusy("sync-docs")).toBe(true);
    expect(isRowSyncing("docs", "sync-docs")).toBe(true);
    expect(syncPhaseMessage("starting")).toBe("Syncing Drive…");
  });

  it("disables sync conceptually while busy", () => {
    expect(isDriveSyncBusy("sync-all")).toBe(true);
    expect(isDriveSyncBusy("add")).toBe(false);
  });

  it("polls async jobs until terminal state", async () => {
    const triggerDriveSync = vi.fn().mockResolvedValue({
      job_id: "job_1",
      status: "pending",
    });
    const runJobAndWait = vi.fn().mockResolvedValue({
      job_id: "job_1",
      status: "succeeded",
      result: {
        sources: [
          {
            sync_summary: "Synced with warnings: 2 discovered, 1 fetched, 1 failed.",
          },
        ],
      },
    });
    const phases = [];
    const finalJob = await runDriveSyncJob({
      token: "t",
      clientId: "default",
      sourceIds: ["docs"],
      triggerDriveSync,
      runJobAndWait,
      onProgress: (phase, message) => phases.push([phase, message]),
    });
    expect(phases[0]).toEqual(["starting", "Syncing Drive…"]);
    expect(phases[1]).toEqual(["job_started", "Sync job started"]);
    expect(phases[2]).toEqual(["polling", "Polling job…"]);
    expect(phases[3]).toEqual(["completed", "Sync completed"]);
    expect(runJobAndWait).toHaveBeenCalledWith("t", "default", "job_1");
    expect(formatDriveSyncResult(finalJob)).toContain("Synced with warnings");
  });

  it("formats partial extraction warning summary", () => {
    const summary = formatDriveSyncResult({
      status: "succeeded",
      result: {
        sources: [
          {
            sync_summary: "Synced with warnings: 14 discovered, 14 fetched, 3 skipped unchanged, 2 failed.",
            failure_breakdown: { "DOCX extraction unavailable. Run pip install -r requirements.txt.": 2 },
          },
        ],
      },
    });
    expect(summary).toContain("Synced with warnings");
    expect(summary).toContain("14 fetched");
  });
});
