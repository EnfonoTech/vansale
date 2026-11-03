import { apiCall } from "./client";
import { genUuid } from "@/offline/queue";

export interface LeadRow {
  name: string;
  lead_name: string;
  company_name: string | null;
  mobile_no: string | null;
  email_id: string | null;
  status: string;
  source: string | null;
  territory: string | null;
  customer: string | null;
  creation: string | null;
  modified: string | null;
}

export interface LeadQuotation {
  name: string;
  status: string;
  grand_total: number;
  transaction_date: string | null;
  docstatus: number;
}

export interface LeadDetail extends LeadRow {
  city: string | null;
  notes: Array<{ note: string; added_by: string | null; added_on: string | null }>;
  quotations: LeadQuotation[];
}

export interface LeadInput {
  lead_name?: string;
  company_name?: string;
  mobile_no?: string;
  email_id?: string;
  source?: string;
  territory?: string;
  city?: string;
  status?: string;
  note?: string;
}

export interface LeadOptions {
  sources: string[];
  territories: string[];
  statuses: string[];
}

export async function listLeads(limit = 50, search?: string, status?: string): Promise<LeadRow[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (search) qs.set("search", search);
  if (status) qs.set("status", status);
  return apiCall<LeadRow[]>("GET", `vansale.api.lead.list_mine?${qs.toString()}`);
}

export async function leadDetail(name: string): Promise<LeadDetail> {
  return apiCall<LeadDetail>("GET", `vansale.api.lead.detail?name=${encodeURIComponent(name)}`);
}

export async function leadOptions(): Promise<LeadOptions> {
  return apiCall<LeadOptions>("GET", "vansale.api.lead.options");
}

export async function saveLead(input: LeadInput): Promise<{ name: string }> {
  return apiCall("POST", "vansale.api.lead.save", {
    client_id: genUuid(),
    posting_ts: new Date().toISOString(),
    ...input,
  });
}

export async function updateLead(name: string, input: LeadInput): Promise<{ name: string; status: string }> {
  return apiCall("POST", "vansale.api.lead.update", { name, ...input });
}

/** Lead → Customer. Returns the new customer's name. */
export async function convertLead(name: string): Promise<{ customer: string }> {
  return apiCall("POST", "vansale.api.lead.convert", { client_id: genUuid(), name });
}
