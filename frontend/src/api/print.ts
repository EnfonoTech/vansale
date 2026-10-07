/**
 * Print helpers for native + web.
 *
 * We use the built-in whitelisted method
 *   `frappe.www.printview.get_html_and_style(doc, name, print_format, ...)`
 * which ships with every Frappe v15 install and returns
 *   { html: "<div class='...'>...</div>", style: "<style>...</style>" }.
 *
 * We previously tried `frappe.client.get_print` — that one is NOT
 * exposed on the trading-demo Frappe image (AttributeError). We also
 * tried the `/printview` website route; auth-token auth doesn't cross
 * into website routes on some configurations.
 *
 * The HTML fragment references relative asset URLs (fonts, logo),
 * so we wrap it in a standalone `<html>` document with an absolute
 * `<base href>` pointing at the Frappe host.
 */
import { apiCall } from "./client";
import { apiBase } from "@/app/platform";
import { getCredentials, NetworkError, saveBlobToDevice } from "@/app/frappe";
import { hasNativePrint, printPdfNative } from "@/app/native-print";
import type { Router } from "vue-router";

export const DEFAULT_SI_PRINT_FORMAT = "Vansale Tax Invoice";
export const DEFAULT_PE_PRINT_FORMAT = "Vansale Payment Receipt";

/** Print format for a doctype: the one chosen in Vansale Settings / the van
 *  (thermal or A4), else the app's own. */
export function defaultPrintFormat(
  doctype: string,
  configured?: { invoice: string; receipt: string } | null,
): string {
  if (doctype === "Payment Entry") return configured?.receipt || DEFAULT_PE_PRINT_FORMAT;
  return configured?.invoice || DEFAULT_SI_PRINT_FORMAT;
}

interface PrintResponse {
  html: string | null;
  style: string | null;
}

export async function fetchPrintHtml(
  doctype: string,
  name: string,
  printFormat = DEFAULT_SI_PRINT_FORMAT,
  noLetterhead = false,
  copies = 1,
): Promise<string> {
  const qs = new URLSearchParams({
    doc: doctype,
    name,
    print_format: printFormat,
  });
  if (noLetterhead) qs.set("no_letterhead", "1");
  const res = await apiCall<PrintResponse>(
    "GET",
    `frappe.www.printview.get_html_and_style?${qs.toString()}`,
  );
  if (!res.html) {
    throw new Error(`Print format "${printFormat}" not found`);
  }
  return buildStandalone(res.html, res.style ?? "", apiBase(), copies);
}

/**
 * Build a standalone HTML document so the iframe srcdoc can resolve
 * assets against the Frappe host. `get_html_and_style` returns only a
 * body fragment + style block; the browser's default styles would
 * break the ZATCA format without these wrappers.
 */
/**
 * Fetch the PDF blob for a print format. Callers decide what to do with it:
 *  - `downloadPrintPdf` saves it to the device (Documents/ on native,
 *    browser download on web).
 *  - `printPdfNative` (in `@/app/native-print`) hands it to Android's
 *    system PrintManager for the native print dialog.
 */
export async function fetchPrintPdfBlob(
  doctype: string,
  name: string,
  printFormat = DEFAULT_SI_PRINT_FORMAT,
  noLetterhead = false,
  copies = 1,
): Promise<Blob> {
  const qs = new URLSearchParams({
    doctype,
    name,
    format: printFormat,
    no_letterhead: noLetterhead ? "1" : "0",
  });
  // More than one copy: the app's endpoint repeats the pages in one PDF.
  if (copies > 1) qs.set("copies", String(copies));
  const method = copies > 1 ? "vansale.api.printing.pdf" : "frappe.utils.print_format.download_pdf";
  const url = `${apiBase()}/api/method/${method}?${qs.toString()}`;
  const headers: Record<string, string> = { Accept: "application/pdf" };
  const creds = await getCredentials();
  if (creds) headers.Authorization = `token ${creds.apiKey}:${creds.apiSecret}`;

  const controller = new AbortController();
  const t = window.setTimeout(() => controller.abort(), 30_000);
  let res: Response;
  try {
    res = await fetch(url, {
      method: "GET",
      headers,
      credentials: apiBase() ? "omit" : "include",
      signal: controller.signal,
    });
  } catch (err) {
    if ((err as { name?: string } | null)?.name === "AbortError") {
      throw new NetworkError("PDF download timed out");
    }
    throw new NetworkError();
  } finally {
    window.clearTimeout(t);
  }

  if (!res.ok) {
    throw new Error(`Could not generate PDF (HTTP ${res.status})`);
  }

  return res.blob();
}

/**
 * Download a PDF and save it to the device. On native (APK) this is the
 * "save a copy" path — the system print dialog has its own Save-as-PDF
 * option which is what most users actually want.
 */
