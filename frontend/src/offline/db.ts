/**
 * IndexedDB schema for the offline spine.
 *
 * - `photos` / `signatures` — blob storage keyed by `photo:<uuid>` /
 *   `signature:<uuid>` placeholders that live in queue payloads until
 *   `resolveToRealUrl` uploads them and rewrites the references.
 * - `*_queue` — per-domain outgoing mutations. Each entry carries its
 *   own `clientId` for server-side idempotency and a `clientTs` for
 *   the actual event time (drain-time `now()` would lie).
 * - `*_cache` — read-only snapshots that feed list views when offline.
 * - `kv` — catch-all for tiny settings (last-drain-at, version, etc.).
 *
 * Version bumps must go via `upgrade`. Never skip — missing stores on
 * older clients silently throw `NotFoundError` on first access.
 */
import { openDB, type IDBPDatabase } from "idb";
import type { DBSchema } from "idb";

const DB_NAME = "vansale";
/**
 * IMPORTANT: bump the version whenever you add / remove a store or
 * change an index. Migration logic lives in `upgrade` below. Older
 * clients on version N-1 will run every `oldVersion < M` branch in
 * order, so each bump must be idempotent for that subset of stores.
 *
 * Version history:
 *   v1 — initial (photos, signatures, invoice/payment/return/visit queues,
 *        customer/item caches, kv)
 *   v2 — add `customer_queue` so offline Customer create has a durable
 *        outbox (previously the Customer create call failed silently
 *        when offline).
 *   v3 — add `stock_entry_queue` so van replenishments (Material
 *        Transfer into the van warehouse) can be captured offline and
 *        drained when the device comes back online.
 */
const DB_VERSION = 3;

export interface PhotoBlob {
  id: string;
  blob: Blob;
  filename: string;
  thumb?: string;
  createdAt: number;
}

export interface SignatureBlob {
  id: string;
  blob: Blob;
  createdAt: number;
}

export interface QueuedBase {
  id?: number;
  clientId: string;
  clientTs: string;
  createdAt: number;
  attempts: number;
  lastError?: string;
  status?: "pending" | "draining" | "dismissed";
  /**
   * Earliest epoch-ms the drain engine is allowed to retry this entry.
   * Unset / `undefined` = eligible immediately. Populated on failure by
   * `drainStore` using exponential backoff so we don't hammer the server
   * (or waste device battery) on a persistently-failing entry.
   */
  nextAttemptAt?: number;
  /**
   * Structured category of the last failure — set by `drainStore` via
   * `classifyError`. Drives the sync-errors view (retry / edit / hide).
   * Kept as a plain string so IDB doesn't care about the TS union.
   */
  errorKind?: string;
}

export interface QueuedInvoice extends QueuedBase {
  customerName: string;
  payload: Record<string, unknown>;
}

export interface QueuedPayment extends QueuedBase {
  invoiceName?: string;
  customerName: string;
  payload: Record<string, unknown>;
}

export interface QueuedReturn extends QueuedBase {
  originalInvoice: string;
  payload: Record<string, unknown>;
}

export interface QueuedVisit extends QueuedBase {
  stopName: string;
  payload: Record<string, unknown>;
}

export interface QueuedCustomer extends QueuedBase {
  /** User-provided name — surfaces in the sync-errors list. */
  customerName: string;
  payload: Record<string, unknown>;
}

export interface QueuedStockEntry extends QueuedBase {
  /** Source warehouse the load is transferring FROM — surfaces in sync-errors. */
  fromWarehouse: string;
  /** Destination van warehouse. */
  toWarehouse: string;
  payload: Record<string, unknown>;
}

export interface CachedCustomer {
  name: string;
  customer_name: string;
  mobile_no?: string;
  territory?: string;
  outstanding?: number;
  cachedAt: number;
  raw: Record<string, unknown>;
}

export interface CachedItem {
  name: string;
  item_name: string;
  item_code: string;
  stock_uom: string;
  price?: number;
  stock_qty?: number;
  cachedAt: number;
  raw: Record<string, unknown>;
}

interface VansaleSchema extends DBSchema {
  photos: { key: string; value: PhotoBlob };
  signatures: { key: string; value: SignatureBlob };
  invoice_queue: {
    key: number;
    value: QueuedInvoice;
    indexes: { by_customer: string; by_client_id: string };
  };
  payment_queue: { key: number; value: QueuedPayment; indexes: { by_client_id: string } };
  return_queue: { key: number; value: QueuedReturn; indexes: { by_client_id: string } };
  visit_queue: { key: number; value: QueuedVisit; indexes: { by_stop: string } };
  customer_queue: { key: number; value: QueuedCustomer; indexes: { by_client_id: string } };
  stock_entry_queue: {
    key: number;
    value: QueuedStockEntry;
    indexes: { by_client_id: string };
  };
  customer_cache: { key: string; value: CachedCustomer };
  item_cache: { key: string; value: CachedItem };
  kv: { key: string; value: unknown };
}

let _dbPromise: Promise<IDBPDatabase<VansaleSchema>> | null = null;

/**
 * Test-only helper — drop the DB + reset the memoized promise so the
 * next `db()` call re-runs `upgrade`. Never call from production code.
 */
export async function __resetDbForTests(): Promise<void> {
  if (_dbPromise) {
    try {
      const d = await _dbPromise;
      d.close();
    } catch {
      /* ignore */
    }
  }
  _dbPromise = null;
  await new Promise<void>((resolve) => {
    const req = indexedDB.deleteDatabase(DB_NAME);
    req.onsuccess = () => resolve();
    req.onerror = () => resolve();
    req.onblocked = () => resolve();
  });
}

export function db(): Promise<IDBPDatabase<VansaleSchema>> {
  if (_dbPromise) return _dbPromise;
  _dbPromise = openDB<VansaleSchema>(DB_NAME, DB_VERSION, {
    upgrade(db, oldVersion) {
      if (oldVersion < 1) {
        db.createObjectStore("photos", { keyPath: "id" });
        db.createObjectStore("signatures", { keyPath: "id" });

        const inv = db.createObjectStore("invoice_queue", {
          keyPath: "id",
          autoIncrement: true,
        });
        inv.createIndex("by_customer", "customerName");
        inv.createIndex("by_client_id", "clientId", { unique: true });

        const pay = db.createObjectStore("payment_queue", {
          keyPath: "id",
          autoIncrement: true,
        });
        pay.createIndex("by_client_id", "clientId", { unique: true });

        const ret = db.createObjectStore("return_queue", {
          keyPath: "id",
          autoIncrement: true,
        });
        ret.createIndex("by_client_id", "clientId", { unique: true });

        const visit = db.createObjectStore("visit_queue", {
          keyPath: "id",
          autoIncrement: true,
        });
        visit.createIndex("by_stop", "stopName");

        db.createObjectStore("customer_cache", { keyPath: "name" });
        db.createObjectStore("item_cache", { keyPath: "name" });
        db.createObjectStore("kv");
      }
      if (oldVersion < 2) {
        const cust = db.createObjectStore("customer_queue", {
          keyPath: "id",
          autoIncrement: true,
        });
        cust.createIndex("by_client_id", "clientId", { unique: true });
      }
      if (oldVersion < 3) {
        const se = db.createObjectStore("stock_entry_queue", {
          keyPath: "id",
          autoIncrement: true,
        });
        se.createIndex("by_client_id", "clientId", { unique: true });
      }
    },
  });
  return _dbPromise;
}

export type QueueStoreName =
  | "invoice_queue"
  | "payment_queue"
  | "return_queue"
  | "visit_queue"
  | "customer_queue"
  | "stock_entry_queue";
