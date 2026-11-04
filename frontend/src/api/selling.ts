/**
 * Quotation and Sales Order — the two documents between a lead and an
 * invoice. Same shape, different endpoints, so one typed client serves both
 * (`kind` picks the module). Both are online-only: quoting and ordering need
 * live prices and a server-side tax / stock check.
 */
import { apiCall } from "./client";
import { genUuid } from "@/offline/queue";

export type SellingKind = "quotation" | "order";

export const KIND = {
  quotation: {
    module: "vansale.api.quotation",
    doctype: "Quotation",
    title: "Quotation",
    plural: "Quotations",
    list: "quotations",
    detail: "quotation-detail",
    new: "quotation-new",
    edit: "quotation-edit",
    dateLabel: "Valid till",
  },
  order: {
    module: "vansale.api.sales_order",
    doctype: "Sales Order",
    title: "Sales order",
    plural: "Sales orders",
    list: "orders",
    detail: "order-detail",
    new: "order-new",
    edit: "order-edit",
    dateLabel: "Delivery date",
  },
} as const;

export interface SellingLine {
  item_code: string;
  item_name?: string;
  qty: number;
  rate: number;
  price_list_rate?: number;
  uom?: string;
  conversion_factor?: number;
}

export interface SellingRow {
  name: string;
  customer?: string;
  party_name: string;
  customer_name?: string;
  quotation_to?: "Customer" | "Lead";
  grand_total: number;
  status: string;
  transaction_date: string | null;
  valid_till?: string | null;
  delivery_date?: string | null;
  per_delivered?: number;
  per_billed?: number;
  docstatus: number;
}

export interface SellingDetailLine extends SellingLine {
  name: string;
  amount: number;
  stock_uom?: string | null;
  discount_percentage: number;
  delivered_qty: number;
}

export interface SellingDetail {
  name: string;
  /** Quotation only: who it is addressed to. */
  quotation_to?: "Customer" | "Lead";
  party?: string;
  party_name: string;
  customer: string | null;
  currency: string;
  transaction_date: string | null;
  valid_till?: string | null;
  delivery_date?: string | null;
  warehouse?: string | null;
  status: string;
  docstatus: number;
  per_delivered?: number;
  per_billed?: number;
  remarks: string | null;
  net_total: number;
  total_taxes_and_charges: number;
  discount_amount: number;
  grand_total: number;
  items: SellingDetailLine[];
  taxes: Array<{ description: string; rate: number; tax_amount: number; total: number }>;
  /** Quotation → its orders; Order → its invoices. */
  orders?: string[];
  invoices?: string[];
}

export interface SellingPayload {
  /** Customer (order) or Customer / Lead (quotation). */
  party: string;
  quotation_to?: "Customer" | "Lead";
  items: SellingLine[];
  /** Quotation: valid till. Order: delivery date. */
  date?: string;
  remarks?: string;
  discount_amount?: number;
  warehouse?: string;
  submit?: 0 | 1;
}

export interface SellingSaved {
  name: string;
  grand_total: number;
  status: string;
  docstatus: number;
  /** Quotation: the customer it was made for (a lead is converted on save). */
  customer?: string | null;
  /** Set when saving converted a lead into this new customer. */
  converted_customer?: string | null;
}

const path = (kind: SellingKind, fn: string) => `${KIND[kind].module}.${fn}`;

export async function listDocs(
  kind: SellingKind,
  limit = 50,
  search?: string,
  filter?: { customer?: string; status?: string },
): Promise<SellingRow[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (search) qs.set("search", search);
  if (filter?.status) qs.set("status", filter.status);
  if (filter?.customer) qs.set(kind === "quotation" ? "party" : "customer", filter.customer);
  return apiCall<SellingRow[]>("GET", `${path(kind, "list_mine")}?${qs.toString()}`);
}

export async function docDetail(kind: SellingKind, name: string): Promise<SellingDetail> {
  return apiCall<SellingDetail>("GET", `${path(kind, "detail")}?name=${encodeURIComponent(name)}`);
}

function body(kind: SellingKind, p: SellingPayload): Record<string, unknown> {
  const common = {
    items: p.items,
    remarks: p.remarks,
    discount_amount: p.discount_amount,
    submit: p.submit ?? 0,
  };
  return kind === "quotation"
    ? { ...common, party: p.party, quotation_to: p.quotation_to ?? "Customer", valid_till: p.date }
    : { ...common, customer: p.party, delivery_date: p.date, warehouse: p.warehouse };
}

export async function saveDoc(kind: SellingKind, p: SellingPayload): Promise<SellingSaved> {
  return apiCall<SellingSaved>("POST", path(kind, "save"), {
    client_id: genUuid(),
    posting_ts: new Date().toISOString(),
    ...body(kind, p),
  });
}

export async function updateDocDraft(kind: SellingKind, name: string, p: SellingPayload): Promise<SellingSaved> {
  const { party: _party, quotation_to: _to, ...rest } = body(kind, p) as Record<string, unknown>;
  void _party;
  void _to;
  return apiCall<SellingSaved>("POST", path(kind, "update_draft"), { name, ...rest });
}

/** Never `frappe.client.submit` — see ARCHITECTURE §2. */
export async function submitDoc(kind: SellingKind, name: string): Promise<SellingSaved> {
  return apiCall<SellingSaved>("POST", path(kind, "submit_draft"), { name });
}

export async function deleteDoc(kind: SellingKind, name: string): Promise<void> {
  await apiCall("POST", "frappe.client.delete", { doctype: KIND[kind].doctype, name });
}

export async function markQuotationLost(name: string, reason?: string): Promise<SellingSaved> {
  return apiCall<SellingSaved>("POST", "vansale.api.quotation.mark_lost", { name, reason });
}

/** Quotation → Sales Order (customer quotations only). */
export async function quotationToOrder(name: string, deliveryDate?: string): Promise<{ name: string }> {
  return apiCall("POST", "vansale.api.quotation.make_order", {
    client_id: genUuid(),
    name,
    delivery_date: deliveryDate,
  });
}

/** Sales Order → draft Sales Invoice, finished in the invoice form. */
export async function orderToInvoice(name: string): Promise<{ name: string }> {
  return apiCall("POST", "vansale.api.sales_order.make_invoice", { client_id: genUuid(), name });
}
