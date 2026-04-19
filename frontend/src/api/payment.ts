import { apiCall, ApiError, NetworkError } from "./client";
import { addEntry, genUuid } from "@/offline/queue";
import { isOnline } from "@/app/online";
import { useSyncStore } from "@/stores/sync";
import type { QueuedPayment } from "@/offline/db";

export interface PaymentPayload {
  customer: string;
  paid_amount: number;
  mode_of_payment?: "Cash" | "Bank" | string;
  reference_no?: string;
  reference_date?: string;
  invoice_name?: string;
  remarks?: string;
}

export interface SavedPayment {
  name: string;
  paid_amount: number;
  status: string;
  modified?: string;
  idempotent_replay?: boolean;
  queued?: boolean;
  clientId: string;
}

export async function listMine(limit = 50, customer?: string): Promise<Array<Record<string, unknown>>> {
  const qs = new URLSearchParams();
  qs.set("limit", String(limit));
  if (customer) qs.set("customer", customer);
  return apiCall("GET", `vansale.api.payment.list_mine?${qs.toString()}`);
}

export async function outstanding(customer: string): Promise<Array<Record<string, unknown>>> {
  return apiCall("GET", `vansale.api.payment.outstanding?customer=${encodeURIComponent(customer)}`);
}

export async function save(payload: PaymentPayload): Promise<SavedPayment> {
  const clientId = genUuid();
  const clientTs = new Date().toISOString();

  if (isOnline()) {
    try {
      const res = await apiCall<SavedPayment>("POST", "vansale.api.payment.save", {
        client_id: clientId,
        posting_ts: clientTs,
        ...payload,
      });
      const sync = useSyncStore();
      void sync.refresh();
      return { ...res, clientId };
    } catch (err) {
      if (err instanceof ApiError) throw err;
      if (!(err instanceof NetworkError)) throw err;
    }
  }

  const queued: QueuedPayment = {
    clientId,
    clientTs,
    invoiceName: payload.invoice_name,
    customerName: payload.customer,
    payload: { ...payload } as Record<string, unknown>,
    createdAt: Date.now(),
    attempts: 0,
    status: "pending",
  };
  await addEntry<QueuedPayment>("payment_queue", queued);
  const sync = useSyncStore();
  void sync.refresh();
  void sync.requestDrain();
  return { name: `QUEUED:${clientId.slice(0, 8)}`, paid_amount: 0, status: "Queued", queued: true, clientId };
}
