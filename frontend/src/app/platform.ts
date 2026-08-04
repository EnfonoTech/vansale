/**
 * Runtime platform detection. `isNative()` is the single source of truth
 * for every native-vs-web branch. Do not scatter plugin-existence checks
 * across the codebase — trust this helper and lazily feature-detect inside
 * the relevant modules.
 *
 * See `frappe-vue-pwa` §3.3.
 *
 * `Preferences` is imported statically on purpose — dynamic imports have
 * been observed to hang silently inside the Android WebView (§3.4 rule 14).
 * The web bundle keeps the import inert because every call site is behind
 * an `isNative()` branch.
 */
import { Preferences } from "@capacitor/preferences";

declare global {
  interface Window {
    Capacitor?: {
      isNativePlatform?: () => boolean;
      // Plugins map is keyed by plugin name (matches `@CapacitorPlugin(name=...)`
      // on the Java side). Individual plugin TS bridges narrow the type
      // with their own `declare global` merge (see `native-print.ts`).
      Plugins?: Record<string, unknown>;
    };
  }
}

export function isNative(): boolean {
  try {
    return Boolean(window.Capacitor?.isNativePlatform?.());
  } catch {
    return false;
  }
}

const SITE_URL_KEY = "vansale.siteUrl";

/**
 * Runtime site URL, entered once on the setup screen and kept until
 * uninstall (or an explicit site change).
 *
 * Held in a module variable because `apiBase()` is called synchronously from
 * dozens of places.
 *
 * Stored in localStorage **and** Preferences, and seeded synchronously at
 * import time. That redundancy is load-bearing, not belt-and-braces:
 * `loadSiteUrl()` runs before `app.mount()`, and at that point the Capacitor
 * bridge may not have injected `window.Capacitor` yet — so `isNative()`
 * answers false and a Preferences-only value is invisible. The first router
 * guard then saw "no server configured" and bounced an already-configured
 * app to /setup on every cold start (the field looked pre-filled because the
 * async Preferences read landed after the view rendered).
 *
 * localStorage is readable synchronously and survives app restarts in the
 * Capacitor WebView — the session store already depends on that. Preferences
 * stays as the durable mirror.
 */
function readStoredSiteUrl(): string | null {
  try {
    return window.localStorage.getItem(SITE_URL_KEY) || null;
  } catch {
    return null;
  }
}

let runtimeSiteUrl: string | null = readStoredSiteUrl();

/**
 * Normalise a user-typed host into an origin.
 *
 * Field users type "van.acme.com", "VAN.ACME.COM/", sometimes with a path
 * pasted from a browser. Everything after the origin is dropped: the app
 * builds its own `/api/method/...` paths, so a stray path segment would
 * produce `https://host/app/api/method/...` and 404 every call.
 *
 * Throws on anything unparseable so the setup screen can say why.
 */
export function normalizeSiteUrl(raw: string): string {
  const trimmed = (raw ?? "").trim();
  if (!trimmed) throw new Error("Enter your server address");
  const withScheme = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  let url: URL;
  try {
    url = new URL(withScheme);
  } catch {
    throw new Error("That does not look like a valid address");
  }
  if (!url.hostname.includes(".") && url.hostname !== "localhost") {
    throw new Error("Enter the full address, e.g. van.company.com");
  }
  return url.origin;
}

/**
 * Hydrate the cached site URL. Call once, before mount.
 *
 * The synchronous localStorage seed above already covers the normal case;
 * this only has to recover a value that exists in Preferences but not in
 * localStorage — i.e. an APK upgraded from a build that wrote Preferences
 * only. When that happens the value is mirrored back so later cold starts
 * take the fast synchronous path.
 */
export async function loadSiteUrl(): Promise<void> {
  if (runtimeSiteUrl) return;
  try {
    const { value } = await Preferences.get({ key: SITE_URL_KEY });
    if (value) {
      runtimeSiteUrl = value;
      try {
        window.localStorage.setItem(SITE_URL_KEY, value);
      } catch {
        /* private mode / quota — Preferences alone still works */
      }
    }
  } catch {
    /* plugin absent (web build) — the localStorage seed is authoritative */
  }
}

export async function setSiteUrl(url: string): Promise<void> {
  const origin = normalizeSiteUrl(url);
  runtimeSiteUrl = origin;
  // localStorage first and unconditionally: it is what the next cold start
  // reads synchronously, before the native bridge exists.
  try {
    window.localStorage.setItem(SITE_URL_KEY, origin);
  } catch {
    /* ignore */
  }
  try {
    await Preferences.set({ key: SITE_URL_KEY, value: origin });
  } catch {
    /* web build — localStorage is enough */
  }
}

export async function clearSiteUrl(): Promise<void> {
  runtimeSiteUrl = null;
  try {
    window.localStorage.removeItem(SITE_URL_KEY);
  } catch {
    /* ignore */
  }
  try {
    await Preferences.remove({ key: SITE_URL_KEY });
  } catch {
    /* ignore */
  }
}

/** The configured site, or the build-time default, or null. */
export function siteUrl(): string | null {
  if (runtimeSiteUrl) return runtimeSiteUrl;
  const fromEnv = import.meta.env.VITE_API_BASE;
  return fromEnv ? String(fromEnv).replace(/\/+$/, "") : null;
}

/**
 * True when the APK has no server to talk to yet. Web builds are always
 * served by their own Frappe host, so they never need setup.
 */
export function needsSiteSetup(): boolean {
  return isNative() && !siteUrl();
}

/**
 * API base URL.
 * - Web build: relative (served from the same Frappe host) → empty string.
 * - Native build: the site URL entered on the setup screen, falling back to
 *   `VITE_API_BASE` baked in at build time for pre-pointed customer APKs.
 */
export function apiBase(): string {
  if (isNative()) {
    const base = siteUrl();
    if (!base) {
      throw new Error("No server configured — finish setup first");
    }
    return base;
  }
  return "";
}

/** Absolute URL for a `/files/...` or other root-relative resource.
 *  Fixes broken `<img>` sources inside the Capacitor WebView (§4.8).
 */
export function absoluteUrl(url: string | null | undefined): string {
  if (!url) return "";
  if (/^(https?:|data:|blob:|photo:)/i.test(url)) return url;
  if (isNative() && url.startsWith("/")) return `${apiBase()}${url}`;
  return url;
}
