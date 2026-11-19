/**
 * base64url, the encoding Web Push uses for keys: the server hands the browser
 * its public key as base64url text, and the browser's own keys go back the
 * same way. Pure, so it is tested without a browser.
 */

/**
 * The bytes of a base64url string (`-` and `_` instead of `+` and `/`, padding
 * optional). Throws on text that is not base64url, so a damaged key stops the
 * subscribe instead of reaching `pushManager.subscribe`.
 */
export function urlBase64ToUint8Array(base64Url: string): Uint8Array<ArrayBuffer> {
  const text = base64Url.trim();
  if (!/^[A-Za-z0-9_-]*={0,2}$/.test(text)) throw new Error("Not a base64url value");
  const unpadded = text.replace(/=+$/, "");
  // A single leftover character carries fewer than 8 bits: no byte can come of it.
  if (unpadded.length % 4 === 1) throw new Error("Not a base64url value");
  const base64 = (unpadded + "=".repeat((4 - (unpadded.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

/** base64url (no padding) of some bytes: what the server stores for `p256dh` and `auth`. */
export function bytesToBase64Url(input: ArrayBuffer | ArrayBufferView): string {
  const bytes =
    input instanceof ArrayBuffer ? new Uint8Array(input) : new Uint8Array(input.buffer, input.byteOffset, input.byteLength);
  let raw = "";
  for (const byte of bytes) raw += String.fromCharCode(byte);
  return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
