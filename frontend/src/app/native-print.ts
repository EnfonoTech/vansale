/**
 * Native Android print bridge.
 *
 * The Capacitor WebView silently ignores `window.print()` from inside a
 * sandboxed iframe — on native we fetch PDF bytes ourselves and hand them
 * to the `AndroidPrint` Capacitor plugin (see
 * `android/app/src/main/java/com/enfono/vansale/demo/AndroidPrintPlugin.java`).
 * The plugin wires up Android's system {@code PrintManager} which shows
 * the native print dialog (preview, copies, orientation, Save-as-PDF, any
 * Wi-Fi/Bluetooth printer the user has configured).
 *
 * The plugin is only registered on Android — on web we fall back to
 * {@code iframe.contentWindow.print()}.
 */
import { isNative } from "./platform";

interface AndroidPrintApi {
  printPdf: (opts: { pdfBase64: string; jobName: string }) => Promise<{ dispatched: boolean }>;
}

function pluginApi(): AndroidPrintApi | undefined {
  const plugins = window.Capacitor?.Plugins;
  if (!plugins) return undefined;
  const maybe = (plugins as Record<string, unknown>).AndroidPrint;
  if (!maybe || typeof (maybe as AndroidPrintApi).printPdf !== "function") return undefined;
  return maybe as AndroidPrintApi;
}

export function hasNativePrint(): boolean {
  return isNative() && pluginApi() !== undefined;
}

/**
 * Convert a Blob to a base64 string (no data-url prefix). FileReader's
 * `readAsDataURL` is the only synchronous-ish path that works reliably
 * across all Android WebView versions; `Blob.arrayBuffer()` + btoa chokes
 * on the 16kb stack limit for larger PDFs.
 */
function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      const comma = result.indexOf(",");
      if (comma < 0) {
        reject(new Error("FileReader returned no base64 payload"));
        return;
      }
      resolve(result.slice(comma + 1));
    };
    reader.onerror = () => reject(new Error("FileReader failed"));
    reader.readAsDataURL(blob);
  });
}

/**
 * Hand a PDF blob to the native Android print dialog. No-ops on web.
 *
 * Resolves when the plugin has dispatched the doc to the system print
 * service — not when the user hits Print. That's intentional: the JS
 * side only cares that the bridge accepted the document.
 */
export async function printPdfNative(blob: Blob, jobName: string): Promise<void> {
  const api = pluginApi();
  if (!api) {
    throw new Error("AndroidPrint plugin not registered");
  }
  const pdfBase64 = await blobToBase64(blob);
  await api.printPdf({ pdfBase64, jobName });
}
