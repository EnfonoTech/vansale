import { describe, expect, it, vi } from "vitest";
import { subscribeWithKey, toSubscribeBody, type SubscriptionLike } from "../subscription";

function keys(p256dh: ArrayBuffer | null, auth: ArrayBuffer | null): SubscriptionLike["getKey"] {
  return (name) => (name === "p256dh" ? p256dh : auth);
}

describe("toSubscribeBody", () => {
  it("sends the endpoint and both keys as base64url", () => {
    const sub: SubscriptionLike = {
      endpoint: "https://push.example/send/abc",
      getKey: keys(Uint8Array.of(0xfb, 0xff).buffer, Uint8Array.of(1, 2, 3).buffer),
    };
    expect(toSubscribeBody(sub, "Mozilla/5.0 Test")).toEqual({
      endpoint: "https://push.example/send/abc",
      p256dh: "-_8",
      auth: "AQID",
      user_agent: "Mozilla/5.0 Test",
    });
  });

  it("asks the browser for the keys by their standard names", () => {
    const getKey = vi.fn(keys(Uint8Array.of(1).buffer, Uint8Array.of(2).buffer));
    toSubscribeBody({ endpoint: "https://push.example/x", getKey });
    expect(getKey.mock.calls.map((c) => c[0])).toEqual(["p256dh", "auth"]);
  });

  it("sends an empty user agent when none is given", () => {
    const sub: SubscriptionLike = { endpoint: "https://push.example/x", getKey: keys(Uint8Array.of(1).buffer, Uint8Array.of(2).buffer) };
    expect(toSubscribeBody(sub).user_agent).toBe("");
  });

  it.each([
    ["no p256dh", keys(null, Uint8Array.of(2).buffer)],
    ["no auth", keys(Uint8Array.of(1).buffer, null)],
    ["an empty p256dh", keys(new ArrayBuffer(0), Uint8Array.of(2).buffer)],
    ["an empty auth", keys(Uint8Array.of(1).buffer, new ArrayBuffer(0))],
  ])("refuses a subscription with %s", (_name, getKey) => {
    expect(() => toSubscribeBody({ endpoint: "https://push.example/x", getKey })).toThrow(/incomplete/);
  });

  it("refuses a subscription with no endpoint", () => {
    expect(() =>
      toSubscribeBody({ endpoint: "", getKey: keys(Uint8Array.of(1).buffer, Uint8Array.of(2).buffer) }),
    ).toThrow(/incomplete/);
  });
});

describe("subscribeWithKey", () => {
  const KEY = Uint8Array.of(4, 1, 2, 3);
  const OPTIONS = { userVisibleOnly: true, applicationServerKey: KEY };

  function sub(name: string) {
    return { name, unsubscribe: vi.fn().mockResolvedValue(true) };
  }
  function invalidState() {
    return Object.assign(new Error("different key"), { name: "InvalidStateError" });
  }

  it("subscribes visibly with the server's key", async () => {
    const made = sub("new");
    const pm = { getSubscription: vi.fn(), subscribe: vi.fn().mockResolvedValue(made) };
    await expect(subscribeWithKey(pm, KEY)).resolves.toBe(made);
    expect(pm.subscribe).toHaveBeenCalledOnce();
    expect(pm.subscribe).toHaveBeenCalledWith(OPTIONS);
    expect(pm.getSubscription).not.toHaveBeenCalled();
  });

  it("drops a subscription made with another key and subscribes again", async () => {
    const old = sub("old");
    const made = sub("new");
    const pm = {
      getSubscription: vi.fn().mockResolvedValue(old),
      subscribe: vi.fn().mockRejectedValueOnce(invalidState()).mockResolvedValueOnce(made),
    };
    await expect(subscribeWithKey(pm, KEY)).resolves.toBe(made);
    expect(old.unsubscribe).toHaveBeenCalledOnce();
    expect(pm.subscribe).toHaveBeenCalledTimes(2);
    expect(pm.subscribe).toHaveBeenLastCalledWith(OPTIONS);
  });

  it("tries only once more", async () => {
    const pm = {
      getSubscription: vi.fn().mockResolvedValue(null),
      subscribe: vi.fn().mockRejectedValue(invalidState()),
    };
    await expect(subscribeWithKey(pm, KEY)).rejects.toMatchObject({ name: "InvalidStateError" });
    expect(pm.subscribe).toHaveBeenCalledTimes(2);
  });

  it("passes any other refusal on without touching what the browser holds", async () => {
    const denied = Object.assign(new Error("denied"), { name: "NotAllowedError" });
    const pm = { getSubscription: vi.fn(), subscribe: vi.fn().mockRejectedValue(denied) };
    await expect(subscribeWithKey(pm, KEY)).rejects.toBe(denied);
    expect(pm.subscribe).toHaveBeenCalledOnce();
    expect(pm.getSubscription).not.toHaveBeenCalled();
  });
});
