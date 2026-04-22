/**
 * Customer queue — offline Customer create.
 *
 * Shipping this fills the biggest gap in offline coverage: a van driver
 * in a dead-zone meeting a brand-new customer must be able to add them,
 * make the sale, collect payment, and have everything sync later.
 *
 * Server contract: `vansale.api.customer.create` is POST, accepts
 * `client_id` (+ the existing fields) and returns the created Customer's
 * `name`. Idempotency is enforced server-side via the Vansale Outbox row.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetOfflineDb } from "@/test/offline-utils";
import { addEntry, getAllEntries, totalPending } from "@/offline/queue";
import { drainStore } from "@/offline/drain";
import type { QueuedCustomer } from "@/offline/db";

function makeCustomer(overrides: Partial<QueuedCustomer> = {}): QueuedCustomer {
  return {
    clientId: `cid-${Math.random().toString(36).slice(2, 10)}`,
    clientTs: new Date().toISOString(),
    createdAt: Date.now(),
    attempts: 0,
    customerName: "New Corner Store",
    payload: {
      customer_name: "New Corner Store",
      customer_type: "b2c",
      mobile_no: "+966501234567",
    },
    ...overrides,
  };
}

describe("customer_queue", () => {
  beforeEach(async () => {
    await resetOfflineDb();
  });

  it("accepts QueuedCustomer entries", async () => {
    await addEntry<QueuedCustomer>("customer_queue", makeCustomer());
    const rows = await getAllEntries<QueuedCustomer>("customer_queue");
    expect(rows).toHaveLength(1);
    expect(rows[0].customerName).toBe("New Corner Store");
  });

  it("counts towards totalPending", async () => {
    await addEntry<QueuedCustomer>("customer_queue", makeCustomer());
    expect(await totalPending()).toBe(1);
  });

  it("drainStore deletes the entry on successful processor call", async () => {
    await addEntry<QueuedCustomer>("customer_queue", makeCustomer());
    const processor = vi.fn(async () => ({ refName: "CUST-0042" }));

    const res = await drainStore("customer_queue", processor);

    expect(processor).toHaveBeenCalledTimes(1);
    expect(res.processed).toBe(1);
    expect(await getAllEntries<QueuedCustomer>("customer_queue")).toHaveLength(0);
  });
});
