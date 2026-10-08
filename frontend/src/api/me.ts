import { apiCall } from "./client";

export interface ConfigDefaults {
  user: string;
  full_name: string;
  language: string;
  is_van_user: boolean;
  is_van_manager: boolean;
  is_system_manager: boolean;
  roles: string[];
  company: string | null;
  branch: string | null;
  default_warehouse: string | null;
  warehouses: string[];
  default_cost_center: string | null;
  cost_centers: string[];
  van_code: string | null;
  currency: string | null;
  sales_person: string | null;
  sales_person_name: string | null;
  require_location?: boolean;
  selling_price_list?: string | null;
  /** Per-van route-planning toggle. Absent on sites older than v1.0.26. */
  enable_route?: boolean;
  /** Effective PIN requirement: user row -> van -> global master switch. */
  require_pin?: boolean;
  /** Effective UOM-change permission on invoice lines: van -> global. */
  allow_uom_change?: boolean;
  /** Customer-specific Item Prices used for pricing: van -> global. */
  use_customer_price?: boolean;
  /** Decimals for rates/amounts, as ERPNext rounds Sales Invoice Item.rate. */
  currency_precision?: number;
  /** "POS Invoice" | "Payment Entry": how a cash sale is posted. */
  cash_sale_posting?: string;
  /** Several payment modes on one cash sale (setting). */
  split_payment?: boolean;
  advance_payment?: boolean;
  /** Returns without an original invoice allowed (setting). */
  return_without_invoice?: boolean;
  /** Print formats chosen in Vansale Settings / the van. */
  print_formats?: { invoice: string; receipt: string };
  /** Print button: direct or preview; print after submit; copies. */
  print?: { direct: boolean; after_submit: boolean; copies: number };
  /** Optional customer fields the site has (customer create form). */
  customer_form?: {
    name_2: { field: string; label: string } | null;
    cr_number: boolean;
    additional_number: boolean;
  };
}

export function configDefaults() {
  return apiCall<ConfigDefaults>("GET", "vansale.api.me.config_defaults");
}

export interface VanListRow {
  name: string;
  van_code: string;
  van_name: string | null;
  company: string | null;
  branch: string | null;
}

export function vans() {
  return apiCall<VanListRow[]>("GET", "vansale.api.me.vans");
}
