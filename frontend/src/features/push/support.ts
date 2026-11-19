/**
 * Can this device take Web Push, and may it ask? `readSupport` is pure: the
 * store hands it what the page offers (`browserEnv`), the tests hand it
 * anything they like.
 */

/** What the toggle needs from the page; every member is optional because a browser may lack it. */
export interface PushEnv {
  /** The Capacitor app: it has no service worker, so the control is not offered. */
  native: boolean;
  navigator?: { serviceWorker?: unknown };
  PushManager?: unknown;
  Notification?: { permission?: string };
}

export type Support = "unsupported" | "denied" | "ready";

/**
 * - `unsupported`: the native app, or a browser without service workers, the
 *   Push API or Notifications (an iPhone tab that was not added to the Home
 *   Screen is one).
 * - `denied`: the user blocked notifications for this site; only the browser's
 *   own settings can lift that, so the app cannot ask again.
 * - `ready`: permission is granted or not asked yet.
 */
export function readSupport(env: PushEnv): Support {
  if (env.native) return "unsupported";
  if (!env.navigator || !("serviceWorker" in env.navigator) || !env.navigator.serviceWorker) return "unsupported";
  if (!env.PushManager || !env.Notification) return "unsupported";
  return env.Notification.permission === "denied" ? "denied" : "ready";
}

/**
 * An iPhone or iPad. Safari there offers Web Push only to an app added to the
 * Home Screen, so "not supported" in a plain tab deserves its own advice.
 * An iPad can pose as a Mac: it is told apart by its touch screen.
 */
export function isIos(ua: string, platform = "", maxTouchPoints = 0): boolean {
  return /iPhone|iPad|iPod/.test(ua) || (platform === "MacIntel" && maxTouchPoints > 1);
}
