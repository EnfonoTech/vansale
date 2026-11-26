/**
 * The approvals store: what it shows (the saved copy first, then the
 * server's), what it does when a decision is refused, how it polls, and what
 * it forgets when the user goes. The API is mocked; the cache, the session
 * store and localStorage are the real ones.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { inbox as makeInbox, item } from "@/features/approvals/__tests__/fixtures";
import type { HistoryRow, MyRequestRow, SentBackRow } from "@/api/approvals";
import { loadInbox, saveInbox } from "@/features/approvals/cache";
import type { ConfigDefaults } from "@/api/me";

const api = vi.hoisted(() => ({
  inbox: vi.fn(),
  count: vi.fn(),
  apply: vi.fn(),
  myRequests: vi.fn(),
  sentBack: vi.fn(),
  history: vi.fn(),
}));
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

const MINE_ROW: MyRequestRow = {
  doctype: "Sales Invoice",
  docname: "SINV-1",
  transaction: "Sales Invoice",
  state: "Pending Finance",
  holder: "Mariam K.",
  role_id: "Finance Head",
  days: 2,
  priority: "Medium",
};
const SENT_BACK_ROW: SentBackRow = {
  doctype: "Sales Order",
  transaction: "Sales Order",
  transaction_filter: "Sales Order",
  docname: "SO-00231",
  state: "Draft",
  submitted_by: "Me",
  days: 2,
  doc_url: "/app/sales-order/SO-00231",
  sent_back_by: "Mariam K.",
  sent_back_on: "2026-11-17 10:00:00",
  role: "Finance Head",
  reason: "Wrong cost centre",
};
const HISTORY_ROW: HistoryRow = {
  name: "PMWA-9",
  doctype: "Journal Entry",
  transaction: "Journal Entry",
  transaction_filter: "Journal Entry",
  docname: "ACC-JV-1",
  action_state: "Approved",
  current_state: "Approved",
  role: "Accounts Manager",
  completed_by: "A",
  date: "18/11/26 09:00",
  doc_url: "/app/journal-entry/ACC-JV-1",
  event_count: 2,
};

beforeEach(() => {
  window.localStorage.clear();
  setActivePinia(createPinia());
  online.isOnline.mockReturnValue(true);
  api.inbox.mockResolvedValue(THREE);
  api.count.mockResolvedValue({ total: 9, needs_you: 7, waiting: 2, high: 1, overdue: 1 });
  api.apply.mockResolvedValue({ ok: true, new_state: "Approved", recommended: false });
  api.myRequests.mockResolvedValue({ items: [MINE_ROW] });
  api.sentBack.mockResolvedValue({ items: [SENT_BACK_ROW] });
  api.history.mockResolvedValue({ items: [HISTORY_ROW] });
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

  it("an error that carries markup is stored as plain text", async () => {
    api.inbox.mockRejectedValue(new Error("<b>Not allowed</b> &amp; logged"));
    const store = useApprovalsStore();
    await store.refresh();
    expect(store.error).toBe("Not allowed & logged");
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

  it("a user switch clears the previous user's saved copy from the phone at once, not when the new answer lands", () => {
    const store = useApprovalsStore();
    saveInbox("a@x", THREE);
    store.adopt("a@x");
    expect(loadInbox("a@x")).not.toBeNull();

    store.adopt("b@x");

    expect(loadInbox("a@x")).toBeNull();
    expect(window.localStorage.getItem("vansale.approvals.cache.v1")).toBeNull();
  });

  it("the first user after a fresh start does not keep a copy left by someone else, but keeps their own", () => {
    saveInbox("old@x", THREE);
    const store = useApprovalsStore();
    store.adopt("a@x");
    expect(window.localStorage.getItem("vansale.approvals.cache.v1")).toBeNull();

    setActivePinia(createPinia());
    saveInbox("a@x", THREE);
    useApprovalsStore().adopt("a@x");
    expect(loadInbox("a@x")?.inbox).toEqual(THREE);
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

  it("an answer older than the latest inbox refresh is ignored", async () => {
    const slow = deferred<{ total: number; needs_you: number; waiting: number; high: number; overdue: number }>();
    api.count.mockReturnValue(slow.promise);
    const store = useApprovalsStore();
    const counting = store.refreshCount();

    // The inbox is asked for after the count was, and its answer lands first.
    await store.refresh();
    expect(store.needsYou).toBe(2);
    slow.resolve({ total: 9, needs_you: 7, waiting: 2, high: 1, overdue: 1 });
    await counting;

    expect(store.needsYou).toBe(2);
  });

  it("of two counts in flight the later one wins, whichever answers last", async () => {
    const first = deferred<{ total: number; needs_you: number; waiting: number; high: number; overdue: number }>();
    const second = deferred<{ total: number; needs_you: number; waiting: number; high: number; overdue: number }>();
    api.count.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const store = useApprovalsStore();
    const a = store.refreshCount();
    const b = store.refreshCount();

    second.resolve({ total: 5, needs_you: 5, waiting: 0, high: 0, overdue: 0 });
    await b;
    first.resolve({ total: 1, needs_you: 1, waiting: 0, high: 0, overdue: 0 });
    await a;

    expect(store.needsYou).toBe(5);
  });

  it("an answer that arrives after a reset is dropped", async () => {
    const slow = deferred<{ total: number; needs_you: number; waiting: number; high: number; overdue: number }>();
    api.count.mockReturnValue(slow.promise);
    const store = useApprovalsStore();
    const counting = store.refreshCount();
    store.reset();
    slow.resolve({ total: 9, needs_you: 7, waiting: 2, high: 1, overdue: 1 });
    await counting;
    expect(store.needsYou).toBe(0);
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

    await store.apply("Journal Entry", "JV-1", "Approve", "ok", "High", "Pending Approval");

    expect(api.apply).toHaveBeenCalledWith("Journal Entry", "JV-1", "Approve", "ok", "High", "Pending Approval");
    expect(api.inbox).toHaveBeenCalledTimes(1);
  });

  it("passes no expected state when the caller has none", async () => {
    const store = useApprovalsStore();
    await store.refresh();

    await store.apply("Journal Entry", "JV-1", "Approve", "", "");

    expect(api.apply).toHaveBeenCalledWith("Journal Entry", "JV-1", "Approve", "", "", "");
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

describe("list tabs: loadMine, loadSentBack, loadHistory", () => {
  const LOADERS = [
    { name: "mine" as const, load: (s: ReturnType<typeof useApprovalsStore>) => s.loadMine(), call: () => api.myRequests, row: MINE_ROW },
    { name: "sentBack" as const, load: (s: ReturnType<typeof useApprovalsStore>) => s.loadSentBack(), call: () => api.sentBack, row: SENT_BACK_ROW },
    { name: "history" as const, load: (s: ReturnType<typeof useApprovalsStore>) => s.loadHistory(), call: () => api.history, row: HISTORY_ROW },
  ];

  describe.each(LOADERS)("$name", ({ name, load, call, row }) => {
    it("online: fills its slot and marks it loaded", async () => {
      const store = useApprovalsStore();
      expect(store.lists[name]).toEqual({ loading: false, error: null, loaded: false });

      await load(store);

      expect(call()).toHaveBeenCalledTimes(1);
      expect(store[name]).toEqual([row]);
      expect(store.lists[name]).toEqual({ loading: false, error: null, loaded: true });
    });

    it("is loading while the server answers", async () => {
      const pending = deferred<{ items: unknown[] }>();
      call().mockReturnValue(pending.promise);
      const store = useApprovalsStore();
      const done = load(store);
      expect(store.lists[name].loading).toBe(true);

      pending.resolve({ items: [row] });
      await done;
      expect(store.lists[name].loading).toBe(false);
    });

    it("a failure keeps the rows already shown and records the message", async () => {
      const store = useApprovalsStore();
      await load(store);
      call().mockRejectedValue(new Error("Request timed out"));

      await load(store);

      expect(store[name]).toEqual([row]);
      expect(store.lists[name]).toEqual({ loading: false, error: "Request timed out", loaded: true });
    });

    it("a failure with nothing shown stays not loaded", async () => {
      call().mockRejectedValue(new Error("HTTP 500"));
      const store = useApprovalsStore();
      await load(store);
      expect(store[name]).toEqual([]);
      expect(store.lists[name]).toEqual({ loading: false, error: "HTTP 500", loaded: false });
    });

    it("a later success clears the error", async () => {
      call().mockRejectedValueOnce(new Error("HTTP 500"));
      const store = useApprovalsStore();
      await load(store);
      await load(store);
      expect(store.lists[name].error).toBeNull();
      expect(store[name]).toEqual([row]);
    });

    it("offline: calls nothing and keeps what it holds, with no error", async () => {
      const store = useApprovalsStore();
      await load(store);
      call().mockClear();
      online.isOnline.mockReturnValue(false);

      await load(store);

      expect(call()).not.toHaveBeenCalled();
      expect(store[name]).toEqual([row]);
      expect(store.lists[name]).toEqual({ loading: false, error: null, loaded: true });
    });

    it("offline with nothing held: stays empty and not loaded", async () => {
      online.isOnline.mockReturnValue(false);
      const store = useApprovalsStore();
      await load(store);
      expect(call()).not.toHaveBeenCalled();
      expect(store[name]).toEqual([]);
      expect(store.lists[name]).toEqual({ loading: false, error: null, loaded: false });
    });

    it("does nothing without a signed-in user", async () => {
      useSessionStore().$patch({ user: null });
      const store = useApprovalsStore();
      await load(store);
      expect(call()).not.toHaveBeenCalled();
    });

    it("an older answer never replaces a newer one", async () => {
      const older = deferred<{ items: unknown[] }>();
      const newer = deferred<{ items: unknown[] }>();
      call().mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);

      const store = useApprovalsStore();
      const first = load(store);
      const second = load(store);
      newer.resolve({ items: [row, row] });
      await second;
      older.resolve({ items: [] });
      await first;

      expect(store[name]).toHaveLength(2);
      expect(store.lists[name].loading).toBe(false);
    });

    it("an answer that arrives after a user switch is dropped", async () => {
      const pending = deferred<{ items: unknown[] }>();
      call().mockReturnValue(pending.promise);
      const store = useApprovalsStore();
      const done = load(store);

      signIn("b@x");
      store.adopt("b@x");
      pending.resolve({ items: [row] });
      await done;

      expect(store[name]).toEqual([]);
      expect(store.lists[name]).toEqual({ loading: false, error: null, loaded: false });
    });

    it("an answer that arrives after reset is dropped", async () => {
      const pending = deferred<{ items: unknown[] }>();
      call().mockReturnValue(pending.promise);
      const store = useApprovalsStore();
      const done = load(store);

      store.reset();
      pending.resolve({ items: [row] });
      await done;

      expect(store[name]).toEqual([]);
      expect(store.lists[name]).toEqual({ loading: false, error: null, loaded: false });
    });

    it("reset forgets what was loaded", async () => {
      const store = useApprovalsStore();
      await load(store);
      store.reset();
      expect(store[name]).toEqual([]);
      expect(store.lists[name]).toEqual({ loading: false, error: null, loaded: false });
    });

    it("a user switch forgets what the previous user loaded", async () => {
      const store = useApprovalsStore();
      await load(store);
      signIn("b@x");
      store.adopt("b@x");
      expect(store[name]).toEqual([]);
      expect(store.lists[name].loaded).toBe(false);
    });

    it("leaves the inbox's own loading, error and in-flight answer alone", async () => {
      const inboxPending = deferred<typeof THREE>();
      api.inbox.mockReturnValue(inboxPending.promise);
      call().mockRejectedValue(new Error("HTTP 500"));
      const store = useApprovalsStore();
      const refreshing = store.refresh();

      await load(store);
      expect(store.loading).toBe(true);
      expect(store.error).toBeNull();

      inboxPending.resolve(THREE);
      await refreshing;
      expect(store.inbox).toEqual(THREE);
      expect(store.error).toBeNull();
      expect(store.lists[name].error).toBe("HTTP 500");
    });
  });

  describe("loadHistory filters", () => {
    it("asks for the default page when no filter is given", async () => {
      await useApprovalsStore().loadHistory();
      expect(api.history).toHaveBeenCalledWith(100, "", "", "");
    });

    it("passes the date range, the transaction and the page size", async () => {
      await useApprovalsStore().loadHistory({
        fromDate: "2026-11-01",
        toDate: "2026-11-18",
        transaction: "Journal Entry",
        limit: 50,
      });
      expect(api.history).toHaveBeenCalledWith(50, "2026-11-01", "2026-11-18", "Journal Entry");
    });

    it("a partial filter leaves the rest empty", async () => {
      await useApprovalsStore().loadHistory({ transaction: "Sales Return" });
      expect(api.history).toHaveBeenCalledWith(100, "", "", "Sales Return");
    });

    it("a new filter replaces the rows", async () => {
      const store = useApprovalsStore();
      await store.loadHistory();
      expect(store.history).toHaveLength(1);
      api.history.mockResolvedValue({ items: [] });
      await store.loadHistory({ transaction: "Purchase Order" });
      expect(store.history).toEqual([]);
      expect(store.lists.history.loaded).toBe(true);
    });
  });

  describe("sent back: the server may say the list is unavailable for this user", () => {
    it("is available unless the server says otherwise (also on a server that sends no flag)", async () => {
      const store = useApprovalsStore();
      expect(store.sentBackUnavailable).toBe(false);
      await store.loadSentBack();
      expect(store.sentBackUnavailable).toBe(false);
      api.sentBack.mockResolvedValue({ items: [SENT_BACK_ROW], unavailable: false });
      await store.loadSentBack();
      expect(store.sentBackUnavailable).toBe(false);
    });

    it("records the flag and an empty list when the server cannot list it", async () => {
      api.sentBack.mockResolvedValue({ items: [], unavailable: true });
      const store = useApprovalsStore();
      await store.loadSentBack();

      expect(store.sentBackUnavailable).toBe(true);
      expect(store.sentBack).toEqual([]);
      // An answer arrived: the tab shows its explanation, not a skeleton or a retry.
      expect(store.lists.sentBack).toEqual({ loading: false, error: null, loaded: true });
    });

    it("a later answer that works clears it", async () => {
      api.sentBack.mockResolvedValue({ items: [], unavailable: true });
      const store = useApprovalsStore();
      await store.loadSentBack();
      api.sentBack.mockResolvedValue({ items: [SENT_BACK_ROW], unavailable: false });
      await store.loadSentBack();

      expect(store.sentBackUnavailable).toBe(false);
      expect(store.sentBack).toEqual([SENT_BACK_ROW]);
    });

    it("a failed load leaves the last answer's flag alone", async () => {
      api.sentBack.mockResolvedValue({ items: [], unavailable: true });
      const store = useApprovalsStore();
      await store.loadSentBack();
      api.sentBack.mockRejectedValue(new Error("Request timed out"));
      await store.loadSentBack();

      expect(store.sentBackUnavailable).toBe(true);
    });

    it("reset forgets it", async () => {
      api.sentBack.mockResolvedValue({ items: [], unavailable: true });
      const store = useApprovalsStore();
      await store.loadSentBack();
      store.reset();
      expect(store.sentBackUnavailable).toBe(false);
    });
  });

  it("the three lists load independently", async () => {
    const pending = deferred<{ items: MyRequestRow[] }>();
    api.myRequests.mockReturnValue(pending.promise);
    const store = useApprovalsStore();
    const mine = store.loadMine();
    await store.loadSentBack();
    await store.loadHistory();

    expect(store.lists.mine.loading).toBe(true);
    expect(store.lists.sentBack.loaded).toBe(true);
    expect(store.lists.history.loaded).toBe(true);

    pending.resolve({ items: [MINE_ROW] });
    await mine;
    expect(store.mine).toEqual([MINE_ROW]);
    expect(store.sentBack).toEqual([SENT_BACK_ROW]);
  });
});
