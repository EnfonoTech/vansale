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
  invoice_name?: string;            // legacy single-invoice
  invoice_names?: string[];         // multi-pick (Phase E)
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

export interface ModeOfPayment { name: string; type: string | null }

export async function modesOfPayment(): Promise<ModeOfPayment[]> {
  return apiCall<ModeOfPayment[]>("GET", "vansale.api.payment.modes_of_payment");
}

export interface PaymentReference {
  reference_doctype: string;
  reference_name: string;
  allocated_amount: number;
  total_amount: number;
  outstanding_amount: number;
}

export interface PaymentDetail {
  name: string;
  party: string;
  party_name: string | null;
  payment_type: string;
  paid_amount: number;
  received_amount: number;
  mode_of_payment: string | null;
  reference_no: string | null;
  reference_date: string | null;
  posting_date: string | null;
  remarks: string | null;
  status: string;
  docstatus: number;
  references: PaymentReference[];
  modified: string | null;
}

export async function detail(name: string): Promise<PaymentDetail> {
  return apiCall<PaymentDetail>(
    "GET",
    `vansale.api.payment.detail?name=${encodeURIComponent(name)}`,
  );
}

/**
 * Delete a draft Payment Entry. Backend enforces owner check and
 * refuses submitted entries — cancellation of a posted payment needs
 * the Desk workflow because it reverses GL entries.
 */
export async function deletePayment(name: string): Promise<{ deleted: boolean; name: string }> {
  return apiCall<{ deleted: boolean; name: string }>(
    "POST",
    "vansale.api.payment.delete_payment",
    { name },
  );
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
