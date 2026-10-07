/**
 * Offline PIN unlock.
 *
 * PIN unlock is a server call, and the router asks for the PIN again after
 * the 2-hour window. Without a local check a driver out of coverage was
 * locked out of the whole app — including queuing sales.
 *
 * After every PIN the server accepts we keep a PBKDF2-SHA256 hash of it
 * (random salt, 150k iterations) for that user — never the PIN itself.
 * Offline, the PIN screen checks against it. After MAX_OFFLINE_FAILURES
 * wrong PINs the local check is refused until the next online unlock.
 *
 * Needs WebCrypto (`crypto.subtle`), i.e. a secure context: the APK and
 * HTTPS sites. Without it offline unlock is simply unavailable.
 */

const STORE_KEY = "vansale.pinVerifier";
const ITERATIONS = 150_000;
const MAX_OFFLINE_FAILURES = 5;

interface Verifier {
  user: string;
  salt: string; // base64
  hash: string; // base64
  failures: number;
}

const b64 = (bytes: ArrayBuffer | Uint8Array) =>
  btoa(String.fromCharCode(...new Uint8Array(bytes)));
const unb64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

function available(): boolean {
  return typeof crypto !== "undefined" && Boolean(crypto.subtle);
}

async function derive(pin: string, salt: Uint8Array): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(pin), "PBKDF2", false, [
    "deriveBits",
  ]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: salt as BufferSource, iterations: ITERATIONS },
    key,
    256,
  );
  return b64(bits);
}

function load(): Verifier | null {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY) || "null") as Verifier | null;
  } catch {
    return null;
  }
}

function save(v: Verifier | null): void {
  try {
    if (v) localStorage.setItem(STORE_KEY, JSON.stringify(v));
    else localStorage.removeItem(STORE_KEY);
  } catch {
    /* storage blocked — offline unlock just stays unavailable */
  }
}

/** Remember a PIN the server just accepted (or set) for `user`. */
export async function rememberPin(user: string, pin: string): Promise<void> {
  if (!available() || !user) return;
  const salt = crypto.getRandomValues(new Uint8Array(16));
  save({ user, salt: b64(salt), hash: await derive(pin, salt), failures: 0 });
}

/** Whether this device can unlock `user` offline. */
export function canUnlockOffline(user: string): boolean {
  const v = load();
  return available() && Boolean(v && v.user === user && v.failures < MAX_OFFLINE_FAILURES);
}

/**
 * Check a PIN offline. Returns true on a match; counts failures and stops
 * accepting after MAX_OFFLINE_FAILURES until the next online unlock.
 */
export async function verifyPinOffline(user: string, pin: string): Promise<boolean> {
  const v = load();
  if (!available() || !v || v.user !== user || v.failures >= MAX_OFFLINE_FAILURES) return false;
  const ok = (await derive(pin, unb64(v.salt))) === v.hash;
  save({ ...v, failures: ok ? 0 : v.failures + 1 });
  return ok;
}

/** Forget the stored PIN hash (logout, PIN reset). */
export function forgetPin(): void {
  save(null);
}
