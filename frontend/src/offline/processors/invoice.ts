import { apiCall } from "@/app/frappe";
import type { QueuedInvoice } from "../db";

/**
 * Drain processor for `invoice_queue`. The payload mirrors what
 * `vansale.api.invoice.save` accepts on the server — the `client_id`
 * is the idempotency key (same UUID the client used to queue the entry).
 * NOTE: `client_modified` is deliberately NOT sent at drain time
 * (`frappe-vue-pwa` §4.5 rule 6).
 */
export async function drainInvoice(entry: QueuedInvoice): Promise<{ refName: string }> {
  const res = await apiCall<{ name: string }>("POST", "vansale.api.invoice.save", {
    client_id: entry.clientId,
    posting_ts: entry.clientTs,
    ...entry.payload,
  });
  return { refName: res.name };
}
