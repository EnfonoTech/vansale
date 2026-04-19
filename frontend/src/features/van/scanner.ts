/**
 * Barcode scanner wrapper.
 *
 * Native (Android): uses `@capacitor-mlkit/barcode-scanning` lazily —
 * the plugin must also be added under `android-capacitor/package.json`
 * and `npx cap sync android` run, per `frappe-vue-pwa` §3.9.
 *
 * Web: falls back to a promise that resolves with `null` — caller
 * should present a manual-entry dialog.
 */
import { isNative } from "@/app/platform";

export interface ScanResult {
  value: string;
  format?: string;
}

export async function scanBarcode(): Promise<ScanResult | null> {
  if (!isNative()) return null;
  try {
    // @ts-ignore — optional peer dep; only present on native bundles.
    const mod = await import("@capacitor-mlkit/barcode-scanning");
    const { barcodes } = await mod.BarcodeScanner.scan();
    const first = Array.isArray(barcodes) && barcodes.length > 0 ? barcodes[0] : null;
    if (!first) return null;
    return { value: String(first.rawValue ?? first.displayValue ?? ""), format: first.format };
  } catch {
    return null;
  }
}

export async function isScannerAvailable(): Promise<boolean> {
  if (!isNative()) return false;
  try {
    // @ts-ignore optional
    const mod = await import("@capacitor-mlkit/barcode-scanning");
    const supported = await mod.BarcodeScanner.isSupported?.();
    return Boolean(supported?.supported ?? true);
  } catch {
    return false;
  }
}
