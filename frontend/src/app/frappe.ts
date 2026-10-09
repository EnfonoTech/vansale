/**
 * Thin Frappe API facade.
 *
 * Responsibilities:
 *   - URL + auth branching for web (cookie + CSRF) vs native (token).
 *   - Distinguishing `ApiError` (server validation) from network errors —
 *     the offline queue must ONLY swallow network failures. See
 *     `frappe-vue-pwa` §4 commandment 2 + fatehhr lesson #2.
 *   - GET params go in the URL; body on GET is silently dropped by
 *     `fetch` (fatehhr lesson §1.0.10 bug 3).
 *   - `saveBlobToDevice` placeholder for native-safe PDF download; the
 *     Filesystem plugin wiring lives in Phase 5.
 *
 * Capacitor plugins are imported statically — dynamic imports have been
 * observed to hang silently inside the Android WebView (§3.4 rule 14).
 * In Phase 1 the Preferences plugin is only used when `isNative()` is
 * true, so the web bundle's static import is inert.
 */

import { Preferences } from "@capacitor/preferences";
import { absoluteUrl, apiBase, isNative } from "./platform";
import { arrayBufferToBase64 } from "@/offline/_base64";

const CRED_KEY = "vansale.credentials";

export interface Credentials {
  apiKey: string;
  apiSecret: string;
}

let credsCache: Credentials | null = null;

export async function getCredentials(): Promise<Credentials | null> {
  if (credsCache) return credsCache;
  if (!isNative()) {
    const raw = window.localStorage.getItem(CRED_KEY);
    if (raw) credsCache = JSON.parse(raw) as Credentials;
    return credsCache;
  }
  const { value } = await Preferences.get({ key: CRED_KEY });
  if (value) credsCache = JSON.parse(value) as Credentials;
  return credsCache;
}

export async function setCredentials(creds: Credentials): Promise<void> {
  credsCache = creds;
  const raw = JSON.stringify(creds);
  if (isNative()) {
    await Preferences.set({ key: CRED_KEY, value: raw });
  } else {
    window.localStorage.setItem(CRED_KEY, raw);
  }
}

export async function clearCredentials(): Promise<void> {
  credsCache = null;
  if (isNative()) {
    await Preferences.remove({ key: CRED_KEY });
  } else {
    window.localStorage.removeItem(CRED_KEY);
  }
}

/**
 * Thrown when the server returns a non-2xx response with a parsed
 * Frappe error body. Distinct from network failures (which bubble up
 * as plain `TypeError`/`Error("OFFLINE")`) — the queue-drain logic
 * MUST re-throw `ApiError` to surface validation messages instead of
 * looping forever.
 */
export class ApiError extends Error {
  status: number;
  serverMessage?: string;
  constructor(message: string, status: number, serverMessage?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.serverMessage = serverMessage;
  }
}

/** Plain "we couldn't reach the server" error — safe to queue + retry. */
export class NetworkError extends Error {
  constructor(message = "Network unreachable") {
    super(message);
    this.name = "NetworkError";
  }
}

/**
 * Synchronous CSRF sources, both of which are absent for the web SPA.
 *
 * Frappe v15 keeps `csrf_token` in server-side session data, not in a cookie,
 * and only injects `window.csrf_token` into desk/website pages it renders. Our
 * SPA is a STATIC asset under /assets/, so neither source exists — which is why
 * this needs the async fetch below rather than only reading these.
 */
function getCsrfTokenSync(): string | null {
  const m = document.cookie.match(/csrf_token=([^;]+)/);
  if (m) return decodeURIComponent(m[1]);
  const w = window as unknown as { csrf_token?: string };
  return w.csrf_token ?? null;
}

let csrfCache: string | null = null;

/**
 * CSRF token for the web build, fetched once and cached.
 *
 * Without this, web login failed with **400 "Invalid Request"** in any browser
 * that already held a Frappe session (a desk tab open in another tab is enough).
 * `auth.validate_csrf_token` skips the check when the session has no saved
 * token — so an incognito window worked — but throws `CSRFTokenError` as soon as
 * one exists and the request header does not match. A static page has no way to
 * read that token, so it must ask the server for it.
 *
 * `util.get_csrf_token` is `allow_guest`, and the request carries cookies, so
 * the token returned belongs to the same session that will be validated.
 */
