/**
 * Attaching a file from the action sheet. Approvals need a connection and are
 * never queued, so unlike the van photos this does not go through IndexedDB:
 * the picked file is read, shrunk if it is a photo, turned into base64 and sent
 * to `attach` when the approver confirms.
 */
import { arrayBufferToBase64 } from "@/offline/_base64";

/** Photos are shrunk to this longest edge (as the van photos are). */
const MAX_EDGE = 1280;
const JPEG_QUALITY = 0.82;

/** The largest file sent, after any photo has been shrunk. */
export const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;

const DOCUMENT_TYPES = [
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "text/plain",
  "text/csv",
];

/** The `accept` list of the file picker. */
export const FILE_ACCEPT = ["image/*", ...DOCUMENT_TYPES].join(",");

export type AttachmentProblem = "type" | "empty" | "tooLarge";

/** Why `file` cannot be attached, or null when it can. */
export function checkAttachment(file: { size: number; type: string }): AttachmentProblem | null {
  if (!(file.size > 0)) return "empty";
  const type = (file.type || "").toLowerCase();
  if (!type.startsWith("image/") && !DOCUMENT_TYPES.includes(type)) return "type";
  // Photos are shrunk before they are sent, so only the others are held to the cap here.
  if (!type.startsWith("image/") && file.size > MAX_ATTACHMENT_BYTES) return "tooLarge";
  return null;
}

const EXTENSION_OF: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
  "image/heic": "heic",
  "application/pdf": "pdf",
  "text/plain": "txt",
  "text/csv": "csv",
};

/**
 * A file name safe to send: no folders, no control characters, and an
 * extension. A camera may give "image.jpg" or nothing at all.
 */
export function attachmentName(file: { name: string; type: string }, now = Date.now()): string {
  const base = (file.name || "").split(/[\\/]/).pop() ?? "";
  // eslint-disable-next-line no-control-regex
  const clean = base.replace(/[\u0000-\u001f]/g, "").trim();
  if (clean && /\.[A-Za-z0-9]{1,5}$/.test(clean)) return clean;
  const extension = EXTENSION_OF[(file.type || "").toLowerCase()] ?? "bin";
  return `${clean || `attachment-${now}`}.${extension}`;
}

/** `name` with its extension replaced by `extension` ("scan.png" gives "scan.jpg"). */
export function withExtension(name: string, extension: string): string {
  const stem = name.replace(/\.[A-Za-z0-9]{1,5}$/, "");
  return `${stem || "attachment"}.${extension}`;
}

/** A photo shrunk to the longest edge, as JPEG; the file itself when the browser cannot. */
async function shrink(file: File): Promise<Blob> {
  if (typeof createImageBitmap !== "function") return file;
  try {
    const bitmap = await createImageBitmap(file);
    const ratio = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    // Small enough already, and already a JPEG: nothing to gain.
    if (ratio >= 1 && file.type === "image/jpeg") return file;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * ratio);
    canvas.height = Math.round(bitmap.height * ratio);
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return await new Promise<Blob>((resolve) => {
      canvas.toBlob((blob) => resolve(blob ?? file), "image/jpeg", JPEG_QUALITY);
    });
  } catch {
    return file;
  }
}

export interface AttachmentPayload {
  filename: string;
  /** Base64 with no data-URL prefix, as `attach` takes it. */
  base64: string;
}

/**
 * Read `file` into what `attach` takes, under `name` (the one already shown to
 * the approver). Throws an Error saying "tooLarge" when it is over the cap.
 */
export async function readAttachment(file: File, name = attachmentName(file)): Promise<AttachmentPayload> {
  let filename = name;
  let blob: Blob = file;
  if ((file.type || "").startsWith("image/")) {
    blob = await shrink(file);
    if (blob !== file && blob.type === "image/jpeg") filename = withExtension(filename, "jpg");
  }
  if (blob.size > MAX_ATTACHMENT_BYTES) throw new Error("tooLarge");
  return { filename, base64: arrayBufferToBase64(await blob.arrayBuffer()) };
}

/** "1.4 MB", "320 KB": the size shown beside a picked file. */
export function sizeLabel(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
