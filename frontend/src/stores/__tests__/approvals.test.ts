/**
 * The approvals store: what it shows (the saved copy first, then the
 * server's), what it does when a decision is refused, how it polls, and what
 * it forgets when the user goes. The API is mocked; the cache, the session
 * store and localStorage are the real ones.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { inbox as makeInbox, item } from "@/features/approvals/__tests__/fixtures";
import { loadInbox, saveInbox } from "@/features/approvals/cache";
import type { ConfigDefaults } from "@/api/me";

const api = vi.hoisted(() => ({ inbox: vi.fn(), count: vi.fn(), apply: vi.fn() }));
vi.mock("@/api/approvals", () => api);
const online = vi.hoisted(() => ({ isOnline: vi.fn() }));
vi.mock("@/app/online", () => online);

import { useApprovalsStore } from "../approvals";
import { useSessionStore } from "../session";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function signIn(user = "a@x") {
  useSessionStore().$patch({ user });
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
}

const THREE = makeInbox({
  total: 3,
  needs_you: 2,
  waiting: 1,
  stats: { high: 1, overdue: 0 },
  sections: [
    { category: "Approval Pending", items: [item({ docname: "JV-1" }), item({ docname: "JV-2" })] },
  ],
  waiting_items: [item({ docname: "JV-3", is_waiting: true })],
});

beforeEach(() => {
  window.localStorage.clear();
  setActivePinia(createPinia());
  online.isOnline.mockReturnValue(true);
  api.inbox.mockResolvedValue(THREE);
  api.count.mockResolvedValue({ total: 9, needs_you: 7, waiting: 2, high: 1, overdue: 1 });
  api.apply.mockResolvedValue({ ok: true, new_state: "Approved", recommended: false });
  signIn();
});

afterEach(() => {
  useApprovalsStore().stopPolling();
  vi.useRealTimers();
  setVisibility("visible");
});

describe("refresh", () => {
  it("online: stores the inbox and writes the saved copy", async () => {
    const store = useApprovalsStore();
    await store.refresh();

    expect(api.inbox).toHaveBeenCalledTimes(1);
    expect(store.inbox).toEqual(THREE);
    expect(store.stale).toBe(false);
    expect(store.loading).toBe(false);
    expect(store.error).toBeNull();
    expect(loadInbox("a@x")?.inbox).toEqual(THREE);
  });

  it("the numbers follow the inbox", async () => {
    const store = useApprovalsStore();
    expect(store.needsYou).toBe(0);
    expect(store.badge).toBe(0);
    await store.refresh();
    expect(store.needsYou).toBe(2);
    expect(store.badge).toBe(2);
  });

  it("shows the saved copy while the server is still answering", async () => {
    const saved = makeInbox({ total: 5, needs_you: 5 });
    saveInbox("a@x", saved);
    const pending = deferred<typeof THREE>();
    api.inbox.mockReturnValue(pending.promise);

    const store = useApprovalsStore();
    const done = store.refresh();
    expect(store.inbox).toEqual(saved);
    expect(store.stale).toBe(true);
    expect(store.loading).toBe(true);

    pending.resolve(THREE);
    await done;
    expect(store.inbox).toEqual(THREE);
    expect(store.stale).toBe(false);
    expect(store.loading).toBe(false);
  });

  it("offline with a saved copy for this user: shows it as stale and calls nothing", async () => {
    const saved = makeInbox({ total: 5, needs_you: 5 });
    saveInbox("a@x", saved);
    online.isOnline.mockReturnValue(false);

    const store = useApprovalsStore();
    await store.refresh();

    expect(api.inbox).not.toHaveBeenCalled();
    expect(store.inbox).toEqual(saved);
    expect(store.stale).toBe(true);
    expect(store.needsYou).toBe(5);
  });

  it("offline with another user's saved copy: shows nothing", async () => {
    saveInbox("someone@else", makeInbox({ total: 5, needs_you: 5 }));
    online.isOnline.mockReturnValue(false);

    const store = useApprovalsStore();
    await store.refresh();

    expect(api.inbox).not.toHaveBeenCalled();
    expect(store.inbox).toBeNull();
    expect(store.stale).toBe(false);
  });

  it("a failed fetch keeps what was shown, marked stale, with the error", async () => {
    const store = useApprovalsStore();
    await store.refresh();
    api.inbox.mockRejectedValue(new Error("Request timed out"));

    await store.refresh();

    expect(store.inbox).toEqual(THREE);
    expect(store.stale).toBe(true);
    expect(store.error).toBe("Request timed out");
    expect(store.loading).toBe(false);
  });

  it("a failed fetch with nothing to show leaves the inbox empty, not stale", async () => {
    api.inbox.mockRejectedValue(new Error("HTTP 500"));
    const store = useApprovalsStore();
    await store.refresh();
    expect(store.inbox).toBeNull();
    expect(store.stale).toBe(false);
    expect(store.error).toBe("HTTP 500");
  });

  it("a later success clears the error", async () => {
    api.inbox.mockRejectedValueOnce(new Error("HTTP 500"));
    const store = useApprovalsStore();
    await store.refresh();
    await store.refresh();
    expect(store.error).toBeNull();
    expect(store.inbox).toEqual(THREE);
  });

  it("does nothing without a signed-in user", async () => {
    useSessionStore().$patch({ user: null });
    const store = useApprovalsStore();
    await store.refresh();
    expect(api.inbox).not.toHaveBeenCalled();
    expect(store.inbox).toBeNull();
  });

  it("the answer of an older request never replaces a newer one", async () => {
    const older = deferred<typeof THREE>();
    const newer = deferred<typeof THREE>();
    api.inbox.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    const fresh = makeInbox({ total: 1, needs_you: 1 });

    const store = useApprovalsStore();
    const first = store.refresh();
    const second = store.refresh();
    newer.resolve(fresh);
    await second;
    older.resolve(THREE);
    await first;

    expect(store.inbox).toEqual(fresh);
    expect(loadInbox("a@x")?.inbox).toEqual(fresh);
  });

  it("a user switch drops the previous user's inbox before showing anything", async () => {
    const store = useApprovalsStore();
    await store.refresh();
    expect(store.inbox).toEqual(THREE);

    store.mine = [
      { doctype: "Journal Entry", docname: "JV-1", transaction: "Journal Entry", state: "Pending", holder: "x", role_id: "r", days: 1, priority: "Low" },
    ];
    signIn("b@x");
    const pending = deferred<typeof THREE>();
    api.inbox.mockReturnValue(pending.promise);
    const done = store.refresh();

    expect(store.inbox).toBeNull();
    expect(store.mine).toEqual([]);
    expect(store.needsYou).toBe(0);
    pending.resolve(makeInbox({ total: 4, needs_you: 4 }));
    await done;
    expect(store.needsYou).toBe(4);
    expect(loadInbox("a@x")).toBeNull();
    expect(loadInbox("b@x")?.inbox.total).toBe(4);
  });

  it("what a tab already set before the first refresh is kept", async () => {
    const store = useApprovalsStore();
    store.history = [
      { name: "H-1", doctype: "Journal Entry", transaction: "Journal Entry", transaction_filter: "", docname: "JV-1", action_state: "Approved", current_state: "Approved", role: "r", completed_by: "a@x", date: "2026-11-18", doc_url: "", event_count: 1 },
    ];
    await store.refresh();
    expect(store.history).toHaveLength(1);
  });

  it("an answer that arrives after the user signed out is dropped, and not saved", async () => {
    const pending = deferred<typeof THREE>();
    api.inbox.mockReturnValue(pending.promise);
    const store = useApprovalsStore();
    const done = store.refresh();

    useSessionStore().logout();
    pending.resolve(THREE);
    await done;

    expect(store.inbox).toBeNull();
    expect(loadInbox("a@x")).toBeNull();
  });
});

describe("refreshCount", () => {
  it("stores the numbers without fetching the inbox", async () => {
    const store = useApprovalsStore();
    await store.refreshCount();
    expect(api.count).toHaveBeenCalledTimes(1);
    expect(api.inbox).not.toHaveBeenCalled();
    expect(store.needsYou).toBe(7);
    expect(store.badge).toBe(7);
  });

  it("offline: calls nothing", async () => {
    online.isOnline.mockReturnValue(false);
    const store = useApprovalsStore();
    await store.refreshCount();
    expect(api.count).not.toHaveBeenCalled();
  });

  it("a failed call keeps the last numbers", async () => {
    const store = useApprovalsStore();
    await store.refreshCount();
    api.count.mockRejectedValue(new Error("offline"));
    await expect(store.refreshCount()).resolves.toBeUndefined();
    expect(store.needsYou).toBe(7);
  });
});

describe("apply", () => {
  it("sends the decision, then reloads the inbox", async () => {
    const store = useApprovalsStore();
    await store.refresh();
    api.inbox.mockClear();

    await store.apply("Journal Entry", "JV-1", "Approve", "ok", "High");

    expect(api.apply).toHaveBeenCalledWith("Journal Entry", "JV-1", "Approve", "ok", "High");
    expect(api.inbox).toHaveBeenCalledTimes(1);
  });

  it("a refusal reloads the inbox once more, then is thrown unchanged", async () => {
    const store = useApprovalsStore();
    await store.refresh();
    api.inbox.mockClear();
    const refusal = new Error("A comment is required for this action");
    api.apply.mockRejectedValue(refusal);

    await expect(store.apply("Journal Entry", "JV-1", "Reject", "", "Medium")).rejects.toBe(refusal);

    expect(api.inbox).toHaveBeenCalledTimes(1);
  });

  it("the reload that follows a refusal shows what the server now says", async () => {
    const store = useApprovalsStore();
    await store.refresh();
    const after = makeInbox({ total: 0, needs_you: 0, sections: [] });
    api.inbox.mockResolvedValue(after);
    api.apply.mockRejectedValue(new Error("not allowed"));

    await expect(store.apply("Journal Entry", "JV-1", "Approve", "", "Medium")).rejects.toThrow("not allowed");

    expect(store.inbox).toEqual(after);
    expect(store.needsYou).toBe(0);
  });

  it("a reload that fails does not hide the refusal", async () => {
    const store = useApprovalsStore();
    await store.refresh();
    const refusal = new Error("not allowed");
    api.apply.mockRejectedValue(refusal);
    api.inbox.mockRejectedValue(new Error("Request timed out"));

    await expect(store.apply("Journal Entry", "JV-1", "Approve", "", "Medium")).rejects.toBe(refusal);
  });

  it("when the connection is gone the refusal is thrown and nothing is reloaded", async () => {
    const store = useApprovalsStore();
    await store.refresh();
    api.inbox.mockClear();
    online.isOnline.mockReturnValue(false);
    const down = new Error("Failed to fetch");
    api.apply.mockRejectedValue(down);

    await expect(store.apply("Journal Entry", "JV-1", "Approve", "", "Medium")).rejects.toBe(down);
    expect(api.inbox).not.toHaveBeenCalled();
  });
});

describe("polling", () => {
  it("starting twice makes one timer: one inbox call per 60 seconds", async () => {
    vi.useFakeTimers();
    const store = useApprovalsStore();
    store.startPolling();
    store.startPolling();

    await vi.advanceTimersByTimeAsync(59_999);
    expect(api.inbox).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(api.inbox).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(api.inbox).toHaveBeenCalledTimes(2);
  });

  it("stopping ends the timer and the listeners", async () => {
    vi.useFakeTimers();
    const store = useApprovalsStore();
    store.startPolling();
    store.stopPolling();

    await vi.advanceTimersByTimeAsync(180_000);
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("online"));
    await vi.advanceTimersByTimeAsync(0);
    expect(api.inbox).not.toHaveBeenCalled();
  });

  it("can be started again after stopping", async () => {
    vi.useFakeTimers();
    const store = useApprovalsStore();
    store.startPolling();
    store.stopPolling();
    store.startPolling();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(api.inbox).toHaveBeenCalledTimes(1);
  });

  it("refreshes when the app comes back to the front", async () => {
    const store = useApprovalsStore();
    store.startPolling();
    setVisibility("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.waitFor(() => expect(api.inbox).toHaveBeenCalledTimes(1));
  });

  it("does not refresh when it goes to the back", async () => {
    vi.useFakeTimers();
    const store = useApprovalsStore();
    store.startPolling();
    setVisibility("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(0);
    expect(api.inbox).not.toHaveBeenCalled();
  });

  it("skips the timer's refresh while the app is in the background", async () => {
    vi.useFakeTimers();
    const store = useApprovalsStore();
    store.startPolling();
    setVisibility("hidden");
    await vi.advanceTimersByTimeAsync(120_000);
    expect(api.inbox).not.toHaveBeenCalled();
  });

  it("refreshes when the connection returns", async () => {
    const store = useApprovalsStore();
    store.startPolling();
    window.dispatchEvent(new Event("online"));
    await vi.waitFor(() => expect(api.inbox).toHaveBeenCalledTimes(1));
  });
});

describe("reset", () => {
  it("clears the state and the saved copy, and stops polling", async () => {
    vi.useFakeTimers();
    const store = useApprovalsStore();
    await store.refresh();
    await store.refreshCount();
    store.mine = [
      { doctype: "Journal Entry", docname: "JV-1", transaction: "Journal Entry", state: "Pending", holder: "x", role_id: "r", days: 1, priority: "Low" },
    ];
    store.startPolling();
    api.inbox.mockClear();

    store.reset();

    expect(store.inbox).toBeNull();
    expect(store.mine).toEqual([]);
    expect(store.sentBack).toEqual([]);
    expect(store.history).toEqual([]);
    expect(store.needsYou).toBe(0);
    expect(store.stale).toBe(false);
    expect(store.error).toBeNull();
    expect(loadInbox("a@x")).toBeNull();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(api.inbox).not.toHaveBeenCalled();
  });

  it("an answer still on its way is dropped", async () => {
    const pending = deferred<typeof THREE>();
    api.inbox.mockReturnValue(pending.promise);
    const store = useApprovalsStore();
    const done = store.refresh();

    store.reset();
    pending.resolve(THREE);
    await done;

    expect(store.inbox).toBeNull();
    expect(store.loading).toBe(false);
    expect(loadInbox("a@x")).toBeNull();
  });
});

describe("session wiring", () => {
  function defaults(over: Partial<ConfigDefaults> = {}): ConfigDefaults {
    return { user: "a@x", full_name: "A", language: "en", ...over } as ConfigDefaults;
  }

  it("approvalsEnabled follows the server's switch", () => {
    const session = useSessionStore();
    expect(session.approvalsEnabled).toBe(false);
    session.setDefaults(defaults({ approvals: { enabled: true } }));
    expect(session.approvalsEnabled).toBe(true);
    session.setDefaults(defaults({ approvals: { enabled: false } }));
    expect(session.approvalsEnabled).toBe(false);
  });

  it("an older server that sends no switch means off", () => {
    const session = useSessionStore();
    session.setDefaults(defaults());
    expect(session.approvalsEnabled).toBe(false);
  });

  it("logout clears the saved inbox", () => {
    saveInbox("a@x", makeInbox());
    useSessionStore().logout();
    expect(loadInbox("a@x")).toBeNull();
  });
});
