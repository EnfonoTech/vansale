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
