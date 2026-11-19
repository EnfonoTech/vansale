/**
 * Approval notifications on this device: whether the browser may be told, by
 * Web Push, when a document reaches the signed-in user (even with the app
 * closed), and the switch that turns that on or off.
 *
 * - The app's service worker (`vansale/pwa.py`) shows the notification and
 *   opens the document; this store only subscribes the browser and tells the
 *   server.
 * - The native app has no service worker: `visible` is false there.
 * - `enable` must be called straight from a tap: the permission prompt needs
 *   the tap's user activation, so nothing is awaited before it is asked.
 * - Turning it on or off needs a connection (both talk to the server).
 *   Nothing is queued.
 * - `detach` is for logout: best effort, quick, and it never throws, so a
 *   logged-out device stops receiving that user's approvals without ever
 *   holding the logout up.
 */
import { defineStore } from "pinia";
import * as api from "@/api/push";
import { NetworkError } from "@/api/client";
import { isOnline } from "@/app/online";
import { isNative } from "@/app/platform";
import { withTimeout } from "@/features/push/async";
import { urlBase64ToUint8Array } from "@/features/push/encoding";
import { readSupport, type PushEnv } from "@/features/push/support";
import { subscribeWithKey, toSubscribeBody } from "@/features/push/subscription";
import { INITIAL, isOn, reduce, type Problem, type ToggleEvent, type ToggleState } from "@/features/push/toggle";
import { useSessionStore } from "@/stores/session";

/** How long to wait for the app's service worker to be ready before giving up. */
export const READY_MS = 10_000;
/** Logout: how long the browser may take to look up the subscription. */
export const DETACH_LOOKUP_MS = 2_000;
/** Logout: how long the server may take to drop it. */
export const DETACH_SERVER_MS = 4_000;

interface State {
  /** The server can send pushes for this site. Until it says so, the switch stays hidden. */
  enabled: boolean;
  /** The server's VAPID public key (base64url). */
  publicKey: string;
  /** The endpoint of this browser's subscription, "" when it holds none. */
  endpoint: string;
  toggle: ToggleState;
}

function blank(): State {
  return { enabled: false, publicKey: "", endpoint: "", toggle: INITIAL };
}

/** What the page offers, for `readSupport`. */
function browserEnv(): PushEnv {
  return {
    native: isNative(),
    navigator: typeof navigator === "undefined" ? undefined : navigator,
    PushManager: typeof window === "undefined" ? undefined : window.PushManager,
    Notification: typeof window === "undefined" ? undefined : window.Notification,
  };
}

/** The registration of the app's worker; null when none is registered (the dev server registers none). */
async function registration(): Promise<ServiceWorkerRegistration | null> {
  return (await navigator.serviceWorker.getRegistration()) ?? null;
}

async function currentSubscription(): Promise<PushSubscription | null> {
  return (await (await registration())?.pushManager.getSubscription()) ?? null;
}

function problemOf(error: unknown): Problem {
  return error instanceof NetworkError ? "offline" : "failed";
}

/** Drop a browser subscription and say nothing if that fails. */
async function dropQuietly(subscription: PushSubscription | null): Promise<void> {
  try {
    await subscription?.unsubscribe();
  } catch {
    /* the server prunes a dead endpoint the next time it sends */
  }
}

/** Only the newest look at the browser and the server may land; a reset drops the ones on their way. */
let refreshSeq = 0;

