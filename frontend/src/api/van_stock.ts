import { apiCall, ApiError, NetworkError } from "./client";
import { isOnline } from "@/app/online";
import { addEntry, genUuid } from "@/offline/queue";
import type { QueuedStockEntry } from "@/offline/db";
import { useSyncStore } from "@/stores/sync";

export interface VanStockRow {
  item_code: string;
  item_name: string;
  stock_uom: string;
  actual_qty: number;
  stock_value: number;
  image?: string;
}

export interface TransferInPayload {
  from_warehouse: string;
  to_warehouse?: string;
  items: Array<{ item_code: string; qty: number }>;
  reason?: string;
}

export interface SavedTransferIn {
  name: string;
  queued?: boolean;
  clientId: string;
}

export async function myWarehouse(): Promise<{ warehouse: string | null }> {
  return apiCall("GET", "vansale.api.van_stock.my_warehouse");
}

export async function listStock(warehouse?: string): Promise<{ warehouse: string; items: VanStockRow[] }> {
  const qs = warehouse ? `?warehouse=${encodeURIComponent(warehouse)}` : "";
  return apiCall("GET", `vansale.api.van_stock.list_stock${qs}`);
}

/** Low-level online call — retained so any caller that KNOWS it's online
 *  (e.g. the drain engine) can bypass the offline-first wrapper. */
export async function transferIn(payload: TransferInPayload) {
  return apiCall<{ name: string }>("POST", "vansale.api.van_stock.transfer_in", payload);
}

/**
 * Offline-first van replenishment. Same shape as `invoice.save`:
 *   1. Try the online path synchronously (server throws = surface to user).
 *   2. On network loss, push to `stock_entry_queue` and let the drain
 *      engine retry when connectivity returns.
 *
 * Every attempt carries the same `clientId`, so an online retry from the
 * Sync drawer is idempotent via the Vansale Outbox lookup on the server.
 */
export async function saveTransferIn(payload: TransferInPayload): Promise<SavedTransferIn> {
  const clientId = genUuid();
  const clientTs = new Date().toISOString();

  if (isOnline()) {
    try {
      const res = await apiCall<{ name: string }>(
        "POST",
        "vansale.api.van_stock.transfer_in",
        { client_id: clientId, posting_ts: clientTs, ...payload },
      );
      const sync = useSyncStore();
      void sync.refresh();
      return { name: res.name, clientId };
    } catch (err) {
      if (err instanceof ApiError) throw err;
      if (!(err instanceof NetworkError)) throw err;
      /* fall through to queue */
    }
  }

  const queued: QueuedStockEntry = {
    clientId,
    clientTs,
    fromWarehouse: payload.from_warehouse,
    toWarehouse: payload.to_warehouse ?? "",
    payload: { ...payload } as Record<string, unknown>,
    createdAt: Date.now(),
    attempts: 0,
    status: "pending",
  };
  await addEntry<QueuedStockEntry>("stock_entry_queue", queued);
  const sync = useSyncStore();
  void sync.refresh();
  void sync.requestDrain();
  return { name: `QUEUED:${clientId.slice(0, 8)}`, queued: true, clientId };
}
