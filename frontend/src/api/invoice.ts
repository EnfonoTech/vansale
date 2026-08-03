import { apiCall, ApiError, NetworkError } from "./client";
import { addEntry } from "@/offline/queue";
import { genUuid } from "@/offline/queue";
import { isOnline } from "@/app/online";
import { useSyncStore } from "@/stores/sync";
import type { QueuedInvoice } from "@/offline/db";

export interface InvoiceItem {
  item_code: string;
  item_name?: string;
  qty: number;
  rate: number;
  price_list_rate?: number;
  discount_percentage?: number;
  discount_amount?: number;
  uom?: string;
  conversion_factor?: number;
  warehouse?: string;
}

export interface InvoicePayload {
  customer: string;
  items: InvoiceItem[];
  warehouse?: string;
  remarks?: string;
  update_stock?: 0 | 1;
  submit?: 0 | 1;
  payment_type?: "cash" | "credit";
  mode_of_payment?: string;
  discount_amount?: number;
  apply_discount_on?: "Grand Total" | "Net Total";
}

export interface SavedInvoice {
  name: string;
  grand_total: number;
  status: string;
  modified?: string;
  idempotent_replay?: boolean;
  queued?: boolean;
  clientId: string;
}

/** List sales invoices for the current user. */
export async function listMine(limit = 50, customer?: string): Promise<Array<Record<string, unknown>>> {
  const qs = new URLSearchParams();
  qs.set("limit", String(limit));
  if (customer) qs.set("customer", customer);
  return apiCall("GET", `vansale.api.invoice.list_mine?${qs.toString()}`);
}

export interface ReturnRow {
  name: string;
  customer: string;
  customer_name: string;
  grand_total: number;
  status: string;
  posting_date: string | null;
  posting_time: string | null;
  is_return: number;
  return_against: string | null;
  modified: string | null;
}

/** List sales returns (credit notes) — always includes `return_against`. */
export async function listReturns(limit = 50, customer?: string): Promise<ReturnRow[]> {
  const qs = new URLSearchParams();
  qs.set("limit", String(limit));
  qs.set("is_return", "1");
  if (customer) qs.set("customer", customer);
  return apiCall<ReturnRow[]>("GET", `vansale.api.invoice.list_mine?${qs.toString()}`);
}

export interface InvoiceDetailTax {
  description: string;
  rate: number;
  tax_amount: number;
  total: number;
}

export interface InvoiceDetailItem {
  item_code: string;
  item_name: string;
  qty: number;
  rate: number;
  price_list_rate: number;
  discount_percentage: number;
  discount_amount: number;
  amount: number;
  uom: string | null;
  warehouse: string | null;
}

export interface InvoiceDetailSalesPerson {
  sales_person: string;
  allocated_percentage: number;
}

export interface InvoiceDetail {
  name: string;
  customer: string;
  customer_name: string;
  company: string;
  currency: string;
  posting_date: string | null;
  posting_time: string | null;
  due_date: string | null;
  is_return: number;
  grand_total: number;
  net_total: number;
  total_taxes_and_charges: number;
  discount_amount: number;
  outstanding_amount: number;
  paid_amount: number;
  status: string;
  docstatus: number;
  remarks: string | null;
  items: InvoiceDetailItem[];
  taxes: InvoiceDetailTax[];
  sales_persons: InvoiceDetailSalesPerson[];
  modified: string | null;
}

export async function detail(name: string): Promise<InvoiceDetail> {
  return apiCall<InvoiceDetail>(
    "GET",
    `vansale.api.invoice.detail?name=${encodeURIComponent(name)}`,
  );
}

/**
 * Submit an existing draft Sales Invoice.
 *
 * Must NOT use `frappe.client.submit`. That endpoint rebuilds the doc from
 * whatever dict the client posts, so a `{doctype, name}` payload produced
 * "Document has been modified after you have opened it" on every submit —
 * and would have blanked items + totals if the check had passed. The
 * server-side `submit_draft` loads the stored doc by name instead.
 */
