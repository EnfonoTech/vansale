/**
 * The client calls: which method, path and parameters each one sends. The
 * user is never an argument (the server acts for the signed-in user), and the
 * endpoint in a GET travels encoded.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiCall = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ apiCall }));

import { pushConfig, pushSubscribe, pushUnsubscribe } from "@/api/push";

const BASE = "vansale.steelforce.approvals_push";

describe("push api", () => {
  beforeEach(() => {
    apiCall.mockReset();
    apiCall.mockResolvedValue({});
  });

  it("pushConfig asks with the endpoint, encoded in the query", async () => {
    await pushConfig("https://fcm.googleapis.com/fcm/send/a:b?c=1&d=2");
    expect(apiCall).toHaveBeenCalledWith(
      "GET",
      `${BASE}.push_config?endpoint=https%3A%2F%2Ffcm.googleapis.com%2Ffcm%2Fsend%2Fa%3Ab%3Fc%3D1%26d%3D2`,
    );
  });

  it("pushConfig sends no query when the browser holds no subscription", async () => {
    await pushConfig();
    await pushConfig("");
    expect(apiCall.mock.calls).toEqual([
      ["GET", `${BASE}.push_config`],
      ["GET", `${BASE}.push_config`],
    ]);
  });

  it("pushSubscribe posts the endpoint, both keys and the user agent", async () => {
    await pushSubscribe({ endpoint: "https://push.example/x", p256dh: "k", auth: "a", user_agent: "UA" });
    expect(apiCall).toHaveBeenCalledWith("POST", `${BASE}.push_subscribe`, {
      endpoint: "https://push.example/x",
      p256dh: "k",
      auth: "a",
      user_agent: "UA",
    });
  });

  it("pushSubscribe sends an empty user agent when there is none", async () => {
    await pushSubscribe({ endpoint: "https://push.example/x", p256dh: "k", auth: "a" });
    expect(apiCall.mock.calls[0][2]).toMatchObject({ user_agent: "" });
  });

  it("pushUnsubscribe posts the endpoint alone", async () => {
    await pushUnsubscribe("https://push.example/x");
    expect(apiCall).toHaveBeenCalledWith("POST", `${BASE}.push_unsubscribe`, { endpoint: "https://push.example/x" });
  });

  it("hands back what the server answered", async () => {
    apiCall.mockResolvedValue({ enabled: true, public_key: "BKEY", subscribed: false });
    await expect(pushConfig("e")).resolves.toEqual({ enabled: true, public_key: "BKEY", subscribed: false });
  });
});
