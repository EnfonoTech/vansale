import { apiCall } from "./client";
import { NetworkError } from "@/app/frappe";
import { isOnline } from "@/app/online";
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

export interface ItemUom {
  uom: string;
  conversion_factor: number;
  price_list_rate: number;
}

export interface ItemDetail extends ItemRow {
  price_list_rate: number;
  price_list?: string | null;
  uoms: ItemUom[];
  tax_template?: string | null;
  customer?: string | null;
}

export interface PriceForResult {
  item_code: string;
  uom: string | null;
  price_list: string | null;
  price_list_rate: number;
}

/**
 * Offline-aware item list.
 *
 * Online: hit the server, write-through to `item_cache` so the next
 *   offline boot has data to show.
 * Offline (or network error): return cached rows. Search is respected
 *   locally via a cheap contains match on item_code / item_name.
 *
 * The in-view caller used to fall over silently when the network was
 * down — the InvoiceFormView rendered an empty catalog and an empty
 * customer list, which read as "app is broken". With cache fallback
 * the driver sees the last-known set and can keep booking invoices
 * (they queue).
 */
export async function listMine(
  search?: string,
  warehouse?: string,
  limit = 100,
  onlyInStock = false,
): Promise<ItemRow[]> {
  const qs = new URLSearchParams();
  qs.set("limit", String(limit));
  if (search) qs.set("search", search);
  if (warehouse) qs.set("warehouse", warehouse);
  if (onlyInStock) qs.set("only_in_stock", "1");

  if (!isOnline()) {
    return await _listFromCache(search, limit, onlyInStock);
  }
  try {
    const rows = await apiCall<ItemRow[]>("GET", `vansale.api.item.list_mine?${qs.toString()}`);
    // Write-through on unfiltered fetches so the cache mirrors the "open
    // the form with no search" experience. Search queries are one-off.
    if (!search) void _writeCache(rows).catch(() => {});
    return rows;
  } catch (err) {
    if (err instanceof NetworkError) {
      return await _listFromCache(search, limit, onlyInStock);
    }
    throw err;
  }
}

async function _listFromCache(
  search: string | undefined,
  limit: number,
  onlyInStock = false,
): Promise<ItemRow[]> {
  const d = await db();
  const all = await d.getAll("item_cache");
  const rows = all.map((c) => (c.raw as unknown as ItemRow) ?? {
    name: c.name,
    item_code: c.item_code,
    item_name: c.item_name,
    stock_uom: c.stock_uom,
    standard_rate: c.price,
    stock_qty: c.stock_qty,
  });
  const q = (search ?? "").trim().toLowerCase();
  let filtered = q
    ? rows.filter(
        (r) =>
          (r.item_code ?? "").toLowerCase().includes(q) ||
          (r.item_name ?? "").toLowerCase().includes(q),
      )
    : rows;
  if (onlyInStock) {
    // Offline mirror of the server's Bin filter. `stock_qty` is undefined
    // for rows cached before a warehouse-scoped fetch — keep those rather
    // than blanking the catalogue on a cold cache.
    filtered = filtered.filter((r) => r.stock_qty === undefined || (r.stock_qty ?? 0) > 0);
  }
  return filtered.slice(0, limit);
}

async function _writeCache(rows: ItemRow[]): Promise<void> {
  const d = await db();
  const tx = d.transaction("item_cache", "readwrite");
  for (const r of rows) {
    // Merge: preserve any previously-stored `detail` (uoms + price_list_rate)
    // that a prior `detail()` call hydrated — don't clobber on list refresh.
    const existing = (await tx.store.get(r.name)) as (CachedItem & { detail?: ItemDetail }) | undefined;
    const entry: CachedItem & { detail?: ItemDetail } = {
      name: r.name,
      item_name: r.item_name,
      item_code: r.item_code,
      stock_uom: r.stock_uom,
      price: r.standard_rate,
      stock_qty: r.stock_qty,
      cachedAt: Date.now(),
      raw: r as unknown as Record<string, unknown>,
      detail: existing?.detail,
    };
    await tx.store.put(entry);
  }
  await tx.done;
}

