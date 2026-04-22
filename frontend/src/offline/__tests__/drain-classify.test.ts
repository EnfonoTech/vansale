/**
 * Drain engine integration with classifier.
 *
 * Behavior under test:
 *   1. Idempotent replay → entry deleted, `processed += 1`. The server
 *      confirms the clientId is already persisted; the local queue
 *      entry is now redundant.
 *   2. Validation failure → entry kept, `errorKind = "validation"`
 *      stored, counted as `failed`. Backoff still applies.
 *   3. Network failure → entry kept, `errorKind = "network"`, counted
 *      as `skipped` (no user-facing alert; silent auto-retry).
 *   4. Permission failure → entry kept, `errorKind = "permission"`,
 *      counted as `failed`, retryable=false so the UI can hide the
 *      Retry button.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetOfflineDb } from "@/test/offline-utils";
import { addEntry, getAllEntries } from "@/offline/queue";
import { drainStore } from "@/offline/drain";
import { ApiError, NetworkError } from "@/app/frappe";
import type { QueuedInvoice } from "@/offline/db";

function makeInvoice(overrides: Partial<QueuedInvoice> = {}): QueuedInvoice {
  return {
    clientId: `cid-${Math.random().toString(36).slice(2, 10)}`,
    clientTs: new Date().toISOString(),
    createdAt: Date.now(),
    attempts: 0,
    customerName: "Acme",
    payload: { customer: "Acme" },
    ...overrides,
  };
}

describe("drainStore — classified errors", () => {
  beforeEach(async () => {
    await resetOfflineDb();
  });

  it("deletes the entry on idempotent-replay and counts it as processed", async () => {
    await addEntry<QueuedInvoice>("invoice_queue", makeInvoice());
    const processor = vi.fn(async () => {
      throw new ApiError("dup", 417, "Sales Invoice has already been submitted");
    });

    const res = await drainStore("invoice_queue", processor);

    expect(res.processed).toBe(1);
    expect(res.failed).toBe(0);
    const remaining = await getAllEntries<QueuedInvoice>("invoice_queue");
    expect(remaining).toHaveLength(0);
  });

  it("stamps errorKind=validation on a mandatory-fields failure", async () => {
    await addEntry<QueuedInvoice>("invoice_queue", makeInvoice());
    const processor = vi.fn(async () => {
      throw new ApiError("val", 417, "Mandatory fields required: items");
    });

    const res = await drainStore("invoice_queue", processor);

    expect(res.failed).toBe(1);
    const [entry] = await getAllEntries<QueuedInvoice>("invoice_queue");
    expect(entry.errorKind).toBe("validation");
    expect(entry.lastError).toMatch(/Mandatory/);
    expect(entry.attempts).toBe(1);
  });

  it("stamps errorKind=network on NetworkError and counts as skipped", async () => {
    await addEntry<QueuedInvoice>("invoice_queue", makeInvoice());
    const processor = vi.fn(async () => {
      throw new NetworkError("Offline");
    });

    const res = await drainStore("invoice_queue", processor);

    expect(res.skipped).toBe(1);
    expect(res.failed).toBe(0);
    const [entry] = await getAllEntries<QueuedInvoice>("invoice_queue");
    expect(entry.errorKind).toBe("network");
  });

  it("stamps errorKind=permission on a forbidden failure", async () => {
    await addEntry<QueuedInvoice>("invoice_queue", makeInvoice());
    const processor = vi.fn(async () => {
      throw new ApiError("perm", 403, "User not permitted");
    });

    const res = await drainStore("invoice_queue", processor);

    expect(res.failed).toBe(1);
    const [entry] = await getAllEntries<QueuedInvoice>("invoice_queue");
    expect(entry.errorKind).toBe("permission");
  });
});
