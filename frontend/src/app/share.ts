/**
 * Share a PDF (invoice, receipt, statement) to WhatsApp, email, … through the
 * phone's share sheet.
 *
 *  - Web / installed web app: the Web Share API with the file attached
 *    (Android Chrome, iPhone / iPad Safari; needs HTTPS).
 *  - APK: Capacitor's Share plugin (`@capacitor/share` in android-capacitor)
 *    with the PDF written to the app's cache folder first. The Android WebView
 *    has no Web Share API.
 *  - Neither available (e.g. desktop Firefox): the PDF is saved instead.
 *
 * A file can't be sent to a chosen WhatsApp number; the user picks the chat.
 */
import { registerPlugin } from "@capacitor/core";
import { Directory, Filesystem } from "@capacitor/filesystem";
import { isNative } from "./platform";
import { saveBlobToDevice } from "./frappe";
import { arrayBufferToBase64 } from "@/offline/_base64";
import { fetchPrintPdfBlob } from "@/api/print";

interface SharePlugin {
  share(options: { title?: string; text?: string; files?: string[]; dialogTitle?: string }): Promise<unknown>;
}
const NativeShare = registerPlugin<SharePlugin>("Share");

/** "shared": the share sheet was used; "saved": no sharing here, the file was
 *  saved instead; "cancelled": the user closed the share sheet. */
export type ShareResult = "shared" | "saved" | "cancelled";

function isCancel(err: unknown): boolean {
  const e = err as { name?: string; message?: string } | null;
  return e?.name === "AbortError" || /cancel/i.test(e?.message ?? "");
}

export async function sharePdf(blob: Blob, fileName: string, title: string): Promise<ShareResult> {
  const safeName = fileName.replace(/[^A-Za-z0-9._-]+/g, "_") || "document.pdf";

  if (isNative()) {
    try {
      const written = await Filesystem.writeFile({
        path: `share/${safeName}`,
        data: arrayBufferToBase64(await blob.arrayBuffer()),
        directory: Directory.Cache,
        recursive: true,
      });
      await NativeShare.share({ title, files: [written.uri], dialogTitle: title });
      return "shared";
    } catch (err) {
      if (isCancel(err)) return "cancelled";
      // Plugin missing in an older APK build: save instead.
      await saveBlobToDevice(blob, safeName);
      return "saved";
    }
  }

  const file = new File([blob], safeName, { type: "application/pdf" });
  if (typeof navigator.canShare === "function" && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title });
      return "shared";
    } catch (err) {
      if (isCancel(err)) return "cancelled";
      throw err;
    }
  }
  await saveBlobToDevice(blob, safeName);
  return "saved";
}

/** Share a document's PDF (the same one the PDF button gives) — from the
 *  print screen or straight from the invoice / payment screen, so "Print
 *  directly" vans, which skip the preview, can share too. */
export async function shareDocument(doctype: string, name: string, printFormat: string): Promise<ShareResult> {
  const blob = await fetchPrintPdfBlob(doctype, name, printFormat);
  return sharePdf(blob, `${name}.pdf`, `${doctype} ${name}`);
}
