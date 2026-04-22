import { apiCall } from "@/app/frappe";
import type { QueuedStockEntry } from "../db";

/**
 * Drain processor for `stock_entry_queue`. Calls
 * `vansale.api.van_stock.transfer_in` with `client_id` + `posting_ts`
 * so the server can dedup via Vansale Outbox (event_type="stock_adjust")
 * if the request is replayed after a network retry.
 *
 * Note: stock_adjust is also used by any future on-device stock
 * corrections (damage, spoilage). Both share the same outbox
 * namespace — each row still carries a unique `client_id`, so there's
 * no collision risk.
 */
export async function drainStockEntry(
  entry: QueuedStockEntry,
): Promise<{ refName: string }> {
  const res = await apiCall<{ name: string }>("POST", "vansale.api.van_stock.transfer_in", {
    client_id: entry.clientId,
    posting_ts: entry.clientTs,
    ...entry.payload,
  });
  return { refName: res.name };
}
