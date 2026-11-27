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
  /** 1 = advance: nothing allocated, the amount stays as customer credit. */
  advance?: 0 | 1;
  /** 0 = keep as a draft (only where collections are submitted). */
  submit?: 0 | 1;
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

export async function listMine(
  limit = 50,
  customer?: string,
  search?: string,
): Promise<Array<Record<string, unknown>>> {
  const qs = new URLSearchParams();
  qs.set("limit", String(limit));
  if (customer) qs.set("customer", customer);
  if (search) qs.set("search", search);
  return apiCall("GET", `vansale.api.payment.list_mine?${qs.toString()}`);
}

/** `exclude`: a draft collection being edited (its own allocation stays on offer). */
export async function outstanding(customer: string, exclude?: string): Promise<Array<Record<string, unknown>>> {
  const qs = new URLSearchParams({ customer });
  if (exclude) qs.set("exclude", exclude);
  return apiCall("GET", `vansale.api.payment.outstanding?${qs.toString()}`);
}

/** Change a draft collection and keep it as a draft or submit it. */
export async function updateDraft(payload: {
  name: string;
  paid_amount: number;
  mode_of_payment: string;
  reference_no?: string;
  invoice_names?: string[];
  remarks?: string;
  advance?: 0 | 1;
  submit: 0 | 1;
}): Promise<{ name: string; paid_amount: number; status: string; docstatus: number }> {
  return apiCall("POST", "vansale.api.payment.update_draft", payload);
}

/** Submit a draft collection (where collections are submitted from the app). */
export async function submitDraft(name: string): Promise<{ name: string; status: string; docstatus: number }> {
  return apiCall("POST", "vansale.api.payment.submit_draft", { name });
}

export interface ModeOfPayment {
  name: string;
  type: string | null;
  /** Account is a Bank account → ERPNext requires a reference number. */
  needs_reference?: boolean;
}

const MOP_CACHE_KEY = "vansale.modesOfPayment";

/** Modes with an account for the user's company; last list kept for offline use. */
export async function modesOfPayment(): Promise<ModeOfPayment[]> {
  const fromCache = (): ModeOfPayment[] => {
    try {
      return JSON.parse(localStorage.getItem(MOP_CACHE_KEY) || "[]") as ModeOfPayment[];
    } catch {
      return [];
    }
  };
  if (!isOnline()) return fromCache();
  try {
    const rows = await apiCall<ModeOfPayment[]>("GET", "vansale.api.payment.modes_of_payment");
    try {
      localStorage.setItem(MOP_CACHE_KEY, JSON.stringify(rows));
    } catch {
      /* storage full / blocked — the live list still works */
    }
    return rows;
  } catch (err) {
    if (err instanceof NetworkError) return fromCache();
    throw err;
  }
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
  /** The customer's title (Badria: English name). */
  party_title?: string | null;
  payment_type: string;
  paid_amount: number;
  received_amount: number;
  mode_of_payment: string | null;
  reference_no: string | null;
  reference_date: string | null;
  posting_date: string | null;
  remarks: string | null;
  /** 1 = the remarks were typed (not ERPNext's own "Amount … received from …"). */
  custom_remarks?: number;
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
      // No posting_ts: the server's clock dates an online payment; a queued
      // one sends the time it was taken.
      const res = await apiCall<SavedPayment>("POST", "vansale.api.payment.save", {
        client_id: clientId,
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
