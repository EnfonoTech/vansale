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

export const DEFAULT_SI_PRINT_FORMAT = "Vansale Tax Invoice";

interface PrintResponse {
  html: string | null;
  style: string | null;
}

export async function fetchPrintHtml(
  doctype: string,
  name: string,
  printFormat = DEFAULT_SI_PRINT_FORMAT,
  noLetterhead = false,
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
  return buildStandalone(res.html, res.style ?? "", apiBase());
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
): Promise<Blob> {
  const qs = new URLSearchParams({
    doctype,
    name,
    format: printFormat,
    no_letterhead: noLetterhead ? "1" : "0",
  });
  const url = `${apiBase()}/api/method/frappe.utils.print_format.download_pdf?${qs.toString()}`;
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

function buildStandalone(html: string, style: string, base: string): string {
  const absBase = base ? (base.endsWith("/") ? base : `${base}/`) : "/";
  const baseTag = `<base href="${absBase}">`;
  const { html: cleanHtml, inlineStyle } = normalisePrintHtml(html);
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
${baseTag}
<meta name="viewport" content="width=device-width, initial-scale=1">
${style ?? ""}
${inlineStyle}
<style>
  body { margin: 0; padding: 1rem; background: #f6f7fb; font-family: system-ui, -apple-system, sans-serif; }
  @media print { body { background: #fff; padding: 0; } }
</style>
</head>
<body>${cleanHtml}</body>
</html>`;
}
