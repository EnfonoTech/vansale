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
 * Runtime site URL, entered once on the setup screen and kept in
 * Preferences until uninstall (or an explicit site change).
 *
 * Held in a module variable because `apiBase()` is called synchronously
 * from dozens of places. `loadSiteUrl()` hydrates it from storage BEFORE
 * the app mounts — see `main.ts`.
 */
let runtimeSiteUrl: string | null = null;

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

/** Hydrate the cached site URL from storage. Call once, before mount. */
export async function loadSiteUrl(): Promise<void> {
  try {
    if (isNative()) {
      const { value } = await Preferences.get({ key: SITE_URL_KEY });
      runtimeSiteUrl = value || null;
    } else {
      runtimeSiteUrl = window.localStorage.getItem(SITE_URL_KEY);
    }
  } catch {
    runtimeSiteUrl = null;
  }
}

export async function setSiteUrl(url: string): Promise<void> {
  const origin = normalizeSiteUrl(url);
  runtimeSiteUrl = origin;
  if (isNative()) {
    await Preferences.set({ key: SITE_URL_KEY, value: origin });
  } else {
    window.localStorage.setItem(SITE_URL_KEY, origin);
  }
}

export async function clearSiteUrl(): Promise<void> {
  runtimeSiteUrl = null;
  if (isNative()) {
    await Preferences.remove({ key: SITE_URL_KEY });
  } else {
    window.localStorage.removeItem(SITE_URL_KEY);
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
