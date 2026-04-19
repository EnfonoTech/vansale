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

function getCsrfToken(): string | null {
  const m = document.cookie.match(/csrf_token=([^;]+)/);
  if (m) return decodeURIComponent(m[1]);
  const w = window as unknown as { csrf_token?: string };
  return w.csrf_token ?? null;
}

async function authHeaders(): Promise<Record<string, string>> {
  if (isNative()) {
    const creds = await getCredentials();
    return creds ? { Authorization: `token ${creds.apiKey}:${creds.apiSecret}` } : {};
  }
  const csrf = getCsrfToken();
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

  let res: Response;
  try {
    res = await fetch(url, fetchOpts(init));
  } catch {
    throw new NetworkError();
  }

  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* empty body is fine for 204 etc. */
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
 * - Native: Phase 1 uses a stub that falls back to anchor (the Android
 *   WebView silently drops `<a download>` — see fatehhr lesson #10.1,
 *   so Phase 5 replaces this with `@capacitor/filesystem` writeFile).
 *
 * Filenames are sanitised: Frappe doc names contain `/` and spaces
 * which break Filesystem + share sheets (fatehhr lesson #12).
 */
export async function saveBlobToDevice(blob: Blob, rawName: string): Promise<void> {
  const safeName = rawName.replace(/[^A-Za-z0-9._-]+/g, "_");
  if (isNative()) {
    /* Phase 5: await Filesystem.writeFile(...)  */
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
