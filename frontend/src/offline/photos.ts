/**
 * Photo capture + upload. Implements the ONE-uploader rule
 * (`frappe-vue-pwa` §5 commandment 1): capturing a photo stores the
 * blob locally under a `photo:<uuid>` placeholder. The ONLY path that
 * actually uploads is `resolveToRealUrl`, invoked either by the online
 * save path or by the drain engine — never both for the same blob.
 *
 * Background uploads on capture caused races in prior apps: winner
 * deletes the blob, loser throws "photo not found" and the queue
 * entry is stuck.
 */
import { apiCall } from "@/app/frappe";
import { db } from "./db";
import { genUuid } from "./queue";
import { arrayBufferToBase64 } from "./_base64";

const MAX_DIM = 1280; // longest edge; keeps uploads quick on 3G
const JPEG_Q = 0.82;

/** Compress to max 1280px longest edge; never upscale. */
async function compressImage(file: Blob): Promise<Blob> {
  if (typeof createImageBitmap !== "function") return file;
  const bitmap = await createImageBitmap(file);
  const ratio = Math.min(1, MAX_DIM / Math.max(bitmap.width, bitmap.height));
  if (ratio >= 1 && file.type === "image/jpeg") return file;
  const w = Math.round(bitmap.width * ratio);
  const h = Math.round(bitmap.height * ratio);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return file;
  ctx.drawImage(bitmap, 0, 0, w, h);
  return await new Promise<Blob>((resolve) => {
    canvas.toBlob((b) => resolve(b ?? file), "image/jpeg", JPEG_Q);
  });
}

async function makeThumbnail(file: Blob, size = 160): Promise<string | undefined> {
  if (typeof createImageBitmap !== "function") return undefined;
  try {
    const bitmap = await createImageBitmap(file);
    const ratio = size / Math.max(bitmap.width, bitmap.height);
    const w = Math.round(bitmap.width * ratio);
    const h = Math.round(bitmap.height * ratio);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    canvas.getContext("2d")?.drawImage(bitmap, 0, 0, w, h);
    return canvas.toDataURL("image/jpeg", 0.7);
  } catch {
    return undefined;
  }
}

/**
 * Capture a photo locally. Returns a `photo:<uuid>` placeholder which
 * the caller stores on its form model / queue payload.
 *
 * IMPORTANT: we deliberately DO NOT kick off an upload here. The only
 * paths that upload are `resolveToRealUrl` (online save) and the drain
 * engine (offline save → come back online). Two uploaders racing each
 * other break everything — see commandment 1.
 */
export async function capturePhoto(
  file: Blob,
  filename = `photo-${Date.now()}.jpg`,
): Promise<{ url: string; thumb?: string }> {
  const compressed = await compressImage(file);
  const thumb = await makeThumbnail(file);
  const id = genUuid();
  const d = await db();
  await d.put("photos", {
    id,
    blob: compressed,
    filename,
    thumb,
    createdAt: Date.now(),
  });
  return { url: `photo:${id}`, thumb };
}

/** Read a `photo:<uuid>` thumbnail back for preview rendering. */
export async function resolvePreview(placeholder: string): Promise<string | undefined> {
  if (!placeholder?.startsWith("photo:")) return undefined;
  const id = placeholder.slice("photo:".length);
  const d = await db();
  const rec = await d.get("photos", id);
  return rec?.thumb;
}

/**
 * Upload a local `photo:<uuid>` placeholder to the server, return the
 * real `/files/...` URL, and delete the IDB blob.
 *
 * Side effect: rewrites any queue entries that reference the same
 * placeholder, so the drain engine uploads each blob exactly once.
 */
export async function resolveToRealUrl(placeholder: string | null | undefined): Promise<string> {
  if (!placeholder) return "";
  if (!placeholder.startsWith("photo:")) return placeholder;
  const id = placeholder.slice("photo:".length);

  const d = await db();
  const rec = await d.get("photos", id);
  if (!rec?.blob) throw new Error("Photo not found locally — please retake");

  const buf = await rec.blob.arrayBuffer();
  const content_base64 = arrayBufferToBase64(buf);

  const res = await apiCall<{ file_url: string }>("POST", "vansale.api.file_upload.upload", {
    filename: rec.filename,
    content_base64,
    is_private: 0,
  });

  const realUrl = res.file_url;

  // Rewrite every queue entry that pointed at this placeholder so the
  // drain engine doesn't try to re-upload a deleted blob.
  for (const store of ["invoice_queue", "payment_queue", "return_queue", "visit_queue"] as const) {
    const all = await (d.getAll as (s: typeof store) => Promise<Array<Record<string, unknown>>>)(
      store,
    );
    for (const entry of all) {
      let changed = false;
      const payload = (entry.payload as Record<string, unknown>) ?? {};
      for (const key of Object.keys(payload)) {
        if (payload[key] === placeholder) {
          payload[key] = realUrl;
          changed = true;
        }
        if (Array.isArray(payload[key])) {
          const arr = payload[key] as unknown[];
          for (let i = 0; i < arr.length; i++) {
            const item = arr[i];
            if (item && typeof item === "object") {
              const obj = item as Record<string, unknown>;
              for (const ik of Object.keys(obj)) {
                if (obj[ik] === placeholder) {
                  obj[ik] = realUrl;
                  changed = true;
                }
              }
            }
          }
        }
      }
      if (changed) {
        entry.payload = payload;
        await (d.put as (s: typeof store, v: unknown) => Promise<IDBValidKey>)(store, entry);
      }
    }
  }

  try {
    await d.delete("photos", id);
  } catch {
    /* blob deletion is best-effort */
  }
  return realUrl;
}
