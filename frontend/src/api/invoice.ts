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
  /** Split cash payment (setting): a row without amount takes what's left. */
  payments?: PaymentRow[];
  discount_amount?: number;
  apply_discount_on?: "Grand Total" | "Net Total";
}

export interface PaymentRow {
  mode_of_payment: string;
  amount?: number | null;
  reference_no?: string | null;
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
export async function listMine(
  limit = 50,
  customer?: string,
  returnable = false,
  search?: string,
): Promise<Array<Record<string, unknown>>> {
  const qs = new URLSearchParams();
  qs.set("limit", String(limit));
  if (customer) qs.set("customer", customer);
  if (search) qs.set("search", search);
  // Return picker: submitted sales with something left to return.
  if (returnable) qs.set("returnable", "1");
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
export async function listReturns(limit = 50, customer?: string, search?: string): Promise<ReturnRow[]> {
  const qs = new URLSearchParams();
  qs.set("limit", String(limit));
  qs.set("is_return", "1");
  if (customer) qs.set("customer", customer);
  if (search) qs.set("search", search);
  return apiCall<ReturnRow[]>("GET", `vansale.api.invoice.list_mine?${qs.toString()}`);
}

export interface InvoiceDetailTax {
  description: string;
  rate: number;
  tax_amount: number;
  total: number;
}

export interface InvoiceDetailItem {
  /** Invoice row name (Sales Invoice Item). */
  name?: string;
  /** Qty already returned on submitted credit notes (in this row's UOM). */
  returned_qty?: number;
  /** Same, in stock units (returns may use a smaller UOM). */
  returned_stock_qty?: number;
  stock_qty?: number;
  /** Units this row may be returned in: the sold UOM first, then smaller ones. */
  return_uoms?: Array<{ uom: string; conversion_factor: number }>;
  item_code: string;
  item_name: string;
  qty: number;
  rate: number;
  price_list_rate: number;
  discount_percentage: number;
  discount_amount: number;
  amount: number;
  uom: string | null;
  conversion_factor?: number;
  stock_uom?: string | null;
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
  /** 1 = cash (POS) invoice. Absent on servers older than this field. */
  is_pos?: number;
  /** Cash or credit, whichever way the cash sale is posted (POS or Payment Entry). */
  payment_type?: "cash" | "credit";
  mode_of_payment?: string | null;
  payments?: PaymentRow[];
  grand_total: number;
  net_total: number;
  total_taxes_and_charges: number;
  discount_amount: number;
  outstanding_amount: number;
  /** Credit note: what may still be paid back (open credit less draft refunds). */
  refundable_amount?: number;
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
  payments?: PaymentRow[];
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

export interface TaxInfo {
  template: string | null;
  /** Sum of "On Net Total" rows, as a percentage. 0 when zero-rated/exempt. */
  rate: number;
  /** True when the price list rate ALREADY contains the tax. */
  inclusive: boolean;
  /** False for compound templates that cannot collapse to one percentage. */
  simple: boolean;
  taxes: Array<{
    description: string | null;
    charge_type: string | null;
    rate: number;
    included_in_print_rate: number;
  }>;
}

/**
 * Tax template + headline rate for the live totals. Resolved server-side
 * through the customer's Tax Category / Tax Rule, so a zero-rated customer
 * shows 0% instead of the old hardcoded 15%.
 */
export async function taxInfo(customer?: string): Promise<TaxInfo> {
  const qs = new URLSearchParams();
  if (customer) qs.set("customer", customer);
  return apiCall<TaxInfo>("GET", `vansale.api.invoice.tax_info?${qs.toString()}`);
}

export interface ReturnLine {
  /** Original invoice row being returned (server matches by item code without it). */
  sales_invoice_item?: string;
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
  /** One of RETURN_REASONS — mandatory server-side. */
  reason: string;
  /** Optional free-text detail, appended to the credit note's remarks. */
  note?: string;
  submit?: 0 | 1;
  refund?: RefundPayload;
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

export interface ReturnWithoutInvoiceLine {
  item_code: string;
  qty: number;              // positive — server negates
  uom?: string;
  rate?: number | null;     // blank → the server's default price
}

/** Credit note without an original invoice ("Return without invoice" setting).
 *  Online only, like returns against an invoice. */
export async function returnWithoutInvoice(payload: {
  customer: string;
  items: ReturnWithoutInvoiceLine[];
  reason: string;
  note?: string;
  /** ZATCA reference invoices chosen by the user (required on ZATCA sites). */
  references?: string[];
  refund?: RefundPayload;
}): Promise<SavedReturn & { references?: string[] }> {
  const clientId = genUuid();
  const res = await apiCall<SavedReturn & { references?: string[] }>(
    "POST",
    "vansale.api.sales_return.save_without_invoice",
    { client_id: clientId, posting_ts: new Date().toISOString(), submit: 1, ...payload },
  );
  void useSyncStore().refresh();
  return { ...res, clientId };
}

export interface ReturnTotals {
  net_total: number;
  tax: number;
  grand_total: number;
  /** Credit keeps its own balance → can be refunded now (bulk, or a paid invoice). */
  refundable?: boolean;
  original_outstanding?: number | null;
}

/** Pay the customer back for the credit now (Payment Entry "Pay"). */
export interface RefundPayload {
  mode_of_payment: string;
  amount?: number;
  reference_no?: string;
}

/** Net / VAT / total of a return before saving (server builds + calculates, never saves). */
export async function returnPreview(payload: {
  items: Array<{ item_code: string; qty: number; uom?: string; rate?: number | null; sales_invoice_item?: string }>;
  original_invoice?: string;
  customer?: string;
}): Promise<ReturnTotals> {
  return apiCall<ReturnTotals>("POST", "vansale.api.sales_return.preview", payload);
}

export interface ReferenceOptions {
  /** False when the site has no ZATCA reference field. */
  enabled: boolean;
  defaults: string[];
  never_sold: string[];
  invoices: Array<{ name: string; posting_date: string; grand_total: number }>;
}

/** Bulk return: default ZATCA references for the items + the customer's invoices to pick from. */
export async function referenceOptions(customer: string, itemCodes: string[]): Promise<ReferenceOptions> {
  const qs = new URLSearchParams({ customer, items: JSON.stringify(itemCodes) });
  return apiCall<ReferenceOptions>("GET", `vansale.api.sales_return.reference_options?${qs.toString()}`);
}

/** Pay out a credit note later (a return kept as customer credit). Online only. */
export async function refundCreditNote(payload: {
  credit_note: string;
  mode_of_payment: string;
  amount?: number;
  reference_no?: string;
}): Promise<{ payment_entry: string; docstatus?: number; idempotent_replay?: boolean }> {
  return apiCall("POST", "vansale.api.sales_return.refund", {
    client_id: genUuid(),
    posting_ts: new Date().toISOString(),
    ...payload,
  });
}
