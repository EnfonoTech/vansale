/**
 * Steel Force (sf_trading) extras. On other sites the server answers
 * "nothing here" (empty lists / can_request false), so callers just hide.
 */
import { apiCall } from "./client";

export interface DriverRow {
  name: string;
  full_name: string;
  /** Cash from earlier sales the driver still has to hand in. */
  holding?: number;
  /** The driver's cash limit (0 = none), and their limit at this branch. */
  cash_limit?: number;
  branch_holding?: number;
  branch_limit?: number;
  /** Why sf_trading refuses this driver a new cash sale, or null. */
  blocked?: string | null;
}

/** Delivery persons serving the salesman's branch, with the cash they hold. */
export function drivers(): Promise<DriverRow[]> {
  return apiCall<DriverRow[]>("GET", "vansale.steelforce.api.drivers");
}

export interface CancellationOptions {
  can_request: boolean;
  reasons: string[];
}

export function cancellationOptions(doctype: "Quotation" | "Sales Order", name: string): Promise<CancellationOptions> {
  const qs = new URLSearchParams({ doctype, name });
  return apiCall<CancellationOptions>("GET", `vansale.steelforce.api.cancellation_options?${qs.toString()}`);
}

/** Ask the office to cancel a submitted quotation / order (their approval decides). */
export function requestCancellation(
  doctype: "Quotation" | "Sales Order",
  name: string,
  reason: string,
  details?: string,
): Promise<{ workflow_state?: string }> {
  return apiCall("POST", "vansale.steelforce.api.request_cancellation", { doctype, name, reason, details });
}

/** The salesman's own uncollected cash (Steel Force), with his limits; {} elsewhere. */
export interface MyCash {
  holding?: number;
  cash_limit?: number;
  payment_days?: number;
  branch?: string | null;
  branch_holding?: number;
  branch_limit?: number;
  overdue?: { name: string; posting_date: string; outstanding_amount: number } | null;
}
export function myCash(): Promise<MyCash> {
  return apiCall<MyCash>("GET", "vansale.steelforce.api.my_cash");
}

/** Steel Force: taking money on a submitted order (sf_trading's own state). */
export interface OrderPaymentState {
  enabled: boolean;
  balance?: number;
  advance_paid?: number;
  modes?: string[];
  cheque_modes?: string[];
  /** Loyalty limit (0 = none); loyalty only when it closes the order. */
  max_write_off?: number;
}
export function orderPaymentState(salesOrder: string): Promise<OrderPaymentState> {
  return apiCall<OrderPaymentState>("GET", `vansale.steelforce.api.order_payment_state?sales_order=${encodeURIComponent(salesOrder)}`);
}
export function collectOrder(payload: {
  sales_order: string;
  mode_of_payment: string;
  amount: number;
  cheque_no?: string;
  cheque_date?: string;
  write_off_amount?: number;
}): Promise<{ payment_entries: string[] }> {
  return apiCall("POST", "vansale.steelforce.api.collect_order", payload);
}
