/**
 * Ordered drain engine.
 *
 * Drain order is fixed: photos → invoices → payments → returns → visits.
 * An entry with an unresolved `photo:*` placeholder is skipped (not
 * failed) so a failed photo upload doesn't mark an otherwise-fine
 * invoice as errored.
 *
 * Unrecoverable server errors (narrow regex — not bare substrings, which
 * would match harmless messages, see `frappe-vue-pwa` §4.5) flag the
 * entry for the user to RETRY or DISMISS. **Never silently delete user
 * work** — commandment 3.
 */
import { db, type QueueStoreName, type QueuedBase } from "./db";
import { getAllEntries, updateEntry, deleteEntry } from "./queue";
import { resolveToRealUrl } from "./photos";
import { resolveSignatureToRealUrl } from "./signatures";
import { classifyError } from "./classify";

export type DrainProcessor<T extends QueuedBase> = (entry: T) => Promise<{ refName: string }>;

/**
 * Exponential backoff cap. Caps the retry window at 30 minutes so a
 * permanently-broken entry doesn't starve the device but also doesn't
 * chew battery polling every few seconds.
 */
const BACKOFF_CAP_MS = 30 * 60_000;
const BACKOFF_BASE_MS = 60_000;

/**
 * `attempts` is the count PRIOR to this failure — so the very first
 * failure (attempts=0) waits 1 minute, then 2, 4, 8, 16, 30 (capped).
 */
function computeBackoff(attempts: number): number {
  const raw = BACKOFF_BASE_MS * Math.pow(2, Math.max(0, attempts));
  return Math.min(raw, BACKOFF_CAP_MS);
}

function placeholders(payload: Record<string, unknown>): string[] {
  const found: string[] = [];
  const walk = (v: unknown) => {
    if (!v) return;
    if (typeof v === "string") {
      if (v.startsWith("photo:") || v.startsWith("signature:")) found.push(v);
      return;
    }
    if (Array.isArray(v)) {
      for (const item of v) walk(item);
      return;
    }
    if (typeof v === "object") {
      for (const val of Object.values(v as Record<string, unknown>)) walk(val);
    }
  };
  walk(payload);
  return found;
}

async function resolvePlaceholders(entry: { payload: Record<string, unknown> }): Promise<void> {
  const list = placeholders(entry.payload);
  for (const ph of list) {
    if (ph.startsWith("signature:")) {
      await resolveSignatureToRealUrl(ph);
    } else {
      await resolveToRealUrl(ph);
    }
    // resolveXxx rewrites the stored entries in IDB; we re-read next iter.
  }
}

export async function drainStore<T extends QueuedBase & { payload: Record<string, unknown> }>(
  store: QueueStoreName,
  processor: DrainProcessor<T>,
): Promise<{ processed: number; failed: number; skipped: number }> {
  const summary = { processed: 0, failed: 0, skipped: 0 };
  const entries = (await getAllEntries<T>(store)) as T[];

  for (const entry of entries) {
    if (entry.status === "dismissed") {
      summary.skipped += 1;
      continue;
    }
    // Exponential-backoff gate — skip entries whose retry window hasn't
    // opened yet. Prior failure stamped `nextAttemptAt`.
    if (typeof entry.nextAttemptAt === "number" && entry.nextAttemptAt > Date.now()) {
      summary.skipped += 1;
      continue;
    }
    try {
      await resolvePlaceholders(entry);
      // Re-read so we work with the rewritten payload.
      const d = await db();
      const fresh = (await (d.get as (s: QueueStoreName, k: number) => Promise<T>)(
        store,
        entry.id as number,
      )) as T | undefined;
      const live = fresh ?? entry;
      if (placeholders(live.payload).length > 0) {
        summary.skipped += 1;
        continue;
      }
      const res = await processor(live);
      if (typeof entry.id === "number") {
        await deleteEntry(store, entry.id);
      }
      summary.processed += 1;
      void res;
    } catch (err) {
      const classified = classifyError(err);

      // Server already has this clientId — our local entry is redundant.
      // Delete it and count as processed so the user's "pending" counter
      // drops as expected.
      if (classified.treatAsSuccess && typeof entry.id === "number") {
        await deleteEntry(store, entry.id);
        summary.processed += 1;
        continue;
      }

      const priorAttempts = entry.attempts ?? 0;
      const next: T = {
        ...entry,
        attempts: priorAttempts + 1,
        nextAttemptAt: Date.now() + computeBackoff(priorAttempts),
        lastError: classified.message,
        errorKind: classified.kind,
      };

      // Network = transient → `skipped` (no user-facing error). All other
      // classifications surface to the user via the sync-errors view.
      const bucket: "skipped" | "failed" = classified.kind === "network" ? "skipped" : "failed";
      await updateEntry(store, next);
      summary[bucket] += 1;
    }
  }
  return summary;
}

