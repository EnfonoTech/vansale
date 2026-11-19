/**
 * The approval-notifications store: what it reads from the browser and the
 * server, the steps of turning notifications on and off, what logout does,
 * and what it forgets. The server calls are mocked; the browser is a set of
 * fakes standing in for `navigator.serviceWorker`, `PushManager` and
 * `Notification`; the session store is the real one.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { NetworkError } from "@/api/client";

const api = vi.hoisted(() => ({
  pushConfig: vi.fn(),
  pushSubscribe: vi.fn(),
  pushUnsubscribe: vi.fn(),
}));
vi.mock("@/api/push", () => api);
const online = vi.hoisted(() => ({ isOnline: vi.fn() }));
vi.mock("@/app/online", () => online);
const platform = vi.hoisted(() => ({ native: false }));
vi.mock("@/app/platform", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/app/platform")>()),
  isNative: () => platform.native,
}));

import { DETACH_SERVER_MS, usePushStore } from "../push";
import { useSessionStore } from "../session";

const PUBLIC_KEY = "BAECAw"; // 0x04 0x01 0x02 0x03
const ENDPOINT = "https://push.example/send/device-1";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function fakeSubscription(endpoint = ENDPOINT) {
  return {
    endpoint,
    getKey: (name: string) => (name === "p256dh" ? Uint8Array.of(1, 2, 3).buffer : Uint8Array.of(9, 8).buffer),
    unsubscribe: vi.fn().mockResolvedValue(true),
  };
}
type FakeSubscription = ReturnType<typeof fakeSubscription>;

type AnyMock = Mock<any[], any>;

interface Browser {
  pushManager: { getSubscription: AnyMock; subscribe: AnyMock };
  getRegistration: AnyMock;
  requestPermission: AnyMock;
  /** The subscription the browser holds now. */
  held: { current: FakeSubscription | null };
  /** The one `subscribe` hands out. */
  made: FakeSubscription;
}

/** Install the fakes. `held` is what the browser already subscribes; `permission` is what the site may do. */
function browser(opts: { held?: FakeSubscription | null; permission?: string; asked?: string } = {}): Browser {
  const held = { current: opts.held ?? null };
  const made = fakeSubscription();
  const pushManager = {
    getSubscription: vi.fn(async () => held.current),
    subscribe: vi.fn(async () => {
      held.current = made;
      return made;
    }),
  };
  const registration = { pushManager };
  const getRegistration = vi.fn(async () => registration);
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: { getRegistration, ready: Promise.resolve(registration) },
  });
  const requestPermission = vi.fn(async () => opts.asked ?? "granted");
  vi.stubGlobal("PushManager", class {});
  vi.stubGlobal("Notification", { permission: opts.permission ?? "default", requestPermission });
  return { pushManager, getRegistration, requestPermission, held, made };
}

function signIn(user = "a@x") {
  useSessionStore().$patch({ user });
}

/** A signed-in store that has already looked: the switch is shown with the server's key. */
async function ready(held: FakeSubscription | null = null, subscribedOnServer = held !== null) {
  const b = browser({ held });
  api.pushConfig.mockResolvedValue({ enabled: true, public_key: PUBLIC_KEY, subscribed: subscribedOnServer });
  const store = usePushStore();
  await store.refresh();
  return { store, b };
}

beforeEach(() => {
  window.localStorage.clear();
  setActivePinia(createPinia());
  platform.native = false;
  online.isOnline.mockReturnValue(true);
  api.pushConfig.mockResolvedValue({ enabled: true, public_key: PUBLIC_KEY, subscribed: false });
  api.pushSubscribe.mockResolvedValue({ ok: true });
  api.pushUnsubscribe.mockResolvedValue({ ok: true });
  signIn();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "serviceWorker");
});

