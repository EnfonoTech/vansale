/**
 * Observability — pure mapping from raw queue rows to a display-ready
 * struct. Keeps Vue components thin (no string-matching, no date math)
 * and makes the contract testable without rendering a DOM.
 */
import { db, type QueueStoreName, type QueuedBase } from "./db";
import type { ErrorKind } from "./classify";

const STORES: QueueStoreName[] = [
  "invoice_queue",
  "payment_queue",
  "return_queue",
  "visit_queue",
  "customer_queue",
  "stock_entry_queue",
];

export interface PendingEntry {
  store: QueueStoreName;
  id: number;
  clientId: string;
  clientTs: string;
  createdAt: number;
  attempts: number;
  lastError?: string;
  errorKind?: string;
  nextAttemptAt?: number;
  payload: Record<string, unknown>;
}

/**
 * Human-readable relative age. Deterministic output — testable without
 * mocking `Date`.
 *   <60s  → "just now"
 *   <60m  → "Nm ago"
 *   <24h  → "Nh ago"
 *   else  → "Nd ago"
 */
export function formatAge(createdAt: number, now: number): string {
  const diff = Math.max(0, now - createdAt);
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

function summarise(store: QueueStoreName, payload: Record<string, unknown>): string {
  if (store === "invoice_queue") return `Invoice for ${String(payload.customer ?? "—")}`;
  if (store === "payment_queue")
    return `Payment against ${String(payload.invoice_name ?? payload.customer ?? "—")}`;
  if (store === "return_queue") return `Return against ${String(payload.original_invoice ?? "—")}`;
  if (store === "visit_queue") return `Visit ${String(payload.stop_name ?? payload.customer ?? "—")}`;
  if (store === "customer_queue") return `New customer ${String(payload.customer_name ?? "—")}`;
  if (store === "stock_entry_queue") {
    const from = String(payload.from_warehouse ?? "—");
    const to = String(payload.to_warehouse ?? "van");
    return `Load ${from} → ${to}`;
  }
  return store;
}

function cooldownLabel(nextAttemptAt: number | undefined, now: number): string | undefined {
  if (typeof nextAttemptAt !== "number") return undefined;
  const remain = nextAttemptAt - now;
  if (remain <= 0) return undefined;
  const mins = Math.max(1, Math.ceil(remain / 60_000));
  return `Retries in ${mins}m`;
}

export type DisplayKind = "pending" | ErrorKind;

export interface EntryDescriptor {
  store: QueueStoreName;
  id: number;
  summary: string;
  age: string;
  kind: DisplayKind;
  errorMessage?: string;
  cooldown?: string;
  attempts: number;
  canRetry: boolean;
  canEdit: boolean;
  canDismiss: boolean;
}

/**
 * Map a stored entry to its display struct. `now` is an explicit arg so
 * tests + the UI share the same time source without spying on Date.
 */
export function describeQueueEntry(
  store: QueueStoreName,
  entry: QueuedBase & { payload: Record<string, unknown> },
  now: number,
): EntryDescriptor {
  const kind: DisplayKind = ((entry.errorKind ?? (entry.lastError ? "unknown" : "pending")) as DisplayKind);
  // Retry is only meaningful for network / unknown / pending. Validation /
  // not-found need the user to edit first. Permission is a hard stop.
  const canRetry = kind === "pending" || kind === "network" || kind === "unknown";
  const canEdit = kind === "validation" || kind === "not-found";
  return {
    store,
    id: entry.id as number,
    summary: summarise(store, entry.payload),
    age: formatAge(entry.createdAt, now),
    kind,
    errorMessage: entry.lastError,
    cooldown: cooldownLabel(entry.nextAttemptAt, now),
    attempts: entry.attempts ?? 0,
    canRetry,
    canEdit,
    // Always dismissable — covers "I queued this by mistake while offline"
    // as well as "this error won't go away, hide it".
    canDismiss: true,
  };
}

/** List all non-dismissed queued rows across every store. */
export async function listAllPending(): Promise<PendingEntry[]> {
  const d = await db();
  const out: PendingEntry[] = [];
  for (const store of STORES) {
    const rows = (await (d.getAll as (s: QueueStoreName) => Promise<QueuedBase[]>)(
      store,
    )) as Array<QueuedBase & { payload: Record<string, unknown> }>;
    for (const r of rows) {
      if (r.status === "dismissed") continue;
      if (typeof r.id !== "number") continue;
      out.push({
        store,
        id: r.id,
        clientId: r.clientId,
        clientTs: r.clientTs,
        createdAt: r.createdAt,
        attempts: r.attempts,
        lastError: r.lastError,
        errorKind: r.errorKind,
        nextAttemptAt: r.nextAttemptAt,
        payload: r.payload,
      });
    }
  }
  return out;
}
