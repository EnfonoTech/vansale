import { apiCall } from "./client";
import { db, type CachedCustomer } from "@/offline/db";
import { apiBase } from "@/app/platform";
import { getCredentials, NetworkError, saveBlobToDevice } from "@/app/frappe";

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

export interface StatementPayload {
  html: string;
}

export async function statement(
  name: string,
  fromDate?: string,
  toDate?: string,
): Promise<StatementPayload> {
  const qs = new URLSearchParams({ name });
  if (fromDate) qs.set("from_date", fromDate);
  if (toDate) qs.set("to_date", toDate);
  return apiCall<StatementPayload>(
    "GET",
    `vansale.api.customer.statement_json?${qs.toString()}`,
  );
}

/**
 * Fetch the statement as a PDF binary and save to device. Works on both
 * web (anchor download) and native (Filesystem Documents/). The server
 * endpoint uses `frappe.utils.pdf.get_pdf` which requires wkhtmltopdf.
 */
/**
 * Fetch the statement PDF as a Blob without saving it — used by the Print
 * button to hand bytes directly to the `AndroidPrint` plugin. Web callers
 * who want a downloaded file should keep using `downloadStatementPdf`.
 */
export async function fetchStatementPdf(
  name: string,
  fromDate?: string,
  toDate?: string,
): Promise<Blob> {
  const qs = new URLSearchParams({ name });
  if (fromDate) qs.set("from_date", fromDate);
  if (toDate) qs.set("to_date", toDate);
  const url = `${apiBase()}/api/method/vansale.api.customer.statement_pdf?${qs.toString()}`;
  const headers: Record<string, string> = { Accept: "application/pdf" };
  const creds = await getCredentials();
  if (creds) headers.Authorization = `token ${creds.apiKey}:${creds.apiSecret}`;

  const controller = new AbortController();
  const t = window.setTimeout(() => controller.abort(), 30_000);
  let res: Response;
  try {
    res = await fetch(url, {
      method: "GET",
      headers,
      credentials: apiBase() ? "omit" : "include",
      signal: controller.signal,
    });
  } catch (err) {
    if ((err as { name?: string } | null)?.name === "AbortError") {
      throw new NetworkError("Statement PDF timed out");
    }
    throw new NetworkError();
  } finally {
    window.clearTimeout(t);
  }

  if (!res.ok) {
    throw new Error(`Could not generate statement PDF (HTTP ${res.status})`);
  }
  return await res.blob();
}

export async function downloadStatementPdf(
  name: string,
  fromDate?: string,
  toDate?: string,
): Promise<void> {
  const blob = await fetchStatementPdf(name, fromDate, toDate);
  const safeName = name.replace(/[^A-Za-z0-9._-]+/g, "_");
  await saveBlobToDevice(blob, `statement-${safeName}.pdf`);
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
  /** KSA ZATCA Phase 2: mandatory for B2B. */
  building_number?: string;
  additional_number?: string;
  district?: string;
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
