import { apiCall } from "./client";
import { db, type CachedCustomer } from "@/offline/db";

export interface CustomerRow {
  name: string;
  customer_name: string;
  customer_group?: string;
  territory?: string;
  mobile_no?: string;
  email_id?: string;
  tax_id?: string;
  default_currency?: string;
  modified?: string;
}

export interface CustomerDetail extends CustomerRow {
  addresses: Array<Record<string, string>>;
  outstanding: number;
}

export async function listMine(search?: string, limit = 50): Promise<CustomerRow[]> {
  const qs = new URLSearchParams();
  qs.set("limit", String(limit));
  if (search) qs.set("search", search);
  return apiCall<CustomerRow[]>("GET", `vansale.api.customer.list_mine?${qs.toString()}`);
}

export async function detail(name: string): Promise<CustomerDetail> {
  return apiCall<CustomerDetail>(
    "GET",
    `vansale.api.customer.detail?name=${encodeURIComponent(name)}`,
  );
}

export interface CustomerCreatePayload {
  customer_name: string;
  customer_type?: "b2b" | "b2c";
  mobile_no?: string;
  email_id?: string;
  territory?: string;
  tax_id?: string;
  customer_group?: string;
  address_line1?: string;
  address_line2?: string;
  city?: string;
  state?: string;
  pincode?: string;
  country?: string;
}

export interface CustomerCreateResult {
  name: string;
  customer_name: string;
  customer_type?: string;
  address?: string | null;
}

export async function create(payload: CustomerCreatePayload): Promise<CustomerCreateResult> {
  return apiCall<CustomerCreateResult>("POST", "vansale.api.customer.create", payload);
}

/** Populate the local cache (online only). Used on dashboard refresh. */
export async function refreshCache(): Promise<CustomerRow[]> {
  const rows = await listMine(undefined, 200);
  const d = await db();
  const tx = d.transaction("customer_cache", "readwrite");
  for (const r of rows) {
    const entry: CachedCustomer = {
      name: r.name,
      customer_name: r.customer_name,
      mobile_no: r.mobile_no,
      territory: r.territory,
      outstanding: 0,
      cachedAt: Date.now(),
      raw: r as unknown as Record<string, unknown>,
    };
    await tx.store.put(entry);
  }
  await tx.done;
  return rows;
}

export async function fromCache(): Promise<CachedCustomer[]> {
  const d = await db();
  return await d.getAll("customer_cache");
}
