import { apiCall } from "./client";
import { db, type CachedItem } from "@/offline/db";

export interface ItemRow {
  name: string;
  item_code: string;
  item_name: string;
  item_group?: string;
  stock_uom: string;
  standard_rate?: number;
  image?: string;
  stock_qty?: number;
}

export interface ItemDetail extends ItemRow {
  price_list_rate: number;
  tax_template?: string | null;
}

export async function listMine(search?: string, warehouse?: string, limit = 100): Promise<ItemRow[]> {
  const qs = new URLSearchParams();
  qs.set("limit", String(limit));
  if (search) qs.set("search", search);
  if (warehouse) qs.set("warehouse", warehouse);
  return apiCall<ItemRow[]>("GET", `vansale.api.item.list_mine?${qs.toString()}`);
}

export async function detail(itemCode: string, customer?: string): Promise<ItemDetail> {
  const qs = new URLSearchParams();
  qs.set("item_code", itemCode);
  if (customer) qs.set("customer", customer);
  return apiCall<ItemDetail>("GET", `vansale.api.item.detail?${qs.toString()}`);
}

export async function refreshCache(warehouse?: string): Promise<ItemRow[]> {
  const rows = await listMine(undefined, warehouse, 500);
  const d = await db();
  const tx = d.transaction("item_cache", "readwrite");
  for (const r of rows) {
    const entry: CachedItem = {
      name: r.name,
      item_name: r.item_name,
      item_code: r.item_code,
      stock_uom: r.stock_uom,
      price: r.standard_rate,
      stock_qty: r.stock_qty,
      cachedAt: Date.now(),
      raw: r as unknown as Record<string, unknown>,
    };
    await tx.store.put(entry);
  }
  await tx.done;
  return rows;
}

export async function fromCache(): Promise<CachedItem[]> {
  const d = await db();
  return await d.getAll("item_cache");
}
