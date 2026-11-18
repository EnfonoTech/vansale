/**
 * How a file attached to a document is opened from the detail screen.
 *
 * On the web the browser's session cookie opens any file, private or not, so a
 * plain link does. The phone app signs in with a token header only; a link in
 * the WebView cannot send it, so a private file (`/private/files/...`) would
 * bounce to a login page. There the file is fetched with the app's token and
 * saved to the device instead. Pure: no Vue, no network.
 */

export type FileAccess =
  /** A plain link opens it. */
  | "link"
  /** Fetch it with the app's token and save it to the device. */
  | "download"
  /** It cannot be opened from here: say where to open it. */
  | "explain";

/**
 * A path on this site (`/private/files/x.pdf`). Anything else, a full URL on
 * another host or a protocol-relative `//host/...`, must never be sent the
 * app's token.
 */
export function isSitePath(url: string | null | undefined): boolean {
  const value = url ?? "";
  return value.startsWith("/") && !value.startsWith("//") && !value.includes("\\");
}

/** Whether the server keeps the file private (the flag, or the folder it lives in). */
export function isPrivateFile(file: { url: string | null; is_private: boolean }): boolean {
  return Boolean(file.is_private) || (file.url ?? "").startsWith("/private/");
}

/** How to open `file`, on the phone app (`native`) or the web. */
export function fileAccess(file: { url: string | null; is_private: boolean }, native: boolean): FileAccess {
  if (!file.url) return "explain";
  if (!native || !isPrivateFile(file)) return "link";
  return isSitePath(file.url) ? "download" : "explain";
}

/**
 * The name to show and to save under. The server's `name` is the File record's
 * id (a hash), so the file's own name is taken from the end of its URL.
 */
export function fileLabel(file: { name: string; url: string | null }): string {
  const path = (file.url ?? "").split(/[?#]/)[0];
  const last = path.split("/").pop() ?? "";
  let decoded = last;
  try {
    decoded = decodeURIComponent(last);
  } catch {
    /* a stray "%": keep the text as it is */
  }
  return decoded.trim() || file.name;
}
