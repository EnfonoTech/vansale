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
function buildStandalone(html: string, style: string, base: string): string {
  const absBase = base ? (base.endsWith("/") ? base : `${base}/`) : "/";
  const baseTag = `<base href="${absBase}">`;
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
${baseTag}
<meta name="viewport" content="width=device-width, initial-scale=1">
${style ?? ""}
<style>
  body { margin: 0; padding: 1rem; background: #f6f7fb; font-family: system-ui, -apple-system, sans-serif; }
  @media print { body { background: #fff; padding: 0; } }
</style>
</head>
<body>${html}</body>
</html>`;
}
