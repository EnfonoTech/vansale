/**
 * Exponential backoff on queue entries.
 *
 * Behavior under test:
 *   1. `drainStore` skips an entry when `nextAttemptAt > Date.now()` —
 *      the processor is NOT invoked and the entry stays in the store.
 *   2. On processor failure, `drainStore` stamps a future `nextAttemptAt`
 *      following `min(60_000 * 2^attempts, 30 * 60_000)` — capped at 30 min.
 *   3. A successful processor call clears the entry (delete, not update),
 *      so `nextAttemptAt` is irrelevant after success.
 *   4. An entry whose `nextAttemptAt` has passed is processed normally.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetOfflineDb } from "@/test/offline-utils";
import { addEntry, getAllEntries } from "@/offline/queue";
import { drainStore } from "@/offline/drain";
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

describe("drainStore — exponential backoff", () => {
  beforeEach(async () => {
    await resetOfflineDb();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("skips an entry whose nextAttemptAt is in the future", async () => {
    await addEntry<QueuedInvoice>(
      "invoice_queue",
      makeInvoice({ nextAttemptAt: Date.now() + 60_000 }),
    );
    const processor = vi.fn(async () => ({ refName: "SINV-0001" }));

    const res = await drainStore("invoice_queue", processor);

    expect(processor).not.toHaveBeenCalled();
    expect(res.processed).toBe(0);
    expect(res.skipped).toBe(1);
    expect(res.failed).toBe(0);
    // Entry is still in the store — we didn't delete or mutate it.
    const remaining = await getAllEntries<QueuedInvoice>("invoice_queue");
    expect(remaining).toHaveLength(1);
    expect(remaining[0].attempts).toBe(0);
  });

  it("processes an entry whose nextAttemptAt has already passed", async () => {
    await addEntry<QueuedInvoice>(
      "invoice_queue",
      makeInvoice({ nextAttemptAt: Date.now() - 1_000 }),
    );
    const processor = vi.fn(async () => ({ refName: "SINV-0002" }));

    const res = await drainStore("invoice_queue", processor);

    expect(processor).toHaveBeenCalledTimes(1);
    expect(res.processed).toBe(1);
    // Successful drain deletes the entry.
    const remaining = await getAllEntries<QueuedInvoice>("invoice_queue");
    expect(remaining).toHaveLength(0);
  });

  it("stamps next backoff on failure: 1m after 0 attempts, 2m after 1, 4m after 2", async () => {
    // Only fake Date — fake-indexeddb relies on real setTimeout internally.
    vi.useFakeTimers({ toFake: ["Date"] });
    const T0 = new Date("2026-05-01T10:00:00Z").getTime();
    vi.setSystemTime(T0);

    const cases: Array<{ attempts: number; expectedDelayMs: number }> = [
      { attempts: 0, expectedDelayMs: 60_000 },
      { attempts: 1, expectedDelayMs: 120_000 },
      { attempts: 2, expectedDelayMs: 240_000 },
    ];

    for (const c of cases) {
      await resetOfflineDb();
      await addEntry<QueuedInvoice>(
        "invoice_queue",
        makeInvoice({ attempts: c.attempts }),
      );
      const processor = vi.fn(async () => {
        throw new Error("boom");
      });

      await drainStore("invoice_queue", processor);

      const [entry] = await getAllEntries<QueuedInvoice>("invoice_queue");
      expect(entry.attempts).toBe(c.attempts + 1);
      expect(entry.nextAttemptAt).toBe(T0 + c.expectedDelayMs);
    }
  });

  it("caps the backoff at 30 minutes even after many failures", async () => {
    // Only fake Date — fake-indexeddb relies on real setTimeout internally.
    vi.useFakeTimers({ toFake: ["Date"] });
    const T0 = new Date("2026-05-01T10:00:00Z").getTime();
    vi.setSystemTime(T0);

    await addEntry<QueuedInvoice>(
      "invoice_queue",
      makeInvoice({ attempts: 20 }), // 60_000 * 2^20 ≫ 30 min
    );
    const processor = vi.fn(async () => {
      throw new Error("boom");
    });

    await drainStore("invoice_queue", processor);

    const [entry] = await getAllEntries<QueuedInvoice>("invoice_queue");
    expect(entry.nextAttemptAt).toBe(T0 + 30 * 60_000);
  });
});