export interface DrainResult {
  customers: Awaited<ReturnType<typeof drainStore>>;
  stockEntries: Awaited<ReturnType<typeof drainStore>>;
  invoices: Awaited<ReturnType<typeof drainStore>>;
  payments: Awaited<ReturnType<typeof drainStore>>;
  returns: Awaited<ReturnType<typeof drainStore>>;
  visits: Awaited<ReturnType<typeof drainStore>>;
}

/**
 * Drain order — customers MUST run first so any downstream invoice/
 * payment/return that references a brand-new customer has a concrete
 * `Customer.name` to point at. Stock entries (van replenishments) run
 * next so that invoices drafted against newly-loaded items don't throw
 * "negative stock" on the server. Once those are online we replay the
 * rest in cause → effect order: invoices → payments → returns → visits.
 */
export async function drainAll(): Promise<DrainResult> {
  const { drainCustomer } = await import("./processors/customer");
  const { drainStockEntry } = await import("./processors/stock_entry");
  const { drainInvoice } = await import("./processors/invoice");
  const { drainPayment } = await import("./processors/payment");
  const { drainReturn } = await import("./processors/return");
  const { drainVisit } = await import("./processors/visit");

  return {
    customers: await drainStore("customer_queue", drainCustomer),
    stockEntries: await drainStore("stock_entry_queue", drainStockEntry),
    invoices: await drainStore("invoice_queue", drainInvoice),
    payments: await drainStore("payment_queue", drainPayment),
    returns: await drainStore("return_queue", drainReturn),
    visits: await drainStore("visit_queue", drainVisit),
  };
}

/** Flag entries referencing blobs that have been deleted — surface to user,
 *  NEVER auto-delete (§4.6). */
export async function flagOrphans(): Promise<number> {
  const d = await db();
  const photoIds = new Set((await d.getAll("photos")).map((p) => p.id));
  const sigIds = new Set((await d.getAll("signatures")).map((s) => s.id));
  let flagged = 0;
  for (const store of [
    "invoice_queue",
    "payment_queue",
    "return_queue",
    "visit_queue",
    "customer_queue",
    "stock_entry_queue",
  ] as const) {
    const all = (await (d.getAll as (s: typeof store) => Promise<unknown[]>)(store)) as Array<{
      id?: number;
      payload: Record<string, unknown>;
      attempts?: number;
      lastError?: string;
    }>;
    for (const entry of all) {
      const refs = placeholders(entry.payload);
      const dead = refs.filter((p) =>
        p.startsWith("photo:")
          ? !photoIds.has(p.slice(6))
          : p.startsWith("signature:")
            ? !sigIds.has(p.slice(10))
            : false,
      );
      if (dead.length > 0 && !entry.lastError) {
        entry.lastError = "Attachment missing — please recapture";
        entry.attempts = Math.max(1, entry.attempts ?? 0);
        await (d.put as (s: typeof store, v: unknown) => Promise<IDBValidKey>)(store, entry);
        flagged += 1;
      }
    }
  }
  return flagged;
}
