/**
 * Generic queue helpers. Domain-specific logic (what a "save invoice"
 * means) lives in `processors/*.ts` — this module only moves rows in
 * and out of IndexedDB stores.
 */
import { db, type QueueStoreName, type QueuedBase } from "./db";

export function genUuid(): string {
  // Crypto is available in all Capacitor WebViews we target.
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return (crypto as Crypto & { randomUUID(): string }).randomUUID();
  }
  // Fallback — extremely rarely needed.
  return `uuid-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export async function addEntry<T extends QueuedBase>(
  store: QueueStoreName,
  entry: T,
): Promise<number> {
  const d = await db();
  return Number(await (d.add as (s: QueueStoreName, v: unknown) => Promise<IDBValidKey>)(store, entry));
}

export async function getAllEntries<T extends QueuedBase>(
  store: QueueStoreName,
): Promise<T[]> {
  const d = await db();
  return (await (d.getAll as (s: QueueStoreName) => Promise<T[]>)(store)) as T[];
}

export async function updateEntry<T extends QueuedBase>(
  store: QueueStoreName,
  entry: T,
): Promise<void> {
  const d = await db();
  await (d.put as (s: QueueStoreName, v: unknown) => Promise<IDBValidKey>)(store, entry);
}

export async function deleteEntry(store: QueueStoreName, id: number): Promise<void> {
  const d = await db();
  await (d.delete as (s: QueueStoreName, k: number) => Promise<void>)(store, id);
}

export async function countPending(store: QueueStoreName): Promise<number> {
  const entries = await getAllEntries(store);
  return entries.filter((e) => e.status !== "dismissed").length;
}

export async function totalPending(): Promise<number> {
  const stores: QueueStoreName[] = [
    "invoice_queue",
    "payment_queue",
    "return_queue",
    "visit_queue",
  ];
  const counts = await Promise.all(stores.map(countPending));
  return counts.reduce((a, b) => a + b, 0);
}
