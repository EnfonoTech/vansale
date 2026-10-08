import { apiCall } from "./client";

export interface TodaySales { amount: number; count: number; returned: number }
export interface TodayCollection {
  amount: number;
  /** Collected today but still draft Payment Entries (awaiting office). */
  pending?: number;
  by_mode: Array<{ mode: string; amount: number; count: number }>;
}
export interface MonthSummary { from: string; to: string; sales: number; collections: number }
export interface ActivityRow {
  kind: "invoice" | "payment";
  name: string;
  party: string;
  amount: number;
  posting_date: string;
  modified: string;
}

export function todaySales() {
  return apiCall<TodaySales>("GET", "vansale.api.dashboard.today_sales");
}

export function todayCollection() {
  return apiCall<TodayCollection>("GET", "vansale.api.dashboard.today_collection");
}

export function monthSummary(offset = 0) {
  return apiCall<MonthSummary>("GET", `vansale.api.dashboard.month_summary?offset=${offset}`);
}

export function recentActivity(limit = 10) {
  return apiCall<ActivityRow[]>("GET", `vansale.api.dashboard.recent_activity?limit=${limit}`);
}

export function warehouses() {
  return apiCall<Array<{ name: string; warehouse_name: string }>>("GET", "vansale.api.dashboard.warehouses");
}