describe("refresh", () => {
  it("shows the switch off when the server can send and nothing is subscribed", async () => {
    const { store } = await ready();
    expect(store.visible).toBe(true);
    expect(store.toggle).toEqual({ kind: "off" });
    expect(store.publicKey).toBe(PUBLIC_KEY);
    expect(api.pushConfig).toHaveBeenCalledWith("");
  });

  it("shows it on when the browser holds a subscription and the server knows it", async () => {
    const { store } = await ready(fakeSubscription());
    expect(store.toggle).toEqual({ kind: "on" });
    expect(api.pushConfig).toHaveBeenCalledWith(ENDPOINT);
  });

  it("shows it off when the browser holds a subscription the server does not know", async () => {
    const { store } = await ready(fakeSubscription(), false);
    expect(store.toggle).toEqual({ kind: "off" });
  });

  it("keeps the switch hidden when the server cannot send", async () => {
    browser();
    api.pushConfig.mockResolvedValue({ enabled: false, public_key: "", subscribed: false });
    const store = usePushStore();
    await store.refresh();
    expect(store.visible).toBe(false);
    expect(store.publicKey).toBe("");
  });

  it("says blocked when notifications are blocked for the site, and still asks the server", async () => {
    browser({ permission: "denied" });
    const store = usePushStore();
    await store.refresh();
    expect(store.toggle).toEqual({ kind: "blocked" });
    expect(store.visible).toBe(true);
  });

  it("says unsupported without the Push API, and the server still decides whether the row shows", async () => {
    browser();
    vi.stubGlobal("PushManager", undefined);
    const store = usePushStore();
    await store.refresh();
    expect(store.toggle).toEqual({ kind: "unsupported" });
    expect(store.visible).toBe(true);
    expect(api.pushConfig).toHaveBeenCalledWith("");
  });

  it("asks nothing and shows nothing in the native app", async () => {
    browser();
    platform.native = true;
    const store = usePushStore();
    await store.refresh();
    expect(api.pushConfig).not.toHaveBeenCalled();
    expect(store.visible).toBe(false);
    expect(store.toggle).toEqual({ kind: "checking" });
  });

  it("asks nothing when nobody is signed in", async () => {
    browser();
    useSessionStore().$patch({ user: null });
    await usePushStore().refresh();
    expect(api.pushConfig).not.toHaveBeenCalled();
  });

  it("offline: asks the server nothing, shows what the browser holds, and keeps the row hidden", async () => {
    browser({ held: fakeSubscription() });
    online.isOnline.mockReturnValue(false);
    const store = usePushStore();
    await store.refresh();
    expect(api.pushConfig).not.toHaveBeenCalled();
    expect(store.toggle).toEqual({ kind: "on" });
    expect(store.visible).toBe(false);
  });

  it("offline after an answer: keeps the row and the side the server gave", async () => {
    const { store } = await ready(fakeSubscription(), false);
    online.isOnline.mockReturnValue(false);
    await store.refresh();
    expect(store.visible).toBe(true);
    expect(store.toggle).toEqual({ kind: "off" });
  });

  it("when the server does not answer, keeps what was known", async () => {
    const { store } = await ready(fakeSubscription());
    api.pushConfig.mockRejectedValue(new NetworkError());
    await store.refresh();
    expect(store.visible).toBe(true);
    expect(store.toggle).toEqual({ kind: "on" });
  });

  it("when there is no service worker to ask (the dev server), nothing is subscribed", async () => {
    const b = browser();
    b.getRegistration.mockResolvedValue(undefined);
    const store = usePushStore();
    await store.refresh();
    expect(store.toggle).toEqual({ kind: "off" });
    expect(api.pushConfig).toHaveBeenCalledWith("");
  });

  it("drops an answer that arrives after a reset", async () => {
    browser();
    const slow = deferred<{ enabled: boolean; public_key: string; subscribed: boolean }>();
    api.pushConfig.mockReturnValue(slow.promise);
    const store = usePushStore();
    const pending = store.refresh();
    await vi.waitFor(() => expect(api.pushConfig).toHaveBeenCalled());
    store.reset();
    slow.resolve({ enabled: true, public_key: PUBLIC_KEY, subscribed: true });
    await pending;
    expect(store.visible).toBe(false);
    expect(store.toggle).toEqual({ kind: "checking" });
  });

  it("drops an answer that arrives after another user signed in", async () => {
    browser();
    const slow = deferred<{ enabled: boolean; public_key: string; subscribed: boolean }>();
    api.pushConfig.mockReturnValue(slow.promise);
    const store = usePushStore();
    const pending = store.refresh();
    await vi.waitFor(() => expect(api.pushConfig).toHaveBeenCalled());
    signIn("b@x");
    slow.resolve({ enabled: true, public_key: PUBLIC_KEY, subscribed: true });
    await pending;
    expect(store.visible).toBe(false);
  });

  it("does not disturb a change on its way", async () => {
    const { store } = await ready();
    store.dispatch({ type: "start", target: "on" });
    api.pushConfig.mockClear();
    await store.refresh();
    expect(api.pushConfig).not.toHaveBeenCalled();
    expect(store.toggle).toEqual({ kind: "busy", target: "on" });
  });
});

