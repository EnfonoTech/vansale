/**
 * Stock entry queue — offline van replenishment.
 *
 * Van drivers often load their truck at a branch with spotty wifi
 * (warehouse, back office). `transfer_in` is the only write the stock
 * UI makes, so giving it an offline queue means a load captured at
 * 6am while the tower is down isn't lost.
 *
 * Server contract: `vansale.api.van_stock.transfer_in` is POST, accepts
 * `client_id` + `posting_ts` and returns `{name}` of the new Stock
 * Entry. Idempotency is enforced server-side via Vansale Outbox
 * (event_type="stock_adjust").
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetOfflineDb } from "@/test/offline-utils";
import { addEntry, getAllEntries, totalPending } from "@/offline/queue";
import { drainStore } from "@/offline/drain";
import type { QueuedStockEntry } from "@/offline/db";

function makeStockEntry(overrides: Partial<QueuedStockEntry> = {}): QueuedStockEntry {
  return {
    clientId: `cid-${Math.random().toString(36).slice(2, 10)}`,
    clientTs: new Date().toISOString(),
    createdAt: Date.now(),
    attempts: 0,
    fromWarehouse: "Main Stores - GS",
    toWarehouse: "Van 01 - GS",
    payload: {
      from_warehouse: "Main Stores - GS",
      to_warehouse: "Van 01 - GS",
      reason: "Morning load",
      items: [
        { item_code: "WATER-500", qty: 48 },
        { item_code: "JUICE-330", qty: 24 },
      ],
    },
    ...overrides,
  };
}

describe("stock_entry_queue", () => {
  beforeEach(async () => {
    await resetOfflineDb();
  });

  it("accepts QueuedStockEntry entries", async () => {
    await addEntry<QueuedStockEntry>("stock_entry_queue", makeStockEntry());
    const rows = await getAllEntries<QueuedStockEntry>("stock_entry_queue");
    expect(rows).toHaveLength(1);
    expect(rows[0].fromWarehouse).toBe("Main Stores - GS");
    expect(rows[0].toWarehouse).toBe("Van 01 - GS");
  });

  it("counts towards totalPending", async () => {
    await addEntry<QueuedStockEntry>("stock_entry_queue", makeStockEntry());
    expect(await totalPending()).toBe(1);
  });

  it("drainStore deletes the entry on successful processor call", async () => {
    await addEntry<QueuedStockEntry>("stock_entry_queue", makeStockEntry());
    const processor = vi.fn(async () => ({ refName: "MAT-STE-2026-00042" }));

    const res = await drainStore("stock_entry_queue", processor);

    expect(processor).toHaveBeenCalledTimes(1);
    expect(res.processed).toBe(1);
    expect(await getAllEntries<QueuedStockEntry>("stock_entry_queue")).toHaveLength(0);
  });
});
