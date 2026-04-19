/**
 * Signature capture. Same pattern as photos — local storage +
 * single-shot upload via the shared file_upload endpoint.
 */
import { apiCall } from "@/app/frappe";
import { db } from "./db";
import { genUuid } from "./queue";
import { arrayBufferToBase64 } from "./_base64";

export async function storeSignature(pngBlob: Blob): Promise<string> {
  const id = genUuid();
  const d = await db();
  await d.put("signatures", { id, blob: pngBlob, createdAt: Date.now() });
  return `signature:${id}`;
}

export async function resolveSignatureToRealUrl(
  placeholder: string | null | undefined,
): Promise<string> {
  if (!placeholder) return "";
  if (!placeholder.startsWith("signature:")) return placeholder;
  const id = placeholder.slice("signature:".length);

  const d = await db();
  const rec = await d.get("signatures", id);
  if (!rec?.blob) throw new Error("Signature not found locally — please recapture");

  const buf = await rec.blob.arrayBuffer();
  const content_base64 = arrayBufferToBase64(buf);

  const res = await apiCall<{ file_url: string }>("POST", "vansale.api.file_upload.upload", {
    filename: `signature-${id}.png`,
    content_base64,
    is_private: 1,
  });

  try {
    await d.delete("signatures", id);
  } catch {
    /* best effort */
  }
  return res.file_url;
}
