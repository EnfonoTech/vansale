import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearApprovalsCache, loadInbox, saveInbox } from "../cache";
import { inbox, item } from "./fixtures";

const KEY = "vansale.approvals.cache.v1";

describe("approvals cache", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("returns the inbox for the user it was saved for, with when it was saved", () => {
    const saved = inbox({ sections: [{ category: "Approval Pending", items: [item({ docname: "JV-9" })] }] });
    saveInbox("a@x", saved);
    const hit = loadInbox("a@x");
    expect(hit?.inbox).toEqual(saved);
    expect(Number.isNaN(Date.parse(hit?.savedAt ?? ""))).toBe(false);
  });

  it("never shows one user's inbox to another", () => {
    saveInbox("a@x", inbox());
    expect(loadInbox("b@x")).toBeNull();
  });

  it("saving for another user replaces the first user's copy", () => {
    saveInbox("a@x", inbox());
    saveInbox("b@x", inbox({ total: 5 }));
    expect(loadInbox("a@x")).toBeNull();
    expect(loadInbox("b@x")?.inbox.total).toBe(5);
  });

  it("clearApprovalsCache removes it for everyone", () => {
    saveInbox("a@x", inbox());
    clearApprovalsCache();
    expect(loadInbox("a@x")).toBeNull();
    expect(loadInbox("b@x")).toBeNull();
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it("a corrupt stored string reads as nothing, without throwing", () => {
    window.localStorage.setItem(KEY, "{not json");
    expect(loadInbox("a@x")).toBeNull();
  });

  it("stored JSON of the wrong shape reads as nothing", () => {
    window.localStorage.setItem(KEY, JSON.stringify({ user: "a@x", savedAt: "2026-11-19T08:00:00Z", inbox: { total: 1 } }));
    expect(loadInbox("a@x")).toBeNull();
    window.localStorage.setItem(KEY, JSON.stringify("text"));
    expect(loadInbox("a@x")).toBeNull();
    window.localStorage.setItem(KEY, "null");
    expect(loadInbox("a@x")).toBeNull();
  });

  it("a storage that refuses writes or reads does not break the screen", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    expect(() => saveInbox("a@x", inbox())).not.toThrow();
    vi.restoreAllMocks();

    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(loadInbox("a@x")).toBeNull();
    vi.restoreAllMocks();

    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(() => clearApprovalsCache()).not.toThrow();
  });
});