describe("enable", () => {
  it("asks permission first, straight from the tap, before anything is awaited", async () => {
    const { store, b } = await ready();
    const done = store.enable();
    expect(b.requestPermission).toHaveBeenCalledOnce(); // no tick has passed yet
    expect(b.pushManager.subscribe).not.toHaveBeenCalled();
    await done;
  });

  it("subscribes with the server's key, hands the subscription to the server and ends on", async () => {
    const { store, b } = await ready();
    await store.enable();
    expect(b.pushManager.subscribe).toHaveBeenCalledOnce();
    const options = b.pushManager.subscribe.mock.calls[0][0];
    expect(options.userVisibleOnly).toBe(true);
    expect(Array.from(options.applicationServerKey)).toEqual([4, 1, 2, 3]);
    expect(api.pushSubscribe).toHaveBeenCalledOnce();
    expect(api.pushSubscribe).toHaveBeenCalledWith({
      endpoint: ENDPOINT,
      p256dh: "AQID",
      auth: "CQg",
      user_agent: navigator.userAgent,
    });
    expect(store.toggle).toEqual({ kind: "on" });
    expect(store.endpoint).toBe(ENDPOINT);
    expect(b.made.unsubscribe).not.toHaveBeenCalled();
  });

  it("shows the switch on while it works", async () => {
    const { store, b } = await ready();
    const slow = deferred<{ ok: boolean }>();
    api.pushSubscribe.mockReturnValue(slow.promise);
    const done = store.enable();
    await vi.waitFor(() => expect(api.pushSubscribe).toHaveBeenCalled());
    expect(store.toggle).toEqual({ kind: "busy", target: "on" });
    slow.resolve({ ok: true });
    await done;
    expect(store.toggle).toEqual({ kind: "on" });
    expect(b.requestPermission).toHaveBeenCalledOnce();
  });

  it("is blocked when the user refuses the prompt, and subscribes nothing", async () => {
    const b = browser({ asked: "denied" });
    const store = usePushStore();
    await store.refresh();
    await store.enable();
    expect(store.toggle).toEqual({ kind: "blocked" });
    expect(b.pushManager.subscribe).not.toHaveBeenCalled();
    expect(api.pushSubscribe).not.toHaveBeenCalled();
  });

  it("goes back to off, with no error, when the prompt is closed without an answer", async () => {
    const b = browser({ asked: "default" });
    const store = usePushStore();
    await store.refresh();
    await store.enable();
    expect(store.toggle).toEqual({ kind: "off" });
    expect(b.pushManager.subscribe).not.toHaveBeenCalled();
  });

  it("undoes the browser side when the server refuses, and says it could not turn on", async () => {
    const { store, b } = await ready();
    api.pushSubscribe.mockRejectedValue(new Error("Push is not set up"));
    await store.enable();
    expect(b.made.unsubscribe).toHaveBeenCalledOnce();
    expect(store.toggle).toEqual({ kind: "error", was: "off", problem: "failed" });
    expect(store.endpoint).toBe("");
  });

  it("calls a lost connection a problem of connection", async () => {
    const { store, b } = await ready();
    api.pushSubscribe.mockRejectedValue(new NetworkError());
    await store.enable();
    expect(b.made.unsubscribe).toHaveBeenCalledOnce();
    expect(store.toggle).toEqual({ kind: "error", was: "off", problem: "offline" });
  });

  it("can be tried again after a failure", async () => {
    const { store } = await ready();
    api.pushSubscribe.mockRejectedValueOnce(new Error("x"));
    await store.enable();
    await store.enable();
    expect(store.toggle).toEqual({ kind: "on" });
  });

  it("says blocked when the browser refuses to subscribe because notifications are blocked", async () => {
    const { store, b } = await ready();
    b.pushManager.subscribe.mockImplementation(async () => {
      (window.Notification as unknown as { permission: string }).permission = "denied";
      throw Object.assign(new Error("denied"), { name: "NotAllowedError" });
    });
    await store.enable();
    expect(store.toggle).toEqual({ kind: "blocked" });
  });

  it("does nothing without a connection: the prompt is not even shown", async () => {
    const { store, b } = await ready();
    online.isOnline.mockReturnValue(false);
    await store.enable();
    expect(b.requestPermission).not.toHaveBeenCalled();
    expect(store.toggle).toEqual({ kind: "off" });
  });

  it("does nothing when it is already on, or busy, or blocked", async () => {
    const { store, b } = await ready(fakeSubscription());
    await store.enable();
    expect(b.requestPermission).not.toHaveBeenCalled();
    expect(store.toggle).toEqual({ kind: "on" });
  });

  it("fails cleanly when the server gave no key, before asking permission", async () => {
    const { store, b } = await ready();
    store.$patch({ publicKey: "" });
    await store.enable();
    expect(b.requestPermission).not.toHaveBeenCalled();
    expect(store.toggle).toEqual({ kind: "error", was: "off", problem: "failed" });
  });

  it("drops the subscription when the user signed out while it worked", async () => {
    const { store, b } = await ready();
    const slow = deferred<{ ok: boolean }>();
    api.pushSubscribe.mockReturnValue(slow.promise);
    const done = store.enable();
    await vi.waitFor(() => expect(api.pushSubscribe).toHaveBeenCalled());
    signIn("b@x");
    slow.resolve({ ok: true });
    await done;
    expect(b.made.unsubscribe).toHaveBeenCalledOnce();
    expect(store.toggle).not.toEqual({ kind: "on" });
  });
});

