/**
 * Web Push for approvals: ask whether this device can be told when a document
 * reaches the signed-in user, and register or drop the device's subscription.
 * Endpoints live in `vansale.steelforce.approvals_push`; on a site without
 * Permission Manager, or without the VAPID keys set up, `push_config` answers
 * `enabled: false` and the switch stays hidden.
 *
 * The server always acts for the signed-in user: no call names one. Like the
 * rest of approvals these calls are never queued offline.
 */
import { apiCall } from "./client";

const BASE = "vansale.steelforce.approvals_push";

/** What `push_config` answers. */
export interface PushConfig {
  /** Approvals are available, the VAPID keys are set and the server can send. */
  enabled: boolean;
  /** The VAPID public key (base64url) the browser subscribes with; "" when not enabled. */
  public_key: string;
  /** The server already holds a subscription with the asked endpoint for this user. */
  subscribed: boolean;
}

/** One browser subscription as the server stores it. */
export interface PushSubscribeBody {
  endpoint: string;
  /** base64url of the subscription's `p256dh` key. */
  p256dh: string;
  /** base64url of the subscription's `auth` secret. */
  auth: string;
  /** The browser's user agent, so a list of devices can name them; the server cuts it to 255. */
  user_agent?: string;
}

export interface PushAck {
  ok: boolean;
}

/** `endpoint` is "" when the browser holds no subscription yet: `subscribed` is then false. */
export function pushConfig(endpoint = ""): Promise<PushConfig> {
  const qs = endpoint ? `?${new URLSearchParams({ endpoint }).toString()}` : "";
  return apiCall("GET", `${BASE}.push_config${qs}`);
}

export function pushSubscribe(subscription: PushSubscribeBody): Promise<PushAck> {
  return apiCall("POST", `${BASE}.push_subscribe`, {
    endpoint: subscription.endpoint,
    p256dh: subscription.p256dh,
    auth: subscription.auth,
    user_agent: subscription.user_agent ?? "",
  });
}

export function pushUnsubscribe(endpoint: string): Promise<PushAck> {
  return apiCall("POST", `${BASE}.push_unsubscribe`, { endpoint });
}
