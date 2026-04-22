/**
 * Observability model — pure mapping from IDB queue entries to a display
 * struct the Vue components render. Testing the model (not the DOM) keeps
 * the unit tests fast and lets us evolve the UI without rewriting assertions.
 */
import { describe, expect, it } from "vitest";
import { describeQueueEntry, formatAge, listAllPending } from "@/offline/observability";
import { resetOfflineDb } from "@/test/offline-utils";
import { addEntry } from "@/offline/queue";
import type { QueuedInvoice } from "@/offline/db";

describe("formatAge", () => {
  it('returns "just now" for sub-minute ages', () => {
    expect(formatAge(45_000, 0)).toBe("just now"); // 45s ago
  });

  it("returns minutes for ages under an hour", () => {
    expect(formatAge(0, 5 * 60_000)).toBe("5m ago");
  });

  it("returns hours for ages between 1h and 24h", () => {
    expect(formatAge(0, 3 * 3_600_000)).toBe("3h ago");
  });

  it("returns days for ages beyond 24h", () => {
    expect(formatAge(0, 2 * 86_400_000)).toBe("2d ago");
  });
});

describe("describeQueueEntry", () => {
  const now = Date.now();

  it("returns a fresh pending entry with kind='pending' and a summary", () => {
    const entry: QueuedInvoice = {
      id: 1,
      clientId: "cid-1",
      clientTs: new Date(now - 30_000).toISOString(),
      createdAt: now - 30_000,
      attempts: 0,
      customerName: "Acme Corp",
      payload: { customer: "Acme Corp", items: [] },
    };

    const d = describeQueueEntry("invoice_queue", entry, now);

    expect(d.kind).toBe("pending");
    expect(d.summary).toMatch(/Acme/);
    expect(d.age).toBe("just now");
    expect(d.canRetry).toBe(true);
    expect(d.canDismiss).toBe(true);
  });

  it("surfaces errorKind=validation with canRetry=false", () => {
    const entry: QueuedInvoice = {
      id: 2,
      clientId: "cid-2",
      clientTs: new Date(now - 600_000).toISOString(),
      createdAt: now - 600_000,
      attempts: 2,
      customerName: "Beta",
      lastError: "Mandatory fields required",
      errorKind: "validation",
      payload: { customer: "Beta" },
    };

    const d = describeQueueEntry("invoice_queue", entry, now);

    expect(d.kind).toBe("validation");
    expect(d.canRetry).toBe(false);
    expect(d.canEdit).toBe(true);
    expect(d.age).toBe("10m ago");
    expect(d.errorMessage).toMatch(/Mandatory/);
  });

  it("shows backoff cooldown when nextAttemptAt is in the future", () => {
    const entry: QueuedInvoice = {
      id: 3,
      clientId: "cid-3",
      clientTs: new Date(now - 120_000).toISOString(),
      createdAt: now - 120_000,
      attempts: 1,
      nextAttemptAt: now + 90_000,
      errorKind: "unknown",
      lastError: "timeout",
      customerName: "Gamma",
      payload: { customer: "Gamma" },
    };

    const d = describeQueueEntry("invoice_queue", entry, now);

    expect(d.cooldown).toBe("Retries in 2m");
  });

  it("hides cooldown once nextAttemptAt has passed", () => {
    const entry: QueuedInvoice = {
      id: 4,
      clientId: "cid-4",
      clientTs: new Date(now - 600_000).toISOString(),
      createdAt: now - 600_000,
      attempts: 3,
      nextAttemptAt: now - 1_000,
      lastError: "boom",
      customerName: "Delta",
      payload: { customer: "Delta" },
    };

    const d = describeQueueEntry("invoice_queue", entry, now);

    expect(d.cooldown).toBeUndefined();
  });
});

describe("listAllPending", () => {
  it("returns entries from every queue, excluding dismissed", async () => {
    await resetOfflineDb();
    await addEntry<QueuedInvoice>("invoice_queue", {
      clientId: "cid-a",
      clientTs: new Date().toISOString(),
      createdAt: Date.now(),
      attempts: 0,
      customerName: "Acme",
      payload: { customer: "Acme" },
    });
    await addEntry<QueuedInvoice>("invoice_queue", {
      clientId: "cid-b",
      clientTs: new Date().toISOString(),
      createdAt: Date.now(),
      attempts: 0,
      customerName: "Beta",
      payload: { customer: "Beta" },
      status: "dismissed",
    });

    const all = await listAllPending();

    expect(all).toHaveLength(1);
    expect(all[0].clientId).toBe("cid-a");
  });
});
