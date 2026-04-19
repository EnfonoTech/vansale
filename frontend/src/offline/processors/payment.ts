import { apiCall } from "@/app/frappe";
import type { QueuedPayment } from "../db";

export async function drainPayment(entry: QueuedPayment): Promise<{ refName: string }> {
  const res = await apiCall<{ name: string }>("POST", "vansale.api.payment.save", {
    client_id: entry.clientId,
    posting_ts: entry.clientTs,
    ...entry.payload,
  });
  return { refName: res.name };
}