export async function submitDraft(name: string, modeOfPayment?: string): Promise<void> {
  await apiCall("POST", "vansale.api.invoice.submit_draft", {
    name,
    ...(modeOfPayment ? { mode_of_payment: modeOfPayment } : {}),
  });
  const sync = useSyncStore();
  void sync.refresh();
}

/**
 * Delete a draft Sales Invoice. Only allowed when `docstatus === 0`
 * (Frappe enforces this server-side). Uses `frappe.client.delete`.
 */
export async function deleteDraft(name: string): Promise<void> {
  await apiCall("POST", "frappe.client.delete", {
    doctype: "Sales Invoice",
    name,
  });
  const sync = useSyncStore();
  void sync.refresh();
}

export interface UpdateDraftPayload {
  name: string;
  items: InvoiceItem[];
  remarks?: string;
  discount_amount?: number;
  apply_discount_on?: "Grand Total" | "Net Total";
  submit?: 0 | 1;
  payment_type?: "cash" | "credit";
  mode_of_payment?: string;
  warehouse?: string;
}

/**
 * In-place draft update. Previously we deleted-and-recreated, but Van
 * Users don't have delete permission on Sales Invoice — they got
 * "Insufficient Permission" even though they'd created the draft.
 * Server-side `update_draft` mutates the existing doc under the owner's
 * write permission and (optionally) submits it.
 */
export async function updateDraft(payload: UpdateDraftPayload): Promise<SavedInvoice> {
  const res = await apiCall<SavedInvoice>("POST", "vansale.api.invoice.update_draft", payload);
  const sync = useSyncStore();
  void sync.refresh();
  // updateDraft works on an existing doc — there is no clientId to return.
  return { ...res, clientId: "" };
}

export interface ReturnLine {
  item_code: string;
  qty: number;                 // positive — server negates
  rate?: number;
  uom?: string;
  conversion_factor?: number;
  warehouse?: string;
}

export interface ReturnPayload {
  original_name: string;
  items: ReturnLine[];
  remarks?: string;
  submit?: 0 | 1;
}

export interface SavedReturn extends SavedInvoice {
  is_return: number;
}

/** Create a Sales Return (Credit Note) against a submitted invoice.
 *  Offline path not supported — returns require server-side stock validation. */
export async function returnAgainst(payload: ReturnPayload): Promise<SavedReturn> {
  const clientId = genUuid();
  const clientTs = new Date().toISOString();
  const res = await apiCall<SavedReturn>("POST", "vansale.api.invoice.return_against", {
    client_id: clientId,
    posting_ts: clientTs,
    ...payload,
  });
  const sync = useSyncStore();
  void sync.refresh();
  return { ...res, clientId };
}

/** Offline-first save. Online synchronous path first, queue on network failure,
 *  re-throw ApiError so validation surfaces to the user (frappe-vue-pwa §4.1). */
export async function save(payload: InvoicePayload): Promise<SavedInvoice> {
  const clientId = genUuid();
  const clientTs = new Date().toISOString();

  if (isOnline()) {
    try {
      const res = await apiCall<SavedInvoice>("POST", "vansale.api.invoice.save", {
        client_id: clientId,
        posting_ts: clientTs,
        ...payload,
      });
      const sync = useSyncStore();
      void sync.refresh();
      return { ...res, clientId };
    } catch (err) {
      if (err instanceof ApiError) throw err; // server said no — surface it
      if (!(err instanceof NetworkError)) throw err;
      /* fall through to queue */
    }
  }

  const queued: QueuedInvoice = {
    clientId,
    clientTs,
    customerName: payload.customer,
    payload: { ...payload } as Record<string, unknown>,
    createdAt: Date.now(),
    attempts: 0,
    status: "pending",
  };
  await addEntry<QueuedInvoice>("invoice_queue", queued);
  const sync = useSyncStore();
  void sync.refresh();
  void sync.requestDrain();
  return { name: `QUEUED:${clientId.slice(0, 8)}`, grand_total: 0, status: "Queued", queued: true, clientId };
}
