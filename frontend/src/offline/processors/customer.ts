import { apiCall } from "@/app/frappe";
import type { QueuedCustomer } from "../db";

/**
 * Drain processor for `customer_queue`. Calls `vansale.api.customer.create`
 * with the queued payload + `client_id` so the server can dedup via
 * Vansale Outbox (matching the invoice / payment / return pattern).
 *
 * Returns the created Customer's `name` — callers that queued an invoice
 * against `customer_name` will need a follow-up resolver to swap the
 * human name for the canonical `CUST-NNNN`, but that wiring is out of
 * scope here.
 */
export async function drainCustomer(entry: QueuedCustomer): Promise<{ refName: string }> {
  const res = await apiCall<{ name: string }>("POST", "vansale.api.customer.create", {
    client_id: entry.clientId,
    posting_ts: entry.clientTs,
    ...entry.payload,
  });
  return { refName: res.name };
}
