/** A browser subscription, reduced to what the server stores. */
import type { PushSubscribeBody } from "@/api/push";
import { bytesToBase64Url } from "./encoding";

/** The part of `PushSubscription` this needs, so a test can pass a plain object. */
export interface SubscriptionLike {
  endpoint: string;
  getKey(name: "p256dh" | "auth"): ArrayBuffer | null;
}

/**
 * The body of `push_subscribe`. A subscription that lacks a key cannot be
 * encrypted for, so this throws instead of sending half of one.
 */
export function toSubscribeBody(subscription: SubscriptionLike, userAgent = ""): PushSubscribeBody {
  const p256dh = subscription.getKey("p256dh");
  const auth = subscription.getKey("auth");
  if (!subscription.endpoint || !p256dh || !auth || p256dh.byteLength === 0 || auth.byteLength === 0) {
    throw new Error("The browser gave an incomplete push subscription");
  }
  return {
    endpoint: subscription.endpoint,
    p256dh: bytesToBase64Url(p256dh),
    auth: bytesToBase64Url(auth),
    user_agent: userAgent,
  };
}

/** What `subscribeWithKey` needs of `PushManager`. */
export interface PushManagerLike<S extends { unsubscribe(): Promise<boolean> }> {
  getSubscription(): Promise<S | null>;
  subscribe(options: { userVisibleOnly: boolean; applicationServerKey: BufferSource }): Promise<S>;
}

/**
 * Subscribe with the server's public key. When the browser already holds a
 * subscription made with another key (the server's keys were replaced since),
 * `subscribe` refuses with `InvalidStateError`: that old subscription is
 * dropped and the subscribe is tried once more. Any other refusal is passed on.
 */
export async function subscribeWithKey<S extends { unsubscribe(): Promise<boolean> }>(
  pushManager: PushManagerLike<S>,
  applicationServerKey: BufferSource,
): Promise<S> {
  const options = { userVisibleOnly: true, applicationServerKey };
  try {
    return await pushManager.subscribe(options);
  } catch (error) {
    if ((error as { name?: string } | null)?.name !== "InvalidStateError") throw error;
    await (await pushManager.getSubscription())?.unsubscribe();
    return pushManager.subscribe(options);
  }
}