export async function detail(itemCode: string, customer?: string): Promise<ItemDetail> {
  const qs = new URLSearchParams();
  qs.set("item_code", itemCode);
  if (customer) qs.set("customer", customer);

  const fetchFromCache = async (): Promise<ItemDetail> => {
    const d = await db();
    const cached = (await d.get("item_cache", itemCode)) as (CachedItem & { detail?: ItemDetail }) | undefined;
    if (cached?.detail) return cached.detail;
    if (cached) {
      // Synthesize a minimal detail from row data — single stock_uom entry,
      // no price list. Better than throwing when offline.
      return {
        name: cached.name,
        item_code: cached.item_code,
        item_name: cached.item_name,
        item_group: undefined,
        stock_uom: cached.stock_uom,
        standard_rate: cached.price,
        price_list_rate: cached.price ?? 0,
        price_list: null,
        uoms: [{ uom: cached.stock_uom, conversion_factor: 1, price_list_rate: cached.price ?? 0 }],
        tax_template: null,
        customer: customer ?? null,
      };
    }
    throw new NetworkError("Item not cached");
  };

  if (!isOnline()) return await fetchFromCache();
  try {
    const doc = await apiCall<ItemDetail>("GET", `vansale.api.item.detail?${qs.toString()}`);
    // Write-through: stash the detail so the next offline addLine has UOMs + price.
    void _writeDetail(doc).catch(() => {});
    return doc;
  } catch (err) {
    if (err instanceof NetworkError) return await fetchFromCache();
    throw err;
  }
}

async function _writeDetail(doc: ItemDetail): Promise<void> {
  const d = await db();
  const tx = d.transaction("item_cache", "readwrite");
  const existing = (await tx.store.get(doc.item_code)) as (CachedItem & { detail?: ItemDetail }) | undefined;
  const entry: CachedItem & { detail?: ItemDetail } = {
    name: doc.name,
    item_name: doc.item_name,
    item_code: doc.item_code,
    stock_uom: doc.stock_uom,
    price: doc.standard_rate,
    stock_qty: existing?.stock_qty,
    cachedAt: Date.now(),
    raw: (existing?.raw ?? doc) as unknown as Record<string, unknown>,
    detail: doc,
  };
  await tx.store.put(entry);
  await tx.done;
}

export async function priceFor(itemCode: string, customer?: string, uom?: string): Promise<PriceForResult> {
  const qs = new URLSearchParams();
  qs.set("item_code", itemCode);
  if (customer) qs.set("customer", customer);
  if (uom) qs.set("uom", uom);

  const fetchFromCache = async (): Promise<PriceForResult> => {
    const d = await db();
    const cached = (await d.get("item_cache", itemCode)) as (CachedItem & { detail?: ItemDetail }) | undefined;
    const uomRow = cached?.detail?.uoms?.find((u) => u.uom === (uom ?? cached.detail?.stock_uom));
    const rate = uomRow?.price_list_rate ?? cached?.detail?.price_list_rate ?? cached?.price ?? 0;
    return {
      item_code: itemCode,
      uom: uom ?? null,
      price_list: cached?.detail?.price_list ?? null,
      price_list_rate: rate,
    };
  };

  if (!isOnline()) return await fetchFromCache();
  try {
    return await apiCall<PriceForResult>("GET", `vansale.api.item.price_for?${qs.toString()}`);
  } catch (err) {
    if (err instanceof NetworkError) return await fetchFromCache();
    throw err;
  }
}

export async function refreshCache(warehouse?: string): Promise<ItemRow[]> {
  const rows = await apiCall<ItemRow[]>(
    "GET",
    `vansale.api.item.list_mine?limit=500${warehouse ? `&warehouse=${encodeURIComponent(warehouse)}` : ""}`,
  );
  await _writeCache(rows);
  return rows;
}

export async function fromCache(): Promise<CachedItem[]> {
  const d = await db();
  return await d.getAll("item_cache");
}
