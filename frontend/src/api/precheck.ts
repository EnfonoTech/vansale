/**
 * Pre-check before submit: what the server would refuse for this sale
 * (customer documents, approval, overdue credit, rates below the minimum),
 * shown in one dialog while the salesman is still with the customer.
 *
 * Online only. Offline, or if the check itself fails, the sale goes on: the
 * submit runs every rule anyway, so skipping the pre-check never bypasses one.
 */
import { apiCall } from "./client";
import { isOnline } from "@/app/online";
import { useConfirmStore } from "@/stores/confirm";

export interface PrecheckLine {
  item_code: string;
  item_name?: string;
  rate: number;
  /** The rate after the invoice's additional discount, tax left out (ERPNext
   *  `net_rate`): what the minimum price is checked on. Missing = `rate`. */
  net_rate?: number;
  conversion_factor?: number;
  /** The line's own price list: its minimum applies. */
  price_list?: string | null;
}

export interface PrecheckResult {
  problems: string[];
  warnings: string[];
}

/** For the credit-limit check: the unpaid part of the sale, and whether an
 *  invoice was made from an order (the order was already checked). */
export interface PrecheckCredit {
  amount?: number;
  fromOrder?: boolean;
  /** A return (credit note): only the customer gates that also refuse a return. */
  isReturn?: boolean;
}

export function precheck(
  doctype: "Sales Invoice" | "Sales Order" | "Quotation",
  customer: string,
  paymentType: string | undefined,
  lines: PrecheckLine[],
  credit: PrecheckCredit = {},
): Promise<PrecheckResult> {
  return apiCall<PrecheckResult>("POST", "vansale.api.precheck.check", {
    doctype,
    customer,
    payment_type: paymentType,
    lines,
    amount: credit.amount ?? 0,
    from_order: credit.fromOrder ? 1 : 0,
    is_return: credit.isReturn ? 1 : 0,
  });
}

/** Run the pre-check and show what it found. Resolves true when the submit may go on. */
export async function precheckBeforeSubmit(
  doctype: "Sales Invoice" | "Sales Order" | "Quotation",
  customer: string,
  paymentType: string | undefined,
  lines: PrecheckLine[],
  credit: PrecheckCredit = {},
): Promise<boolean> {
  if (!isOnline() || !customer) return true;
  let result: PrecheckResult;
  try {
    result = await precheck(doctype, customer, paymentType, lines, credit);
  } catch {
    return true;
  }
  const confirm = useConfirmStore();
  if (result.problems.length) {
    await confirm.ask({
      title: "Can't submit yet",
      message: result.problems.map((p) => `• ${p}`).join("\n"),
      confirmText: "OK",
      cancelText: "Close",
    });
    return false;
  }
  if (result.warnings.length) {
    return confirm.ask({
      title: "Before you submit",
      message: result.warnings.map((w) => `• ${w}`).join("\n"),
      confirmText: "Continue",
    });
  }
  return true;
}
