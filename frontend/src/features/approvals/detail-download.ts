/**
 * Save a private file of a document to the phone, fetched with the app's own
 * token (the same way the print PDFs are: `api/print.ts` fetches, then
 * `saveBlobToDevice` writes). Only for the phone app: on the web the session
 * cookie makes a plain link enough (see `detail-file.ts`).
 */
import { NetworkError, getCredentials, saveBlobToDevice } from "@/app/frappe";
import { absoluteUrl, apiBase } from "@/app/platform";
import { isSitePath } from "./detail-file";

const TIMEOUT_MS = 30_000;

/**
 * Fetch `url` (a path on this site) and save it under `filename`. Throws when
 * the server refuses (the message carries the HTTP status), when the call does
 * not get through (`NetworkError`), or when `url` is not a path on this site:
 * the token is never sent anywhere else.
 */
export async function downloadPrivateFile(url: string, filename: string): Promise<void> {
  if (!isSitePath(url)) throw new Error("Not a file on this site");

  const headers: Record<string, string> = {};
  const credentials = await getCredentials();
  if (credentials) headers.Authorization = `token ${credentials.apiKey}:${credentials.apiSecret}`;

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(absoluteUrl(url), {
      method: "GET",
      headers,
      credentials: apiBase() ? "omit" : "include",
      signal: controller.signal,
    });
  } catch (error) {
    if ((error as { name?: string } | null)?.name === "AbortError") {
      throw new NetworkError("The download timed out");
    }
    throw new NetworkError();
  } finally {
    window.clearTimeout(timer);
  }

  if (!response.ok) throw new Error(`Could not download the file (HTTP ${response.status})`);
  await saveBlobToDevice(await response.blob(), filename);
}
