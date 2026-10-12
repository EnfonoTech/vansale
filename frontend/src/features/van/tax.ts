/**
 * Invoice tax arithmetic.
 *
 * Extracted from InvoiceFormView deliberately: this is the only code in the app
 * that decides what a customer is charged, and it was previously a hardcoded
 * `TAX_RATE = 0.15` buried in a computed with no test.
 *
 * The inclusive branch is the dangerous one. Under a template with
 * `included_in_print_rate`, the price list rate the driver sees and types
 * ALREADY contains the tax. Adding tax on top of it overcharges by the full
 * tax amount on every line — the kind of bug that is only noticed by a
 * customer with a calculator.
 */

export interface TaxTotals {
  /** Line subtotal after the invoice-level discount. */
  afterDiscount: number;
  /** Tax portion. Backed out of the total when inclusive, added when not. */
  tax: number;
  /** What the customer pays. */
  grand: number;
  /** Taxable base — what ERPNext stores as `net_total`. */
  netOfTax: number;
}

export interface TaxInput {
  /** Sum of line amounts before the invoice-level discount. */
  net: number;
  /** Invoice-level additional discount. */
  discount?: number | null;
  /** Headline rate as a PERCENTAGE (15 , not 0.15). 0 = zero-rated/exempt. */
  ratePercent: number;
  /** True when the rate is `included_in_print_rate` on the tax template. */
  inclusive: boolean;
  /**
   * ERPNext additional discount (`apply_discount_on`):
   *   "Net Total"   — off the amount before tax; tax is charged on what is left.
   *   "Grand Total" — the customer pays exactly `discount` less; ERPNext splits
   *                   it back into net and tax.
   * Omitted: the discount comes off the line total (older behaviour).
   */
  applyOn?: "Grand Total" | "Net Total" | null;
}

export function computeTaxTotals({
  net,
  discount,
  ratePercent,
  inclusive,
  applyOn,
}: TaxInput): TaxTotals {
  const r = (Number(ratePercent) || 0) / 100;
  const d = Number(discount) || 0;
  const lines = Number(net) || 0;

  if (applyOn === "Net Total") {
    // Taxable base = line amounts net of tax, less the discount.
    const base = (inclusive ? lines / (1 + r) : lines) - d;
    const tax = base * r;
    return { afterDiscount: base, tax, grand: base + tax, netOfTax: base };
  }
  if (applyOn === "Grand Total") {
    // Grand total before discount, less the discount; tax backed out of it.
    const grand = (inclusive ? lines : lines * (1 + r)) - d;
    const tax = r ? grand * (r / (1 + r)) : 0;
    return { afterDiscount: grand, tax, grand, netOfTax: grand - tax };
  }

  const afterDiscount = lines - d;

  if (!r) {
    // Zero-rated or exempt: no tax line at all. Not "15% of nothing".
    return { afterDiscount, tax: 0, grand: afterDiscount, netOfTax: afterDiscount };
  }

  if (inclusive) {
    const tax = afterDiscount * (r / (1 + r));
    return { afterDiscount, tax, grand: afterDiscount, netOfTax: afterDiscount - tax };
  }

  const tax = afterDiscount * r;
  return { afterDiscount, tax, grand: afterDiscount + tax, netOfTax: afterDiscount };
}
