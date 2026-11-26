/**
 * The name, logo and look of the sign-in screens, set in Vansale Settings and
 * read from a public endpoint (`vansale.api.auth.branding`).
 *
 * The last answer is kept in localStorage so the screen is right on first paint
 * and offline. With no answer yet it falls back to what the build was made with:
 * the build title (`__APP_TITLE__`), the built-in mark, the Classic style.
 */
import { readonly, ref, type Ref } from "vue";
import { absoluteUrl, apiBase } from "@/app/platform";

export type LoginStyle = "classic" | "split" | "dark";

export interface Branding {
  appName: string;
  logoUrl: string;
  style: LoginStyle;
}

export const BRANDING_CACHE_KEY = "vansale.branding";

const STYLES: readonly LoginStyle[] = ["classic", "split", "dark"];
const MAX_NAME = 40;
const TIMEOUT_MS = 8000;

/** Accepts the endpoint's `{app_name, logo_url, style}` or a cached `Branding`. */
export function normalizeBranding(raw: unknown): Branding {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const appName = String(r.app_name ?? r.appName ?? "").trim().slice(0, MAX_NAME);
  const logoUrl = String(r.logo_url ?? r.logoUrl ?? "").trim();
  const style = String(r.style ?? "") as LoginStyle;
  return {
    appName: appName || __APP_TITLE__,
    logoUrl,
    style: STYLES.includes(style) ? style : "classic",
  };
}

export function readCachedBranding(): Branding | null {
  try {
    const text = window.localStorage.getItem(BRANDING_CACHE_KEY);
    if (!text) return null;
    const parsed: unknown = JSON.parse(text);
    return parsed && typeof parsed === "object" ? normalizeBranding(parsed) : null;
  } catch {
    return null;
  }
}

function writeCachedBranding(value: Branding): void {
  try {
    window.localStorage.setItem(BRANDING_CACHE_KEY, JSON.stringify(value));
  } catch {
    /* private mode or full storage: the next open just uses the fallbacks */
  }
}

/** The browser tab's title: the build's own is "Van Sale". */
function applyTitle(value: Branding): void {
  try {
    document.title = value.appName;
  } catch {
    /* no document (tests, workers): nothing to title */
  }
}

const cachedAtStart = readCachedBranding();
const state = ref<Branding>(cachedAtStart ?? normalizeBranding(null));
if (cachedAtStart) applyTitle(cachedAtStart);

/** The class that tells the global auth stylesheet which look to draw. */
export function authStyleClass(style: LoginStyle): string {
  return `auth-style-${style}`;
}

async function refreshBranding(): Promise<void> {
  let url: string;
  try {
    url = `${apiBase()}/api/method/vansale.api.auth.branding`;
  } catch {
    return; // native build before a server is set: nothing to ask yet
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, { headers: { Accept: "application/json" }, signal: controller.signal });
    if (!res.ok) return; // an older server has no endpoint: keep what we have
    const body = (await res.json()) as { message?: unknown };
    const next = normalizeBranding(body?.message);
    next.logoUrl = absoluteUrl(next.logoUrl);
    state.value = next;
    applyTitle(next);
    writeCachedBranding(next);
  } catch {
    /* offline or slow: keep the cached or fallback value */
  } finally {
    clearTimeout(timer);
  }
}

export function useBranding(): { branding: Readonly<Ref<Branding>>; refreshBranding: () => Promise<void> } {
  return { branding: readonly(state) as Readonly<Ref<Branding>>, refreshBranding };
}

export function resetBrandingForTests(): void {
  const cached = readCachedBranding();
  state.value = cached ?? normalizeBranding(null);
  if (cached) applyTitle(cached);
}