export const usePushStore = defineStore("push", {
  state: (): State => blank(),
  getters: {
    /** Show the switch: the web app, on a site whose server can send. */
    visible: (s): boolean => s.enabled && !isNative(),
  },
  actions: {
    dispatch(event: ToggleEvent) {
      this.toggle = reduce(this.toggle, event);
    },

    /**
     * Read the browser (support, permission, current subscription), then ask
     * the server whether it can send and knows this subscription. Offline, or
     * when the server does not answer, what is known stays: the switch keeps
     * its side, and stays hidden if it never saw an answer.
     */
    async refresh(): Promise<void> {
      if (isNative()) return;
      const session = useSessionStore();
      const user = session.user;
      if (!user) return;

      // A change on its way owns the state: a look that overlaps it would only get in its way.
      if (this.toggle.kind === "busy") return;
      const seq = ++refreshSeq;
      const current = () => seq === refreshSeq && session.user === user && this.toggle.kind !== "busy";

      const support = readSupport(browserEnv());
      let endpoint = "";
      if (support !== "unsupported") {
        try {
          endpoint = (await currentSubscription())?.endpoint ?? "";
        } catch {
          /* no worker to ask: nothing is subscribed */
        }
        if (!current()) return;
      }

      // What the switch shows when the server cannot say: its last answer, else what the browser holds.
      const guess = this.toggle.kind === "checking" ? endpoint !== "" : isOn(this.toggle);
      if (!isOnline()) {
        this.dispatch({ type: "checked", support, subscribed: guess });
        return;
      }
      try {
        const config = await api.pushConfig(endpoint);
        if (!current()) return;
        this.enabled = config.enabled === true;
        this.publicKey = config.enabled === true ? config.public_key : "";
        this.endpoint = endpoint;
        this.dispatch({ type: "checked", support, subscribed: endpoint !== "" && config.subscribed === true });
      } catch {
        if (!current()) return;
        this.dispatch({ type: "checked", support, subscribed: guess });
      }
    },

    /**
     * Turn notifications on: ask permission, subscribe the browser with the
     * server's key and give the subscription to the server. Call it straight
     * from the tap. When the server refuses, the browser side is undone too,
     * so the two never disagree.
     */
    async enable(): Promise<void> {
      if (!isOnline() || reduce(this.toggle, { type: "start", target: "on" }).kind !== "busy") return;
      this.dispatch({ type: "start", target: "on" });
      const user = useSessionStore().user;
      let subscription: PushSubscription | null = null;
      try {
        if (!this.publicKey) throw new Error("The server sent no key");
        // The first thing awaited, and asked before anything else is: still inside the tap.
        const permission = await window.Notification.requestPermission();
        if (permission !== "granted") {
          this.dispatch({ type: permission === "denied" ? "denied" : "dismissed" });
          return;
        }

        const ready = await withTimeout(navigator.serviceWorker.ready, READY_MS, "The service worker is not ready");
        subscription = await subscribeWithKey(ready.pushManager, urlBase64ToUint8Array(this.publicKey));
        await api.pushSubscribe(toSubscribeBody(subscription, navigator.userAgent));

        // Signed out while it worked: the subscription is not this user's to keep.
        if (useSessionStore().user !== user) {
          await dropQuietly(subscription);
          return;
        }
        this.endpoint = subscription.endpoint;
        this.dispatch({ type: "done" });
      } catch (error) {
        await dropQuietly(subscription);
        if (window.Notification?.permission === "denied") this.dispatch({ type: "denied" });
        else this.dispatch({ type: "failed", problem: problemOf(error) });
      }
    },

    /** Turn notifications off: the server forgets this device, then the browser does. */
    async disable(): Promise<void> {
      if (!isOnline() || reduce(this.toggle, { type: "start", target: "off" }).kind !== "busy") return;
      this.dispatch({ type: "start", target: "off" });
      try {
        const subscription = await currentSubscription();
        const endpoint = subscription?.endpoint ?? this.endpoint;
        if (endpoint) await api.pushUnsubscribe(endpoint);
        // The server has let go; a browser that fails to is harmless (nothing is sent to it).
        await dropQuietly(subscription);
        this.endpoint = "";
        this.dispatch({ type: "done" });
      } catch (error) {
        this.dispatch({ type: "failed", problem: problemOf(error) });
      }
    },

    /**
     * Logout: stop this device receiving the user's approvals. Call it BEFORE
     * the server logout (the call needs the session). Always unsubscribes the
     * browser, even when the server cannot be reached: the push service then
     * refuses the endpoint and the server deletes it on its next send. Quick
     * (a few seconds at most) and never throws.
     */
    async detach(): Promise<void> {
      if (isNative() || readSupport(browserEnv()) === "unsupported") return;
      try {
        const subscription = await withTimeout(currentSubscription(), DETACH_LOOKUP_MS, "No answer from the browser");
        if (!subscription) return;
        if (isOnline()) {
          try {
            await withTimeout(api.pushUnsubscribe(subscription.endpoint), DETACH_SERVER_MS, "No answer from the server");
          } catch {
            /* best effort: the browser side below still stops the pushes */
          }
        }
        await dropQuietly(subscription);
      } catch {
        /* never hold a logout up */
      }
    },

    /** Forget everything held (logout, another user). */
    reset() {
      refreshSeq++;
      // Replaced, not merged: `$patch(object)` would merge the old side's fields into the new one.
      this.$patch((state) => Object.assign(state, blank()));
    },
  },
});
