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
import { ApiError, NetworkError } from "@/app/frappe";
import { db, type QueueStoreName, type QueuedBase } from "./db";
import { getAllEntries, updateEntry, deleteEntry } from "./queue";
import { resolveToRealUrl } from "./photos";
import { resolveSignatureToRealUrl } from "./signatures";

export type DrainProcessor<T extends QueuedBase> = (entry: T) => Promise<{ refName: string }>;

const UNRECOVERABLE = [
  /not\s+found/i,
  /locked\s+by/i,
  /already\s+submitted/i,
  /invalid\s+status/i,
  /permission/i,
];

function isUnrecoverable(msg: string): boolean {
  return UNRECOVERABLE.some((re) => re.test(msg));
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
      const next: T = { ...entry, attempts: (entry.attempts ?? 0) + 1 };
      if (err instanceof ApiError) {
        const msg = err.serverMessage ?? err.message;
        next.lastError = msg;
        if (isUnrecoverable(msg)) {
          next.status = "pending";
          await updateEntry(store, next);
          summary.failed += 1;
          continue;
        }
        // Other ApiErrors — still surface to user but keep pending for retry.
        await updateEntry(store, next);
        summary.failed += 1;
        continue;
      }
      if (err instanceof NetworkError) {
        next.lastError = "Offline";
        await updateEntry(store, next);
        summary.skipped += 1;
        continue;
      }
      next.lastError = err instanceof Error ? err.message : String(err);
      await updateEntry(store, next);
      summary.failed += 1;
    }
  }
  return summary;
}

export interface DrainResult {
  invoices: Awaited<ReturnType<typeof drainStore>>;
  payments: Awaited<ReturnType<typeof drainStore>>;
  returns: Awaited<ReturnType<typeof drainStore>>;
  visits: Awaited<ReturnType<typeof drainStore>>;
}

export async function drainAll(): Promise<DrainResult> {
  const { drainInvoice } = await import("./processors/invoice");
  const { drainPayment } = await import("./processors/payment");
  const { drainReturn } = await import("./processors/return");
  const { drainVisit } = await import("./processors/visit");

  return {
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
