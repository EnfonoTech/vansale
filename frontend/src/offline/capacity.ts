/**
 * Queue capacity + purge helpers.
 *
 * The drain engine doesn't enforce a cap — a van user on a multi-day
 * offline trip should never lose work because a counter rolled. Instead
 * we expose utilization metrics so the UI can warn the user (and a
 * manager can see it in the sync badge) before the device is clogged.
 *
 * `purgeDismissed` is the only path that hard-deletes queued rows, and
 * it only touches entries the user explicitly marked `dismissed` from
 * the sync-errors view. Pending / draining entries are untouchable
 * from here — commandment 3 (never silently delete user work).
 */
import { db, type QueueStoreName, type QueuedBase } from "./db";

export const QUEUE_CAP = 500;
const NEAR_CAP_RATIO = 0.9;

export interface StoreUtilization {
  count: number;
  cap: number;
  nearCap: boolean;
  atCap: boolean;
}

export type QueueUtilization = Record<QueueStoreName, StoreUtilization>;

const STORES: QueueStoreName[] = [
  "invoice_queue",
  "payment_queue",
  "return_queue",
  "visit_queue",
  "customer_queue",
  "stock_entry_queue",
];

function derive(count: number): StoreUtilization {
  return {
    count,
    cap: QUEUE_CAP,
    nearCap: count >= Math.floor(QUEUE_CAP * NEAR_CAP_RATIO),
    atCap: count >= QUEUE_CAP,
  };
}

/**
 * Reduce per-store utilization down to the single worst bucket. The
 * SyncBadge only has room for one pill — show the store closest to
 * full so a user whose `invoice_queue` is at 90% sees the warning
 * even while `visit_queue` is fine.
 */
export interface WorstUtilization extends StoreUtilization {
  store: QueueStoreName;
}

export function maxUtilization(util: QueueUtilization): WorstUtilization {
  let worst: WorstUtilization | null = null;
  for (const store of STORES) {
    const row = util[store];
    if (!row) continue;
    if (!worst || row.count > worst.count) {
      worst = { store, ...row };
    }
  }
  // STORES is a non-empty constant, so worst is always set; satisfy TS.
  return (
    worst ?? {
      store: STORES[0],
      count: 0,
      cap: QUEUE_CAP,
      nearCap: false,
      atCap: false,
    }
  );
}

export async function queueUtilization(): Promise<QueueUtilization> {
  const d = await db();
  const entries = await Promise.all(
    STORES.map(
      (s) =>
        (d.getAll as (name: QueueStoreName) => Promise<QueuedBase[]>)(s),
    ),
  );
  // Exclude dismissed — the user has already decided not to retry those,
  // they shouldn't count against capacity.
  const counts = entries.map((rows) => rows.filter((r) => r.status !== "dismissed").length);
  const out = {} as QueueUtilization;
  STORES.forEach((s, i) => {
    out[s] = derive(counts[i]);
  });
  return out;
}

export async function purgeDismissed(): Promise<number> {
  const d = await db();
  let purged = 0;
  for (const store of STORES) {
    const rows = (await (d.getAll as (s: QueueStoreName) => Promise<QueuedBase[]>)(
      store,
    )) as QueuedBase[];
    for (const row of rows) {
      if (row.status === "dismissed" && typeof row.id === "number") {
        await (d.delete as (s: QueueStoreName, k: number) => Promise<void>)(store, row.id);
        purged += 1;
      }
    }
  }
  return purged;
}
