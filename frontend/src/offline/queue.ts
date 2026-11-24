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

/** Who is signed in (read from the saved session; no store needed). */
export function currentUser(): string | null {
  try {
    const raw = window.localStorage.getItem("vansale.session");
    return raw ? (JSON.parse(raw) as { user?: string | null }).user ?? null : null;
  } catch {
    return null;
  }
}

export async function addEntry<T extends QueuedBase>(
  store: QueueStoreName,
  entry: T,
): Promise<number> {
  // Queued work belongs to the user who did it: it must never post under the
  // next person who signs in on this phone.
  if (!entry.owner) entry.owner = currentUser();
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
    "customer_queue",
    "stock_entry_queue",
  ];
  const counts = await Promise.all(stores.map(countPending));
  return counts.reduce((a, b) => a + b, 0);
}

/** "Retry" pressed: every waiting entry may go now, whatever its backoff
 *  (it waited up to 30 minutes after the tap). */
export async function clearBackoff(): Promise<void> {
  const stores: QueueStoreName[] = [
    "invoice_queue",
    "payment_queue",
    "return_queue",
    "visit_queue",
    "customer_queue",
    "stock_entry_queue",
  ];
  for (const store of stores) {
    for (const entry of await getAllEntries(store)) {
      if (entry.status === "dismissed" || entry.nextAttemptAt === undefined) continue;
      await updateEntry(store, { ...entry, nextAttemptAt: undefined });
    }
  }
}