describe("disable", () => {
  it("tells the server, drops the browser subscription and ends off", async () => {
    const held = fakeSubscription();
    const { store } = await ready(held);
    await store.disable();
    expect(api.pushUnsubscribe).toHaveBeenCalledWith(ENDPOINT);
    expect(held.unsubscribe).toHaveBeenCalledOnce();
    expect(store.toggle).toEqual({ kind: "off" });
    expect(store.endpoint).toBe("");
  });

  it("asks the server before the browser, so a failure leaves both as they were", async () => {
    const held = fakeSubscription();
    const { store } = await ready(held);
    api.pushUnsubscribe.mockRejectedValue(new NetworkError());
    await store.disable();
    expect(held.unsubscribe).not.toHaveBeenCalled();
    expect(store.toggle).toEqual({ kind: "error", was: "on", problem: "offline" });
  });

  it("still ends off when the browser fails to drop it after the server let go", async () => {
    const held = fakeSubscription();
    held.unsubscribe.mockRejectedValue(new Error("x"));
    const { store } = await ready(held);
    await store.disable();
    expect(store.toggle).toEqual({ kind: "off" });
  });

  it("forgets a subscription the browser no longer holds, by its saved endpoint", async () => {
    const { store, b } = await ready(fakeSubscription());
    b.held.current = null;
    await store.disable();
    expect(api.pushUnsubscribe).toHaveBeenCalledWith(ENDPOINT);
    expect(store.toggle).toEqual({ kind: "off" });
  });

  it("does nothing without a connection", async () => {
    const { store } = await ready(fakeSubscription());
    online.isOnline.mockReturnValue(false);
    await store.disable();
    expect(api.pushUnsubscribe).not.toHaveBeenCalled();
    expect(store.toggle).toEqual({ kind: "on" });
  });

  it("does nothing when it is off", async () => {
    const { store } = await ready();
    await store.disable();
    expect(api.pushUnsubscribe).not.toHaveBeenCalled();
  });
});

