import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearSessionId,
  listStoredSessionKeys,
  readSessionId,
  sessionStorageKey,
  writeSessionId,
} from "./storage.js";

function createMemoryStorage() {
  const map = new Map();
  return {
    get length() {
      return map.size;
    },
    key(i) {
      return [...map.keys()][i] ?? null;
    },
    getItem(k) {
      return map.has(k) ? map.get(k) : null;
    },
    setItem(k, v) {
      map.set(k, String(v));
    },
    removeItem(k) {
      map.delete(k);
    },
    clear() {
      map.clear();
    },
  };
}

describe("session storage", () => {
  beforeEach(() => {
    vi.stubGlobal("sessionStorage", createMemoryStorage());
    vi.stubGlobal("localStorage", createMemoryStorage());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses prefixed key per client", () => {
    expect(sessionStorageKey("acme")).toBe("chatbot:session:acme");
  });

  it("reads and writes session_id only", () => {
    writeSessionId("default", "sess-123");
    expect(readSessionId("default")).toBe("sess-123");
    expect(listStoredSessionKeys()).toEqual(["chatbot:session:default"]);
  });

  it("clears session per client", () => {
    writeSessionId("default", "sess-123");
    writeSessionId("other", "sess-456");
    clearSessionId("default");
    expect(readSessionId("default")).toBeNull();
    expect(readSessionId("other")).toBe("sess-456");
  });

  it("does not store messages or history keys", () => {
    writeSessionId("default", "sess-abc");
    sessionStorage.setItem("chatbot:messages", "should-not-exist");
    sessionStorage.setItem("chatbot:history", "[]");

    const keys = listStoredSessionKeys();
    expect(keys).toEqual(["chatbot:session:default"]);
    expect(keys.some((k) => k.includes("message") || k.includes("history"))).toBe(false);
  });
});
