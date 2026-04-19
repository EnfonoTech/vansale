import { apiCall } from "@/app/frappe";
import type { QueuedReturn } from "../db";

export async function drainReturn(entry: QueuedReturn): Promise<{ refName: string }> {
  const res = await apiCall<{ name: string }>("POST", "vansale.api.sales_return.save", {
    client_id: entry.clientId,
    posting_ts: entry.clientTs,
    ...entry.payload,
  });
  return { refName: res.name };
}
