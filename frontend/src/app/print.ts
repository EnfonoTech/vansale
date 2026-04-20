/**
 * Print-format helpers.
 *
 * KSA compliance: ZATCA Phase 2 is mandatory for all B2B / B2G and
 * large-tax-payer invoicing. We ship a Vansale-branded thermal-receipt
 * format (`Vansale Tax Invoice`) which:
 *   - renders bilingual Arabic/English on 110mm paper
 *   - pulls company logo, C.F. No, VAT ID from the Company doc
 *   - switches title between DRAFT INVOICE / TAX INVOICE / CREDIT NOTE
 *   - shows Cash vs Card vs Balance from doc.payments + Payment Entries
 *   - embeds the ZATCA QR from `ksa_einv_qr` (Phase 2 attach-image)
 *
 * The format doc itself is created/updated by the patch
 * `vansale.patches.v1_0.install_vansale_tax_invoice` on `bench migrate`.
 *
 * Centralise the name here so we can swap per-customer later
 * without hunting callsites.
 */

export const DEFAULT_SI_PRINT_FORMAT = "Vansale Tax Invoice";

export interface PrintOptions {
  triggerPrint?: boolean;
  noLetterhead?: boolean;
  format?: string;
}

export function salesInvoicePrintUrl(name: string, opts: PrintOptions = {}): string {
  const qs = new URLSearchParams();
  qs.set("doctype", "Sales Invoice");
  qs.set("name", name);
  qs.set("format", opts.format ?? DEFAULT_SI_PRINT_FORMAT);
  qs.set("no_letterhead", opts.noLetterhead ? "1" : "0");
  if (opts.triggerPrint) qs.set("trigger_print", "1");
  return `/printview?${qs.toString()}`;
}

export function openSalesInvoicePrint(name: string, opts: PrintOptions = {}): void {
  window.open(salesInvoicePrintUrl(name, opts), "_blank", "noopener,noreferrer");
}
