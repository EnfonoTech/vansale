/**
 * Runtime platform detection. `isNative()` is the single source of truth
 * for every native-vs-web branch. Do not scatter plugin-existence checks
 * across the codebase — trust this helper and lazily feature-detect inside
 * the relevant modules.
 *
 * See `frappe-vue-pwa` §3.3.
 */

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

/**
 * API base URL.
 * - Web build: relative (served from the same Frappe host) → empty string.
 * - Native build: absolute, read from `VITE_API_BASE` at build time so the
 *   APK can target a specific server.
 */
export function apiBase(): string {
  if (isNative()) {
    const fromEnv = import.meta.env.VITE_API_BASE;
    if (!fromEnv) {
      throw new Error("VITE_API_BASE not set for native build");
    }
    return String(fromEnv).replace(/\/+$/, "");
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