async function ensureCsrfToken(): Promise<string | null> {
  const local = getCsrfTokenSync();
  if (local) return local;
  if (csrfCache) return csrfCache;
  try {
    const res = await fetch(`${apiBase()}/api/method/vansale.api.util.get_csrf_token`, {
      method: "GET",
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { message?: string };
    csrfCache = body?.message || null;
    return csrfCache;
  } catch {
    // Offline, or the endpoint is missing on an older server. Send the request
    // without the header; Frappe only rejects it when a saved token exists.
    return null;
  }
}

/** Discard the cached token — the session, and therefore the token, changed. */
export function resetCsrfToken(): void {
  csrfCache = null;
}

async function authHeaders(): Promise<Record<string, string>> {
  if (isNative()) {
    const creds = await getCredentials();
    return creds ? { Authorization: `token ${creds.apiKey}:${creds.apiSecret}` } : {};
  }
  const csrf = await ensureCsrfToken();
  return csrf ? { "X-Frappe-CSRF-Token": csrf } : {};
}

function fetchOpts(opts: RequestInit): RequestInit {
  if (isNative()) {
    const { credentials: _c, ...rest } = opts;
    return rest;
  }
  return { credentials: "include", ...opts };
}

function apiUrl(pathOrMethod: string, asMethod: boolean): string {
  const base = apiBase();
  if (asMethod) {
    return `${base}/api/method/${pathOrMethod}`;
  }
  return pathOrMethod.startsWith("/") ? `${base}${pathOrMethod}` : `${base}/${pathOrMethod}`;
}

interface FrappeErrorBody {
  exception?: string;
  exc?: string;
  _server_messages?: string;
}

function parseServerError(body: unknown): string | undefined {
  if (!body || typeof body !== "object") return undefined;
  const b = body as FrappeErrorBody;
  if (b._server_messages) {
    try {
      const parsed = JSON.parse(b._server_messages);
      const first = Array.isArray(parsed) && parsed.length > 0 ? parsed[0] : null;
      const inner = typeof first === "string" ? JSON.parse(first) : first;
      if (inner && typeof inner === "object" && "message" in inner) {
        return String((inner as { message?: string }).message ?? "").replace(/<[^>]+>/g, "");
      }
    } catch {
      /* ignore parse errors */
    }
  }
  return b.exception;
}

/**
 * Call a whitelisted method.
 *
 * Usage:
 *   await apiCall("GET", "vansale.api.customer.detail?name=CUST-0001");
 *   await apiCall("POST", "vansale.api.auth.setup_pin", { pin: "1234" });
 *
 * GET params must be in the URL (fatehhr lesson #13).
 */
export async function apiCall<T>(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  return callOnce<T>(method, path, body, false);
}

async function callOnce<T>(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  body: unknown,
  csrfRetried: boolean,
): Promise<T> {
  const hasDotted = /^[a-z_][\w.]+$/i.test(path.split("?")[0]);
  const url = apiUrl(path, hasDotted);
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(await authHeaders()),
  };
  const init: RequestInit = { method, headers };
  if (method !== "GET" && body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  // 20s timeout so mobile WebView doesn't hang forever on flaky networks.
  // Without this, slow/failing requests surface as indefinite blank screens.
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 20_000);
  init.signal = controller.signal;

  let res: Response;
  try {
    res = await fetch(url, fetchOpts(init));
  } catch (err) {
    if ((err as { name?: string } | null)?.name === "AbortError") {
      throw new NetworkError("Request timed out");
    }
    throw new NetworkError();
  } finally {
    window.clearTimeout(timeoutId);
  }

  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* empty body is fine for 204 etc. */
  }

  // The cached CSRF token is stale: the browser's Frappe session changed
  // outside the app (e.g. a desk login in another tab). Fetch the current
  // session's token and retry once.
  if (
    res.status === 400 && !csrfRetried && !isNative() &&
    (data as { exc_type?: string } | null)?.exc_type === "CSRFTokenError"
  ) {
    resetCsrfToken();
    return callOnce<T>(method, path, body, true);
  }

  if (!res.ok) {
    const msg = parseServerError(data) ?? `HTTP ${res.status}`;
    throw new ApiError(msg, res.status, msg);
  }

  const wrapped = data as { message?: T } | null;
  return (wrapped?.message ?? (data as T)) as T;
}

/**
 * Save a Blob to the user's device.
 *
 * - Web: constructs an object-URL and clicks a hidden anchor.
 * - Native (Android/iOS): `<a download>` is silently dropped by the
 *   WebView (fatehhr lesson #10.1). Uses `@capacitor/filesystem` +
 *   Documents/ directory instead.
 *
 * Filenames are sanitised: Frappe doc names contain `/` and spaces
 * which break Filesystem + share sheets (fatehhr lesson #12).
 */
export async function saveBlobToDevice(blob: Blob, rawName: string): Promise<void> {
  const safeName = rawName.replace(/[^A-Za-z0-9._-]+/g, "_") || "download";

  if (isNative()) {
    try {
      const { Filesystem, Directory } = await import("@capacitor/filesystem");
      const buf = await blob.arrayBuffer();
      const res = await Filesystem.writeFile({
        path: safeName,
        data: arrayBufferToBase64(buf),
        directory: Directory.Documents,
        recursive: true,
      });
      // eslint-disable-next-line no-console
      console.info("vansale: saved", res.uri);
      return;
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("saveBlobToDevice native failed", err);
      // Fall through to anchor as last resort.
    }
  }

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = safeName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export { absoluteUrl };