export async function downloadPrintPdf(
  doctype: string,
  name: string,
  printFormat = DEFAULT_SI_PRINT_FORMAT,
  noLetterhead = false,
): Promise<void> {
  const blob = await fetchPrintPdfBlob(doctype, name, printFormat, noLetterhead);
  const safeDoctype = doctype.replace(/\s+/g, "_");
  const safeName = name.replace(/[^A-Za-z0-9._-]+/g, "_");
  await saveBlobToDevice(blob, `${safeDoctype}-${safeName}.pdf`);
}

/**
 * Some print formats (e.g. Vansale Tax Invoice) are authored as full
 * `<!doctype html><html><head><style/></head><body>…</body></html>`
 * documents for stand-alone use with `wkhtmltopdf`. When Frappe's
 * `get_html_and_style` returns that verbatim and we embed it inside
 * another `<html>` wrapper, the browser renders the nested `<!doctype>`
 * + `<html>`/`<head>` as visible text at the top of the page. Strip
 * the outer wrappers so only the body + inlined `<style>` survive.
 */
function normalisePrintHtml(raw: string): { html: string; inlineStyle: string } {
  let html = raw;
  let inlineStyle = "";
  const headMatch = html.match(/<head[^>]*>([\s\S]*?)<\/head>/i);
  if (headMatch) {
    const head = headMatch[1];
    const styles = head.match(/<style[\s\S]*?<\/style>/gi);
    if (styles) inlineStyle = styles.join("\n");
  }
  // Prefer the body contents when present; otherwise just strip doctype/html/head.
  const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
  if (bodyMatch) {
    html = bodyMatch[1];
  } else {
    html = html
      .replace(/<!doctype[^>]*>/gi, "")
      .replace(/<\/?html[^>]*>/gi, "")
      .replace(/<head[\s\S]*?<\/head>/gi, "");
  }
  return { html, inlineStyle };
}

function buildStandalone(html: string, style: string, base: string, copies = 1): string {
  const absBase = base ? (base.endsWith("/") ? base : `${base}/`) : "/";
  const baseTag = `<base href="${absBase}">`;
  const { html: cleanHtml, inlineStyle } = normalisePrintHtml(html);
  // Frappe's `get_html_and_style` returns `style` as raw CSS (no surrounding
  // <style> tags). Dropping it into <head> as naked text made browsers
  // parse-error-recover by moving it into <body>, which is why the iframe
  // showed raw CSS source above the invoice. Always wrap in <style>.
  const styleTag = style ? `<style>${style}</style>` : "";
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
${baseTag}
<meta name="viewport" content="width=device-width, initial-scale=1">
${styleTag}
${inlineStyle}
<style>
  body { margin: 0; padding: 1rem; background: #f6f7fb; font-family: system-ui, -apple-system, sans-serif; }
  @media print { body { background: #fff; padding: 0; } }
</style>
</head>
<body>${Array.from({ length: Math.max(1, copies) }, () => cleanHtml).join(
    '<div style="page-break-after: always; break-after: page;"></div>',
  )}</body>
</html>`;
}

/**
 * Print a document straight away, `copies` times in one job.
 * Native: server PDF → Android print dialog (the WebView ignores print()).
 * Web: the print HTML in a hidden frame → the browser print dialog. The
 * browser renders it, like desk printing, so images and page breaks match.
 */
export async function printDocument(
  doctype: string,
  name: string,
  printFormat: string,
  copies = 1,
): Promise<void> {
  if (hasNativePrint()) {
    const blob = await fetchPrintPdfBlob(doctype, name, printFormat, false, copies);
    await printPdfNative(blob, `${doctype}-${name}`);
    return;
  }
  const html = await fetchPrintHtml(doctype, name, printFormat, false, copies);
  await printHtmlInHiddenFrame(html);
}

function printHtmlInHiddenFrame(html: string): Promise<void> {
  return new Promise((resolve) => {
    const frame = document.createElement("iframe");
    frame.setAttribute("aria-hidden", "true");
    frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden;";
    const cleanup = () => window.setTimeout(() => frame.remove(), 1000);
    frame.onload = () => {
      const win = frame.contentWindow;
      if (!win) {
        cleanup();
        resolve();
        return;
      }
      win.addEventListener("afterprint", cleanup, { once: true });
      // Let images (logo, QR) finish before the dialog snapshots the page.
      window.setTimeout(() => {
        win.focus();
        win.print();
        resolve();
      }, 300);
    };
    frame.srcdoc = html;
    document.body.appendChild(frame);
  });
}

export interface PrintBehaviour {
  direct: boolean;
  after_submit: boolean;
  copies: number;
}

/**
 * The app's Print action: print at once when "Print directly" is on,
 * otherwise open the preview screen.
 */
export async function openPrint(
  router: Router,
  doctype: string,
  name: string,
  formats: { invoice: string; receipt: string } | null,
  behaviour: PrintBehaviour | null,
): Promise<void> {
  if (behaviour?.direct) {
    await printDocument(doctype, name, defaultPrintFormat(doctype, formats), behaviour.copies || 1);
    return;
  }
  await router.push({ name: "print-view", params: { doctype, name } });
}
