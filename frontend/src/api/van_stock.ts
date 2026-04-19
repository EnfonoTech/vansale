import { apiCall } from "./client";

export interface VanStockRow {
  item_code: string;
  item_name: string;
  stock_uom: string;
  actual_qty: number;
  stock_value: number;
  image?: string;
}

export async function myWarehouse(): Promise<{ warehouse: string | null }> {
  return apiCall("GET", "vansale.api.van_stock.my_warehouse");
}

export async function listStock(warehouse?: string): Promise<{ warehouse: string; items: VanStockRow[] }> {
  const qs = warehouse ? `?warehouse=${encodeURIComponent(warehouse)}` : "";
  return apiCall("GET", `vansale.api.van_stock.list_stock${qs}`);
}

export async function transferIn(payload: {
  from_warehouse: string;
  to_warehouse?: string;
  items: Array<{ item_code: string; qty: number }>;
  reason?: string;
}) {
  return apiCall<{ name: string }>("POST", "vansale.api.van_stock.transfer_in", payload);
}