describe("detach (logout)", () => {
  it("drops this device's subscription on the server, then in the browser", async () => {
    const held = fakeSubscription();
    const { store } = await ready(held);
    const order: string[] = [];
    api.pushUnsubscribe.mockImplementation(async () => {
      order.push("server");
      return { ok: true };
    });
    held.unsubscribe.mockImplementation(async () => {
      order.push("browser");
      return true;
    });
    await store.detach();
    expect(api.pushUnsubscribe).toHaveBeenCalledWith(ENDPOINT);
    expect(order).toEqual(["server", "browser"]);
  });

  it("works without a look first (the More screen was never opened)", async () => {
    const held = fakeSubscription();
    browser({ held });
    await usePushStore().detach();
    expect(api.pushUnsubscribe).toHaveBeenCalledWith(ENDPOINT);
    expect(held.unsubscribe).toHaveBeenCalledOnce();
  });

  it("still stops the pushes in the browser when the server cannot be reached", async () => {
    const held = fakeSubscription();
    const { store } = await ready(held);
    api.pushUnsubscribe.mockRejectedValue(new NetworkError());
    await expect(store.detach()).resolves.toBeUndefined();
    expect(held.unsubscribe).toHaveBeenCalledOnce();
  });

  it("offline: skips the server and still drops the browser side", async () => {
    const held = fakeSubscription();
    const { store } = await ready(held);
    online.isOnline.mockReturnValue(false);
    await store.detach();
    expect(api.pushUnsubscribe).not.toHaveBeenCalled();
    expect(held.unsubscribe).toHaveBeenCalledOnce();
  });

  it("does not wait for a server that never answers", async () => {
    const held = fakeSubscription();
    const { store } = await ready(held);
    api.pushUnsubscribe.mockReturnValue(new Promise(() => {}));
    vi.useFakeTimers();
    const done = store.detach();
    await vi.advanceTimersByTimeAsync(DETACH_SERVER_MS + 1);
    await done;
    expect(held.unsubscribe).toHaveBeenCalledOnce();
  });

  it("never throws, whatever fails", async () => {
    browser();
    const store = usePushStore();
    (navigator.serviceWorker.getRegistration as unknown as AnyMock).mockRejectedValue(new Error("x"));
    await expect(store.detach()).resolves.toBeUndefined();
  });

  it("does nothing when nothing is subscribed", async () => {
    const { store } = await ready();
    await store.detach();
    expect(api.pushUnsubscribe).not.toHaveBeenCalled();
  });

  it("does nothing on a device that cannot take push, or in the native app", async () => {
    const held = fakeSubscription();
    browser({ held });
    platform.native = true;
    await usePushStore().detach();
    platform.native = false;
    vi.stubGlobal("PushManager", undefined);
    await usePushStore().detach();
    expect(api.pushUnsubscribe).not.toHaveBeenCalled();
    expect(held.unsubscribe).not.toHaveBeenCalled();
  });
});

describe("reset", () => {
  it("forgets the answer, the key and the side", async () => {
    const { store } = await ready(fakeSubscription());
    store.reset();
    expect(store.visible).toBe(false);
    expect(store.publicKey).toBe("");
    expect(store.endpoint).toBe("");
    expect(store.toggle).toEqual({ kind: "checking" });
  });

  it("ends a change that was on its way: its outcome no longer lands", async () => {
    const { store } = await ready();
    const slow = deferred<{ ok: boolean }>();
    api.pushSubscribe.mockReturnValue(slow.promise);
    const done = store.enable();
    await vi.waitFor(() => expect(api.pushSubscribe).toHaveBeenCalled());
    store.reset();
    slow.resolve({ ok: true });
    await done;
    expect(store.toggle).toEqual({ kind: "checking" });
  });
});
