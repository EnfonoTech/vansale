/**
 * ESC/POS thermal receipt printer wrapper.
 *
 * Native: uses `@capacitor-community/bluetooth-le` to write raw ESC/POS
 * bytes to a paired printer (common 58mm / 80mm thermal models speak
 * the subset we generate here).
 *
 * Web: falls back to `window.print()` of a styled receipt template.
 *
 * Paired device id is persisted under `vansale.printer.deviceId` via
 * localStorage; the user selects once via `pairPrinter()` and every
 * subsequent receipt prints silently.
 */
import { isNative } from "@/app/platform";

const DEVICE_KEY = "vansale.printer.deviceId";

export interface ReceiptLine {
  left: string;
  right?: string;
  qty?: number;
  rate?: number;
  bold?: boolean;
}

export interface Receipt {
  title: string;
  company?: string;
  customer?: string;
  date: string;
  number: string;
  lines: ReceiptLine[];
  totalLabel?: string;
  total?: number;
  footer?: string;
  currency?: string;
}

function escposHeader(): Uint8Array {
  return new Uint8Array([0x1b, 0x40, 0x1b, 0x61, 0x01]); // init + centre-align
}
function escposLeft(): Uint8Array { return new Uint8Array([0x1b, 0x61, 0x00]); }
function escposBold(on: boolean): Uint8Array { return new Uint8Array([0x1b, 0x45, on ? 0x01 : 0x00]); }
function escposNl(n = 1): Uint8Array { return new Uint8Array(Array(n).fill(0x0a)); }
function escposCut(): Uint8Array { return new Uint8Array([0x1d, 0x56, 0x42, 0x00]); }

function text(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

function buildPayload(r: Receipt): Uint8Array {
  const chunks: Uint8Array[] = [];
  chunks.push(escposHeader());
  chunks.push(escposBold(true));
  if (r.company) { chunks.push(text(`${r.company}\n`)); }
  chunks.push(text(`${r.title}\n`));
  chunks.push(escposBold(false));
  chunks.push(escposLeft());
  chunks.push(text(`# ${r.number}\n${r.date}\n`));
  if (r.customer) chunks.push(text(`Customer: ${r.customer}\n`));
  chunks.push(text("--------------------------------\n"));
  for (const l of r.lines) {
    const qtyRate = l.qty !== undefined ? `  ${l.qty} x ${l.rate?.toFixed?.(2) ?? l.rate ?? ""}` : "";
    chunks.push(escposBold(Boolean(l.bold)));
    chunks.push(text(`${l.left}\n${qtyRate}${l.right ? `    ${l.right}` : ""}\n`));
    chunks.push(escposBold(false));
  }
  chunks.push(text("--------------------------------\n"));
  if (r.total !== undefined) {
    chunks.push(escposBold(true));
    chunks.push(text(`${r.totalLabel ?? "Total"}: ${r.currency ?? ""} ${r.total.toFixed(2)}\n`));
    chunks.push(escposBold(false));
  }
  if (r.footer) chunks.push(text(`\n${r.footer}\n`));
  chunks.push(escposNl(3));
  chunks.push(escposCut());

  const total = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) { out.set(c, off); off += c.length; }
  return out;
}

export function getPairedDeviceId(): string | null {
  return window.localStorage.getItem(DEVICE_KEY);
}

export function setPairedDeviceId(id: string | null): void {
  if (id) window.localStorage.setItem(DEVICE_KEY, id);
  else window.localStorage.removeItem(DEVICE_KEY);
}

export async function pairPrinter(): Promise<string | null> {
  if (!isNative()) return null;
  try {
    // @ts-ignore optional
    const mod = await import("@capacitor-community/bluetooth-le");
    await mod.BleClient.initialize();
    const device = await mod.BleClient.requestDevice({
      namePrefix: "Printer", // most thermal printers; user can re-pair manually on others
    });
    setPairedDeviceId(device.deviceId);
    return device.deviceId;
  } catch {
    return null;
  }
}

export async function printReceipt(receipt: Receipt): Promise<void> {
  const bytes = buildPayload(receipt);

  if (isNative()) {
    let deviceId = getPairedDeviceId();
    if (!deviceId) deviceId = await pairPrinter();
    if (!deviceId) return;
    try {
      // @ts-ignore optional
      const mod = await import("@capacitor-community/bluetooth-le");
      await mod.BleClient.connect(deviceId);
      // Generic SPP service UUID common to thermal printers; fall back if present.
      const services = await mod.BleClient.getServices(deviceId);
      const writable = services
        .flatMap((s: { characteristics?: Array<{ properties?: { write?: boolean }; uuid?: string }>; uuid?: string }) =>
          (s.characteristics ?? []).map((c) => ({
            service: s.uuid,
            char: c.uuid,
            writable: Boolean(c.properties?.write),
          })),
        )
        .find((x: { writable: boolean }) => x.writable);
      if (!writable || !writable.service || !writable.char) return;
      // Some BLE stacks cap at ~180 bytes/write — chunk.
      const CHUNK = 180;
      for (let i = 0; i < bytes.length; i += CHUNK) {
        const slice = bytes.slice(i, i + CHUNK);
        await mod.BleClient.write(deviceId, writable.service, writable.char, new DataView(slice.buffer));
      }
      await mod.BleClient.disconnect(deviceId);
      return;
    } catch {
      /* fall through to web print */
    }
  }

  // Web fallback — print a formatted HTML receipt.
  const w = window.open("", "_blank", "width=380,height=700");
  if (!w) return;
  w.document.write(`<!doctype html><title>${receipt.title}</title>
    <style>body { font-family: monospace; font-size: 12px; padding: 1rem; }
    h1 { font-size: 1rem; margin: 0 0 0.25rem; }
    table { width: 100%; border-collapse: collapse; }
    td { vertical-align: top; }
    .total { font-weight: bold; border-top: 1px solid #000; padding-top: 0.5rem; margin-top: 0.5rem; }
    </style>`);
  w.document.write(`<h1>${receipt.company ?? ""}</h1><div>${receipt.title}</div>`);
  w.document.write(`<div># ${receipt.number}</div><div>${receipt.date}</div>`);
  if (receipt.customer) w.document.write(`<div>Customer: ${receipt.customer}</div>`);
  w.document.write(`<hr><table>`);
  for (const l of receipt.lines) {
    w.document.write(
      `<tr><td>${l.left}${l.qty !== undefined ? ` (${l.qty} × ${l.rate ?? ""})` : ""}</td><td style="text-align:right">${l.right ?? ""}</td></tr>`,
    );
  }
  w.document.write(`</table>`);
  if (receipt.total !== undefined)
    w.document.write(`<div class="total">${receipt.totalLabel ?? "Total"}: ${receipt.currency ?? ""} ${receipt.total.toFixed(2)}</div>`);
  if (receipt.footer) w.document.write(`<p>${receipt.footer}</p>`);
  w.document.close();
  w.focus();
  w.print();
  setTimeout(() => w.close(), 500);
}
