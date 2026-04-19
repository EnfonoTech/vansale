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
const DB_VERSION = 1;

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
  customer_cache: { key: string; value: CachedCustomer };
  item_cache: { key: string; value: CachedItem };
  kv: { key: string; value: unknown };
}

let _dbPromise: Promise<IDBPDatabase<VansaleSchema>> | null = null;

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
    },
  });
  return _dbPromise;
}

export type QueueStoreName = "invoice_queue" | "payment_queue" | "return_queue" | "visit_queue";
